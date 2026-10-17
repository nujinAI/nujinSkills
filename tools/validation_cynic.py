#!/usr/bin/env python3
"""
validation_cynic.py — thin CLI shim over server.cynic_gates.

All gate math now lives in `server/cynic_gates.py` (single source of truth).
This module exists only to preserve the historical import path
(`from tools.validation_cynic import compute_dsr, ...`) used by
server/backtest_engine.py and server/strategy_executor.py.

Do NOT re-implement any gate here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.cynic_gates import (  # noqa: E402  (canonical implementations, re-exported)
    compute_dsr,
    compute_equity_linearity,
    compute_cusum_degradation,
    evaluate_gates,
    format_matrix,
    verify_monte_carlo,
    verify_parameter_stability,
)

__all__ = [
    "compute_dsr",
    "compute_equity_linearity",
    "compute_cusum_degradation",
    "evaluate_gates",
    "verify_monte_carlo",
    "verify_parameter_stability",
    "run_monte_carlo",
    "run_parameter_stability",
]


# ── Backwards-compatible aliases ─────────────────────────────────────────────
# Historical name -> canonical implementation. Kept so existing callers
# (server/backtest_engine.py) keep working without carrying their own math.

def run_monte_carlo(returns, num_simulations: int = 1000) -> dict:
    return verify_monte_carlo(returns, num_simulations=num_simulations)


def run_parameter_stability(param_grid_json, observed_sr: float) -> dict:
    """
    Historically this synthesised a parameter matrix from `observed_sr` and so
    could never fail. It now returns INCONCLUSIVE unless genuinely perturbed
    results are supplied, which is the honest answer given only a grid spec.
    """
    matrix = None
    if isinstance(param_grid_json, dict):
        candidate = param_grid_json.get("metric_matrix")
        if isinstance(candidate, list) and candidate:
            matrix = candidate
    return verify_parameter_stability(metric_matrix=matrix, observed_sr=observed_sr)


def _resolve_returns(args) -> np.ndarray:
    """Load a return series from --returns, --strategy, or the default location."""
    if args.strategy:
        try:
            from server.backtest_engine import run_real_backtest
            bt = run_real_backtest(args.strategy, save_as_active=False)
            trades = bt.get("trades_detail", [])
            return np.array([float(t.get("pnl_pct", 0.0)) / 100.0 for t in trades])
        except Exception as e:  # pragma: no cover - defensive
            print(f"[ValidationCynic] ERROR running backtest: {e}", file=sys.stderr)
            return np.array([])

    candidates = [args.returns] if args.returns else []
    candidates += [os.path.join("data", "candidate_returns.json"),
                   os.path.join(".nujin", "candidate_returns.json")]
    for path in candidates:
        if path and os.path.exists(path):
            try:
                with open(path, "r") as f:
                    return np.array(json.load(f), dtype=float)
            except Exception as e:
                print(f"[ValidationCynic] Error reading returns file {path}: {e}",
                      file=sys.stderr)
    return np.array([])


def main() -> None:
    parser = argparse.ArgumentParser(description="Adversarial Audit & Falsification Cynic CLI")
    parser.add_argument("--returns", default="", help="JSON file path containing candidate returns")
    parser.add_argument("--strategy", default="", help="Strategy filename to audit via a real backtest")
    parser.add_argument("--trials", type=int, default=100, help="Cumulative trial count across ideation")
    parser.add_argument("--param-grid", default="{}", help="Parameter grid JSON for stability testing")
    parser.add_argument("--oos-data", default="", help="Optional OOS features CSV path")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if the candidate is rejected")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON only")
    args = parser.parse_args()

    returns = _resolve_returns(args)
    if len(returns) == 0:
        print("[ValidationCynic] ERROR: no return series found (--returns or --strategy).",
              file=sys.stderr)
        result = {"overall_status": "REJECT", "reason": "Empty return series"}
        print(json.dumps(result, indent=2))
        if args.strict:
            sys.exit(1)
        return

    # A real backtest's fills are already net of spread, slippage and fees.
    matrix = evaluate_gates(returns, n_trials=args.trials,
                            returns_are_net=bool(args.strategy))

    # Legacy flat keys preserved for existing consumers (e.g. autoresearch_miner),
    # derived from the canonical matrix so they can never diverge again.
    result = dict(matrix)
    result["gate_5_equity_linearity"] = matrix["gate_8_equity_linearity"]
    result["overall_status"] = ("PASS" if matrix["overall_status"] == "APPROVED"
                                else matrix["overall_status"])

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(json.dumps(result, indent=2))

    if args.strict and matrix["overall_status"] != "APPROVED":
        sys.exit(1)


if __name__ == "__main__":
    main()
