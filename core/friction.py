"""
core/friction.py - Universal Single Source of Truth for Broker Friction, Carry & Hurdle Math.
Used by: AI CLI tools, Backtest Simulation, Live Bot Execution, and Server APIs.

Design principles:
  - Exact normalized symbol lookup for major benchmarks (never loose substring matching).
  - Dynamic asset-class inference for ANY instrument a user brings (crypto, equities/ETFs,
    futures, FX, or custom local datasets) so the engine stays universal without silent
    zero-fee fallbacks.
  - Full caller/strategy override support (`friction_override`) and optional overnight
    financing (`daily_carry_bps`, default 0.0 unless configured).
"""
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger("Friction")

_CRYPTO_EXCHANGES = {"BINANCE", "BYBIT", "COINBASE", "OKX", "KRAKEN", "BITGET", "KUCOIN", "DERIBIT", "HYPERLIQUID"}
_EQUITY_EXCHANGES = {"NASDAQ", "NYSE", "AMEX", "ARCA", "BATS", "LSE", "XETR", "TSX", "ASX", "TSE", "HKEX"}
_FUTURES_EXCHANGES = {"CME", "CME_MINI", "CBOT", "NYMEX", "COMEX", "ICE", "ICEUS", "EUREX", "CBOE"}
_FX_EXCHANGES = {"OANDA", "FX", "FXCM", "PEPPERSTONE", "ICMARKETS", "FOREXCOM", "SAXO", "CAPITALCOM"}
_ISO_FX_CCYS = {"EUR", "GBP", "AUD", "NZD", "CAD", "CHF", "USD", "JPY", "SEK", "NOK", "SGD", "HKD", "MXN", "ZAR", "CNH"}


def resolve_asset_friction(
    symbol: str,
    price: float,
    friction_override: Optional[Dict[str, float]] = None,
) -> Tuple[float, float, float]:
    """
    Returns (spread_pts, fee_pct, slippage_pts) for ANY instrument dynamically.

    Priority:
      1. Explicit `friction_override` dict (e.g. from strategy or broker profile).
      2. Exact normalized institutional benchmark schedule.
      3. Dynamic asset-class inference (crypto / equity-ETF / futures / FX / conservative generic).
    """
    if friction_override:
        sp = float(friction_override.get("spread_pts", 0.0))
        fee = float(friction_override.get("fee_pct", 0.0))
        sl = float(friction_override.get("slippage_pts", 0.0))
        return max(0.0, sp), max(0.0, fee), max(0.0, sl)

    from core.data import resolve_market_symbol
    resolved = resolve_market_symbol(symbol)
    px = max(float(price or 0.0), 1e-9)

    # 1. Exact benchmark schedules (realistic institutional / raw-ECN / exchange taker pricing)
    if resolved == "OANDA:XAUUSD":
        return 0.25, 0.000035, 0.05
    if resolved == "COMEX:GC1!":
        return 0.20, 0.00001, 0.10
    if resolved == "CME_MINI:ES1!":
        return 0.50, 0.00001, 0.25
    if resolved == "AMEX:SPY":
        return 0.02, 0.00001, 0.02
    if resolved == "CME_MINI:NQ1!":
        return 1.00, 0.00001, 0.50
    if resolved == "NASDAQ:QQQ":
        return 0.02, 0.00001, 0.02
    if resolved == "TVC:USOIL":
        return 0.03, 0.00005, 0.02
    if resolved == "BINANCE:BTCUSDT":
        return 5.0, 0.0004, 2.5
    if resolved == "BINANCE:ETHUSDT":
        return 0.50, 0.0004, 0.25
    if resolved == "BINANCE:SOLUSDT":
        return px * 0.0003, 0.0004, px * 0.0002
    if resolved in ("OANDA:EURUSD", "OANDA:USDJPY", "OANDA:GBPUSD"):
        return px * 0.00008, 0.000035, px * 0.00002

    # 2. Universal dynamic asset-class inference (exchange + ticker structure)
    exchange, ticker = resolved.split(":", 1) if ":" in resolved else ("", resolved)
    exchange = exchange.upper()
    ticker = ticker.upper()

    # 2a. Crypto (exchange or quote suffix)
    if exchange in _CRYPTO_EXCHANGES or ticker.endswith(("USDT", "USDC", "BUSD", "PERP")):
        return px * 0.0003, 0.0004, px * 0.0002

    # 2b. Equities & ETFs
    if exchange in _EQUITY_EXCHANGES:
        return max(0.01, px * 0.0001), 0.00001, max(0.01, px * 0.0001)

    # 2c. Futures (exchange or continuous contract suffix 1!/2!)
    if exchange in _FUTURES_EXCHANGES or ticker.endswith(("1!", "2!")):
        return px * 0.00015, 0.000015, px * 0.0001

    # 2d. Forex (6-char ISO pair or FX venue)
    is_iso_fx = len(ticker) == 6 and ticker.isalpha() and ticker[:3] in _ISO_FX_CCYS and ticker[3:] in _ISO_FX_CCYS
    if is_iso_fx or exchange in _FX_EXCHANGES:
        return px * 0.00015, 0.000035, px * 0.00003

    # 2e. Conservative non-zero generic schedule for arbitrary/custom instruments
    logger.debug(
        f"[Friction] Using dynamic conservative default for custom instrument '{symbol}' (resolved='{resolved}'). "
        "Pass friction_override on strategy for broker-exact costs."
    )
    return px * 0.0002, 0.00005, px * 0.0001


def compute_carry_cost(
    price: float,
    holding_hours: float,
    direction: int = 1,
    daily_carry_bps: float = 0.0,
) -> float:
    """
    Computes optional overnight financing / funding cost in price units.
    Default `daily_carry_bps=0.0` (opt-in per strategy/broker so no single broker's swap sheet is forced).
    Conservative: positive `daily_carry_bps` charges drag proportional to holding_hours / 24.
    """
    if daily_carry_bps <= 0.0 or holding_hours <= 0.0 or price <= 0.0:
        return 0.0
    return float(price) * (float(daily_carry_bps) / 10000.0) * (float(holding_hours) / 24.0)


def get_roundtrip_friction(
    symbol: str,
    price: float,
    atr: float = 0.0,
    friction_override: Optional[Dict[str, float]] = None,
) -> float:
    """Returns authentic round-trip dollar drag per unit (1x spread + roundtrip fees + 2x slippage)."""
    spread_pts, fee_pct, slippage_pts = resolve_asset_friction(symbol, price, friction_override=friction_override)
    return spread_pts + (price * fee_pct * 2.0) + (slippage_pts * 2.0)


def check_friction_hurdle(
    symbol: str,
    entry_price: float,
    stop_distance: float,
    friction_override: Optional[Dict[str, float]] = None,
) -> Tuple[bool, float]:
    """
    Enforces the Institutional Friction Floor:
    Round-trip friction must be <= 10.0% of stop distance.
    Returns: (passes_hurdle: bool, friction_ratio_pct: float)
    """
    if stop_distance <= 0:
        return False, 100.0
    rt_cost = get_roundtrip_friction(symbol, entry_price, friction_override=friction_override)
    ratio_pct = (rt_cost / stop_distance) * 100.0
    return ratio_pct <= 10.0, round(ratio_pct, 2)
