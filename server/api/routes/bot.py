import asyncio
import logging
import os
from typing import Optional
from fastapi import APIRouter, HTTPException

from server.api.deps import (
    manager,
    bot_supervisor,
    strategy_registry,
    state_manager,
    plugin_manager,
)
from server.schemas.bot import DeployBotRequest, StopBotRequest
from server.backtest_engine import run_real_backtest

logger = logging.getLogger("NujinBotRouter")
router = APIRouter(tags=["Bot Execution"])


@router.post("/api/bot/deploy")
async def deploy_bot(req: DeployBotRequest):
    raw_strat = req.strategy or req.strategy_name or strategy_registry.get_active_strategy_name()
    clean_strat = (raw_strat or "").replace(".py", "").strip()
    if not clean_strat or clean_strat == ".":
        raise HTTPException(
            status_code=400,
            detail="No strategy available to deploy. Please mine or register a strategy in strategies/ first.",
        )
    strat_path = os.path.join(os.getcwd(), "strategies", f"{clean_strat}.py")
    if not os.path.exists(strat_path) and plugin_manager:
        resolved = plugin_manager.resolve_strategy_path(clean_strat) or plugin_manager.resolve_strategy_path(f"{clean_strat}.py")
        if resolved:
            strat_path = resolved
    if not os.path.exists(strat_path):
        raise HTTPException(
            status_code=404,
            detail=f"Strategy file '{clean_strat}.py' not found in strategies/ or plugins/. Please mine or register this strategy first.",
        )
    strat = clean_strat
    logger.info(f"Activating & deploying strategy for system: {strat}")
    bt_result = await asyncio.to_thread(run_real_backtest, strat, True)
    bot_supervisor.set_broadcast_callback(manager.broadcast)
    res = bot_supervisor.deploy_strategy(strat, req.mode or "dry-run")
    try:
        strategy_registry.update_status(strat, "ACTIVE_LIVE")
    except Exception as e_reg:
        logger.warning(f"Error updating registry for {strat}: {e_reg}")
    all_strats = await asyncio.to_thread(strategy_registry.get_all, False, False)
    portfolio = strategy_registry.get_portfolio_summary()
    distribution = strategy_registry.get_distribution_analytics()
    await manager.broadcast({"event_type": "STATE_UPDATED", "payload": bt_result["state"]})
    await manager.broadcast({
        "event_type": "STRATEGIES_UPDATED",
        "payload": {
            "strategies": all_strats,
            "portfolio_summary": portfolio,
            "distribution_analytics": distribution,
        },
    })
    return {**res, "state": bt_result["state"], "strategies": all_strats}


@router.post("/api/bot/stop")
async def stop_bot(req: Optional[StopBotRequest] = None):
    strat = (req.strategy or req.strategy_name) if req else None
    res = bot_supervisor.stop_bot(strat)
    if strat:
        try:
            strategy_registry.update_status(strat, "DEACTIVATED")
        except Exception as e_s:
            logger.warning(f"Error deactivating {strat}: {e_s}")
    else:
        all_active = [s["name"] for s in strategy_registry.get_all(sync=False) if s.get("status") == "ACTIVE_LIVE"]
        active_state_strats = state_manager.get().get("active_strategies", [])
        to_stop = set(all_active + active_state_strats + list(bot_supervisor.runners.keys()))
        for s in to_stop:
            try:
                strategy_registry.update_status(s, "DEACTIVATED")
            except Exception as e_s:
                logger.warning(f"Error deactivating {s}: {e_s}")
        state_manager.patch({"status": "STOPPED", "active_strategies": [], "active_strategy": ""})
    new_state = state_manager.get()
    all_strats = strategy_registry.get_all(sync=False)
    portfolio = strategy_registry.get_portfolio_summary()
    distribution = strategy_registry.get_distribution_analytics()
    await manager.broadcast({"event_type": "STATE_UPDATED", "payload": new_state})
    await manager.broadcast({
        "event_type": "STRATEGIES_UPDATED",
        "payload": {
            "strategies": all_strats,
            "portfolio_summary": portfolio,
            "distribution_analytics": distribution,
        },
    })
    return res


@router.post("/api/strategy/activate")
async def strategy_activate(req: DeployBotRequest):
    return await deploy_bot(req)


@router.post("/api/strategy/deactivate")
async def strategy_deactivate(req: Optional[StopBotRequest] = None):
    return await stop_bot(req)


@router.get("/api/bot/status")
async def get_bot_status():
    return bot_supervisor.get_status()
