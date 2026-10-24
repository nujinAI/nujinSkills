#!/usr/bin/env python3
"""
tools/strategy_search_engine.py - Multi-Paradigm Iterative Search & Backtesting Engine
Evaluates vectorized conditions across Trend, Momentum, Volatility Squeeze,
Pullback, and Reversion families (or user-specified rules) and writes the winning
rule specification and candidate trade returns into the isolated session workspace.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.constants import (  # noqa: E402
    DEFAULT_TIMEFRAME,
    FEE_BPS,
    SLIPPAGE_BPS,
    annualization_factor,
)
from server.indicators import compute_all_standard_features  # noqa: E402
from server.session_store import create_session, get_session_paths  # noqa: E402
from server.trial_ledger import fingerprint as _trial_fingerprint, record_trial  # noqa: E402
from tools.autoresearch_miner import ARCHETYPE_TEMPLATES  # noqa: E402
from tools.vectorized_screener import evaluate_rule_dict_on_df  # noqa: E402


def run_vectorized_backtest(
    df: pd.DataFrame,
    entry_signal: pd.Series,
    exit_signal: pd.Series,
    fee_bps: float = FEE_BPS,
    slippage_bps: float = SLIPPAGE_BPS,
    timeframe: str = DEFAULT_TIMEFRAME,
) -> Dict[str, Any]:
    """Computes vectorized bar-level return metrics with friction."""
    price = df["close"] if "close" in df.columns else df.iloc[:, 1]
    returns = price.pct_change().fillna(0)

    pos = 0
    positions = []
    for i in range(len(df)):
        if bool(entry_signal.iloc[i]) and pos == 0:
            pos = 1
        elif bool(exit_signal.iloc[i]) and pos == 1:
            pos = 0
        positions.append(pos)

    position = pd.Series(positions, index=df.index)
    trades_mask = position.diff().abs() > 0
    num_trades = int(trades_mask.sum())

    friction_per_trade = (fee_bps + slippage_bps) / 10000.0
    strategy_returns = position.shift(1).fillna(0.0) * returns
    strategy_returns[trades_mask] -= friction_per_trade

    cum_returns = (1 + strategy_returns).cumprod()
    peak = cum_returns.cummax()
    drawdown = (cum_returns - peak) / peak
    max_dd = abs(float(drawdown.min())) if len(drawdown) > 0 else 0.0

    mean_ret = float(strategy_returns.mean())
    std_ret = float(strategy_returns.std())
    sharpe = (mean_ret / std_ret * annualization_factor(timeframe)) if std_ret > 0 else 0.0

    return {
        "sharpe": float(sharpe),
        "max_drawdown": float(max_dd),
        "num_trades": int(num_trades),
        "total_return": float(cum_returns.iloc[-1] - 1) if len(cum_returns) > 0 else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="NujinSkills Multi-Paradigm Strategy Search Engine")
    parser.add_argument("--features", type=str, required=True, help="Path to features or OHLCV CSV")
    parser.add_argument("--target-sharpe", type=float, default=1.5, help="Target Sharpe Ratio threshold")
    parser.add_argument("--max-dd", type=float, default=0.03, help="Maximum allowed Drawdown (default: 0.03 = 3.0%)")
    parser.add_argument("--timeframe", type=str, default=DEFAULT_TIMEFRAME, help="Timeframe of the feature set (e.g. 15m, 1h, 4h)")
    parser.add_argument("--id", "--session", dest="session_id", type=str, default="", help="Session ID for isolated storage")
    parser.add_argument("--new-session", action="store_true", help="Create a fresh isolated session")
    args = parser.parse_args()

    print(f"🚀 Initializing Multi-Paradigm Search Engine on: {args.features}")
    if not os.path.exists(args.features):
        print(f"❌ Feature file not found: {args.features}")
        sys.exit(1)

    asset_slug = os.path.basename(args.features).replace(".csv", "")
    if args.new_session:
        meta = create_session(session_id=args.session_id or None, symbol=asset_slug, timeframe=args.timeframe, activate=True)
        sid = meta["session_id"]
    else:
        sid = args.session_id or None
    paths = get_session_paths(session_id=sid, symbol=asset_slug, timeframe=args.timeframe, create_if_missing=True)

    df = pd.read_csv(args.features)
    df.columns = [c.lower() for c in df.columns]
    if "ema_21" not in df.columns and {"open", "high", "low", "close", "volume"}.issubset(df.columns):
        df = compute_all_standard_features(df, window=20)
    print(f"  • Feature dataset shape: {df.shape}")

    best_result: Optional[Dict[str, Any]] = None
    best_returns: list[float] = []
    best_score = -999.0

    print("\n🔄 Evaluating Data-Mined TA-Lib IC Anomalies & Orthogonal Strategy Families...")
    candidate_templates: list[Dict[str, Any]] = []
    if os.path.exists(paths["briefing"]):
        try:
            with open(paths["briefing"], "r", encoding="utf-8") as f:
                bdata = json.load(f)
            for anom in bdata.get("empirical_anomalies_detected", [])[:12]:
                if anom.get("suggested_entry_long"):
                    hz = max(4, int(anom.get("alpha_half_life_bars", 10)))
                    candidate_templates.append({
                        "archetype": anom.get("archetype", "data_mined"),
                        "anomaly_id": anom.get("anomaly_id", "DATA_MINED"),
                        "entry_long": anom["suggested_entry_long"],
                        "entry_short": anom.get("suggested_entry_short", anom["suggested_entry_long"]),
                        "exit": f"bars >= {hz}",
                        "max_bars_held": hz,
                        "risk_per_trade_pct": 0.0045,
                        "bias": "DUAL",
                    })
        except Exception:
            pass

    for arch_name, template in ARCHETYPE_TEMPLATES.items():
        candidate_templates.append(dict(template))

    for template in candidate_templates:
        for sl in (0.012, 0.015, 0.018):
            for tp_mult in (2.0, 2.5):
                candidate = dict(template)
                candidate["timeframe"] = args.timeframe
                candidate["stoploss_pct"] = sl
                candidate["takeprofit_pct"] = round(sl * tp_mult, 4)
                try:
                    res = evaluate_rule_dict_on_df(df, candidate, fee_bps=FEE_BPS, slippage_bps=SLIPPAGE_BPS)
                except Exception:
                    continue

                record_trial(
                    kind="search_engine",
                    fingerprint=_trial_fingerprint(candidate),
                    metrics={"sharpe": res.get("sharpe"), "trades": res.get("trades")},
                    source="strategy_search_engine",
                    path=paths["trial_ledger"],
                )

                n_tr = int(res.get("trades", 0))
                sh = float(res.get("sharpe", 0.0))
                r2 = float(res.get("equity_r_squared", 0.0))
                dd = float(res.get("max_drawdown", 1.0))
                composite = sh + 1.5 * r2 - (5.0 * max(0.0, dd - args.max_dd))
                if n_tr >= 20 and composite > best_score:
                    best_score = composite
                    best_returns = list(res.get("trade_returns", []))
                    best_result = dict(candidate)
                    best_result["metrics"] = {k: v for k, v in res.items() if k != "trade_returns"}

    if best_result:
        with open(paths["best_rule"], "w", encoding="utf-8") as f:
            json.dump(best_result, f, indent=2)
        with open(paths["candidate_returns"], "w", encoding="utf-8") as f:
            json.dump(best_returns, f)

        m = best_result["metrics"]
        print("\n✨ Search Loop Completed!")
        print(f"  • Session ID:       {paths['session_id']}")
        print(f"  • Winning Family:   {best_result.get('archetype')}")
        print(f"  • Best Sharpe:      {m.get('sharpe', 0.0):.2f}")
        print(f"  • Equity R^2:       {m.get('equity_r_squared', 0.0):.3f}")
        print(f"  • Max Drawdown:     {m.get('max_drawdown', 0.0)*100:.2f}%")
        print(f"  • Total Trades:     {m.get('trades', 0)}")
        print(f"  • Saved rule spec:  {paths['best_rule']}")
    else:
        print("  ⚠️ No rule satisfied criteria in initial grid.")


if __name__ == "__main__":
    main()
