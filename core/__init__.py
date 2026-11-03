"""
core - The Single Source of Truth quant & execution library for NujinAI.
Imported uniformly by:
- AI CLI Tools (`tools/run_backtest_audit.py`, `tools/bot_control.py`)
- Live Server Daemon & Background Watchers (`server/main.py`)
- Frontend Telemetry Cockpit
"""
from core.data import fetch_ohlcv, resolve_market_symbol
from core.friction import resolve_asset_friction, get_roundtrip_friction, check_friction_hurdle
from core.risk import parse_prompt_to_risk, calculate_position_units
from core.simulation import run_discrete_simulation, TradeRecord
from core.cynic_gates import evaluate_cynic_gates, render_gate_matrix

__all__ = [
    "fetch_ohlcv",
    "resolve_market_symbol",
    "resolve_asset_friction",
    "get_roundtrip_friction",
    "check_friction_hurdle",
    "parse_prompt_to_risk",
    "calculate_position_units",
    "run_discrete_simulation",
    "TradeRecord",
    "evaluate_cynic_gates",
    "render_gate_matrix"
]
