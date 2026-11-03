"""
Guards for the single-source-of-truth contract in server/engines/cynic_gates.py.
"""

import os
import sys
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.engines.cynic_gates import (
    CANONICAL_GATES,
    GATE_KEYS,
    INCONCLUSIVE,
    PASS,
    compute_dsr,
    compute_equity_linearity,
    evaluate_gates,
    summarize_gates,
    verify_monte_carlo,
    verify_parameter_stability,
)


def _fixture_returns(n: int = 120, seed: int = 7) -> np.ndarray:
    """A positive-edge return series with enough trades to exercise every gate."""
    rng = np.random.default_rng(seed)
    return rng.normal(0.0015, 0.01, size=n)


def test_matrix_contains_every_canonical_gate():
    gates = evaluate_gates(_fixture_returns(), n_trials=40)
    for key in GATE_KEYS:
        assert key in gates, f"missing canonical gate {key}"
        assert gates[key]["status"] in {"PASS", "FAIL", INCONCLUSIVE}

    summary = gates["gates_summary"]
    assert summary["gates_total"] == len(CANONICAL_GATES)
    assert (summary["gates_passed"] + summary["gates_failed"]
            + summary["gates_inconclusive"]) == summary["gates_total"]
    assert gates["overall_status"] == summary["verdict"]


def test_parameter_stability_can_fail():
    """Regression: this gate previously always reported PASS."""
    no_data = verify_parameter_stability(metric_matrix=None, observed_sr=3.0)
    assert no_data["status"] == INCONCLUSIVE, "gate must not claim PASS without real re-runs"

    healthy = verify_parameter_stability([[3.0, 2.9], [2.8, 2.7]], observed_sr=3.0)
    assert healthy["status"] == PASS

    cliff = verify_parameter_stability([[3.0, 0.1], [0.1, 0.1]], observed_sr=3.0)
    assert cliff["status"] == "FAIL", "a collapsing plateau must fail"


def test_inconclusive_never_counts_as_passed():
    gates = evaluate_gates(_fixture_returns(), n_trials=40)
    summary = gates["gates_summary"]
    assert summary["gates_passed"] == sum(
        1 for k in GATE_KEYS if gates[k]["status"] == PASS
    )
    assert summary["gates_inconclusive"] >= 1


def test_friction_not_double_charged_on_backtest_returns():
    """Backtest fills are already net; charging friction again inverts the gate."""
    r = np.full(60, 0.0005)

    net = evaluate_gates(r, n_trials=40, returns_are_net=True)
    assert net["gate_6_friction"]["status"] == PASS
    assert net["gate_6_friction"]["returns_were_net_of_friction"] is True

    gross = evaluate_gates(r, n_trials=40, returns_are_net=False)
    assert gross["gate_6_friction"]["status"] == "FAIL"


def test_summarize_gates_verdict_precedence():
    failed = summarize_gates({"gate_1_dsr": {"status": "FAIL"}})
    assert failed["verdict"] == "REJECTED"

    inconclusive = summarize_gates({"gate_1_dsr": {"status": PASS},
                                    "gate_2_parameter_stability": {"status": INCONCLUSIVE}})
    assert inconclusive["verdict"] == "INCONCLUSIVE"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("all cynic-gate single-source tests passed")
