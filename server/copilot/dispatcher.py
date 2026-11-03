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
from core.indicators import ensure_dynamic_indicators
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

    # 3. Supply & Demand / Order Blocks & Liquidity Structures
    boxes: List[ZoneBoxPrimitive] = []
    structures: List[Dict[str, Any]] = []

    # Check if liquidity (BSL / SSL) or market structure is requested
    thesis_lower = (thesis or "").lower()
    include_liquidity = "liquidity" in thesis_lower or "bsl" in thesis_lower or "ssl" in thesis_lower or "sweep" in thesis_lower

    if include_liquidity:
        # Extract prominent 15m/1h swing highs (BSL) and swing lows (SSL)
        tail_df = df.tail(60).copy().reset_index(drop=True)
        highs = tail_df["high"].values
        lows = tail_df["low"].values
        last_t = int(tail_df["time"].iloc[-1])

        # BSL: Resting buy stops above recent swing highs
        for i in range(3, len(tail_df) - 3):
            if highs[i] == max(highs[i-3:i+4]) and highs[i] > curr_price:
                structures.append({
                    "id": f"bsl_{int(tail_df['time'].iloc[i])}",
                    "type": "LIQUIDITY",
                    "direction": "BULLISH",
                    "label": "BSL",
                    "time_start": int(tail_df["time"].iloc[i]),
                    "time_end": last_t + 1800,
                    "price": round(float(highs[i]), 2),
                    "color": "#38bdf8"
                })
                break

        # SSL: Resting sell stops below recent swing lows
        for i in range(len(tail_df) - 4, 3, -1):
            if lows[i] == min(lows[i-3:i+4]) and lows[i] < curr_price:
                structures.append({
                    "id": f"ssl_{int(tail_df['time'].iloc[i])}",
                    "type": "LIQUIDITY",
                    "direction": "BEARISH",
                    "label": "SSL",
                    "time_start": int(tail_df["time"].iloc[i]),
                    "time_end": last_t + 1800,
                    "price": round(float(lows[i]), 2),
                    "color": "#f59e0b"
                })
                break

    if include_zones:
        boxes = extract_supply_demand_zones(df, lookback=lookback)

    # 4. Actionable Trade Setup Box
    setup: Optional[TradeSetupPrimitive] = None
    if thesis:
        # Determine explicit direction: "long", "buy", "bull" -> LONG; "short", "sell", "bear" -> SHORT
        is_explicit_short = any(k in thesis_lower for k in ["short", "sell", "bearish", "breakdown"])
        is_explicit_long = any(k in thesis_lower for k in ["long", "buy", "bullish", "reclaim"])
        if is_explicit_long and not is_explicit_short:
            direction = "LONG"
        elif is_explicit_short and not is_explicit_long:
            direction = "SHORT"
        elif "buy" in thesis_lower or "long" in thesis_lower:
            direction = "LONG"
        else:
            direction = "SHORT" if any(k in thesis_lower for k in ["short", "sell"]) else "LONG"

        order_type = "MARKET" if "market" in thesis_lower or "enter now" in thesis_lower else "LIMIT"
        setup = formulate_trade_setup(df, zones=boxes, direction=direction, order_type=order_type, thesis=thesis)

    primitives = CopilotPrimitives(
        series=series_data,
        lines=lines,
        boxes=boxes,
        levels=[],
        structures=structures,
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
