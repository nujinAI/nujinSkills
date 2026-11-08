#!/usr/bin/env python3
"""
tools/scan_edge.py - Universal Empirical Edge & Anomaly Discovery CLI Tool.

Enables the AI or human quant to test ANY candidate hypothesis or formula across
forward horizons, measuring Information Coefficient (Rank IC), t-stat, and
friction hurdle clearance without bias or hardcoded indicators.

Usage:
    python tools/scan_edge.py --symbol OANDA:XAUUSD --tf 15m --days 60
    python tools/scan_edge.py --symbol BINANCE:BTCUSDT --tf 1h --expr "close / ta_sma(close, 20) - 1.0"
"""
import os
import sys
import argparse
import json
import numpy as np
import pandas as pd

# Ensure nujinSkills is in path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.data import fetch_ohlcv, resolve_market_symbol
from core.discovery import scan_candidate_series, compute_forward_returns, evaluate_feature_predictive_power, audit_edge_friction_clearance


def parse_args():
    parser = argparse.ArgumentParser(description="Universal Quantitative Edge & Anomaly Discovery Scanner")
    parser.add_argument("--symbol", type=str, default="OANDA:XAUUSD", help="Market ticker (e.g. OANDA:XAUUSD, BINANCE:BTCUSDT, CME_MINI:ES1!)")
    parser.add_argument("--tf", type=str, default="15m", help="Timeframe (e.g. 1m, 5m, 15m, 1h, 4h, 1d)")
    parser.add_argument("--days", type=int, default=60, help="Days of authentic history for In-Sample discovery")
    parser.add_argument("--horizons", type=str, default="1,3,5,12,24", help="Comma-separated forward bar horizons")
    parser.add_argument("--json", action="store_true", help="Output raw JSON analysis")
    return parser.parse_args()


def main():
    args = parse_args()
    sym = resolve_market_symbol(args.symbol)
    horizons = [int(h.strip()) for h in args.horizons.split(",") if h.strip()]

    # Ingest data (In-Sample calibration window)
    bars_needed = max(1000, args.days * (1440 // 15) if "15m" in args.tf else args.days * 100)
    df = fetch_ohlcv(sym, timeframe=args.tf, count=bars_needed)
    
    if df is None or len(df) < 100:
        print(f"[-] Insufficient market data fetched for {sym} ({args.tf}).", file=sys.stderr)
        sys.exit(1)

    # Strictly isolate In-Sample: first 66.7% of history
    split_idx = int(len(df) * 0.667)
    df_is = df.iloc[:split_idx].copy()

    # Generic candidate hypotheses (Illustrative baseline primitives)
    close = df_is["close"].astype(float)
    high = df_is["high"].astype(float)
    low = df_is["low"].astype(float)
    vol = df_is["volume"].astype(float) if "volume" in df_is.columns else pd.Series(1.0, index=df_is.index)

    # 1. Price Momentum / Return
    roc_5 = (close - close.shift(5)) / close.shift(5)
    roc_20 = (close - close.shift(20)) / close.shift(20)

    # 2. Mean Reversion / Z-Score of Distance to Moving Average
    sma_20 = close.rolling(20).mean()
    dist_sma_20 = (close - sma_20) / (close.rolling(20).std() + 1e-8)

    # 3. High-Low Range Position (Stochastic-style location)
    hh_20 = high.rolling(20).max()
    ll_20 = low.rolling(20).min()
    range_pos_20 = (close - ll_20) / ((hh_20 - ll_20) + 1e-8)

    # 4. Volatility Expansion / True Range Ratio
    tr = np.maximum(high - low, np.maximum(abs(high - close.shift(1)), abs(low - close.shift(1))))
    atr_14 = tr.rolling(14).mean()
    vol_ratio = tr / (atr_14 + 1e-8)

    candidate_features = {
        "momentum_roc_5": roc_5,
        "momentum_roc_20": roc_20,
        "zscore_dist_sma20": dist_sma_20,
        "channel_range_pos20": range_pos_20,
        "volatility_expansion_ratio": vol_ratio
    }

    results = scan_candidate_series(
        df=df_is,
        features=candidate_features,
        symbol=sym,
        horizons=horizons
    )

    if args.json:
        print(json.dumps(results, indent=2))
        return

    print("=" * 80)
    print(f"NUJIN EMPIRICAL EDGE & ANOMALY SCANNER | {sym} [{args.tf}]")
    print(f"In-Sample Calibration Window: {len(df_is)} bars (Blind OOS locked: {len(df) - len(df_is)} bars)")
    print("=" * 80)
    print(f"{'Feature Hypothesis':<28} | {'H':<3} | {'Rank IC':<8} | {'t-stat':<6} | {'Hurdle':<8} | {'Verdict'}")
    print("-" * 80)

    for feat_name, h_dict in results.items():
        for h_key, m in h_dict.items():
            h_val = h_key.replace("horizon_", "")
            ic = m["rank_ic"]
            t = m["t_stat"]
            h_mult = m["friction_audit"]["friction_hurdle_multiple"]
            verdict = "TRADABLE EDGE" if m["has_tradable_edge"] else ("Noise" if not m["is_statistically_significant"] else "Friction Drag")
            print(f"{feat_name:<28} | {h_val:<3} | {ic:>7.4f}  | {t:>5.2f}  | {h_mult:>6.1f}x  | {verdict}")

    print("=" * 80)
    print("Note: Tradable Edge requires |Rank IC| >= 0.02, |t-stat| >= 2.0, and gross move >= 3x friction.")


if __name__ == "__main__":
    main()
