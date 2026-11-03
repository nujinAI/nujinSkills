"""
NujinSkills Telemetry & Signal Gateway API Server
─────────────────────────────────────────────────────────────
Open-source 24/7 Quantitative Telemetry Hub, WebSocket Dispatcher,
and Systematic Strategy Execution Gateway.

Modular 2026 FastAPI Architecture:
  - Bounded context routers under server/api/routes/
  - Typed request & response schemas under server/schemas/
  - Core configuration & modern async lifespan under server/runtime/
  - Single Market Authority: TradingView Provider for ANY asset.
"""

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Core configuration & modern lifespan
from server.runtime.config import APP_TITLE, APP_VERSION, APP_DESCRIPTION
from server.runtime.lifespan import lifespan
from server.runtime.audio import play_system_alert

# API presentation layer
from server.api import register_routes
from server.api.websocket import manager

# Schemas
from server.schemas import (
    EventEnvelope,
    DeployBotRequest,
    SelectStrategyRequest,
    UpdateStrategyStatusRequest,
    RunStrategyBacktestRequest,
    RemoveStrategyRequest,
    CloseSignalRequest,
    ClearSignalsRequest,
    DeleteSignalRequest,
    StopBotRequest,
    UpdateStateRequest,
)

# Core singletons & dependencies (Single Source of Truth)
from server.state.state_manager import state_manager, signal_store, strategy_registry
from server.engines.bot_runner import bot_supervisor
from server.telegram.telegram_bot import telegram_gateway
from server.plugin_loader import plugin_manager
from server.brokers.registry import broker_registry
from server.engines.backtest_engine import run_real_backtest
from server.engines import data_manager

# Route handlers re-exported for backwards compatibility with tests & internal callers
from server.api.routes.brokers import (
    list_brokers,
    list_broker_accounts,
    delete_broker_account,
    toggle_broker_account,
)
from server.api.routes.health import (
    health_check,
    get_system_status as get_health_system_status,
    get_system_state,
    update_system_state,
    list_plugins,
    broadcast_event,
)
from server.api.routes.bot import (
    deploy_bot,
    stop_bot,
    strategy_activate,
    strategy_deactivate,
    get_bot_status,
)
from server.api.routes.strategies import (
    select_and_run_strategy,
    get_backtest_results,
    list_strategies,
    sync_strategies_endpoint,
    get_managed_strategies,
    get_portfolio_overview,
    get_portfolio_correlation,
    update_managed_strategy_status,
    run_managed_strategy_backtest,
    trigger_cron_evaluations,
    get_strategy_rankings,
    recalculate_strategy_rankings,
    remove_strategy_endpoint,
)
from server.api.routes.signals import (
    get_signals,
    get_live_signal_stats,
    clear_signals,
    delete_signal_endpoint,
    close_signal_position,
)
from server.api.routes.market import (
    get_candles,
    get_strategy_primitives,
    get_widgets,
    get_live_quote,
    get_sp500_quote,
    get_xauusd_quote,
    _sanitize_candles,
    _extract_primitives_for_response,
)
from server.api.routes.risk import get_drawdown_status
from server.api.routes.copilot import (
    get_chart_copilot_markup,
    chart_copilot_markup,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("NujinSkillsServer")


def create_app() -> FastAPI:
    """Application factory for NujinSkills Telemetry & Signal Gateway."""
    application = FastAPI(
        title=APP_TITLE,
        version=APP_VERSION,
        description=APP_DESCRIPTION,
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_routes(application)
    return application


app = create_app()

__all__ = [
    "app",
    "create_app",
    "list_brokers",
    "play_system_alert",
    "state_manager",
    "signal_store",
    "strategy_registry",
    "bot_supervisor",
    "manager",
    "run_real_backtest",
    "plugin_manager",
    "broker_registry",
    "telegram_gateway",
    "data_manager",
    "EventEnvelope",
    "DeployBotRequest",
    "SelectStrategyRequest",
    "UpdateStrategyStatusRequest",
    "RunStrategyBacktestRequest",
    "RemoveStrategyRequest",
    "CloseSignalRequest",
    "ClearSignalsRequest",
    "DeleteSignalRequest",
    "StopBotRequest",
    "UpdateStateRequest",
]
