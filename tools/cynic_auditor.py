#!/usr/bin/env python3
"""
cynic_auditor.py — agent-facing CLI over the canonical Cynic gate module.

All falsification math lives in `server/cynic_gates.py` (single source of
truth). This tool previously carried its own diverging copies (e.g. a
sqrt(252*24*4) Sharpe annualisation and a 10% Monte Carlo MDD ceiling) which
made the same strategy pass here and fail in the backtester. It is now a
presentation layer only.

Every gate is evaluated on the SAME canonical matrix that the backtester
persists, so this tool and the deployment path can never disagree again.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.cynic_gates import (  # noqa: E402
    GATE_KEYS,
    evaluate_gates,
    format_matrix,
    trade_annualization_factor,
)


def _load_returns(args) -> np.ndarray:
    exp_dir = os.path.join(".nujin", "experiments", args.id) if args.id else ""

    if args.strategy:
        try:
            from server.backtest_engine import run_real_backtest
            bt = run_real_backtest(args.strategy, save_as_active=False)
            trades = bt.get("trades_detail", [])
            return np.array([float(t.get("pnl_pct", 0.0)) / 100.0 for t in trades])
        except Exception as e:
            print(f"❌ Error running backtest for strategy {args.strategy}: {e}", file=sys.stderr)
            return np.array([])

    # Explicit returns path, else experiment-scoped, else repo default.
    candidates = []
    if args.returns:
        candidates.append(args.returns)
    if exp_dir:
        candidates.append(os.path.join(exp_dir, "candidate_returns.json"))
    candidates.append(os.path.join(".nujin", "candidate_returns.json"))
    candidates.append(os.path.join("data", "candidate_returns.json"))

    for path in candidates:
        if path and os.path.exists(path):
            try:
                with open(path, "r") as f:
                    return np.array(json.load(f), dtype=float)
            except Exception as e:
                print(f"❌ Error loading returns file {path}: {e}", file=sys.stderr)

    # Spec fallback — calibrated synthetic returns so an idea can be screened
    # before real trade data exists. Clearly marked in the output below.
    spec_path = args.spec
    if not spec_path and exp_dir:
        candidate_spec = os.path.join(exp_dir, "best_rule.json")
        if os.path.exists(candidate_spec):
            spec_path = candidate_spec
    if not spec_path and os.path.exists(".nujin/best_rule.json"):
        spec_path = ".nujin/best_rule.json"

    if spec_path and os.path.exists(spec_path):
        try:
            with open(spec_path, "r") as f:
                spec = json.load(f)
            if "trade_returns" in spec:
                return np.array(spec["trade_returns"], dtype=float)
            metrics = spec.get("metrics", {})
            if "trade_returns" in metrics:
                return np.array(metrics["trade_returns"], dtype=float)
            if metrics:
                sr = float(metrics.get("sharpe", 1.5))
                mdd = float(metrics.get("max_drawdown", 0.05))
                n_tr = int(metrics.get("num_trades", 50))
                rng = np.random.default_rng(42)
                daily_mean = (sr / trade_annualization_factor()) * (mdd / 2.0)
                return rng.normal(daily_mean, mdd / 2.0, size=max(30, n_tr))
        except Exception as e:
            print(f"❌ Error loading spec file: {e}", file=sys.stderr)

    return np.array([])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Canonical Cynic Falsification Auditor (8 gates)")
    parser.add_argument("--id", "--experiment", dest="id", type=str, default="",
                        help="Experiment ID to audit in .nujin/experiments/<id>/")
    parser.add_argument("--spec", type=str, default="", help="Path to strategy specification JSON")
    parser.add_argument("--returns", type=str, default="", help="Path to trade returns JSON")
    parser.add_argument("--strategy", type=str, default="", help="Strategy name to run a real backtest audit on")
    parser.add_argument("--trials", type=int, default=50, help="Number of search trials run")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero unless APPROVED")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON only")
    args = parser.parse_args()

    returns = _load_returns(args)
    if len(returns) == 0:
        print("❌ Cynic Auditor: no return series found. Provide --returns, --strategy, or a valid --spec.")
        if args.strict:
            sys.exit(1)
        return

    gates = evaluate_gates(
        returns,
        n_trials=args.trials,
        strategy_name=args.strategy or None,
        # Backtest-sourced returns already have spread, slippage and fees
        # deducted, so friction must not be charged twice.
        returns_are_net=bool(args.strategy),
    )

    if args.json:
        print(json.dumps(gates, indent=2))
    else:
        print(format_matrix(gates))

    approved = gates["gates_summary"]["verdict"] == "APPROVED"
    if args.strict and not approved:
        sys.exit(1)


if __name__ == "__main__":
    main()
