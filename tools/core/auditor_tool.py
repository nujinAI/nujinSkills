"""
tools/core/auditor_tool.py - Canonical Verification Gauntlet Bridge

SINGLE SOURCE OF TRUTH:
All falsification gate evaluations are strictly performed by `server.engines.cynic_gates`
and `tools.run_backtest_audit` / `server.engines.backtest_engine`.

This module acts as the canonical bridge so that AI subagents, autonomous research scripts,
and the telemetry server compute 100% identical metrics and gate evaluations.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional
import numpy as np

# Ensure repository root is on sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from server.engines.cynic_gates import (
    evaluate_gates,
    format_matrix,
    CANONICAL_GATES,
    PASS,
    FAIL,
    INCONCLUSIVE,
)


def audit_trade_log(
    trades: List[Any],
    account_size: Optional[float] = None,
    max_drawdown_limit_pct: float = 0.05,
    daily_drawdown_limit_pct: float = 0.03,
    min_trade_count: int = 20,
    strategy_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Evaluates a list of completed trades against the 8 Canonical Cynic Falsification Gates.
    Delegates directly to server.engines.cynic_gates (Single Source of Truth).
    """
    if len(trades) < min_trade_count:
        return {
            "overall_approved": False,
            "failure_reason": f"Insufficient sample size: {len(trades)} trades (minimum {min_trade_count})",
            "gates_summary": {
                "verdict": "REJECTED",
                "gates_passed": 0,
                "gates_total": len(CANONICAL_GATES),
            },
            "gates": {},
        }

    dollar_pnls = np.array([t.pnl_dollars for t in trades])

    if account_size is None or account_size <= 0:
        first_risk = getattr(trades[0], "dollar_risk_1r", None)
        if first_risk and first_risk > 0:
            account_size = first_risk / 0.0035
        else:
            account_size = 5000.0

    returns = dollar_pnls / account_size

    gates = evaluate_gates(
        returns=returns,
        strategy_name=strategy_name,
        returns_are_net=True,
    )

    summary = gates.get("gates_summary", {})
    overall_approved = summary.get("verdict") == "APPROVED"

    wins = dollar_pnls[dollar_pnls > 0]
    losses = dollar_pnls[dollar_pnls < 0]
    pf = float(wins.sum() / abs(losses.sum())) if len(losses) > 0 and abs(losses.sum()) > 0 else 99.0
    r_multiples = [getattr(t, "pnl_r", 0.0) for t in trades]
    exp_r = float(np.mean(r_multiples)) if r_multiples else 0.0

    return {
        "overall_approved": overall_approved,
        "total_trades": len(trades),
        "expectancy_r": round(exp_r, 3),
        "profit_factor": round(pf, 2),
        "gates": gates,
        "gates_summary": summary,
        "gate_matrix_formatted": format_matrix(gates),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Canonical Cynic Audit Bridge CLI")
    parser.add_argument("--returns", default="", help="JSON file containing candidate returns array")
    parser.add_argument("--trials", type=int, default=40, help="Cumulative trial count for DSR penalty")
    parser.add_argument("--json", action="store_true", help="Emit raw JSON only")
    args = parser.parse_args()

    if not args.returns or not os.path.exists(args.returns):
        print(json.dumps({"overall_status": "REJECT", "reason": "No returns file provided"}, indent=2))
        sys.exit(1)

    with open(args.returns, "r", encoding="utf-8") as f:
        returns = np.array(json.load(f), dtype=float)

    gates = evaluate_gates(returns, n_trials=args.trials, returns_are_net=True)
    summary = gates.get("gates_summary", {})

    output = {
        "overall_status": summary.get("verdict", "REJECTED"),
        "gates_summary": summary,
        "gates": gates,
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(format_matrix(gates))


if __name__ == "__main__":
    main()
