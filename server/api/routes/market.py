import logging
import os
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException

from server.api.deps import manager, strategy_registry
from server.providers.base import ProviderRegistry
from server.services import data_manager

logger = logging.getLogger("NujinMarketRouter")
router = APIRouter(tags=["Market Data & Quotes"])

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data"))


def _sanitize_candles(candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not candles:
        return []
    import numpy as np
    vols = [float(c.get("volume", 0.0)) for c in candles if float(c.get("volume", 0.0)) > 0]
    med_vol = float(np.median(vols)) if vols else 1000.0
    max_vol = max(med_vol * 6.0, 15000.0)

    clean = []
    for c in candles:
        ts = int(c.get("time") or c.get("timestamp") or 0)
        if ts <= 0:
            continue
        op = round(float(c.get("open", 0.0)), 2)
        hi = round(float(c.get("high", 0.0)), 2)
        lo = round(float(c.get("low", 0.0)), 2)
        cl = round(float(c.get("close", 0.0)), 2)
        if cl <= 0:
            continue
        hi = max(hi, op, cl)
        lo = min(lo, op, cl)
        vol = round(min(float(c.get("volume", 10.0)), max_vol), 1)
        clean.append({
            "time": ts,
            "timestamp": ts,
            "open": op,
            "high": hi,
            "low": lo,
            "close": cl,
            "volume": vol,
        })
    return clean


def _extract_primitives_for_response(strategy_name: Optional[str], candles_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not candles_data:
        return {"lines": [], "series": {}, "boxes": [], "levels": [], "hud_items": []}
    strat = strategy_name or strategy_registry.get_active_strategy_name()
    if not strat:
        return {"lines": [], "series": {}, "boxes": [], "levels": [], "hud_items": []}
    try:
        from server.services.chart_primitives import extract_strategy_primitives
        clean_name = strat.replace(".py", "")
        return extract_strategy_primitives(clean_name, candles_data)
    except Exception as e:
        logger.warning(f"[Primitives] Failed extracting visual primitives for {strat}: {e}")
        return {"lines": [], "series": {}, "boxes": [], "levels": [], "hud_items": []}


@router.get("/api/candles")
async def get_candles(
    symbol: Optional[str] = None,
    count: int = 2500,
    mode: str = "live",
    timeframe: Optional[str] = None,
    strategy: Optional[str] = None,
):
    """
    Returns authentic OHLCV candles from TradingView / ProviderRegistry for ANY asset.
    Single Source of Truth: automatically resolves exchange symbol and timeframe.
    """
    if strategy and not timeframe:
        clean_strat = strategy.replace(".py", "")
        rec = strategy_registry.get(clean_strat)
        if rec and rec.get("timeframe"):
            timeframe = rec.get("timeframe")
        rec_sym = rec.get("symbol") if rec else None
        if not symbol and rec_sym and str(rec_sym).lower() not in ["pair", "symbol", "none", "self.symbol"]:
            symbol = rec_sym

    if not symbol or str(symbol).lower() in ["pair", "symbol", "none", "self.symbol"]:
        active_strat = strategy or strategy_registry.get_active_strategy_name()
        clean_active = (active_strat or "").replace(".py", "")
        rec = strategy_registry.get(clean_active) if clean_active else None
        rec_sym = rec.get("symbol") if rec else None
        if rec_sym and str(rec_sym).lower() not in ["pair", "symbol", "none", "self.symbol"]:
            symbol = rec_sym
        else:
            symbol = "BTC/USDT"

    interval = timeframe or "15m"

    try:
        import asyncio
        # Single Market Authority: TradingView / Broker Provider via ProviderRegistry (offloaded from event loop)
        provider = await asyncio.to_thread(ProviderRegistry.get_provider, symbol, interval)
        if not provider.is_running:
            asyncio.create_task(provider.start())

        c_list = await asyncio.to_thread(provider.get_candles, count)
        if c_list and len(c_list) > 0:
            raw_data = c_list[-count:] if (count and count < len(c_list)) else c_list
            data = _sanitize_candles(raw_data)
            prims = _extract_primitives_for_response(strategy, data)
            return {"symbol": symbol, "timeframe": interval, "mode": mode, "data": data, "primitives": prims}

        # Fallback to persistent dataset path via canonical catalog
        dataset_path = data_manager.get_market_dataset_path(symbol, interval)
        if os.path.exists(dataset_path):
            import pandas as pd
            df = pd.read_csv(dataset_path)
            time_col = "timestamp" if "timestamp" in df.columns else "time"
            df = df.dropna(subset=[time_col, "close"]).sort_values(by=time_col)
            records = df.tail(count).to_dict(orient="records") if (count and count > 0) else df.to_dict(orient="records")
            base_candles = [
                {
                    "time": int(r.get("timestamp", r.get("time", 0))),
                    "timestamp": int(r.get("timestamp", r.get("time", 0))),
                    "open": round(float(r["open"]), 2),
                    "high": round(float(r["high"]), 2),
                    "low": round(float(r["low"]), 2),
                    "close": round(float(r["close"]), 2),
                    "volume": round(float(r.get("volume", 10.0)), 4),
                }
                for r in records
            ]
            data = _sanitize_candles(base_candles)
            prims = _extract_primitives_for_response(strategy, data)
            return {"symbol": symbol, "timeframe": interval, "mode": mode, "data": data, "primitives": prims}

        raise HTTPException(
            status_code=503,
            detail=f"Authentic market data feed initializing for {symbol} ({interval}). Please retry shortly.",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Candles] Provider fetch notice for {symbol}: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Real market data feed unavailable for {symbol}. Error: {str(e)}",
        )


@router.get("/api/strategy/primitives")
async def get_strategy_primitives(
    strategy: Optional[str] = None,
    symbol: Optional[str] = None,
    timeframe: Optional[str] = None,
):
    strat = strategy or strategy_registry.get_active_strategy_name()
    if not strat:
        return {"lines": [], "series": {}, "boxes": [], "levels": [], "hud_items": []}
    candles_res = await get_candles(symbol=symbol, timeframe=timeframe, strategy=strat, count=2000)
    return candles_res.get("primitives", {"lines": [], "series": {}, "boxes": [], "levels": [], "hud_items": []})


@router.get("/api/widgets")
async def get_widgets():
    return {"widgets": list(manager.widget_state.values())}


@router.get("/api/quote")
async def get_live_quote(symbol: str = "BTC/USDT", timeframe: str = "1m"):
    """Live quote for ANY requested asset directly from ProviderRegistry (Single Authority)."""
    try:
        provider = ProviderRegistry.get_provider(symbol, timeframe)
        quote = provider.get_latest_quote()
        return {"quote": quote, "symbol": symbol, "timeframe": timeframe}
    except Exception as e:
        logger.warning(f"[Quote] Error fetching quote for {symbol}: {e}")
        return {
            "quote": {
                "symbol": symbol,
                "price": 0.0,
                "timestamp": int(time.time()),
                "source": "error",
            },
            "error": str(e),
        }


@router.get("/api/sp500/quote")
async def get_sp500_quote():
    """Compatibility endpoint for S&P 500 / ES."""
    return await get_live_quote(symbol="S&P 500 (ES)", timeframe="1m")


@router.get("/api/xauusd/quote")
async def get_xauusd_quote():
    """Compatibility endpoint for XAU/USD Spot."""
    return await get_live_quote(symbol="XAU/USD", timeframe="1m")
