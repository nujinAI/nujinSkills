#!/usr/bin/env python3
"""
tools/data_miner.py - Unified Empirical Anomaly & Feature Mining CLI
Analyzes input time series across all 6 orthogonal edge families, computes Lo-MacKinlay
Variance Ratios & Hurst regime characteristics, and engineers the full composable
feature and indicator matrix into the isolated session workspace.
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.session_store import create_session, get_session_paths
from tools.anomaly_scanner import generate_empirical_briefing, print_ascii_briefing
from tools.feature_miner import process_features


def calculate_variance_ratio(series: pd.Series, lag: int = 2) -> float:
    """Calculates Lo-MacKinlay Variance Ratio."""
    returns = np.log(series / series.shift(1)).dropna()
    n = len(returns)
    if n <= lag + 1:
        return 1.0
    mu = returns.mean()
    var_1 = np.sum((returns - mu) ** 2) / (n - 1)
    if var_1 < 1e-12:
        return 1.0
    returns_k = np.log(series / series.shift(lag)).dropna()
    var_k = np.sum((returns_k - lag * mu) ** 2) / (n - lag)
    return float(var_k / (lag * var_1))


def main() -> None:
    parser = argparse.ArgumentParser(description="NujinSkills Empirical Anomaly & Feature Miner")
    parser.add_argument("--input", type=str, required=True, help="Input CSV file path")
    parser.add_argument("--output", type=str, default=None, help="Output features CSV file path (defaults to session features.csv)")
    parser.add_argument("--id", "--session", dest="session_id", type=str, default="", help="Session ID for isolated storage")
    parser.add_argument("--new-session", action="store_true", help="Create a fresh isolated session")
    parser.add_argument("--window", type=int, default=20, help="Rolling window size (default: 20)")
    parser.add_argument("--htf-data", type=str, default=None, help="Optional Higher Timeframe CSV")
    parser.add_argument("--indicators", type=str, default="", help="Optional comma-separated dynamic indicators")
    parser.add_argument("--custom", type=str, default="", help="Optional JSON dict of custom indicator formulas")
    args = parser.parse_args()

    asset_slug = os.path.basename(args.input).replace(".csv", "")
    if args.new_session:
        meta = create_session(session_id=args.session_id or None, symbol=asset_slug, activate=True)
        sid = meta["session_id"]
    else:
        sid = args.session_id or None

    paths = get_session_paths(session_id=sid, symbol=asset_slug, create_if_missing=True)
    out_features = args.output or paths["features"]

    # 1. Generate Multi-Paradigm Statistical Briefing in session workspace
    briefing = generate_empirical_briefing(
        data_path=args.input,
        output_path=paths["briefing"],
        session_id=paths["session_id"],
    )
    print_ascii_briefing(briefing)

    # 2. Extract Composable Standard + Custom Features
    import json
    extra_inds = [t.strip() for t in args.indicators.split(",") if t.strip()] if args.indicators else None
    custom_dict = json.loads(args.custom) if args.custom else None

    process_features(
        input_path=args.input,
        output_path=out_features,
        window=args.window,
        htf_path=args.htf_data,
        extra_indicators=extra_inds,
        custom_formulas=custom_dict,
    )


if __name__ == "__main__":
    main()
