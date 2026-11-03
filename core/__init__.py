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
from core.cynic_gates import evaluate_cynic_gates, render_gate_matrix
from core.indicators import sma, ema, rsi, atr
from core.market_structure import detect_swing_points, extract_market_structure

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
    "evaluate_cynic_gates",
    "render_gate_matrix",
    "sma",
    "ema",
    "rsi",
    "atr",
    "detect_swing_points",
    "extract_market_structure"
]
