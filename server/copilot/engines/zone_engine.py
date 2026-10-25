# server/copilot/engines/zone_engine.py
"""
Deterministic Zone Engine:
Extracts Supply & Demand zones, Order Blocks, and Fair Value Gaps from OHLCV data.
Includes strict deduplication and overlap-merging to prevent redundant visual clutter.
"""
from typing import List, Dict, Any
import numpy as np
import pandas as pd
from server.copilot.models import ZoneBoxPrimitive


def extract_supply_demand_zones(
    df: pd.DataFrame,
    lookback: int = 100,
    atr_multiplier: float = 1.2,
    max_zones: int = 3
) -> List[ZoneBoxPrimitive]:
    """
    Extracts distinct Supply & Demand / Order Block zones based on impulse displacement.
    Merges nearby/overlapping zones to prevent visual duplication.
    """
    if len(df) < 15:
        return []

    tail = df.tail(lookback).copy().reset_index(drop=True)
    n = len(tail)

    # Compute ATR for displacement qualification
    tr = np.maximum(
        tail["high"] - tail["low"],
        np.abs(tail["high"] - tail["close"].shift(1))
    ).fillna(10.0)
    tail["atr"] = tr.rolling(14, min_periods=1).mean()
    curr_atr = float(tail["atr"].iloc[-1])
    curr_price = float(tail["close"].iloc[-1])
    last_time = int(tail["time"].iloc[-1])
    bar_duration = int(tail["time"].iloc[-1] - tail["time"].iloc[-2]) if n > 1 else 14400

    raw_zones: List[Dict[str, Any]] = []

    # 1. Identify Order Blocks (Last opposing candle before strong multi-bar displacement)
    for i in range(2, n - 2):
        prev_candle = tail.iloc[i]
        next_candles = tail.iloc[i + 1: min(i + 4, n)]

        displacement_up = (next_candles["close"].max() - prev_candle["high"])
        displacement_down = (prev_candle["low"] - next_candles["close"].min())

        threshold = prev_candle["atr"] * atr_multiplier

        # Bullish Demand Order Block (Bearish candle before sharp upward displacement)
        if displacement_up >= threshold and prev_candle["close"] <= prev_candle["open"]:
            high = float(max(prev_candle["open"], prev_candle["high"]))
            low = float(prev_candle["low"])
            raw_zones.append({
                "type": "DEMAND",
                "label": "DEMAND OB",
                "time_start": int(prev_candle["time"]),
                "time_end": last_time + (bar_duration * 10),
                "price_high": high,
                "price_low": low,
                "color": "rgba(38, 166, 154, 0.22)",
                "borderColor": "#26a69a"
            })

        # Bearish Supply Order Block (Bullish candle before sharp downward displacement)
        elif displacement_down >= threshold and prev_candle["close"] >= prev_candle["open"]:
            high = float(prev_candle["high"])
            low = float(min(prev_candle["open"], prev_candle["low"]))
            raw_zones.append({
                "type": "SUPPLY",
                "label": "SUPPLY OB",
                "time_start": int(prev_candle["time"]),
                "time_end": last_time + (bar_duration * 10),
                "price_high": high,
                "price_low": low,
                "color": "rgba(239, 83, 80, 0.22)",
                "borderColor": "#ef5350"
            })

    # If no algorithmic displacement candidate found, fall back to key swing extremes
    if not any(z["type"] == "DEMAND" for z in raw_zones):
        low_idx = tail["low"].idxmin()
        low_row = tail.loc[low_idx]
        raw_zones.append({
            "type": "DEMAND",
            "label": "DEMAND OB",
            "time_start": int(low_row["time"]),
            "time_end": last_time + (bar_duration * 10),
            "price_high": float(low_row["low"] + curr_atr * 0.8),
            "price_low": float(low_row["low"]),
            "color": "rgba(38, 166, 154, 0.22)",
            "borderColor": "#26a69a"
        })

    if not any(z["type"] == "SUPPLY" for z in raw_zones):
        high_idx = tail["high"].idxmax()
        high_row = tail.loc[high_idx]
        raw_zones.append({
            "type": "SUPPLY",
            "label": "SUPPLY OB",
            "time_start": int(high_row["time"]),
            "time_end": last_time + (bar_duration * 10),
            "price_high": float(high_row["high"]),
            "price_low": float(high_row["high"] - curr_atr * 0.8),
            "color": "rgba(239, 83, 80, 0.22)",
            "borderColor": "#ef5350"
        })

    # 2. Zone Deduplication & Clustering
    # Merge zones of the same type that overlap or sit within 0.75 * ATR of each other
    merged_demand: List[Dict[str, Any]] = []
    merged_supply: List[Dict[str, Any]] = []

    for z in raw_zones:
        target_list = merged_demand if z["type"] == "DEMAND" else merged_supply
        merged = False
        for existing in target_list:
            # Check overlap or proximity
            overlap = not (z["price_low"] > existing["price_high"] or z["price_high"] < existing["price_low"])
            near = abs(z["price_high"] - existing["price_low"]) <= (curr_atr * 0.75) or \
                   abs(existing["price_high"] - z["price_low"]) <= (curr_atr * 0.75)
            if overlap or near:
                existing["price_high"] = max(existing["price_high"], z["price_high"])
                existing["price_low"] = min(existing["price_low"], z["price_low"])
                existing["time_start"] = min(existing["time_start"], z["time_start"])
                merged = True
                break
        if not merged:
            target_list.append(z)

    # 3. Final Selection: Pick the most relevant zones relative to current price
    # Keep 1 most relevant Demand zone below current price, 1 Supply zone above current price
    final_primitives: List[ZoneBoxPrimitive] = []

    # Demand: sort by proximity to current price (highest price_high under current price)
    demands_below = [d for d in merged_demand if d["price_low"] <= curr_price]
    if demands_below:
        demands_below.sort(key=lambda d: curr_price - d["price_high"])
        best_demand = demands_below[0]
        final_primitives.append(ZoneBoxPrimitive(
            id=f"zone_demand_{best_demand['time_start']}",
            label="DEMAND",
            time_start=best_demand["time_start"],
            time_end=best_demand["time_end"],
            price_high=round(best_demand["price_high"], 2),
            price_low=round(best_demand["price_low"], 2),
            color=best_demand["color"],
            borderColor=best_demand["borderColor"],
            borderStyle="solid",
            type="DEMAND"
        ))

    # Supply: sort by proximity to current price (lowest price_low above current price)
    supplies_above = [s for s in merged_supply if s["price_high"] >= curr_price]
    if supplies_above:
        supplies_above.sort(key=lambda s: s["price_low"] - curr_price)
        best_supply = supplies_above[0]
        final_primitives.append(ZoneBoxPrimitive(
            id=f"zone_supply_{best_supply['time_start']}",
            label="SUPPLY",
            time_start=best_supply["time_start"],
            time_end=best_supply["time_end"],
            price_high=round(best_supply["price_high"], 2),
            price_low=round(best_supply["price_low"], 2),
            color=best_supply["color"],
            borderColor=best_supply["borderColor"],
            borderStyle="solid",
            type="SUPPLY"
        ))

    return final_primitives
