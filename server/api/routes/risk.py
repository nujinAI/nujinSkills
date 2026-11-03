import logging
from typing import Optional
from fastapi import APIRouter

logger = logging.getLogger("NujinRiskRouter")
router = APIRouter(tags=["Risk & Governor"])


@router.get("/api/risk/drawdown-status")
async def get_drawdown_status(strategy: Optional[str] = None):
    """Returns real-time Daily and Total Drawdown Circuit Breaker metrics for active funded account."""
    from server.strategy_executor import NativeStrategyRunner
    from server.state_manager import state_manager
    from server.bot_runner import bot_supervisor

    target_strat = strategy
    if not target_strat:
        active_list = bot_supervisor.active_strategies
        if active_list:
            target_strat = active_list[0]
        else:
            target_strat = state_manager.get_key("active_strategy") or ""

    if not target_strat:
        return {
            "status": "IDLE",
            "reason": "No active strategy deployed",
            "is_safe": True,
            "daily_drawdown_pct": 0.0,
            "total_drawdown_pct": 0.0,
        }

    runner = NativeStrategyRunner(target_strat)
    safe, reason, details = runner.check_drawdown_safety()
    return {
        "status": "SAFE" if safe else "HALTED",
        "reason": reason,
        "is_safe": safe,
        **details,
    }
