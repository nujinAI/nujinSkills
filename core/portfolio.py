"""
core/portfolio.py - Universal Multi-Asset, Multi-Timeframe Portfolio Evaluator.
Single Source of Truth for Portfolio Correlation, Regime Orthogonality, HRP Weights, and Ensemble Metrics.
Part of NujinSkills Quantitative System.
"""
from __future__ import annotations

import os
import logging
from typing import Dict, List, Any, Optional, Tuple
import numpy as np
import pandas as pd
from scipy.spatial.distance import squareform
from scipy.cluster.hierarchy import linkage, leaves_list

from core.data import fetch_ohlcv, resolve_market_symbol, bars_for_days
from core.simulation import run_discrete_simulation, resolve_strategy_close_eod
from server.constants import TRADE_PERIODS_PER_YEAR

logger = logging.getLogger("CorePortfolio")


def classify_market_regimes(df: pd.DataFrame, window: int = 96) -> pd.Series:
    """
    Classifies each bar into one of three market regimes:
    - 'BULL': Price above 200 EMA with positive 20-bar slope and ADX > 20
    - 'BEAR': Price below 200 EMA with negative 20-bar slope and ADX > 20
    - 'RANGE': Oscillating around baseline, ADX <= 20 or low slope
    """
    close = df["close"]
    ema200 = close.ewm(span=min(200, len(df)), adjust=False).mean()
    slope = (ema200 - ema200.shift(20)) / ema200.shift(20)

    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum(
            abs(df["high"] - close.shift(1)),
            abs(df["low"] - close.shift(1))
        )
    )
    atr14 = tr.rolling(14).mean()
    up_move = df["high"] - df["high"].shift(1)
    down_move = df["low"].shift(1) - df["low"]
    pos_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    neg_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    pos_di = 100 * (pd.Series(pos_dm, index=df.index).rolling(14).mean() / (atr14 + 1e-8))
    neg_di = 100 * (pd.Series(neg_dm, index=df.index).rolling(14).mean() / (atr14 + 1e-8))
    dx = 100 * abs(pos_di - neg_di) / (pos_di + neg_di + 1e-8)
    adx = dx.rolling(14).mean()

    regimes = pd.Series("RANGE", index=df.index)
    regimes[(close > ema200) & (slope > 0.001) & (adx > 20)] = "BULL"
    regimes[(close < ema200) & (slope < -0.001) & (adx > 20)] = "BEAR"
    return regimes.bfill().fillna("RANGE")


def _normalize_ohlcv_df(df: pd.DataFrame) -> pd.DataFrame:
    """Ensures a UTC DatetimeIndex on any OHLCV DataFrame."""
    df_eval = df.copy()
    if isinstance(df_eval.index, pd.DatetimeIndex):
        if df_eval.index.tz is None:
            df_eval.index = df_eval.index.tz_localize("UTC")
        else:
            df_eval.index = df_eval.index.tz_convert("UTC")
        return df_eval
    ts_col = "timestamp" if "timestamp" in df_eval.columns else ("time" if "time" in df_eval.columns else None)
    if ts_col is not None:
        df_eval["dt"] = pd.to_datetime(df_eval[ts_col], unit="s", utc=True)
        df_eval = df_eval.set_index("dt")
    return df_eval


def simulate_strategy_bar_returns(
    strategy_name: str,
    df: Optional[pd.DataFrame] = None,
    days: int = 60,
    symbol_override: Optional[str] = None,
    timeframe_override: Optional[str] = None,
) -> Tuple[pd.Series, List[Dict[str, Any]]]:
    """
    Instantiates ANY strategy and executes a discrete simulation on its OWN symbol/timeframe
    (or the supplied DataFrame `df`), returning a timestamp-indexed fractional return Series
    with each trade booked at its actual exit timestamp.
    """
    from server.services.strategy_loader import load_strategy_instance, resolve_strategy_metadata

    clean_name = strategy_name.replace(".py", "")
    strat_inst = load_strategy_instance(clean_name)
    if strat_inst is None:
        logger.warning(f"[CorePortfolio] Failed to load strategy {strategy_name}")
        return pd.Series(dtype=float), []

    meta = resolve_strategy_metadata(clean_name, timeframe_override=timeframe_override)
    raw_sym = symbol_override or getattr(strat_inst, "symbol", None) or meta.get("symbol", "BTC/USDT")
    canon_sym = resolve_market_symbol(raw_sym)
    tf = timeframe_override or getattr(strat_inst, "timeframe", None) or meta.get("timeframe", "15m")

    if df is None:
        bars_needed = bars_for_days(tf, days)
        fetched = fetch_ohlcv(canon_sym, timeframe=tf, count=bars_needed, period=f"{days}d", use_cache=True)
        if fetched is None or (isinstance(fetched, pd.DataFrame) and fetched.empty) or (isinstance(fetched, list) and not fetched):
            logger.warning(f"[CorePortfolio] No market data available for {clean_name} ({canon_sym} {tf})")
            return pd.Series(dtype=float), []
        df = fetched if isinstance(fetched, pd.DataFrame) else pd.DataFrame(fetched)

    df_eval = _normalize_ohlcv_df(df)
    n_bars = len(df_eval)
    returns = pd.Series(0.0, index=df_eval.index, dtype=float)
    trades: List[Dict[str, Any]] = []

    try:
        if hasattr(strat_inst, "compute_indicators"):
            df_eval = strat_inst.compute_indicators(df_eval)

        if hasattr(strat_inst, "generate_signals"):
            sig_df = strat_inst.generate_signals(df_eval)
            # Unit-normalized capital (account_size = 1.0 -> pnl_dollars == fractional return, zero hardcoded capital)
            risk_pct = float(getattr(strat_inst, "risk_pct_1r", getattr(strat_inst, "risk_per_trade_pct", 0.0038)))
            max_daily_l = int(getattr(strat_inst, "max_daily_losses", 2))
            daily_cap_pct = getattr(strat_inst, "daily_profit_cap_pct", None)
            max_hold_b = int(getattr(strat_inst, "max_hold_bars", 24))
            eff_close_eod = resolve_strategy_close_eod(strat_inst, canon_sym, tf)
            eod_hour = int(getattr(strat_inst, "eod_close_hour_utc", 21))
            daily_carry_bps = float(getattr(strat_inst, "daily_carry_bps", 0.0) or 0.0)
            friction_override = getattr(strat_inst, "friction_override", None)

            sim_res = run_discrete_simulation(
                df=df_eval,
                signals=sig_df,
                symbol=canon_sym,
                account_size=1.0,
                dollar_risk_1r=risk_pct,
                max_daily_losses=max_daily_l,
                daily_profit_cap=daily_cap_pct,
                max_hold_bars=max_hold_b,
                close_eod=eff_close_eod,
                eod_close_hour_utc=eod_hour,
                daily_carry_bps=daily_carry_bps,
                friction_override=friction_override,
            )

            for t in sim_res.get("trades", []):
                ret_frac = float(t.pnl_dollars)  # account_size == 1.0 => fractional return
                trades.append({
                    "entry_time": t.entry_time,
                    "exit_time": t.exit_time,
                    "pnl_pct": round(ret_frac * 100.0, 4),
                    "pnl_r": float(t.pnl_r),
                    "exit_reason": t.exit_reason,
                    "symbol": canon_sym,
                    "timeframe": tf,
                })
                # Book P&L strictly at actual exit_time (never at index `bars_held`)
                if n_bars > 0:
                    if t.exit_time in returns.index:
                        returns.loc[t.exit_time] += ret_frac
                    else:
                        idx_arr = returns.index.get_indexer([t.exit_time], method="nearest")
                        if len(idx_arr) > 0 and 0 <= idx_arr[0] < n_bars:
                            returns.iloc[idx_arr[0]] += ret_frac
    except Exception as e:
        logger.error(f"[CorePortfolio] Simulation failed for {strategy_name}: {e}")

    return returns, trades


def calculate_metrics(returns: Any, periods_per_year: float = float(TRADE_PERIODS_PER_YEAR)) -> Dict[str, float]:
    """Computes foundational quantitative metrics from a return series (default daily annualization)."""
    arr = np.asarray(returns, dtype=float)
    arr = arr[~np.isnan(arr)]
    if len(arr) == 0:
        return {"sharpe": 0.0, "total_return_pct": 0.0, "max_drawdown_pct": 0.0, "equity_r_squared": 0.0}

    mean_r = float(np.mean(arr))
    std_r = float(np.std(arr))
    sharpe = float((mean_r / (std_r + 1e-8)) * np.sqrt(periods_per_year)) if std_r > 1e-8 else 0.0

    cum_ret = np.cumsum(arr)
    peak = np.maximum.accumulate(cum_ret)
    dd = peak - cum_ret
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

    x = np.arange(len(cum_ret))
    if len(x) > 2 and np.std(cum_ret) > 1e-8:
        corr_val = np.corrcoef(x, cum_ret)[0, 1]
        r_sq = float(corr_val ** 2) if not np.isnan(corr_val) else 0.0
    else:
        r_sq = 0.0

    return {
        "sharpe": round(sharpe, 2),
        "total_return_pct": round(float(np.sum(arr) * 100), 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "equity_r_squared": round(r_sq, 3),
    }


def compute_hrp_weights(ret_df: pd.DataFrame) -> Dict[str, float]:
    """Computes Hierarchical Risk Parity (HRP) weights from aligned strategy return series."""
    cols = list(ret_df.columns)
    if not cols:
        return {}
    if len(cols) == 1:
        return {cols[0]: 1.0}

    cov = ret_df.cov().fillna(0.0).to_numpy(copy=True)
    corr = ret_df.corr().fillna(0.0).to_numpy(copy=True)
    np.fill_diagonal(corr, 1.0)
    dist = np.sqrt(np.clip((1.0 - corr) / 2.0, 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)

    try:
        condensed = squareform(dist, checks=False)
        link = linkage(condensed, method="single")
        sort_ix = list(leaves_list(link))
    except Exception:
        sort_ix = list(range(len(cols)))

    weights = np.ones(len(cols), dtype=float)

    def _cluster_var(c_indices: List[int]) -> float:
        sub_cov = cov[np.ix_(c_indices, c_indices)]
        ivp = 1.0 / np.maximum(np.diag(sub_cov), 1e-10)
        ivp /= ivp.sum()
        return float(np.dot(ivp, np.dot(sub_cov, ivp)))

    clusters = [sort_ix]
    while clusters:
        next_clusters = []
        for cluster in clusters:
            if len(cluster) > 1:
                mid = len(cluster) // 2
                left = cluster[:mid]
                right = cluster[mid:]
                var_l = _cluster_var(left)
                var_r = _cluster_var(right)
                alpha = 1.0 - var_l / max(var_l + var_r, 1e-12)
                weights[left] *= alpha
                weights[right] *= (1.0 - alpha)
                next_clusters.extend([left, right])
        clusters = next_clusters

    weights /= max(weights.sum(), 1e-12)
    return {cols[i]: round(float(weights[i]), 4) for i in range(len(cols))}


def evaluate_portfolio(
    strategy_names: Optional[List[str]] = None,
    data_path: Optional[str] = None,
    correlation_threshold: float = 0.50,
    days: int = 60,
) -> Dict[str, Any]:
    """
    Evaluates ANY set of strategies across heterogeneous symbols & timeframes on each
    strategy's own authentic market feed, aligned onto a shared UTC daily return grid
    for correlation, HRP allocation, diversification ratio, and regime orthogonality.
    """
    from server.services.strategy_loader import resolve_strategy_metadata

    if not strategy_names:
        strat_dir = "strategies"
        if os.path.exists(strat_dir):
            strategy_names = [f.replace(".py", "") for f in os.listdir(strat_dir) if f.endswith(".py") and not f.startswith("__")]
        else:
            strategy_names = []

    if not strategy_names:
        return {
            "strategies": [],
            "correlation_matrix": {},
            "spearman_matrix": {},
            "individual_metrics": {},
            "regime_breakdown": {},
            "hrp_weights": {},
            "portfolio_ensemble": {
                "blended_sharpe": 0.0,
                "blended_total_return_pct": 0.0,
                "blended_max_drawdown_pct": 0.0,
                "blended_r_squared": 0.0,
                "diversification_ratio": 1.0,
                "hrp_weights": {},
                "correlation_threshold": correlation_threshold
            },
            "pairwise_analysis": []
        }

    # Cache market datasets per (symbol, timeframe) so duplicate feeds are fetched once
    dataset_cache: Dict[Tuple[str, str], pd.DataFrame] = {}
    daily_returns: Dict[str, pd.Series] = {}
    individual_metrics: Dict[str, Any] = {}
    regime_breakdown: Dict[str, Any] = {}

    for s_name in strategy_names:
        clean_name = s_name.replace(".py", "")
        meta = resolve_strategy_metadata(clean_name)
        canon_sym = resolve_market_symbol(meta.get("symbol", "BTC/USDT"))
        tf = meta.get("timeframe", "15m")
        cache_key = (canon_sym, tf)

        if cache_key not in dataset_cache:
            bars_needed = bars_for_days(tf, days)
            fetched = fetch_ohlcv(canon_sym, timeframe=tf, count=bars_needed, period=f"{days}d", use_cache=True)
            if fetched is not None and not (isinstance(fetched, pd.DataFrame) and fetched.empty) and not (isinstance(fetched, list) and not fetched):
                df_sym = fetched if isinstance(fetched, pd.DataFrame) else pd.DataFrame(fetched)
                dataset_cache[cache_key] = _normalize_ohlcv_df(df_sym)
            else:
                dataset_cache[cache_key] = pd.DataFrame()

        df_sym = dataset_cache[cache_key]
        if df_sym.empty:
            continue

        bar_ret, trades = simulate_strategy_bar_returns(clean_name, df=df_sym, days=days, symbol_override=canon_sym, timeframe_override=tf)
        if bar_ret.empty:
            continue

        # Aggregate bar returns to daily UTC calendar grid for apples-to-apples multi-asset / multi-TF correlation
        if isinstance(bar_ret.index, pd.DatetimeIndex):
            d_ret = bar_ret.resample("1D").sum()
        else:
            d_ret = bar_ret

        daily_returns[clean_name] = d_ret
        individual_metrics[clean_name] = {
            **calculate_metrics(d_ret, periods_per_year=float(TRADE_PERIODS_PER_YEAR)),
            "symbol": canon_sym,
            "timeframe": tf,
            "trades": len(trades),
        }

        # Compute regime breakdown on this strategy's own underlying market
        regimes = classify_market_regimes(df_sym)
        reg_metrics = {}
        for r_name in ["BULL", "BEAR", "RANGE"]:
            mask = (regimes == r_name)
            r_ret = bar_ret[mask]
            r_trades = sum(1 for tr in trades if tr["exit_time"] in regimes.index and regimes.loc[tr["exit_time"]] == r_name)
            r_daily = r_ret.resample("1D").sum() if isinstance(r_ret.index, pd.DatetimeIndex) else r_ret
            r_std = float(np.std(r_daily)) if len(r_daily) > 0 else 0.0
            reg_metrics[r_name] = {
                "trades": r_trades,
                "pnl_pct": round(float(np.sum(r_ret) * 100), 2),
                "sharpe": round(float((np.mean(r_daily) / (r_std + 1e-8)) * np.sqrt(TRADE_PERIODS_PER_YEAR)), 2) if r_std > 1e-8 else 0.0
            }
        regime_breakdown[clean_name] = reg_metrics

    if not daily_returns:
        return {
            "strategies": [],
            "correlation_matrix": {},
            "spearman_matrix": {},
            "individual_metrics": {},
            "regime_breakdown": {},
            "hrp_weights": {},
            "portfolio_ensemble": {
                "blended_sharpe": 0.0,
                "blended_total_return_pct": 0.0,
                "blended_max_drawdown_pct": 0.0,
                "blended_r_squared": 0.0,
                "diversification_ratio": 1.0,
                "hrp_weights": {},
                "correlation_threshold": correlation_threshold
            },
            "pairwise_analysis": []
        }

    ret_df = pd.DataFrame(daily_returns).fillna(0.0)
    valid_cols = [c for c in ret_df.columns if ret_df[c].std() > 1e-8]
    if len(valid_cols) > 1:
        corr_matrix = ret_df[valid_cols].corr(method="pearson").round(3).to_dict()
        spearman_matrix = ret_df[valid_cols].corr(method="spearman").round(3).to_dict()
    else:
        corr_matrix = {c: {c: 1.0} for c in valid_cols}
        spearman_matrix = {c: {c: 1.0} for c in valid_cols}

    redundancy_flags = []
    for i, c1 in enumerate(valid_cols):
        for j, c2 in enumerate(valid_cols):
            if i < j:
                rho = corr_matrix.get(c1, {}).get(c2, 0.0)
                if rho > correlation_threshold:
                    redundancy_flags.append({
                        "pair": f"{c1} <-> {c2}",
                        "correlation": rho,
                        "status": "REDUNDANT",
                        "recommendation": f"High collinearity (rho={rho:.2f} > {correlation_threshold}). Running both doubles leverage during drawdowns without diversification benefits."
                    })
                elif rho < 0.15:
                    redundancy_flags.append({
                        "pair": f"{c1} <-> {c2}",
                        "correlation": rho,
                        "status": "COMPLEMENTARY",
                        "recommendation": f"Excellent regime orthogonality (rho={rho:.2f}). Highly complementary return stream."
                    })

    if valid_cols:
        hrp_weights = compute_hrp_weights(ret_df[valid_cols])
        w_vec = np.array([hrp_weights[c] for c in valid_cols], dtype=float)
        blended_returns = ret_df[valid_cols].values @ w_vec
        blended_metrics = calculate_metrics(blended_returns, periods_per_year=float(TRADE_PERIODS_PER_YEAR))

        indiv_vols = [ret_df[c].std() for c in valid_cols]
        blended_vol = float(np.std(blended_returns))
        div_ratio = round(float(np.dot(w_vec, indiv_vols) / (blended_vol + 1e-8)), 2)
    else:
        hrp_weights = {}
        blended_metrics = {"sharpe": 0.0, "total_return_pct": 0.0, "max_drawdown_pct": 0.0, "equity_r_squared": 0.0}
        div_ratio = 1.0

    return {
        "strategies": valid_cols,
        "correlation_matrix": corr_matrix,
        "spearman_matrix": spearman_matrix,
        "individual_metrics": individual_metrics,
        "regime_breakdown": regime_breakdown,
        "hrp_weights": hrp_weights,
        "portfolio_ensemble": {
            "blended_sharpe": blended_metrics["sharpe"],
            "blended_total_return_pct": blended_metrics["total_return_pct"],
            "blended_max_drawdown_pct": blended_metrics["max_drawdown_pct"],
            "blended_r_squared": blended_metrics.get("equity_r_squared", 0.0),
            "diversification_ratio": div_ratio,
            "hrp_weights": hrp_weights,
            "correlation_threshold": correlation_threshold
        },
        "pairwise_analysis": redundancy_flags
    }


def print_ascii_report(report: Dict[str, Any]) -> None:
    """Prints a structured ASCII report of the portfolio correlation & ensemble metrics."""
    strats = report.get("strategies", [])
    print("=" * 72)
    print("📊 PORTFOLIO CYNIC: CORRELATION & REGIME ORTHOGONALITY")
    print("=" * 72)
    if not strats:
        print("No active strategies found to evaluate.")
        print("=" * 72)
        return

    corr = report.get("correlation_matrix", {})
    header = f"{'Strategy':<24}" + "".join(f"{s[:8]:>10}" for s in strats)
    print(header)
    print("-" * len(header))
    for s1 in strats:
        row = f"{s1:<24}"
        for s2 in strats:
            val = corr.get(s1, {}).get(s2, 0.0)
            row += f"{val:>10.2f}"
        print(row)
    print("=" * 72)
