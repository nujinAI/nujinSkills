"""
Guards for the single-source-of-truth contract in server/cynic_gates.py.

These tests exist because the repository previously carried three divergent
copies of the gate math, which made the same strategy produce different
verdicts in the auditor, the backtester, and the ranking scorer.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.cynic_gates import (  # noqa: E402
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


def test_backtester_shim_and_canonical_module_agree():
    """The path the backtester uses must match the canonical module exactly."""
    from tools.validation_cynic import (
        compute_dsr as shim_dsr,
        compute_equity_linearity as shim_linearity,
        run_monte_carlo as shim_mc,
        run_parameter_stability as shim_stability,
    )

    r = _fixture_returns()

    assert shim_dsr(r, 40) == compute_dsr(r, 40)
    assert shim_mc(r) == verify_monte_carlo(r)
    assert shim_linearity(r) == compute_equity_linearity(r)
    assert shim_stability({}, 2.0) == verify_parameter_stability(None, 2.0)


def test_auditor_cli_and_backtester_share_one_dsr():
    """Regression: the two DSR implementations used to differ by ~9.8x."""
    from tools import cynic_auditor
    from tools.validation_cynic import compute_dsr as shim_dsr

    r = _fixture_returns()
    canonical = compute_dsr(r, 40)

    assert canonical["annualization_periods"] == 252
    assert shim_dsr(r, 40)["dsr"] == canonical["dsr"]
    # cynic_auditor must delegate to the canonical module, never re-implement it.
    assert cynic_auditor.evaluate_gates is evaluate_gates


def test_parameter_stability_can_fail():
    """Regression: this gate previously always reported PASS."""
    no_data = verify_parameter_stability(metric_matrix=None, observed_sr=3.0)
    assert no_data["status"] == INCONCLUSIVE, "gate must not claim PASS without real re-runs"

    healthy = verify_parameter_stability([[3.0, 2.9], [2.8, 2.7]], observed_sr=3.0)
    assert healthy["status"] == PASS

    cliff = verify_parameter_stability([[3.0, 0.1], [0.1, 0.1]], observed_sr=3.0)
    assert cliff["status"] == "FAIL", "a collapsing plateau must fail"


def test_inconclusive_never_counts_as_passed():
    gates = evaluate_gates(_fixture_returns(), n_trials=40)  # no grid -> INCONCLUSIVE stability
    summary = gates["gates_summary"]
    assert summary["gates_passed"] == sum(
        1 for k in GATE_KEYS if gates[k]["status"] == PASS
    )
    assert summary["gates_inconclusive"] >= 1


def test_friction_not_double_charged_on_backtest_returns():
    """Backtest fills are already net; charging friction again inverts the gate."""
    r = np.full(60, 0.0005)  # 5 bps/trade: below the 7 bps round-trip charge

    net = evaluate_gates(r, n_trials=40, returns_are_net=True)
    assert net["gate_6_friction"]["status"] == PASS
    assert net["gate_6_friction"]["returns_were_net_of_friction"] is True

    gross = evaluate_gates(r, n_trials=40, returns_are_net=False)
    assert gross["gate_6_friction"]["status"] == "FAIL", "gross returns must be charged friction"


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
