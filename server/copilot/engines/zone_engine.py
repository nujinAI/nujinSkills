# server/copilot/engines/zone_engine.py
"""
Deterministic Zone Engine:
Extracts tight, local Supply & Demand order blocks from recent price action.
Focuses strictly on recent energetic displacement wicks and avoids monolithic mega-boxes.
"""
from typing import List, Dict, Any
import numpy as np
import pandas as pd
from server.copilot.models import ZoneBoxPrimitive


def extract_supply_demand_zones(
    df: pd.DataFrame,
    lookback: int = 50,
    max_zones: int = 2
) -> List[ZoneBoxPrimitive]:
    """
    Extracts tight, localized Supply & Demand zones from the most recent swing pivots.
    Guarantees clean, non-bloated TradingView-style zones.
    """
    if len(df) < 15:
        return []

    # Focus on the most recent candles (max 40-50 bars) so zones represent current market structure
    tail = df.tail(lookback).copy().reset_index(drop=True)
    n = len(tail)

    tr = np.maximum(
        tail["high"] - tail["low"],
        np.abs(tail["high"] - tail["close"].shift(1))
    ).fillna(10.0)
    tail["atr"] = tr.rolling(14, min_periods=1).mean()
    curr_atr = float(tail["atr"].iloc[-1])
    curr_price = float(tail["close"].iloc[-1])
    last_time = int(tail["time"].iloc[-1])
    bar_duration = int(tail["time"].iloc[-1] - tail["time"].iloc[-2]) if n > 1 else 14400

    final_primitives: List[ZoneBoxPrimitive] = []

    # 1. Local Demand Zone / Bullish Order Block (From the recent swing low absorption)
    low_idx = tail["low"].idxmin()
    low_candle = tail.loc[low_idx]
    
    # Tight demand zone: the body and lower wick of the swing low base
    demand_low = float(low_candle["low"])
    demand_high = float(min(low_candle["high"], max(low_candle["open"], low_candle["close"]) + 0.3 * curr_atr))
    # Cap height to max 1.2 ATR so it never becomes a giant brick
    if demand_high - demand_low > curr_atr * 1.2:
        demand_high = demand_low + curr_atr * 1.2

    final_primitives.append(ZoneBoxPrimitive(
        id=f"zone_demand_{int(low_candle['time'])}",
        label="DEMAND",
        time_start=int(low_candle["time"]),
        time_end=last_time + (bar_duration * 6),
        price_high=round(demand_high, 2),
        price_low=round(demand_low, 2),
        color="rgba(38, 166, 154, 0.20)",
        borderColor="#26a69a",
        borderStyle="solid",
        type="DEMAND"
    ))

    # 2. Local Supply Zone / Bearish Order Block (From the immediate breakdown origin)
    # Find the most recent breakdown pivot above current price
    candidates_above = tail[(tail["high"] > curr_price) & (tail.index > n - 30)]
    if not candidates_above.empty:
        # The swing high that initiated the last downward leg
        high_idx = candidates_above["high"].idxmax()
        high_candle = candidates_above.loc[high_idx]
        supply_high = float(high_candle["high"])
        supply_low = float(max(high_candle["low"], min(high_candle["open"], high_candle["close"]) - 0.3 * curr_atr))
        # Cap height to max 1.2 ATR
        if supply_high - supply_low > curr_atr * 1.2:
            supply_low = supply_high - curr_atr * 1.2

        final_primitives.append(ZoneBoxPrimitive(
            id=f"zone_supply_{int(high_candle['time'])}",
            label="SUPPLY",
            time_start=int(high_candle["time"]),
            time_end=last_time + (bar_duration * 6),
            price_high=round(supply_high, 2),
            price_low=round(supply_low, 2),
            color="rgba(239, 83, 80, 0.20)",
            borderColor="#ef5350",
            borderStyle="solid",
            type="SUPPLY"
        ))

    return final_primitives
