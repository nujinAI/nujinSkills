import logging
import time
from typing import Any, Dict
from fastapi import APIRouter

from server.api.deps import (
    manager,
    bot_supervisor,
    telegram_gateway,
    strategy_registry,
    state_manager,
    signal_store,
    plugin_manager,
    play_system_alert,
)
from server.schemas.common import EventEnvelope
from server.schemas.state import UpdateStateRequest
from server.backtest_engine import run_real_backtest

logger = logging.getLogger("NujinHealthRouter")
router = APIRouter(tags=["Health & Status"])


@router.get("/api/health")
async def health_check():
    return {
        "status": "ONLINE",
        "service": "NujinSkills Telemetry Server",
        "connections": len(manager.active_connections),
        "bot_status": bot_supervisor.get_status(),
        "telegram_status": {
            "configured": telegram_gateway.is_configured,
            "has_token": bool(telegram_gateway.bot_token),
            "has_chat_id": bool(telegram_gateway.chat_id),
        },
    }


@router.get("/api/system/status")
async def get_system_status_detailed():
    return {
        "status": "ONLINE",
        "connections": len(manager.active_connections),
        "bot": bot_supervisor.get_status(),
        "telegram": {
            "configured": telegram_gateway.is_configured,
            "has_token": bool(telegram_gateway.bot_token),
            "has_chat_id": bool(telegram_gateway.chat_id),
        },
        "active_strategy": strategy_registry.get_active_strategy_name(),
    }


@router.get("/api/status")
async def get_system_status():
    """Unified system status for cockpit telemetry and monitoring."""
    curr_state = state_manager.get()
    return {
        "status": "ONLINE",
        "timestamp": int(time.time()),
        "active_strategy": curr_state.get("active_strategy", ""),
        "active_strategies": bot_supervisor.active_strategies,
        "bot_status": bot_supervisor.get_status(),
        "telegram_configured": telegram_gateway.is_configured,
        "signals_count": curr_state.get("signals_count", 0),
        "open_positions_count": len(signal_store.get_active_signals()),
    }


@router.get("/api/state")
async def get_system_state():
    """Return current system state from StateManager (single source of truth)."""
    return state_manager.get()


@router.post("/api/state")
async def update_system_state(req: UpdateStateRequest):
    """Patch or deploy strategy — all writes go through StateManager."""
    if req.active_strategy:
        result = run_real_backtest(req.active_strategy, save_as_active=True)
        new_state = result.get("state", state_manager.get())
        await manager.broadcast({"event_type": "STATE_UPDATED", "payload": new_state})
        return {"status": "SUCCESS", "state": new_state}

    updates: Dict[str, Any] = {}
    if req.target_profile:
        updates["target_profile"] = req.target_profile
    if req.status:
        updates["status"] = req.status
    if req.backtest_summary:
        updates["backtest_summary"] = req.backtest_summary

    new_state = state_manager.patch(updates)
    await manager.broadcast({"event_type": "STATE_UPDATED", "payload": new_state})
    return {"status": "SUCCESS", "state": new_state}


@router.get("/api/plugins")
async def list_plugins():
    """Returns all discovered plugins, metadata, and status."""
    plugins = plugin_manager.get_all_plugins()
    return {"plugins": plugins, "total": len(plugins)}


@router.post("/api/broadcast")
async def broadcast_event(envelope: EventEnvelope):
    logger.info(f"Broadcast event received: {envelope.event_type}")
    await manager.broadcast(envelope.model_dump())

    if envelope.event_type == "SIGNAL_TRIGGERED":
        play_system_alert(envelope.payload.get("action", ""))

        if not envelope.payload.get("strategy"):
            envelope.payload["strategy"] = strategy_registry.get_active_strategy_name()
        signal_store.add(envelope.payload)
        telegram_gateway.format_and_send_signal(envelope.payload)

        all_strats = strategy_registry.get_all(sync=False)
        portfolio = strategy_registry.get_portfolio_summary()
        distribution = strategy_registry.get_distribution_analytics()
        await manager.broadcast({
            "event_type": "STRATEGIES_UPDATED",
            "payload": {
                "strategies": all_strats,
                "portfolio_summary": portfolio,
                "distribution_analytics": distribution,
            },
        })
    elif envelope.event_type == "TELEGRAM_ALERT":
        play_system_alert(envelope.payload.get("action", ""))
        telegram_gateway.format_and_send_signal(envelope.payload)
    elif envelope.event_type == "TELEGRAM_BROADCAST":
        msg_body = envelope.payload.get("message") or envelope.payload.get("text") or envelope.payload.get("body", "")
        msg_cat = envelope.payload.get("type") or envelope.payload.get("category", "general")
        msg_title = envelope.payload.get("title", "")
        telegram_gateway.broadcast_custom(msg_body, category=msg_cat, title=msg_title)
    elif envelope.event_type == "UPSERT_WIDGET" and envelope.payload.get("component") == "MetricCard":
        telegram_gateway.format_and_send_dsr_alert(envelope.payload)
    return {"status": "SUCCESS", "event_type": envelope.event_type}
