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
    order_type: str = "LIMIT",
    thesis: str = "Quantitative trade setup"
) -> Optional[TradeSetupPrimitive]:
    """
    Formulates a mathematically anchored trade setup:
    - If order_type == 'LIMIT' (pullback setup):
        - Longs enter at the upper boundary of the Demand zone for tight risk and high R:R.
        - Shorts enter at the lower boundary of the Supply zone.
    - If order_type == 'MARKET':
        - Enters at current close.
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

    demand_zones = [z for z in zones if z.type == "DEMAND"]
    supply_zones = [z for z in zones if z.type == "SUPPLY"]

    if not direction:
        if demand_zones and supply_zones:
            dist_to_demand = curr_price - demand_zones[0].price_high
            dist_to_supply = supply_zones[0].price_low - curr_price
            direction = "LONG" if dist_to_demand <= dist_to_supply else "SHORT"
        else:
            direction = "LONG"

    if direction == "LONG":
        if order_type.upper() == "LIMIT" and demand_zones and demand_zones[0].price_high < curr_price:
            # High expectancy Limit order: wait for pullback to top of Demand zone
            entry = round(demand_zones[0].price_high, 2)
            stop_loss = round(demand_zones[0].price_low - (0.2 * atr), 2)
        else:
            entry = round(curr_price, 2)
            stop_loss = round(demand_zones[0].price_low - (0.2 * atr), 2) if demand_zones else round(entry - (1.5 * atr), 2)

        risk = max(abs(entry - stop_loss), 1.0)
        if supply_zones and supply_zones[0].price_low > entry + (1.5 * risk):
            take_profit = round(supply_zones[0].price_low, 2)
        else:
            take_profit = round(entry + (3.0 * risk), 2)

        reward = max(abs(take_profit - entry), 1.0)
        rr = round(reward / risk, 2)

    else:  # SHORT
        if order_type.upper() == "LIMIT" and supply_zones and supply_zones[0].price_low > curr_price:
            # High expectancy Limit order: wait for rally into base of Supply zone
            entry = round(supply_zones[0].price_low, 2)
            stop_loss = round(supply_zones[0].price_high + (0.2 * atr), 2)
        else:
            entry = round(curr_price, 2)
            stop_loss = round(supply_zones[0].price_high + (0.2 * atr), 2) if supply_zones else round(entry + (1.5 * atr), 2)

        risk = max(abs(stop_loss - entry), 1.0)
        if demand_zones and demand_zones[0].price_high < entry - (1.5 * risk):
            take_profit = round(demand_zones[0].price_high, 2)
        else:
            take_profit = round(entry - (3.0 * risk), 2)

        reward = max(abs(entry - take_profit), 1.0)
        rr = round(reward / risk, 2)

    return TradeSetupPrimitive(
        id=f"setup_{curr_time}",
        direction=direction,
        order_type=order_type.upper(),
        entry_price=round(entry, 2),
        stop_loss=round(stop_loss, 2),
        take_profit=round(take_profit, 2),
        rr_ratio=rr,
        time_entry=curr_time,
        thesis=thesis
    )
