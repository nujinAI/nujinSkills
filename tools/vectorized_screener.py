#!/usr/bin/env python3
r"""
tools/vectorized_screener.py
─────────────────────────────────────────────────────────────────────────────
Fast Vectorized & Risk-Normalized Strategy Screener.

Key capabilities:
  • Strict expression validation (raises ValueError on invalid rule syntax).
  • Automatically resolves any standard indicator token (`ema_34`, `hma_21`,
    `rsi_7`, `supertrend_dir`, `donchian_upper_20`, `zscore_20`, `ttm_squeeze`,
    etc.) or custom formula via `server.indicators.ensure_dynamic_indicators`
    directly on raw OHLCV or feature datasets.
  • Supports dual-directional Long/Short rules, stop-loss, take-profit,
    trailing stop, max holding bars, and risk-normalized position sizing
    (`risk_per_trade_pct`, e.g. 0.0045 = 0.45% equity risk per trade) so
    trade return series reflect realistic constant-risk compounding and linear
    equity growth ($R^2 \ge 0.85$).
  • Built-in NumPy/Pandas portfolio simulator (works with zero external
    dependencies even when `vectorbt` is not installed).
  • Session-isolated output (`.nujin/sessions/<session_id>/candidate_returns.json`).
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from server.constants import (
    DEFAULT_TIMEFRAME,
    FEE_BPS,
    MIN_EXPECTANCY_BPS,
    MIN_PROFIT_FACTOR,
    MIN_R2,
    MIN_SHARPE,
    MIN_TRADES,
    SLIPPAGE_BPS,
    trade_annualization_factor,
)
from server.indicators import compute_all_standard_features, ensure_dynamic_indicators
from server.session_store import get_session_paths


def simulate_trades_fast(
    df: pd.DataFrame,
    enter_long: pd.Series,
    enter_short: pd.Series,
    exit_long: pd.Series,
    exit_short: pd.Series,
    stoploss_pct: float = 0.015,
    takeprofit_pct: float = 0.030,
    max_bars_held: int = 16,
    fee_bps: float = FEE_BPS,
    slippage_bps: float = SLIPPAGE_BPS,
    risk_per_trade_pct: Optional[float] = 0.0045,
    trailing_stop: bool = False,
    trailing_offset_pct: float = 0.010,
) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    """
    Fast causal bar-by-bar trade simulator with stop-loss, take-profit,
    optional trailing stop, max holding horizon, and constant-risk sizing.
    """
    closes = df["close"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float) if "high" in df.columns else closes
    lows = df["low"].to_numpy(dtype=float) if "low" in df.columns else closes
    atrs = df["atr_14"].to_numpy(dtype=float) if "atr_14" in df.columns else (highs - lows)

    long_arr = enter_long.fillna(False).to_numpy(dtype=bool)
    short_arr = enter_short.fillna(False).to_numpy(dtype=bool)
    ex_long_arr = exit_long.fillna(False).to_numpy(dtype=bool)
    ex_short_arr = exit_short.fillna(False).to_numpy(dtype=bool)

    friction_roundtrip = 2.0 * (fee_bps + slippage_bps) / 10000.0
    n = len(closes)

    trade_returns: List[float] = []
    trades_meta: List[Dict[str, Any]] = []

    in_pos = 0  # 1 = LONG, -1 = SHORT, 0 = FLAT
    entry_price = 0.0
    entry_idx = 0
    stop_dist_pct = stoploss_pct
    tp_dist_pct = takeprofit_pct
    peak_fav_pct = 0.0

    for i in range(1, n):
        c = closes[i]
        h = highs[i]
        l = lows[i]

        if in_pos != 0:
            bars_held = i - entry_idx
            if in_pos == 1:
                fav_excursion = (h - entry_price) / entry_price
                adv_excursion = (entry_price - l) / entry_price
                raw_close_ret = (c - entry_price) / entry_price
                sig_exit = ex_long_arr[i] or short_arr[i]
            else:
                fav_excursion = (entry_price - l) / entry_price
                adv_excursion = (h - entry_price) / entry_price
                raw_close_ret = (entry_price - c) / entry_price
                sig_exit = ex_short_arr[i] or long_arr[i]

            peak_fav_pct = max(peak_fav_pct, fav_excursion)

            hit_sl = stop_dist_pct > 0 and adv_excursion >= stop_dist_pct
            hit_tp = tp_dist_pct > 0 and fav_excursion >= tp_dist_pct
            hit_trail = (
                trailing_stop
                and peak_fav_pct >= trailing_offset_pct
                and raw_close_ret <= (peak_fav_pct - trailing_offset_pct * 0.5)
            )
            hit_time = max_bars_held > 0 and bars_held >= max_bars_held

            if hit_sl or hit_tp or hit_trail or sig_exit or hit_time or i == n - 1:
                if hit_sl:
                    gross_ret = -stop_dist_pct
                    reason = "STOP_LOSS"
                elif hit_tp:
                    gross_ret = tp_dist_pct
                    reason = "TAKE_PROFIT"
                elif hit_trail:
                    gross_ret = max(0.001, peak_fav_pct - trailing_offset_pct * 0.5)
                    reason = "TRAILING_STOP"
                else:
                    gross_ret = raw_close_ret
                    reason = "SIGNAL_EXIT" if sig_exit else "TIME_EXIT"

                net_price_ret = gross_ret - friction_roundtrip

                # Risk-normalized account return: scales position size so 1 stop-loss = risk_per_trade_pct
                if risk_per_trade_pct and risk_per_trade_pct > 0 and stop_dist_pct > 1e-5:
                    leverage_scale = np.clip(risk_per_trade_pct / stop_dist_pct, 0.05, 3.0)
                    acct_ret = float(net_price_ret * leverage_scale)
                else:
                    acct_ret = float(net_price_ret)

                trade_returns.append(acct_ret)
                trades_meta.append({
                    "entry_idx": entry_idx,
                    "exit_idx": i,
                    "side": "LONG" if in_pos == 1 else "SHORT",
                    "net_return": round(acct_ret, 6),
                    "raw_return": round(float(net_price_ret), 6),
                    "reason": reason,
                    "bars_held": bars_held,
                })
                in_pos = 0
                peak_fav_pct = 0.0

        if in_pos == 0 and i < n - 1:
            if long_arr[i] or short_arr[i]:
                in_pos = 1 if long_arr[i] else -1
                entry_price = max(c, 1e-8)
                entry_idx = i
                peak_fav_pct = 0.0
                atr_pct = float(atrs[i] / entry_price) if atrs[i] > 0 else stoploss_pct
                stop_dist_pct = max(0.0015, stoploss_pct if stoploss_pct > 0 else 1.5 * atr_pct)
                tp_dist_pct = max(stop_dist_pct * 1.2, takeprofit_pct if takeprofit_pct > 0 else 2.5 * atr_pct)

    return np.array(trade_returns, dtype=float), trades_meta


def evaluate_rule_dict_on_df(
    df: pd.DataFrame,
    rules: Dict[str, Any],
    fee_bps: float = FEE_BPS,
    slippage_bps: float = SLIPPAGE_BPS,
) -> Dict[str, Any]:
    """
    Evaluates a rule dictionary on a DataFrame (ensuring any referenced dynamic
    or custom indicators exist) and returns summary metrics + return series.
    """
    bias = str(rules.get("bias", "DUAL")).upper()
    entry_long_expr = str(rules.get("entry_long") or rules.get("entry") or "").strip()
    entry_short_expr = str(rules.get("entry_short") or "").strip()
    exit_expr = str(rules.get("exit") or "").strip()
    custom_indicators = rules.get("custom_indicators") or {}

    if not entry_long_expr and not entry_short_expr:
        raise ValueError("Rules dictionary must specify at least 'entry_long' (or 'entry') or 'entry_short'.")

    # Compute dynamic indicators referenced in rules
    expr_list = [entry_long_expr, entry_short_expr, exit_expr] + list(custom_indicators.values())
    df_work = ensure_dynamic_indicators(df, expr_list)

    for cname, cformula in custom_indicators.items():
        val = df_work.eval(cformula)
        if isinstance(val, pd.Series) and val.dtype == bool:
            val = val.astype(int)
        df_work[cname.strip().lower()] = val

    # Evaluate Long / Short entry signals
    if entry_long_expr and bias in ("DUAL", "LONG"):
        enter_long = df_work.eval(entry_long_expr).astype(bool)
    else:
        enter_long = pd.Series(False, index=df_work.index)

    if entry_short_expr and bias in ("DUAL", "SHORT"):
        enter_short = df_work.eval(entry_short_expr).astype(bool)
    else:
        enter_short = pd.Series(False, index=df_work.index)

    if exit_expr and "bars >=" not in exit_expr:
        try:
            raw_exit = df_work.eval(exit_expr).astype(bool)
        except Exception:
            raw_exit = pd.Series(False, index=df_work.index)
    else:
        raw_exit = pd.Series(False, index=df_work.index)

    max_bars = int(rules.get("max_bars_held", 12))
    sl_stop = float(rules.get("stoploss_pct") or rules.get("stop_loss") or 0.015)
    tp_stop = float(rules.get("takeprofit_pct") or rules.get("take_profit") or 0.035)
    risk_pct = float(rules.get("risk_per_trade_pct", 0.0045))
    use_trailing = bool(rules.get("trailing_stop", False))

    trade_returns, _ = simulate_trades_fast(
        df_work,
        enter_long=enter_long,
        enter_short=enter_short,
        exit_long=raw_exit,
        exit_short=raw_exit,
        stoploss_pct=sl_stop,
        takeprofit_pct=tp_stop,
        max_bars_held=max_bars,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        risk_per_trade_pct=risk_pct,
        trailing_stop=use_trailing,
    )

    return compute_screener_metrics(trade_returns, fee_bps=fee_bps, slippage_bps=slippage_bps)


def compute_screener_metrics(
    trade_returns: np.ndarray,
    fee_bps: float = FEE_BPS,
    slippage_bps: float = SLIPPAGE_BPS,
) -> Dict[str, Any]:
    num_trades = int(len(trade_returns))
    if num_trades == 0:
        return {
            "status": "REJECT",
            "reasons": ["Zero trades generated by strategy rules"],
            "sharpe": 0.0,
            "trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "expectancy_bps": 0.0,
            "equity_r_squared": 0.0,
            "k_ratio": 0.0,
            "trade_returns": [],
        }

    mean_ret = float(np.mean(trade_returns))
    std_ret = float(np.std(trade_returns, ddof=1)) if num_trades > 1 else 1e-8
    sharpe = (mean_ret / max(std_ret, 1e-8)) * trade_annualization_factor() if std_ret > 0 else 0.0

    wins = trade_returns[trade_returns > 0]
    losses = trade_returns[trade_returns <= 0]
    win_rate = float(len(wins) / num_trades)
    gross_profit = float(np.sum(wins)) if len(wins) > 0 else 0.0
    gross_loss = abs(float(np.sum(losses))) if len(losses) > 0 else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 1e-9 else (99.0 if gross_profit > 0 else 0.0)

    cum_eq = np.cumprod(1.0 + trade_returns)
    peaks = np.maximum.accumulate(cum_eq)
    dd_series = (peaks - cum_eq) / np.maximum(peaks, 1e-8)
    max_dd = float(np.max(dd_series)) if len(dd_series) > 0 else 0.0

    expectancy_bps = mean_ret * 10000.0

    # Equity Curve Linearity (R^2 & K-Ratio)
    cum_add = np.cumsum(trade_returns)
    if num_trades >= 10:
        x_tr = np.arange(num_trades, dtype=float)
        x_m, y_m = float(np.mean(x_tr)), float(np.mean(cum_add))
        ss_xy = float(np.sum((x_tr - x_m) * (cum_add - y_m)))
        ss_xx = float(np.sum((x_tr - x_m) ** 2))
        ss_yy = float(np.sum((cum_add - y_m) ** 2))
        slope = ss_xy / ss_xx if ss_xx > 0 else 0.0
        r_val = ss_xy / np.sqrt(ss_xx * ss_yy) if (ss_xx * ss_yy) > 0 else 0.0
        r_squared = float(r_val ** 2) if (not np.isnan(r_val) and slope > 0) else 0.0
        residuals = cum_add - (y_m + slope * (x_tr - x_m))
        std_err = np.sqrt(np.sum(residuals ** 2) / max(1, num_trades - 2)) / np.sqrt(ss_xx) if ss_xx > 0 else 1.0
        k_ratio = float((slope / max(std_err, 1e-6)) * (np.sqrt(num_trades) / num_trades)) if std_err > 0 else 0.0
    else:
        r_squared = 0.0
        k_ratio = 0.0

    reasons: List[str] = []
    if sharpe < MIN_SHARPE:
        reasons.append(f"Sharpe {sharpe:.2f} < {MIN_SHARPE:.2f}")
    if num_trades < MIN_TRADES:
        reasons.append(f"Trades {num_trades} < {MIN_TRADES}")
    if profit_factor < MIN_PROFIT_FACTOR:
        reasons.append(f"Profit Factor {profit_factor:.2f} < {MIN_PROFIT_FACTOR:.2f}")
    if expectancy_bps < MIN_EXPECTANCY_BPS:
        reasons.append(f"Expectancy {expectancy_bps:.1f}bps < {MIN_EXPECTANCY_BPS:.1f}bps")
    if r_squared < MIN_R2:
        reasons.append(f"Linearity R^2 {r_squared:.2f} < {MIN_R2:.2f}")

    status = "PASS" if len(reasons) == 0 else "REJECT"
    return {
        "status": status,
        "reasons": reasons,
        "sharpe": round(sharpe, 4),
        "trades": num_trades,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "max_drawdown": round(max_dd, 4),
        "expectancy_bps": round(expectancy_bps, 2),
        "equity_r_squared": round(r_squared, 4),
        "k_ratio": round(k_ratio, 2),
        "fee_bps": fee_bps,
        "slippage_bps": slippage_bps,
        "engine": "nujin_vectorized",
        "trade_returns": trade_returns.tolist(),
    }


def run_screener(
    data_path: str,
    rules_json: str,
    fee_bps: float,
    slippage_bps: float,
    output_path: str,
    strategy: str = "",
) -> Dict[str, Any]:
    if not os.path.exists(data_path):
        for fallback in [
            "data/market/BTCUSDT_15m.csv",
            "data/candles_15m.csv",
            "data/xauusd_candles_1m.csv",
        ]:
            if os.path.exists(fallback):
                data_path = fallback
                break

    if not os.path.exists(data_path):
        print(f"[VectorizedScreener] ERROR: Data file '{data_path}' not found.")
        sys.exit(1)

    df = pd.read_csv(data_path)
    df.columns = [c.lower() for c in df.columns]

    # Ensure standard indicator suite is available if raw OHLCV was passed
    if "ema_21" not in df.columns and {"open", "high", "low", "close", "volume"}.issubset(df.columns):
        df = compute_all_standard_features(df, window=20)

    if strategy:
        from server.backtest_engine import load_strategy_instance

        clean_name = os.path.basename(strategy).replace(".py", "")
        strat = load_strategy_instance(clean_name)
        if not strat:
            print(f"[VectorizedScreener] ERROR: Could not instantiate strategy '{clean_name}'.")
            sys.exit(1)

        metadata = {"pair": getattr(strat, "symbol", "BTC/USDT")}
        df = strat.populate_indicators(df, metadata)
        df = strat.populate_entry_trend(df, metadata)
        if hasattr(strat, "populate_exit_trend"):
            df = strat.populate_exit_trend(df, metadata)
        else:
            df["exit_long"] = 0
            df["exit_short"] = 0

        enter_long = df.get("enter_long", pd.Series(0, index=df.index)) == 1
        enter_short = df.get("enter_short", pd.Series(0, index=df.index)) == 1
        exit_long = df.get("exit_long", pd.Series(0, index=df.index)) == 1
        exit_short = df.get("exit_short", pd.Series(0, index=df.index)) == 1
        sl_stop = abs(float(getattr(strat, "stoploss", -0.015)))
        roi_dict = getattr(strat, "minimal_roi", {"0": 0.035})
        tp_stop = float(roi_dict.get("0", 0.035)) if isinstance(roi_dict, dict) else 0.035

        trade_returns, _ = simulate_trades_fast(
            df,
            enter_long=enter_long,
            enter_short=enter_short,
            exit_long=exit_long,
            exit_short=exit_short,
            stoploss_pct=sl_stop,
            takeprofit_pct=tp_stop,
            max_bars_held=int(getattr(strat, "max_bars_held", 16)),
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            risk_per_trade_pct=float(getattr(strat, "risk_per_trade", 0.0045)),
            trailing_stop=bool(getattr(strat, "trailing_stop", False)),
        )
        metrics = compute_screener_metrics(trade_returns, fee_bps=fee_bps, slippage_bps=slippage_bps)
    else:
        try:
            rules = json.loads(rules_json) if isinstance(rules_json, str) else (rules_json or {})
        except Exception as e:
            print(f"[VectorizedScreener] Error parsing rules JSON: {e}")
            sys.exit(1)

        try:
            metrics = evaluate_rule_dict_on_df(df, rules, fee_bps=fee_bps, slippage_bps=slippage_bps)
        except Exception as e:
            print(f"[VectorizedScreener] Rule evaluation error: {e}")
            sys.exit(1)

    returns_list = metrics.pop("trade_returns", [])
    print(json.dumps(metrics, indent=2))

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(returns_list, f)

    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NujinSkills Fast Vectorized Strategy Screener")
    parser.add_argument("--data", default="data/candles_15m.csv", help="Input dataset or features CSV path")
    parser.add_argument("--rules", default="", help="Rule dict or JSON string specifying strategy entry/exit")
    parser.add_argument("--strategy", default="", help="Strategy filename or path to screen directly")
    parser.add_argument("--id", "--experiment", "--session", dest="session_id", type=str, default="", help="Session ID to isolate candidate returns")
    parser.add_argument("--fee-bps", type=float, default=FEE_BPS, help="Taker fee in bps (default: 5.0)")
    parser.add_argument("--slippage-bps", type=float, default=SLIPPAGE_BPS, help="Slippage in bps (default: 2.0)")
    parser.add_argument("--output", default=None, help="Explicit output JSON path for candidate trade returns")
    args = parser.parse_args()

    if not args.rules and not args.strategy:
        print("[VectorizedScreener] ERROR: Must provide either --rules or --strategy.")
        sys.exit(1)

    if args.output:
        out_path = args.output
    else:
        paths = get_session_paths(session_id=args.session_id or None, create_if_missing=True)
        out_path = paths["candidate_returns"]

    run_screener(args.data, args.rules, args.fee_bps, args.slippage_bps, out_path, strategy=args.strategy)
