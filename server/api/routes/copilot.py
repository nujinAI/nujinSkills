import logging
from typing import Any, Dict
from fastapi import APIRouter, Body

from server.api.deps import manager

logger = logging.getLogger("NujinCopilotRouter")
router = APIRouter(tags=["Chart Copilot"])

# Global in-memory cache for active chart copilot markup state
_latest_copilot_markup: Dict[str, Any] = {
    "symbol": "BTC/USDT",
    "timeframe": "15m",
    "primitives": {
        "lines": [],
        "series": {},
        "boxes": [],
        "levels": [],
        "hud_items": [],
        "structures": [],
        "setups": [],
    },
}


@router.get("/api/chart/copilot")
async def get_chart_copilot_markup():
    """Returns the latest active chart copilot markup for initial page loads and reloads."""
    return _latest_copilot_markup


@router.post("/api/chart/copilot")
async def chart_copilot_markup(payload: Dict[str, Any] = Body(...)):
    """
    NujinAI Dynamic Chart Copilot Endpoint.
    Analyzes any requested indicator stack, custom formulas, or SMC structure,
    and broadcasts the visual primitives live to all connected browser charts.
    """
    global _latest_copilot_markup
    symbol = payload.get("symbol", "BTC/USDT")
    timeframe = payload.get("timeframe", "15m")
    lookback = payload.get("lookback", 140)
    requested_indicators = payload.get("indicators")
    thesis = payload.get("thesis")
    action = payload.get("action", "ANALYZE")

    if action == "CLEAR":
        empty_prims = {
            "lines": [],
            "series": {},
            "boxes": [],
            "levels": [],
            "hud_items": [],
            "structures": [],
            "setups": [],
        }
        _latest_copilot_markup = {
            "symbol": symbol,
            "timeframe": timeframe,
            "primitives": empty_prims,
        }
        await manager.broadcast({
            "event_type": "COPILOT_MARKUP",
            "payload": _latest_copilot_markup,
        })
        return {"status": "SUCCESS", "action": "CLEAR", "primitives": empty_prims}

    from server.copilot.dispatcher import run_copilot_analysis
    res_obj = run_copilot_analysis(
        symbol=symbol,
        timeframe=timeframe,
        lookback=lookback,
        requested_indicators=requested_indicators,
        include_zones=payload.get("include_zones", True),
        thesis=thesis,
    )
    res = res_obj.model_dump() if hasattr(res_obj, "model_dump") else res_obj.dict()

    if res.get("status") == "SUCCESS":
        _latest_copilot_markup = {
            "symbol": symbol,
            "timeframe": timeframe,
            "primitives": res.get("primitives", {}),
        }
        await manager.broadcast({
            "event_type": "COPILOT_MARKUP",
            "payload": _latest_copilot_markup,
        })

    return res
