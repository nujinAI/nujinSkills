"""
core - The Single Source of Truth quant & execution library for NujinAI.
"""
from core.data import fetch_ohlcv, resolve_market_symbol
from core.friction import resolve_asset_friction, get_roundtrip_friction, check_friction_hurdle
from core.risk import (
    parse_prompt_to_risk,
    calculate_position_units,
    drawdown_governor_multiplier,
    apply_equity_curve_governor,
)
from core.simulation import run_discrete_simulation, TradeRecord
from core.regimes import classify_market_regimes, compute_regime_breakdown
from core.analytics import (
    compute_summary_metrics,
    compute_equity_curve,
    compute_return_distribution,
    compute_account_growth_models,
)
from core.cynic_gates import evaluate_cynic_gates, render_gate_matrix
from core.indicators import sma, ema, rsi, atr
from core.market_structure import detect_swing_points, extract_market_structure
from core.hypothesis_validator import (
    profile_market_microstructure,
    check_causality_prefix_invariance,
    validate_strategy_in_sample,
)
from core.portfolio import evaluate_portfolio, print_ascii_report

__all__ = [
    "fetch_ohlcv",
    "resolve_market_symbol",
    "resolve_asset_friction",
    "get_roundtrip_friction",
    "check_friction_hurdle",
    "parse_prompt_to_risk",
    "calculate_position_units",
    "drawdown_governor_multiplier",
    "apply_equity_curve_governor",
    "run_discrete_simulation",
    "TradeRecord",
    "classify_market_regimes",
    "compute_regime_breakdown",
    "compute_summary_metrics",
    "compute_equity_curve",
    "compute_return_distribution",
    "compute_account_growth_models",
    "evaluate_cynic_gates",
    "render_gate_matrix",
    "sma",
    "ema",
    "rsi",
    "atr",
    "detect_swing_points",
    "extract_market_structure",
    "profile_market_microstructure",
    "check_causality_prefix_invariance",
    "validate_strategy_in_sample",
    "evaluate_portfolio",
    "print_ascii_report",
]
