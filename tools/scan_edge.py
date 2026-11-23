#!/usr/bin/env python3
"""
tools/scan_edge.py - CPU-Native ML Anomaly, Sub-Era Invariance & MFE/MAE Geometry Scanner.

Replaces hardcoded indicator guessing with a 37-primitive stationary microstructure factory,
ExtraTrees + Shallow Surrogate Tree 2D conditional rule mining, 5-slice Sub-Era Invariance
filtering (preventing 70/30 OOS regime collapse), and 2D MFE/MAE plateau geometry optimization.

Usage:
    python tools/scan_edge.py --symbol OANDA:XAUUSD --tf 15m --days 60
    python tools/scan_edge.py --symbol BINANCE:BTCUSDT --tf 1h --days 90 --json
"""
import os
import sys
import time
import argparse
import json
import numpy as np
import pandas as pd

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.data import fetch_ohlcv, resolve_market_symbol, bars_for_days
from core.discovery import mine_conditional_anomalies


def parse_args():
    parser = argparse.ArgumentParser(description="NujinSkills Pure Mathematical Basis & Sub-Era Invariant Scanner")
    parser.add_argument("--symbol", type=str, default="OANDA:XAUUSD", help="Market ticker (e.g. OANDA:XAUUSD, BINANCE:BTCUSDT)")
    parser.add_argument("--tf", type=str, default="15m", help="Timeframe (e.g. 1m, 5m, 15m, 1h, 4h, 1d)")
    parser.add_argument("--days", type=int, default=60, help="Days of history (first 66.7%% used for In-Sample, 33.3%% locked as Blind OOS)")
    parser.add_argument("--style", type=str, choices=["auto", "scalp", "day", "swing", "invest"], default="auto",
                        help="User mandate envelope (auto-calibrates horizons, friction multiple, and MDD99 risk budget)")
    parser.add_argument("--max-mdd", type=float, default=None, help="Target Monte Carlo MDD99 ceiling as decimal (e.g. 0.020 for 2.0%%)")
    parser.add_argument("--horizons", type=str, default="3,6,12,24", help="Comma-separated forward bar horizons")
    parser.add_argument("--top-k", type=int, default=5, help="Number of top verified conditional anomalies to output")
    parser.add_argument("--output", type=str, default="data/latest_edge_scan.json", help="Path to save discovery JSON")
    parser.add_argument("--json", action="store_true", help="Output raw JSON to stdout")
    return parser.parse_args()


def _bars_for_days(tf: str, days: int) -> int:
    """Delegates to core.data.bars_for_days (SSOT matching backtest_engine.py)."""
    return bars_for_days(tf, days, buffer=1.15, min_bars=500, max_bars=15000)


def main():
    t0 = time.time()
    args = parse_args()
    sym = resolve_market_symbol(args.symbol)
    style_presets = {
        "scalp":  {"horizons": [2, 4, 8, 12], "min_fric": 3.5, "mdd99": 0.018},
        "day":    {"horizons": [3, 6, 12, 24], "min_fric": 3.0, "mdd99": 0.020},
        "swing":  {"horizons": [6, 12, 24, 48], "min_fric": 3.0, "mdd99": 0.022},
        "invest": {"horizons": [10, 20, 40, 60], "min_fric": 2.5, "mdd99": 0.024},
        "auto":   {"horizons": [int(h.strip()) for h in args.horizons.split(",") if h.strip()], "min_fric": 3.0, "mdd99": 0.021},
    }
    preset = style_presets.get(args.style, style_presets["auto"])
    horizons = preset["horizons"] if args.horizons == "3,6,12,24" else [int(h.strip()) for h in args.horizons.split(",") if h.strip()]
    target_mdd99 = args.max_mdd if args.max_mdd is not None else preset["mdd99"]
    min_fric_mult = preset["min_fric"]

    bars_needed = _bars_for_days(args.tf, args.days)
    df = fetch_ohlcv(sym, timeframe=args.tf, count=bars_needed)

    if df is None or len(df) < 150:
        print(f"[-] Insufficient market data fetched for {sym} ({args.tf}).", file=sys.stderr)
        sys.exit(1)

    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    elif df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    # Align calendar window with run_backtest_audit.py --days <days>
    cutoff_ts = df.index[-1] - pd.Timedelta(days=args.days)
    df_win = df[df.index >= cutoff_ts].copy()
    if len(df_win) >= 150:
        df = df_win

    # Strictly isolate In-Sample: first 66.7% of history (matching backtest_engine split)
    split_idx = int(len(df) * 0.667)
    df_is = df.iloc[:split_idx].copy()

    report = mine_conditional_anomalies(
        df_is=df_is,
        symbol=sym,
        horizons=horizons,
        top_k=args.top_k,
        target_mdd99_pct=target_mdd99,
        min_friction_mult=min_fric_mult
    )
    elapsed = round(time.time() - t0, 2)
    report["timeframe"] = args.tf
    report["days"] = args.days
    report["target_mdd99"] = target_mdd99
    report["blind_oos_bars_locked"] = len(df) - len(df_is)
    report["cpu_elapsed_sec"] = elapsed

    for anom in report.get("verified_conditional_anomalies", []):
        anom["synthesizer_cli"] = anom["synthesizer_cli"].replace(
            f"--symbol {sym}", f"--symbol {sym} --tf {args.tf}"
        )

    out_path = os.path.join(PROJECT_ROOT, args.output) if not os.path.isabs(args.output) else args.output
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    tmp_out = f"{out_path}.{os.getpid()}.tmp"
    with open(tmp_out, "w") as f:
        json.dump(report, f, indent=2)
    os.replace(tmp_out, out_path)

    if args.json:
        print(json.dumps(report, indent=2))
        return

    print("=" * 94)
    print(f"NUJIN ML MICROSTRUCTURE & SUB-ERA INVARIANT ANOMALY SCANNER | {sym} [{args.tf}]")
    print(f"In-Sample: {len(df_is)} bars (5 Sub-Eras) | Blind OOS Locked: {len(df) - len(df_is)} bars | CPU Time: {elapsed}s")
    print(f"Primitives Evaluated: {report['total_primitives_scanned']} stationary mathematical ratios (Zero Raw Price Bias)")
    print("=" * 94)

    print("\n[STAGE 1] TOP STATIONARY PRIMITIVES (UNIVARIATE + EXTRATREES IMPORTANCE)")
    print(f"{'Primitive Name':<28} | {'Best H':<6} | {'Rank IC':<8} | {'t-stat':<6} | {'Sub-Era':<8} | {'ML Imp':<7}")
    print("-" * 94)
    for u in report.get("top_univariate_features", []):
        print(
            f"{u['feature']:<28} | {u['best_horizon']:<6} | {u['rank_ic']:>7.4f}  | "
            f"{u['t_stat']:>5.2f}  | {u['sub_era_consistency']*100:>5.0f}%   | {u['ml_importance']:>6.4f}"
        )

    anomalies = report.get("verified_conditional_anomalies", [])
    print("\n" + "=" * 94)
    print(f"[STAGE 2 & 3] VERIFIED 2D CONDITIONAL ANOMALIES & MFE/MAE PLATEAU GEOMETRY ({len(anomalies)} SURVIVORS)")
    print("=" * 94)

    if not anomalies:
        print("[-] Zero conditional anomalies survived the 5-Era Invariance + 3x Friction + Permutation hurdles.")
        print("    Recommendation: Switch timeframe or asset rather than forcing an overfitted strategy.")
        return

    for idx, a in enumerate(anomalies, start=1):
        geom = a["geometry"]
        gm = geom["metrics"]
        print(f"\n  #{idx} ANOMALY [{a['rule_id']}] — Combined Score: {a['combined_edge_score']}")
        print(f"     Mathematical Rule : {a['mathematical_rule_summary']}")
        print(f"     Primary Mechanism : {a['primary_description']}")
        if a["regime_feature"]:
            print(f"     Regime Condition  : {a['regime_feature']} {a['regime_op']} {a['regime_thresh']} ({a['regime_description']})")
        print(
            f"     Statistical Proof : t-stat={a['t_stat']} | Perm p={a['perm_p_val']} | "
            f"Sub-Era Invariance={a['positive_eras']} ({a['sub_era_consistency']*100:.0f}%) | "
            f"Friction Multiple={a['friction_hurdle_multiple']}x"
        )
        print(
            f"     Plateau Geometry  : SL={geom['optimal_sl_atr_mult']}x ATR | TP={geom['optimal_tp_atr_mult']}x ATR | "
            f"Recommended 1R Risk={geom['recommended_risk_pct_1r']*100:.2f}%"
        )
        print(
            f"     Exact Simulation  : Trades={gm['num_trades']} | WinRate={gm['win_rate']*100:.1f}% | "
            f"Expectancy={gm['expectancy_r']:+.3f}R | Equity R²={gm['equity_r2']:.3f} | "
            f"Int-WF={gm['internal_wf_retention']*100:.0f}% | Regimes={gm['regime_survival_ratio']*100:.0f}% | Tail={gm['tail_ratio']:.2f}"
        )
        print(f"     Synthesize Cmd    : {a['synthesizer_cli']}")

    print("\n" + "=" * 94)
    print(f"[+] Saved full discovery report to: {out_path}")
    print("[+] Tip: Run `python tools/build_strategy.py --name <Name> --from-scan-rank 1` to synthesize #1 directly.")
    print("=" * 94)


if __name__ == "__main__":
    main()
