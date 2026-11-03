"""
core/cynic_gates.py - Canonical 8 Cynic Falsification Gates Evaluation.
Single Source of Truth: Evaluates return series against institutional benchmarks.
"""
from typing import Dict, Any, Optional
import numpy as np
from server.engines.cynic_gates import (
    evaluate_gates as _eval_gates,
    format_matrix,
    CANONICAL_GATES,
    GATE_KEYS,
    PASS,
    FAIL,
    INCONCLUSIVE
)

def evaluate_cynic_gates(
    returns: np.ndarray,
    n_trials: int = 40,
    strategy_name: Optional[str] = None,
    metric_matrix: Optional[np.ndarray] = None,
    observed_sr: Optional[float] = None
) -> Dict[str, Any]:
    """
    Evaluates returns against all 8 Canonical Cynic Gates:
    1. Deflated Sharpe Ratio (DSR >= 0.95)
    2. Parameter Stability (plateau surface check)
    3. Monte Carlo Sequence Stress (MDD99 <= 3.0%)
    4. Out-of-Sample Walk-Forward
    5. Regime Survival (Bull, Bear, Choppy)
    6. Microstructure Friction Floor
    7. Noise Jitter Resilience (>= 80% Sharpe retention)
    8. Equity Linearity (R² >= 0.85)
    """
    return _eval_gates(
        returns=returns,
        n_trials=n_trials,
        strategy_name=strategy_name,
        metric_matrix=metric_matrix,
        observed_sr=observed_sr,
        returns_are_net=True
    )

def render_gate_matrix(gates: dict) -> str:
    return format_matrix(gates)
