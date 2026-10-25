# server/copilot/dispatcher.py
"""
Central Copilot Engine Dispatcher:
Directs user requests to composable analysis engines, merges geometric primitives,
and returns clean typed CopilotResponse payloads. Never requires code modifications.
"""
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np

from server import data_manager
from server.indicators import ensure_dynamic_indicators
from server.copilot.models import (
    CopilotResponse,
    CopilotPrimitives,
    ZoneBoxPrimitive,
    StructuralLevelPrimitive,
    TradeSetupPrimitive
)
from server.copilot.engines.zone_engine import extract_supply_demand_zones
from server.copilot.engines.setup_engine import formulate_trade_setup


def run_copilot_analysis(
    symbol: str = "BTC/USDT",
    timeframe: str = "15m",
    lookback: int = 140,
    requested_indicators: Optional[List[str]] = None,
    include_zones: bool = True,
    thesis: Optional[str] = None
) -> CopilotResponse:
    """
    Unified entry point for AI Chart Copilot market analysis.
    """
    # 1. Fetch live historical candles
    candles = data_manager.fetch_real_binance_klines(symbol, timeframe)
    if not candles:
        return CopilotResponse(
            status="ERROR",
            symbol=symbol,
            timeframe=timeframe,
            current_price=0.0
        )

    df = pd.DataFrame(candles)
    curr_price = float(df["close"].iloc[-1])

    # 2. Dynamic Indicators (Lines & Series)
    lines: List[Dict[str, Any]] = []
    series_data: Dict[str, List[Dict[str, Any]]] = {}
    hud_items: List[Dict[str, Any]] = []

    if requested_indicators:
        palette = ["#38bdf8", "#f59e0b", "#ec4899", "#10b981", "#a855f7"]
        df_ind = ensure_dynamic_indicators(df, requested_indicators)
        for i, ind in enumerate(requested_indicators):
            ind_clean = ind.lower().strip()
            if ind_clean in df_ind.columns:
                series = df_ind[ind_clean]
                color = palette[i % len(palette)]
                last_val = float(series.iloc[-1])

                is_overlay = abs(last_val - curr_price) / curr_price < 0.35
                if is_overlay:
                    lines.append({
                        "id": ind_clean,
                        "title": ind_clean.upper().replace("_", " "),
                        "color": color,
                        "lineWidth": 1.5,
                        "lineStyle": 0
                    })
                    series_data[ind_clean] = [
                        {"time": int(t), "value": round(float(v), 2)}
                        for t, v in zip(df["time"], series) if pd.notnull(v)
                    ]

                hud_items.append({
                    "id": ind_clean,
                    "label": ind_clean.upper(),
                    "color": color,
                    "value": f"${last_val:.2f}" if is_overlay else f"{last_val:.2f}"
                })

    # 3. Supply & Demand / Order Blocks
    boxes: List[ZoneBoxPrimitive] = []
    if include_zones:
        boxes = extract_supply_demand_zones(df, lookback=lookback)

    # 4. Actionable Trade Setup Box
    setup: Optional[TradeSetupPrimitive] = None
    if thesis:
        direction = "SHORT" if any(k in thesis.lower() for k in ["short", "bear", "sell", "reversal down", "breakdown"]) else "LONG"
        setup = formulate_trade_setup(df, zones=boxes, direction=direction, thesis=thesis)

    primitives = CopilotPrimitives(
        series=series_data,
        lines=lines,
        boxes=boxes,
        levels=[],
        structures=[],
        setups=[setup] if setup else [],
        hud_items=hud_items
    )

    return CopilotResponse(
        status="SUCCESS",
        symbol=symbol,
        timeframe=timeframe,
        current_price=round(curr_price, 2),
        trend="NEUTRAL",
        primitives=primitives,
        trade_setup=setup
    )
