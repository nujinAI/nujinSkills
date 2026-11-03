"""
server/engines package.
Exposes core quantitative and trading engines with lazy resolution to avoid circular imports.
"""
from __future__ import annotations

import importlib
from typing import Any

_ENGINE_EXPORTS = {
    "StrategyEvaluator": ("server.services.strategy_executor", "StrategyEvaluator"),
    "NativeStrategyRunner": ("server.services.strategy_executor", "NativeStrategyRunner"),
    "run_real_backtest": ("server.services.backtest_engine", "run_real_backtest"),
    "BotSupervisor": ("server.services.bot_runner", "BotSupervisor"),
    "bot_supervisor": ("server.services.bot_runner", "bot_supervisor"),
    "compute_dynamic_slippage_bps": ("core.risk", "compute_dynamic_slippage_bps"),
    "compute_funding_drag_frac": ("core.risk", "compute_funding_drag_frac"),
    "resolve_intrabar_exit": ("core.risk", "resolve_intrabar_exit"),
    "drawdown_governor_multiplier": ("core.risk", "drawdown_governor_multiplier"),
    "apply_equity_curve_governor": ("core.risk", "apply_equity_curve_governor"),
    "evaluate_live_vs_backtest_drift": ("server.services.drift_monitor", "evaluate_live_vs_backtest_drift"),
    "audit_and_quarantine_live_strategies": ("server.services.drift_monitor", "audit_and_quarantine_live_strategies"),
    "evaluate_gates": ("core.cynic_gates", "evaluate_gates"),
    "summarize_gates": ("core.cynic_gates", "summarize_gates"),
    "format_matrix": ("core.cynic_gates", "format_matrix"),
    "compute_dsr": ("core.cynic_gates", "compute_dsr"),
    "verify_monte_carlo": ("core.cynic_gates", "verify_monte_carlo"),
    "verify_oos_walkforward": ("core.cynic_gates", "verify_oos_walkforward"),
    "verify_friction": ("core.cynic_gates", "verify_friction"),
    "GATE_KEYS": ("core.cynic_gates", "GATE_KEYS"),
    "sma": ("core.indicators", "sma"),
    "ema": ("core.indicators", "ema"),
    "rsi": ("core.indicators", "rsi"),
    "macd": ("core.indicators", "macd"),
    "atr": ("core.indicators", "atr"),
    "rolling_vwap": ("core.indicators", "rolling_vwap"),
    "bollinger_bands": ("core.indicators", "bollinger_bands"),
    "donchian_channels": ("core.indicators", "donchian_channels"),
    "supertrend": ("core.indicators", "supertrend"),
    "adx": ("core.indicators", "adx"),
    "compute_all_standard_features": ("core.indicators", "compute_all_standard_features"),
    "ensure_dynamic_indicators": ("core.indicators", "ensure_dynamic_indicators"),
    "detect_swing_points": ("core.market_structure", "detect_swing_points"),
    "extract_market_structure": ("core.market_structure", "extract_market_structure"),
    "synthesize_ai_trade_setup": ("core.market_structure", "synthesize_ai_trade_setup"),
    "extract_strategy_primitives": ("server.services.chart_primitives", "extract_strategy_primitives"),
    "compute_continuous_alpha_and_meta_label": ("server.services.alpha_models", "compute_continuous_alpha_and_meta_label"),
}


def __getattr__(name: str) -> Any:
    if name == "data_manager":
        return importlib.import_module("server.services.data_manager")
    if name in _ENGINE_EXPORTS:
        mod_name, attr_name = _ENGINE_EXPORTS[name]
        mod = importlib.import_module(mod_name)
        val = getattr(mod, attr_name)
        globals()[name] = val
        return val
    try:
        return importlib.import_module(f"server.services.{name}")
    except ModuleNotFoundError:
        raise AttributeError(f"module 'server.services' has no attribute '{name}'")
