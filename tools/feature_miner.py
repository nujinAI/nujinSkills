#!/usr/bin/env python3
"""
tools/feature_miner.py
─────────────────────────────────────────────────────────────────────────────
Composable Standard + Custom Indicator & Multi-Timeframe Feature Miner.

Powered by `server/indicators.py`:
  • Computes all standard trend, momentum, volatility, volume, and market
    structure indicators (`SMA`, `EMA`, `WMA`, `HMA`, `KAMA`, `Supertrend`,
    `Donchian` (strictly causal shift(1)), `Bollinger`, `Keltner`, `TTM Squeeze`,
    `RSI`, `MACD`, `Stochastic`, `CCI`, `Williams %R`, `ROC`, `ADX`, `ATR`,
    `Z-Score`, `Hurst Proxy`, `Slope`, `AVWAP`, `OBV`, `CMF`, and SMC/VSA features).
  • Supports arbitrary parameterized indicator columns (`--indicators "ema_34,hma_55,rsi_5"`).
  • Supports user-defined custom indicator formulas (`--custom '{"spread_z": "(ema_9 - ema_21) / atr_14"}'`).
  • Supports Higher-Timeframe (HTF) as-of backward joins with zero lookahead bias.
  • Writes strictly to the isolated session workspace (`.nujin/sessions/<session_id>/features.csv`)
    unless an explicit `--output` path is provided.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Optional

import pandas as pd
import polars as pl

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.indicators import compute_all_standard_features, ensure_dynamic_indicators
from server.session_store import create_session, get_session_paths


def extract_ohlcv_features(
    df: pl.DataFrame | pd.DataFrame,
    window: int = 20,
    extra_indicators: Optional[List[str]] = None,
    custom_formulas: Optional[Dict[str, str]] = None,
) -> pl.DataFrame:
    """
    Computes the full standard indicator and feature matrix (plus any dynamic or
    custom user formulas) and returns a Polars DataFrame.
    """
    was_polars = isinstance(df, pl.DataFrame)
    pdf = df.to_pandas() if was_polars else df.copy()
    pdf.columns = [c.lower() for c in pdf.columns]

    required_cols = ["open", "high", "low", "close", "volume"]
    for col in required_cols:
        if col not in pdf.columns:
            raise ValueError(f"Missing required column in CSV: {col}")

    pdf = compute_all_standard_features(pdf, window=window)

    if extra_indicators:
        pdf = ensure_dynamic_indicators(pdf, extra_indicators)

    if custom_formulas:
        # First ensure any dynamic tokens referenced inside custom formulas exist
        pdf = ensure_dynamic_indicators(pdf, list(custom_formulas.values()))
        for name, expr in custom_formulas.items():
            clean_name = name.strip().lower()
            try:
                val = pdf.eval(expr)
                if isinstance(val, pd.Series) and val.dtype == bool:
                    val = val.astype(int)
                pdf[clean_name] = val
            except Exception as e:
                raise ValueError(f"Failed to evaluate custom indicator '{clean_name}' = '{expr}': {e}") from e

    return pl.from_pandas(pdf)


def process_features(
    input_path: str,
    output_path: str,
    window: int = 20,
    htf_path: Optional[str] = None,
    htf_prefix: str = "htf_",
    extra_indicators: Optional[List[str]] = None,
    custom_formulas: Optional[Dict[str, str]] = None,
) -> pl.DataFrame:
    print(f"[FeatureMiner] Reading OHLCV data from {input_path}...")
    df = pl.read_csv(input_path)
    df = extract_ohlcv_features(
        df,
        window=window,
        extra_indicators=extra_indicators,
        custom_formulas=custom_formulas,
    )

    # Multi-Timeframe (MTF) Higher-Timeframe Confluence Join (strictly causal backward join_asof)
    if htf_path and os.path.exists(htf_path):
        print(f"[FeatureMiner] Merging Higher-Timeframe (HTF) context from {htf_path}...")
        htf_raw = pl.read_csv(htf_path)
        htf_feat = extract_ohlcv_features(
            htf_raw,
            window=window,
            extra_indicators=extra_indicators,
            custom_formulas=custom_formulas,
        )

        join_col = (
            "timestamp"
            if "timestamp" in df.columns and "timestamp" in htf_feat.columns
            else ("time" if "time" in df.columns and "time" in htf_feat.columns else None)
        )

        if join_col:
            df = df.with_columns(pl.col(join_col).cast(pl.Int64)).sort(join_col)
            htf_feat = htf_feat.with_columns(pl.col(join_col).cast(pl.Int64)).sort(join_col)

            rename_map = {c: f"{htf_prefix}{c}" for c in htf_feat.columns if c != join_col}
            htf_feat = htf_feat.rename(rename_map)

            df = df.join_asof(htf_feat, on=join_col, strategy="backward")

            fill_cols = [pl.col(c).forward_fill().backward_fill() for c in rename_map.values()]
            if fill_cols:
                df = df.with_columns(fill_cols)

            print(f"[FeatureMiner] Joined {len(rename_map)} HTF features with zero lookahead bias.")
        else:
            print("[FeatureMiner] Warning: No matching 'timestamp' or 'time' key found for HTF join.")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    df.write_csv(output_path)
    print(f"[FeatureMiner] Success! Features written to {output_path} ({len(df)} rows, {len(df.columns)} columns)")
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NujinSkills Composable Feature & Indicator Miner")
    parser.add_argument("--input", required=True, help="Input CSV file path with OHLCV data")
    parser.add_argument(
        "--id", "--experiment", "--session",
        dest="session_id",
        type=str,
        default="",
        help="Session ID to isolate features in .nujin/sessions/<id>/features.csv",
    )
    parser.add_argument("--new-session", action="store_true", help="Create a fresh isolated session for this run")
    parser.add_argument("--output", default=None, help="Explicit output CSV path")
    parser.add_argument("--window", type=int, default=20, help="Rolling window size (default: 20)")
    parser.add_argument("--htf-data", default=None, help="Optional Higher Timeframe (HTF) CSV for multi-timeframe confluence")
    parser.add_argument("--htf-prefix", default="htf_", help="Column prefix for Higher Timeframe features (default: htf_)")
    parser.add_argument(
        "--indicators",
        type=str,
        default="",
        help="Comma-separated list of dynamic parameterized indicators to compute (e.g. 'ema_34,hma_55,rsi_5,donchian_upper_40')",
    )
    parser.add_argument(
        "--custom",
        type=str,
        default="",
        help='JSON object of custom indicator formulas, e.g. \'{"trend_gap": "(ema_9 - ema_21) / atr_14"}\'',
    )
    args = parser.parse_args()

    asset_slug = os.path.basename(args.input).replace(".csv", "")
    if args.new_session:
        meta = create_session(session_id=args.session_id or None, symbol=asset_slug, activate=True)
        sid = meta["session_id"]
    else:
        sid = args.session_id or None

    paths = get_session_paths(session_id=sid, symbol=asset_slug, create_if_missing=True)
    out_path = args.output or paths["features"]

    extra_inds = [tok.strip() for tok in args.indicators.split(",") if tok.strip()] if args.indicators else None
    custom_dict: Optional[Dict[str, str]] = None
    if args.custom:
        custom_dict = json.loads(args.custom)

    process_features(
        args.input,
        out_path,
        window=args.window,
        htf_path=args.htf_data,
        htf_prefix=args.htf_prefix,
        extra_indicators=extra_inds,
        custom_formulas=custom_dict,
    )
