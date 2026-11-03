"""
Centralized dependencies and singletons for FastAPI routes.
"""
from server.state.state_manager import state_manager, signal_store, strategy_registry
from server.engines.bot_runner import bot_supervisor
from server.api.websocket import manager
from server.telegram.telegram_bot import telegram_gateway
from server.plugin_loader import plugin_manager
from server.brokers.registry import broker_registry
from server.core.audio import play_system_alert
