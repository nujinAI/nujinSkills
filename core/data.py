"""
core/data.py - The Single Source of Truth for Market Data & Candles.
Used by: AI Agent data tools, Server backtest engine, and Live Streamer.
"""
from typing import Optional
import os
import pandas as pd
from server.engines import data_manager

def resolve_market_symbol(symbol: str) -> str:
    """Canonical mapping to institutional broker/TV symbol."""
    return data_manager.resolve_market_symbol(symbol)

def fetch_ohlcv(symbol: str, timeframe: str = "5m", count: int = 2000) -> pd.DataFrame:
    """
    Fetches clean, continuous OHLCV candles via TradingView / Broker provider.
    Strictly Spot Cash only. Commodity Futures (GC=F, COMEX) are prohibited.
    Returns: DataFrame with DatetimeIndex and lowercase ['open', 'high', 'low', 'close', 'volume', 'atr']
    """
    if not symbol or not str(symbol).strip():
        raise ValueError("Explicit market symbol is required. No silent fallbacks permitted.")

    upper_sym = str(symbol).strip().upper()
    if any(f in upper_sym for f in ["GC=", "GC1", "GC=F", "COMEX"]):
        raise ValueError(
            f"Commodity Futures '{symbol}' are prohibited. We trade Spot Cash ('OANDA:XAUUSD')."
        )

    resolved = resolve_market_symbol(symbol)
    candles = data_manager.fetch_candles_via_tv(resolved, timeframe, count=count)
    if not candles and ("XAU" in resolved or "GOLD" in resolved):
        candles = data_manager.fetch_real_broker_spot_gold_candles(interval=timeframe, count=min(count, 1000))
    if not candles:
        candles = data_manager.fetch_real_binance_klines(symbol=symbol, interval=timeframe, count=count)

    if not candles:
        # Check cached dataset on disk
        cached_file = data_manager.get_market_dataset_path(resolved, timeframe, check_legacy=True)
        if os.path.exists(cached_file):
            df = pd.read_csv(cached_file)
            time_col = "time" if "time" in df.columns else ("timestamp" if "timestamp" in df.columns else None)
            if time_col:
                df[time_col] = pd.to_datetime(df[time_col], unit="s", utc=True)
                df.set_index(time_col, inplace=True)
                return _standardize_df(df)
        raise RuntimeError(f"Could not retrieve authentic candle data for {symbol} ({timeframe})")

    df = pd.DataFrame(candles)
    time_col = "time" if "time" in df.columns else ("timestamp" if "timestamp" in df.columns else None)
    if time_col:
        df[time_col] = pd.to_datetime(df[time_col], unit="s", utc=True)
        df.set_index(time_col, inplace=True)

    return _standardize_df(df)

def _standardize_df(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).lower().replace(' ', '_') for c in df.columns]
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['close'].shift(1)).abs()
    tr3 = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['tr'] = tr
    df['atr'] = tr.ewm(alpha=1/14).mean()
    return df
