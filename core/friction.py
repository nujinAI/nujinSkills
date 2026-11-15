"""
core/friction.py - The Single Source of Truth for Broker Friction & Hurdle Math.
Used by: AI CLI tools, Backtest Simulation, Live Bot Execution, and Server APIs.
"""
from typing import Tuple

def resolve_asset_friction(symbol: str, price: float) -> Tuple[float, float, float]:
    """
    Returns (spread_pts, fee_pct, slippage_pts) for any asset.
    Pure execution reality. Spot Cash only.
    """
    sym = (symbol or "").upper()
    if "XAU" in sym or "GOLD" in sym:
        # Gold Spot CFD: ~$0.25 typical spread, $0.05 slippage buffer
        return 0.25, 0.0000, 0.05
    elif "BTC" in sym:
        # Crypto: 0.04% taker fee, $5.0 spread
        return 5.0, 0.0004, 2.5
    elif "ETH" in sym:
        return 0.50, 0.0004, 0.25
    elif any(k in sym for k in ["SPX", "US500", "ES", "SP500"]):
        # Equity index: 0.50 index pts spread
        return 0.50, 0.0000, 0.20
    elif any(k in sym for k in ["EURUSD", "USDJPY", "GBPUSD"]):
        # Major Forex: 0.8 pips spread, 0.2 pips slippage
        spread_pts = price * 0.00008
        slippage_pts = price * 0.00002
        return spread_pts, 0.0000, slippage_pts
    else:
        # Cross Forex / Spot: 1.5 pips spread
        spread_pts = price * 0.00015
        slippage_pts = price * 0.00003
        return spread_pts, 0.0000, slippage_pts

def get_roundtrip_friction(symbol: str, price: float, atr: float = 0.0) -> float:
    """Returns authentic round-trip dollar drag per unit (1x spread + roundtrip fees + 2x slippage)."""
    spread_pts, fee_pct, slippage_pts = resolve_asset_friction(symbol, price)
    return spread_pts + (price * fee_pct * 2.0) + (slippage_pts * 2.0)

def check_friction_hurdle(symbol: str, entry_price: float, stop_distance: float) -> Tuple[bool, float]:
    """
    Enforces the Institutional Friction Floor:
    Round-trip friction must be <= 10.0% of stop distance.
    Returns: (passes_hurdle: bool, friction_ratio_pct: float)
    """
    if stop_distance <= 0:
        return False, 100.0
    rt_cost = get_roundtrip_friction(symbol, entry_price)
    ratio_pct = (rt_cost / stop_distance) * 100.0
    return ratio_pct <= 10.0, round(ratio_pct, 2)
