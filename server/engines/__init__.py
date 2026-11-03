"""
server/engines package.
Exposes core quantitative and trading engines with lazy resolution to avoid circular imports.
"""
from __future__ import annotations

import importlib
from typing import Any

_ENGINE_EXPORTS = {
    "StrategyEvaluator": ("server.engines.strategy_executor", "StrategyEvaluator"),
    "NativeStrategyRunner": ("server.engines.strategy_executor", "NativeStrategyRunner"),
    "run_real_backtest": ("server.engines.backtest_engine", "run_real_backtest"),
    "BotSupervisor": ("server.engines.bot_runner", "BotSupervisor"),
    "bot_supervisor": ("server.engines.bot_runner", "bot_supervisor"),
    "compute_dynamic_slippage_bps": ("server.engines.risk_governor", "compute_dynamic_slippage_bps"),
    "compute_funding_drag_frac": ("server.engines.risk_governor", "compute_funding_drag_frac"),
    "resolve_intrabar_exit": ("server.engines.risk_governor", "resolve_intrabar_exit"),
    "drawdown_governor_multiplier": ("server.engines.risk_governor", "drawdown_governor_multiplier"),
    "apply_equity_curve_governor": ("server.engines.risk_governor", "apply_equity_curve_governor"),
    "evaluate_live_vs_backtest_drift": ("server.engines.drift_monitor", "evaluate_live_vs_backtest_drift"),
    "audit_and_quarantine_live_strategies": ("server.engines.drift_monitor", "audit_and_quarantine_live_strategies"),
    "evaluate_gates": ("server.engines.cynic_gates", "evaluate_gates"),
    "summarize_gates": ("server.engines.cynic_gates", "summarize_gates"),
    "format_matrix": ("server.engines.cynic_gates", "format_matrix"),
    "compute_dsr": ("server.engines.cynic_gates", "compute_dsr"),
    "verify_monte_carlo": ("server.engines.cynic_gates", "verify_monte_carlo"),
    "verify_oos_walkforward": ("server.engines.cynic_gates", "verify_oos_walkforward"),
    "verify_friction": ("server.engines.cynic_gates", "verify_friction"),
    "GATE_KEYS": ("server.engines.cynic_gates", "GATE_KEYS"),
    "sma": ("server.engines.indicators", "sma"),
    "ema": ("server.engines.indicators", "ema"),
    "rsi": ("server.engines.indicators", "rsi"),
    "macd": ("server.engines.indicators", "macd"),
    "atr": ("server.engines.indicators", "atr"),
    "rolling_vwap": ("server.engines.indicators", "rolling_vwap"),
    "bollinger_bands": ("server.engines.indicators", "bollinger_bands"),
    "donchian_channels": ("server.engines.indicators", "donchian_channels"),
    "supertrend": ("server.engines.indicators", "supertrend"),
    "adx": ("server.engines.indicators", "adx"),
    "compute_all_standard_features": ("server.engines.indicators", "compute_all_standard_features"),
    "ensure_dynamic_indicators": ("server.engines.indicators", "ensure_dynamic_indicators"),
    "detect_swing_points": ("server.engines.market_structure", "detect_swing_points"),
    "extract_market_structure": ("server.engines.market_structure", "extract_market_structure"),
    "synthesize_ai_trade_setup": ("server.engines.market_structure", "synthesize_ai_trade_setup"),
    "extract_strategy_primitives": ("server.engines.chart_primitives", "extract_strategy_primitives"),
    "compute_continuous_alpha_and_meta_label": ("server.engines.alpha_models", "compute_continuous_alpha_and_meta_label"),
}


def __getattr__(name: str) -> Any:
    if name == "data_manager":
        return importlib.import_module("server.engines.data_manager")
    if name in _ENGINE_EXPORTS:
        mod_name, attr_name = _ENGINE_EXPORTS[name]
        mod = importlib.import_module(mod_name)
        val = getattr(mod, attr_name)
        globals()[name] = val
        return val
    try:
        return importlib.import_module(f"server.engines.{name}")
    except ModuleNotFoundError:
        raise AttributeError(f"module 'server.engines' has no attribute '{name}'")
