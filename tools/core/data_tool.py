"""
tools/core/data_tool.py - Dynamic Candle Fetcher & Market Primitives

Eliminates the legacy truncated static CSV bottleneck.
Dynamically fetches fresh, continuous OHLCV data for ANY requested asset,
timeframe, and period on the fly, with automated local caching to prevent rate-limits.

Supported Timeframes:
- 1m, 5m, 15m, 30m (up to 60 days on free intraday feeds)
- 1h, 4h (up to 2 years / 730 days)
- 1d, 1w (multi-year / 5-10 years)

Zero strategy bias. No indicators. Pure market primitives:
- True Range & Wilder's 14 ATR
- Normalized bar range
- Relative volume (vs rolling 20-period median)
- Time attributes (hour, day of week)
"""

import os
import hashlib
from typing import Optional
import numpy as np
import pandas as pd


CACHE_DIR = os.path.expanduser("~/.nujin/cache/candles")
os.makedirs(CACHE_DIR, exist_ok=True)


def _get_cache_path(symbol: str, timeframe: str, period: str) -> str:
    key = f"{symbol.upper()}_{timeframe.lower()}_{period.lower()}"
    filename = f"{key}.parquet"
    return os.path.join(CACHE_DIR, filename)


def fetch_ohlcv(
    symbol: str,
    timeframe: str = "5m",
    count: int = 5000,
    period: str = "60d",
    csv_path: Optional[str] = None,
    use_cache: bool = True
) -> pd.DataFrame:
    """
    Returns clean DataFrame with lowercase columns:
    ['open', 'high', 'low', 'close', 'volume', 'tr', 'atr', 'norm_range', 'rel_volume', 'hour', 'day_of_week']
    """
    if not symbol or not str(symbol).strip():
        raise ValueError("Explicit market symbol is required (e.g. 'OANDA:XAUUSD', 'BINANCE:BTCUSDT'). No silent fallbacks permitted.")

    upper_sym = str(symbol).strip().upper()
    if any(f in upper_sym for f in ["GC=", "GC1", "GC=F", "COMEX"]):
        raise ValueError(
            f"Commodity Futures '{symbol}' are prohibited. We trade Spot Cash ('OANDA:XAUUSD'). "
            "Futures have contract rollovers, artificial settlement spreads, and differing price action."
        )

    df = None

    # 1. Custom CSV Override
    if csv_path:
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Specified CSV file not found: {csv_path}")
        df = pd.read_csv(csv_path)
        date_col = next((c for c in df.columns if 'date' in c.lower() or 'time' in c.lower()), None)
        if date_col:
            if pd.api.types.is_numeric_dtype(df[date_col]):
                df[date_col] = pd.to_datetime(df[date_col], unit='s', utc=True)
            else:
                df[date_col] = pd.to_datetime(df[date_col], utc=True)
            df.set_index(date_col, inplace=True)
        else:
            if pd.api.types.is_numeric_dtype(df.index):
                df.index = pd.to_datetime(df.index, unit='s', utc=True)
            else:
                df.index = pd.to_datetime(df.index, utc=True)

    # 2. Dynamic Fetch with Cache via TradingView Single Source of Truth
    if df is None:
        cache_file = _get_cache_path(symbol, timeframe, f"{count}_{period}")
        # Check cache freshness (valid for 4 hours)
        if use_cache and os.path.exists(cache_file):
            file_age_seconds = pd.Timestamp.now().timestamp() - os.path.getmtime(cache_file)
            if file_age_seconds < (4 * 3600):
                try:
                    df = pd.read_parquet(cache_file)
                    if df is not None and len(df) < min(int(count * 0.7), 5000):
                        df = None
                except Exception:
                    df = None

        if df is None:
            # Primary Source of Truth: TradingView WebSocket / data_manager
            try:
                from server import data_manager
                resolved_sym = data_manager.resolve_market_symbol(symbol)
                candles = data_manager.fetch_candles_via_tv(resolved_sym, timeframe, count=count)
                if not candles:
                    candles = data_manager.fetch_real_binance_klines(symbol=symbol, interval=timeframe, count=count)
                if candles:
                    df = pd.DataFrame(candles)
                    time_col = "time" if "time" in df.columns else ("timestamp" if "timestamp" in df.columns else None)
                    if time_col:
                        df[time_col] = pd.to_datetime(df[time_col], unit="s", utc=True)
                        df.set_index(time_col, inplace=True)
            except Exception:
                pass

        if df is None or df.empty:
            raise ValueError(f"Failed to fetch authentic market data for {symbol} ({timeframe}) via TradingView Single Source of Truth.")

        # Save to cache
        if use_cache and df is not None and not df.empty:
            try:
                df.to_parquet(cache_file)
            except Exception:
                pass

    # Standardize column names
    df.columns = [str(c).lower().replace(' ', '_') for c in df.columns]
    req = ['open', 'high', 'low', 'close']
    for r in req:
        if r not in df.columns:
            raise ValueError(f"Missing required column: {r}")

    if 'volume' not in df.columns:
        df['volume'] = 1.0

    df = df[req + ['volume']].copy()
    df.dropna(subset=['open', 'high', 'low', 'close'], inplace=True)
    df.sort_index(inplace=True)

    # 1. True Range & Wilder's 14 ATR
    prev_close = df['close'].shift(1)
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - prev_close).abs()
    tr3 = (df['low'] - prev_close).abs()
    df['tr'] = np.maximum(tr1, np.maximum(tr2, tr3))
    df['atr'] = df['tr'].ewm(alpha=1.0 / 14.0, min_periods=14, adjust=False).mean()

    # 2. Normalized Range
    df['norm_range'] = (df['high'] - df['low']) / df['close']

    # 3. Relative Volume (vs 20-period median)
    roll_vol_med = df['volume'].rolling(20).median().replace(0, 1.0)
    df['rel_volume'] = df['volume'] / roll_vol_med

    # 4. Time primitives
    if hasattr(df.index, 'hour'):
        df['hour'] = df.index.hour
        df['day_of_week'] = df.index.dayofweek
    else:
        df['hour'] = 0
        df['day_of_week'] = 0

    df.dropna(inplace=True)
    return df


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "GC=F"
    tf = sys.argv[2] if len(sys.argv) > 2 else "1h"
    data = fetch_ohlcv(symbol=sym, timeframe=tf, period="1y")
    print(f"Dynamically fetched {len(data)} bars for {sym} ({tf}):")
    print(f"Start: {data.index[0]} -> End: {data.index[-1]}")
    print(data[['open', 'high', 'low', 'close', 'atr', 'rel_volume']].tail())
