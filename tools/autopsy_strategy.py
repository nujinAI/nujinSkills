#!/usr/bin/env python3
"""
tools/autopsy_strategy.py - ML Trade Autopsy & Cynic Gate Failure Diagnostic Tool.

Replaces blind LLM parameter guessing when a strategy fails any of the 8 Cynic Gates.
Strictly analyzes ONLY In-Sample trades (never leaking Blind Out-of-Sample data) using
a shallow DecisionTree surrogate model on the 37 stationary primitives to isolate the
exact market regime or geometry flaw causing gate failure.

Usage:
    python tools/autopsy_strategy.py --audit-json data/audit_report.json
"""
import os
import sys
import json
import argparse
import numpy as np
import pandas as pd

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.data import fetch_ohlcv, resolve_market_symbol
from core.feature_factory import compute_all_features, FEATURE_METADATA


def parse_args():
    parser = argparse.ArgumentParser(description="NujinSkills ML Trade Autopsy & Gate Remediation")
    parser.add_argument("--audit-json", type=str, default="data/audit_report.json", help="Path to audit_report.json")
    parser.add_argument("--json", action="store_true", help="Output raw JSON diagnosis")
    return parser.parse_args()


def _parse_ts(ts_raw):
    if ts_raw is None:
        return None
    if isinstance(ts_raw, (int, float)):
        unit = "ms" if ts_raw > 1e11 else "s"
        return pd.to_datetime(ts_raw, unit=unit, utc=True)
    return pd.to_datetime(ts_raw, utc=True)


def main():
    args = parse_args()
    audit_path = os.path.join(PROJECT_ROOT, args.audit_json) if not os.path.isabs(args.audit_json) else args.audit_json

    if not os.path.exists(audit_path):
        print(f"[-] Audit report not found at {audit_path}. Run `python tools/run_backtest_audit.py` first.", file=sys.stderr)
        sys.exit(1)

    with open(audit_path, "r") as f:
        audit = json.load(f)

    strat_name = audit.get("strategy", "UnknownStrategy")
    summary = audit.get("summary", {})
    gates = audit.get("falsification_gates", {})
    trades = audit.get("trades_detail", [])
    symbol = resolve_market_symbol(audit.get("symbol") or summary.get("symbol") or "OANDA:XAUUSD")
    tf = audit.get("timeframe") or summary.get("timeframe") or "15m"

    failed_gates = []
    for g_key, g_val in gates.items():
        if g_key == "gates_summary":
            continue
        if isinstance(g_val, dict) and g_val.get("status") != "PASS":
            failed_gates.append((g_key, g_val))

    # Extract In-Sample trades only (first 66.7% of trade sequence) to prevent OOS leakage
    n_total_trades = len(trades)
    is_cutoff = max(1, int(n_total_trades * 0.667))
    is_trades = trades[:is_cutoff]

    tree_filter_recommendation = None
    try:
        from sklearn.tree import DecisionTreeRegressor
        candles_count = int(summary.get("candles_count") or 4000)
        df = fetch_ohlcv(symbol, timeframe=tf, count=max(1500, candles_count + 200))
        if df is not None and len(df) > 100 and len(is_trades) >= 10:
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index, utc=True)
            elif df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            else:
                df.index = df.index.tz_convert("UTC")

            feat_df = compute_all_features(df)
            X_rows = []
            y_vals = []

            for t in is_trades:
                ts_raw = t.get("entry_time") or t.get("timestamp") or t.get("time")
                pnl = float(t.get("pnl_pct") or t.get("pnl") or t.get("return_pct") or 0.0)
                ts = _parse_ts(ts_raw)
                if ts is None:
                    continue
                pos = feat_df.index.get_indexer([ts], method="nearest")[0]
                if 0 <= pos < len(feat_df):
                    X_rows.append(feat_df.iloc[pos].values)
                    y_vals.append(pnl)

            if len(X_rows) >= 10:
                X_mat = np.nan_to_num(np.array(X_rows, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
                y_arr = np.array(y_vals, dtype=float)
                tree = DecisionTreeRegressor(
                    max_depth=1,
                    min_samples_leaf=max(4, len(y_arr) // 4),
                    random_state=42
                )
                tree.fit(X_mat, y_arr)
                if tree.tree_.node_count > 1:
                    f_idx = tree.tree_.feature[0]
                    f_name = feat_df.columns[f_idx]
                    thresh = round(float(tree.tree_.threshold[0]), 4)
                    left_mean = float(tree.tree_.value[tree.tree_.children_left[0]][0, 0])
                    right_mean = float(tree.tree_.value[tree.tree_.children_right[0]][0, 0])
                    keep_op = "<" if left_mean > right_mean else ">"
                    kept_mean = max(left_mean, right_mean)
                    dropped_mean = min(left_mean, right_mean)
                    tree_filter_recommendation = {
                        "feature": f_name,
                        "description": FEATURE_METADATA.get(f_name, {}).get("description", ""),
                        "keep_operator": keep_op,
                        "threshold": thresh,
                        "kept_subset_mean_pnl": round(kept_mean, 4),
                        "dropped_subset_mean_pnl": round(dropped_mean, 4),
                        "cli_flags": f"--extra-filter-feature {f_name} --extra-filter-op '{keep_op}' --extra-filter-thresh {thresh}"
                    }
    except Exception:
        pass

    prescriptions = []
    for g_key, g_info in failed_gates:
        val_str = str(g_info.get("reason") or g_info.get("detail") or g_info.get("value") or g_info.get("status") or "")
        if "gate_3" in g_key or "monte_carlo" in g_key:
            mdd99 = float(summary.get("mdd_99", 0.0) or 0.0)
            prescriptions.append({
                "gate": g_key,
                "failure": val_str,
                "root_cause": "Fat-tail loss clustering or asymmetric payoff ratio (Tail Ratio > 2.5 or MDD99 > 3.0%).",
                "exact_fix": (
                    "1. Tighten TP-to-SL ratio (e.g. increase --sl-mult by +0.25 or lower --tp-mult by -0.5 to raise win-rate and reduce p95 loss tail vs median gain).\n"
                    f"2. If MDD99 ({mdd99*100:.2f}%) > 3.0%, scale --risk-pct down by factor {(0.024 / max(mdd99, 0.025)):.2f}x."
                )
            })
        elif "gate_4" in g_key or "walkforward" in g_key or "walk_forward" in g_key:
            prescriptions.append({
                "gate": g_key,
                "failure": val_str,
                "root_cause": "Out-of-Sample Walk-Forward decay: primary trigger fired during an unfavorable volatility/entropy state.",
                "exact_fix": (
                    f"Apply ML Autopsy Regime Gate ({tree_filter_recommendation['cli_flags']}) OR synthesize the next Sub-Era Invariant rank (`--from-scan-rank 2`)."
                    if tree_filter_recommendation else
                    "Synthesize the next Sub-Era Invariant anomaly (`--from-scan-rank 2`) from `data/latest_edge_scan.json`."
                )
            })
        elif "gate_5" in g_key or "regime" in g_key:
            prescriptions.append({
                "gate": g_key,
                "failure": val_str,
                "root_cause": "Strategy bleeds in one of Bull/Bear/Range slices.",
                "exact_fix": (
                    f"Add ML Autopsy Regime Filter: {tree_filter_recommendation['cli_flags']}"
                    if tree_filter_recommendation else
                    "Add volatility/efficiency gate (`--regime-feature ker_10` or `vol_ratio_5_30`)."
                )
            })
        elif "gate_6" in g_key or "friction" in g_key:
            prescriptions.append({
                "gate": g_key,
                "failure": val_str,
                "root_cause": "Stop distance is too tight relative to broker spread/slippage floor.",
                "exact_fix": "Increase `--sl-mult` to >= 2.0 (and proportionally `--tp-mult`) or move up one timeframe (e.g. 5m -> 15m / 1h)."
            })
        else:
            prescriptions.append({
                "gate": g_key,
                "failure": val_str,
                "root_cause": "Structural instability or lumpy trade distribution.",
                "exact_fix": (
                    f"Apply ML Autopsy Filter: {tree_filter_recommendation['cli_flags']}"
                    if tree_filter_recommendation else
                    "Rebuild using the next highest-scoring plateau anomaly from `scan_edge.py`."
                )
            })

    report = {
        "strategy": strat_name,
        "symbol": symbol,
        "timeframe": tf,
        "in_sample_trades_analyzed": len(is_trades),
        "failed_gates_count": len(failed_gates),
        "ml_tree_regime_diagnosis": tree_filter_recommendation,
        "gate_prescriptions": prescriptions,
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return

    print("=" * 84)
    print(f"NUJIN ML TRADE AUTOPSY & GATE REMEDIATION REPORT | {strat_name}")
    print(f"In-Sample Trades Analyzed: {len(is_trades)} (Blind OOS Strictly Isolated)")
    print("=" * 84)

    if not failed_gates:
        print("[+] All 8 Cynic Gates PASSED. No remediation required.")
        return

    if tree_filter_recommendation:
        tf_rec = tree_filter_recommendation
        print("\n[ML SHALLOW-TREE IN-SAMPLE TRADE AUTOPSY]")
        print(f"  Discovered Splitting Feature : {tf_rec['feature']} ({tf_rec['description']})")
        print(f"  Winning Trade Regime State   : {tf_rec['feature']} {tf_rec['keep_operator']} {tf_rec['threshold']}")
        print(f"  Kept vs Dropped Mean PnL     : {tf_rec['kept_subset_mean_pnl']:+.4f}% vs {tf_rec['dropped_subset_mean_pnl']:+.4f}%")
        print(f"  Exact Builder CLI Flag       : {tf_rec['cli_flags']}")

    print("\n[FAILED CYNIC GATES & PRESCRIPTIVE REMEDIATION]")
    print("-" * 84)
    for p in prescriptions:
        print(f"  * Gate Failed : {p['gate']} ({p['failure']})")
        print(f"    Root Cause  : {p['root_cause']}")
        print(f"    Exact Fix   : {p['exact_fix']}\n")
    print("=" * 84)


if __name__ == "__main__":
    main()
