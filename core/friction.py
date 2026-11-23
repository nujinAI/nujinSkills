"""
core/friction.py - The Single Source of Truth for Broker Friction & Hurdle Math.
Used by: AI CLI tools, Backtest Simulation, Live Bot Execution, and Server APIs.
"""
from typing import Dict, Tuple


def resolve_asset_friction(symbol: str, price: float) -> Tuple[float, float, float]:
    """
    Returns (spread_pts, fee_pct, slippage_pts) for any supported asset.
    Uses exact normalized symbol resolution (no loose substring matching or silent fallbacks).
    """
    from core.data import resolve_market_symbol
    resolved = resolve_market_symbol(symbol)

    # Exact per-instrument friction table: (spread_pts_or_none, fee_pct, slippage_pts_or_none, spread_pct_if_none, slip_pct_if_none)
    # Commissions reflect institutional raw-spread / exchange taker schedules.
    if resolved == "OANDA:XAUUSD":
        # Spot Gold CFD: $0.25 spread, ~$7/lot RT (~0.0035% per side), $0.05 slippage
        return 0.25, 0.000035, 0.05
    if resolved == "COMEX:GC1!":
        # COMEX Gold Futures: $0.20 spread (2 ticks), ~$2.50/side (~0.001%), $0.10 slippage
        return 0.20, 0.00001, 0.10
    if resolved == "CME_MINI:ES1!":
        # E-mini S&P 500 Futures: 0.25-0.50 pts spread, ~$2.25/side (~0.0008%), 0.25 pts slippage
        return 0.50, 0.00001, 0.25
    if resolved == "AMEX:SPY":
        # SPY ETF: $0.02 spread, 0.001% SEC/clearing/slippage
        return 0.02, 0.00001, 0.02
    if resolved == "CME_MINI:NQ1!":
        # E-mini / Micro Nasdaq-100 Futures: 0.50-1.00 pts spread, ~$2.25/side (~0.0008%), 0.50 pts slippage
        return 1.00, 0.00001, 0.50
    if resolved == "NASDAQ:QQQ":
        # QQQ ETF: $0.02 spread, 0.001% fee, $0.02 slippage
        return 0.02, 0.00001, 0.02
    if resolved == "TVC:USOIL":
        # WTI Crude Oil: $0.03 spread, 0.005% fee, $0.02 slippage
        return 0.03, 0.00005, 0.02
    if resolved == "BINANCE:BTCUSDT":
        # Crypto BTC: 0.04% taker fee, $5.0 spread, $2.5 slippage
        return 5.0, 0.0004, 2.5
    if resolved == "BINANCE:ETHUSDT":
        # Crypto ETH: 0.04% taker fee, $0.50 spread, $0.25 slippage
        return 0.50, 0.0004, 0.25
    if resolved == "BINANCE:SOLUSDT":
        # Crypto SOL: 0.04% taker fee, 0.03% spread, 0.02% slippage
        return price * 0.0003, 0.0004, price * 0.0002
    if resolved in ("OANDA:EURUSD", "OANDA:USDJPY", "OANDA:GBPUSD"):
        # Major Forex (Raw ECN): 0.8 pips spread, $7/lot RT (~0.0035% per side), 0.2 pips slippage
        return price * 0.00008, 0.000035, price * 0.00002

    # Explicitly fail on unknown symbols rather than silently applying a cheap FX fallback
    raise ValueError(
        f"[Friction] Unknown or unsupported instrument '{symbol}' (resolved='{resolved}'). "
        "Add its exact friction schedule to core/friction.py before backtesting."
    )

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
