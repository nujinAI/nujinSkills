# server/copilot/engines/setup_engine.py
"""
Deterministic Setup Engine:
Calculates concrete Entry, Invalidation (Stop Loss), and Profit Target(s) with exact mathematical R:R.
Anchors risk directly to detected institutional zones or structural levels.
"""
from typing import List, Optional
import numpy as np
import pandas as pd
from server.copilot.models import TradeSetupPrimitive, ZoneBoxPrimitive


def formulate_trade_setup(
    df: pd.DataFrame,
    zones: List[ZoneBoxPrimitive],
    direction: Optional[str] = None,
    thesis: str = "Quantitative trade setup"
) -> Optional[TradeSetupPrimitive]:
    """
    Formulates a mathematically anchored trade setup:
    - Longs anchor Stop Loss cleanly below the Demand Zone.
    - Shorts anchor Stop Loss cleanly above the Supply Zone.
    - Target is anchored to opposing zone or dynamic ATR expansion.
    """
    if len(df) < 15:
        return None

    curr_price = float(df["close"].iloc[-1])
    curr_time = int(df["time"].iloc[-1])

    # Compute ATR for buffer sizing
    tr = np.maximum(
        df["high"] - df["low"],
        np.abs(df["high"] - df["close"].shift(1))
    ).fillna(10.0)
    atr = float(tr.rolling(14, min_periods=1).mean().iloc[-1])

    # Find Demand and Supply zones
    demand_zones = [z for z in zones if z.type == "DEMAND"]
    supply_zones = [z for z in zones if z.type == "SUPPLY"]

    # Determine direction if not explicitly given
    if not direction:
        # If price is closer to Demand -> bias Long; if closer to Supply -> bias Short
        if demand_zones and supply_zones:
            dist_to_demand = curr_price - demand_zones[0].price_high
            dist_to_supply = supply_zones[0].price_low - curr_price
            direction = "LONG" if dist_to_demand <= dist_to_supply else "SHORT"
        else:
            direction = "LONG"

    if direction == "LONG":
        entry = curr_price
        if demand_zones:
            # Stop loss anchored below the demand zone with 0.2 ATR buffer
            stop_loss = round(demand_zones[0].price_low - (0.2 * atr), 2)
        else:
            stop_loss = round(entry - (1.5 * atr), 2)

        # Target: Overhead supply zone floor, or at least 2.5x Risk
        risk = max(abs(entry - stop_loss), 1.0)
        if supply_zones and supply_zones[0].price_low > entry + (1.2 * risk):
            take_profit = round(supply_zones[0].price_low, 2)
        else:
            take_profit = round(entry + (2.5 * risk), 2)

        reward = max(abs(take_profit - entry), 1.0)
        rr = round(reward / risk, 2)

    else:  # SHORT
        entry = curr_price
        if supply_zones:
            # Stop loss anchored above the supply zone with 0.25 ATR buffer
            stop_loss = round(supply_zones[0].price_high + (0.25 * atr), 2)
        else:
            stop_loss = round(entry + (1.5 * atr), 2)

        if demand_zones and demand_zones[0].price_high < entry:
            take_profit = round(demand_zones[0].price_high, 2)
        else:
            take_profit = round(entry - (3.0 * atr), 2)

        risk = max(abs(stop_loss - entry), 1.0)
        reward = max(abs(entry - take_profit), 1.0)
        rr = round(reward / risk, 2)

    return TradeSetupPrimitive(
        id=f"setup_{curr_time}",
        direction=direction,
        entry_price=round(entry, 2),
        stop_loss=round(stop_loss, 2),
        take_profit=round(take_profit, 2),
        rr_ratio=rr,
        time_entry=curr_time,
        thesis=thesis
    )
