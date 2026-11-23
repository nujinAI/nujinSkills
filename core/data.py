import os
import json
import time
import logging
import urllib.request
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import pandas as pd
import numpy as np

logger = logging.getLogger("DataManager")
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MARKET_DIR = os.path.join(_ROOT, "data", "market")
CATALOG_PATH = os.path.join(MARKET_DIR, "catalog.json")

# Institutional TradingView WebSocket Client
try:
    from tradingview_websocket import TradingViewWebSocket
    HAS_TV_WS = True
except ImportError:
    HAS_TV_WS = False
    logger.warning("[DataManager] tradingview_websocket library not installed. Falling back to REST.")


import re as _re

_EXACT_SYMBOL_MAP: Dict[str, str] = {
    # Spot Gold
    "XAUUSD": "OANDA:XAUUSD",
    "GOLD": "OANDA:XAUUSD",
    "XAU": "OANDA:XAUUSD",
    "OANDA": "OANDA:XAUUSD",
    "OANDAXAUUSD": "OANDA:XAUUSD",
    # Gold Futures
    "GC": "COMEX:GC1!",
    "GC1": "COMEX:GC1!",
    "GC1!": "COMEX:GC1!",
    "MGC": "COMEX:GC1!",
    "MGC1": "COMEX:GC1!",
    "MGC1!": "COMEX:GC1!",
    # S&P 500 Futures / Index
    "SP500": "CME_MINI:ES1!",
    "SPX": "CME_MINI:ES1!",
    "ES": "CME_MINI:ES1!",
    "ES1": "CME_MINI:ES1!",
    "ES1!": "CME_MINI:ES1!",
    "MES": "CME_MINI:ES1!",
    "MES1": "CME_MINI:ES1!",
    "MES1!": "CME_MINI:ES1!",
    "US500": "CME_MINI:ES1!",
    "SP500ES": "CME_MINI:ES1!",
    # S&P 500 ETF
    "SPY": "AMEX:SPY",
    # Nasdaq 100 Futures / Index
    "NQ": "CME_MINI:NQ1!",
    "NQ1": "CME_MINI:NQ1!",
    "NQ1!": "CME_MINI:NQ1!",
    "MNQ": "CME_MINI:NQ1!",
    "MNQ1": "CME_MINI:NQ1!",
    "MNQ1!": "CME_MINI:NQ1!",
    "NDX": "CME_MINI:NQ1!",
    "NAS100": "CME_MINI:NQ1!",
    "US100": "CME_MINI:NQ1!",
    "NASDAQ100": "CME_MINI:NQ1!",
    # Nasdaq 100 ETF
    "QQQ": "NASDAQ:QQQ",
    # Crude Oil
    "CL": "TVC:USOIL",
    "CL1": "TVC:USOIL",
    "CL1!": "TVC:USOIL",
    "USOIL": "TVC:USOIL",
    "WTI": "TVC:USOIL",
    "CRUDEOIL": "TVC:USOIL",
    # Major FX
    "EURUSD": "OANDA:EURUSD",
    "OANDAEURUSD": "OANDA:EURUSD",
    "GBPUSD": "OANDA:GBPUSD",
    "OANDAGBPUSD": "OANDA:GBPUSD",
    "USDJPY": "OANDA:USDJPY",
    "OANDAUSDJPY": "OANDA:USDJPY",
    # Major Crypto
    "BTC": "BINANCE:BTCUSDT",
    "BTCUSD": "BINANCE:BTCUSDT",
    "BTCUSDT": "BINANCE:BTCUSDT",
    "BINANCEBTCUSDT": "BINANCE:BTCUSDT",
    "ETH": "BINANCE:ETHUSDT",
    "ETHUSD": "BINANCE:ETHUSDT",
    "ETHUSDT": "BINANCE:ETHUSDT",
    "BINANCEETHUSDT": "BINANCE:ETHUSDT",
    "SOL": "BINANCE:SOLUSDT",
    "SOLUSD": "BINANCE:SOLUSDT",
    "SOLUSDT": "BINANCE:SOLUSDT",
    "BINANCESOLUSDT": "BINANCE:SOLUSDT",
}


def _normalize_ticker_key(raw: str) -> str:
    """Strips parenthetical display suffixes (e.g. 'MNQ (Futures)' -> 'MNQ') and punctuation."""
    s = (raw or "").strip()
    s = _re.sub(r"\([^)]*\)", "", s)
    return s.replace("/", "").replace("-", "").replace(":", "").replace("_", "").replace(" ", "").replace("&", "").upper()


def resolve_market_symbol(symbol: str) -> str:
    """Maps user symbol to institutional exchange symbol using exact normalized lookup (never loose substrings)."""
    raw = (symbol or "").strip()
    if ":" in raw:
        # User explicitly passed exchange:ticker (e.g. COINBASE:BTCUSD, NASDAQ:QQQ, AMEX:SPY, OANDA:XAUUSD)
        return raw.upper()

    upper = _normalize_ticker_key(raw)
    if upper in _EXACT_SYMBOL_MAP:
        return _EXACT_SYMBOL_MAP[upper]
    return upper


def get_market_price_precision(symbol: str) -> int:
    """Returns price decimal precision for asset class (FX: 5 decimals, JPY: 3, Crypto/Indices/Metals: 2)."""
    resolved = resolve_market_symbol(symbol)
    ticker = resolved.split(":", 1)[1] if ":" in resolved else resolved
    if ticker in ("OANDA:XAUUSD", "XAUUSD", "GC1!", "ES1!", "NQ1!", "SPY", "QQQ", "USOIL", "BTCUSDT", "ETHUSDT", "SOLUSDT"):
        return 2
    if len(ticker) == 6 and ticker.isalpha():
        if ticker.endswith("JPY"):
            return 3
        fx_ccys = {"EUR", "GBP", "AUD", "NZD", "CAD", "CHF", "USD", "JPY"}
        if ticker[:3] in fx_ccys and ticker[3:] in fx_ccys:
            return 5
    return 2


def canonical_market_slug(symbol: str) -> str:
    """Returns a clean filesystem slug for a symbol (e.g., XAUUSD, BTCUSDT, SP500, NQ1, QQQ, SPY)."""
    tv_sym = resolve_market_symbol(symbol)
    if tv_sym == "OANDA:XAUUSD":
        return "XAUUSD"
    if tv_sym == "CME_MINI:ES1!":
        return "SP500"
    if tv_sym == "CME_MINI:NQ1!":
        return "NQ1"
    if ":" in tv_sym:
        tv_sym = tv_sym.split(":", 1)[1]
    return "".join(c for c in tv_sym.upper() if c.isalnum()) or "BTCUSDT"


def get_market_dataset_path(symbol: str, timeframe: str = "15m", check_legacy: bool = True) -> str:
    """
    Single Source of Truth resolver for persistent market OHLCV datasets.
    Canonical path: `data/market/<SLUG>_<TF>.csv`
    """
    slug = canonical_market_slug(symbol)
    tf = (timeframe or "15m").lower().strip()
    os.makedirs(MARKET_DIR, exist_ok=True)
    canon_path = os.path.join(MARKET_DIR, f"{slug}_{tf}.csv")
    if os.path.exists(canon_path) or not check_legacy:
        return canon_path

    # Check legacy paths in data/ for seamless backward compatibility
    legacy_candidates = []
    if slug == "XAUUSD":
        legacy_candidates.append(os.path.join(_ROOT, "data", f"xauusd_candles_{tf}.csv"))
        if tf == "1m":
            legacy_candidates.append(os.path.join(_ROOT, "data", "xauusd_candles_1m.csv"))
    elif slug == "SP500":
        legacy_candidates.append(os.path.join(_ROOT, "data", f"sp500_candles_{tf}.csv"))
        legacy_candidates.append(os.path.join(_ROOT, "data", "sp500_candles_1m.csv"))
    elif slug == "BTCUSDT":
        if tf == "15m":
            legacy_candidates.append(os.path.join(_ROOT, "data", "candles_15m.csv"))
        legacy_candidates.append(os.path.join(_ROOT, "data", f"btc_candles_{tf}.csv"))

    for cand in legacy_candidates:
        if os.path.exists(cand):
            return cand

    return canon_path


def _market_lock(lock_name: str = ".catalog.lock"):
    """Context manager for advisory file locking on the market cache (prevents concurrent corruption)."""
    import contextlib
    try:
        import fcntl
    except ImportError:
        fcntl = None

    @contextlib.contextmanager
    def _cm():
        os.makedirs(MARKET_DIR, exist_ok=True)
        lock_path = os.path.join(MARKET_DIR, lock_name)
        fh = open(lock_path, "a+", encoding="utf-8")
        try:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                if fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            finally:
                fh.close()

    return _cm()


def update_market_catalog(symbol: str, timeframe: str, path: str, df: pd.DataFrame, source: str = "live") -> None:
    """Updates `data/market/catalog.json` atomically under a file lock."""
    try:
        with _market_lock(".catalog.lock"):
            catalog: Dict[str, Any] = {}
            if os.path.exists(CATALOG_PATH):
                try:
                    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                        catalog = json.load(f)
                except Exception:
                    catalog = {}

            slug = canonical_market_slug(symbol)
            tf = (timeframe or "15m").lower().strip()
            key = f"{slug}_{tf}"
            t_col = "timestamp" if "timestamp" in df.columns else ("time" if "time" in df.columns else None)
            start_ts = int(df[t_col].iloc[0]) if (t_col and len(df) > 0) else 0
            end_ts = int(df[t_col].iloc[-1]) if (t_col and len(df) > 0) else 0

            catalog[key] = {
                "symbol": resolve_market_symbol(symbol),
                "slug": slug,
                "timeframe": tf,
                "path": os.path.relpath(path, _ROOT),
                "rows": int(len(df)),
                "start_timestamp": start_ts,
                "end_timestamp": end_ts,
                "source": source,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            tmp_path = f"{CATALOG_PATH}.{os.getpid()}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(catalog, f, indent=2)
            os.replace(tmp_path, CATALOG_PATH)
    except Exception as e:
        logger.debug(f"[DataManager] Catalog update note: {e}")


def get_market_catalog() -> Dict[str, Any]:
    """Returns the persistent market data catalog."""
    if os.path.exists(CATALOG_PATH):
        try:
            with open(CATALOG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def get_oanda_spot_quote() -> Dict[str, Any]:
    """
    Fetches real-time OANDA cash spot Gold (XAUUSD) quote via TradingView CFD feed.
    Sub-100ms keyless institutional quote matching MetaTrader / cTrader prop firm charts.
    """
    url = "https://scanner.tradingview.com/cfd/scan"
    payload = json.dumps({
        "symbols": {"tickers": ["OANDA:XAUUSD"]},
        "columns": ["close", "open", "high", "low", "bid", "ask", "change", "volume"]
    }).encode("utf-8")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Origin": "https://www.tradingview.com",
        "Referer": "https://www.tradingview.com/"
    }
    req = urllib.request.Request(url, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
            row = d["data"][0]["d"]
            close_p = round(float(row[0]), 2)
            bid_p = round(float(row[4] or close_p - 0.15), 2)
            ask_p = round(float(row[5] or close_p + 0.15), 2)
            return {
                "symbol": "XAU/USD (OANDA Spot)",
                "price": close_p,
                "open": round(float(row[1]), 2),
                "high": round(float(row[2]), 2),
                "low": round(float(row[3]), 2),
                "bid": bid_p,
                "ask": ask_p,
                "change_pct": round(float(row[6] or 0.0), 2),
                "volume": 25.0,
                "volume_increment": 15.0,
                "total_volume_24h": round(float(row[7] or 0.0), 1),
                "timestamp": int(time.time()),
                "source": "oanda_spot"
            }
    except Exception as e:
        clean_sym = "OANDA:XAUUSD"
        logger.error(f"[DataManager] Failed to fetch live quote for {clean_sym}: {e}")
        # Check if authentic historical cache exists to get the latest real recorded bar
        csv_path = get_market_dataset_path(clean_sym, "1m")
        if os.path.exists(csv_path):
            try:
                with open(csv_path, "r", encoding="utf-8") as f:
                    lines = [ln.strip() for ln in f.readlines() if ln.strip()]
                    if len(lines) >= 2:
                        last_row = lines[-1].split(",")
                        cached_p = round(float(last_row[4]), 4)
                        return {
                            "symbol": clean_sym,
                            "price": cached_p,
                            "bid": cached_p,
                            "ask": cached_p,
                            "change_pct": 0.0,
                            "volume": float(last_row[5]) if len(last_row) > 5 else 0.0,
                            "timestamp": int(time.time()),
                            "source": "cache_fallback"
                        }
            except Exception as read_err:
                logger.error(f"[DataManager] Cache read error for {clean_sym}: {read_err}")

        raise RuntimeError(
            f"[DataManager] Cannot obtain quote for '{clean_sym}'. "
            "Live TradingView feed failed and no authentic local cache exists. "
            "Refusing to generate fictitious prices."
        )


def _tf_to_tv_resolution(timeframe: str) -> str:
    """Dynamically converts any timeframe string (1m, 5m, 15m, 30m, 1h, 2h, 4h, 1d, 1w) to TradingView resolution code."""
    tf = (timeframe or "15m").lower().strip()
    if tf in ("d", "1d", "daily", "d1"):
        return "1D"
    if tf in ("w", "1w", "weekly", "w1"):
        return "1W"
    m = _re.fullmatch(r"(\d+)\s*([mhdw])", tf)
    if m:
        val, unit = int(m.group(1)), m.group(2)
        if unit == "m":
            return str(max(1, val))
        if unit == "h":
            return str(max(1, val) * 60)
        if unit == "d":
            return f"{max(1, val)}D"
        if unit == "w":
            return f"{max(1, val)}W"
    # Handle reversed notation like m5, h1, h4, d1
    m_rev = _re.fullmatch(r"([mhdw])(\d+)", tf)
    if m_rev:
        unit, val = m_rev.group(1), int(m_rev.group(2))
        if unit == "m":
            return str(max(1, val))
        if unit == "h":
            return str(max(1, val) * 60)
        if unit == "d":
            return f"{max(1, val)}D"
        if unit == "w":
            return f"{max(1, val)}W"
    if tf.isdigit():
        return tf
    return "15"


def _timeframe_to_seconds(timeframe: str) -> int:
    """Dynamically converts any timeframe string (e.g. 1m, 30m, 2h, 4h, 1d, 1w) into seconds."""
    tf = (timeframe or "15m").lower().strip()
    if tf in ("d", "daily"):
        return 86400
    if tf in ("w", "weekly"):
        return 604800
    m = _re.fullmatch(r"(\d+)\s*([mhdw])", tf)
    if not m:
        m_rev = _re.fullmatch(r"([mhdw])(\d+)", tf)
        if m_rev:
            unit, val = m_rev.group(1), int(m_rev.group(2))
        elif tf.isdigit():
            unit, val = "m", int(tf)
        else:
            return 900
    else:
        val, unit = int(m.group(1)), m.group(2)

    val = max(1, val)
    if unit == "m":
        return val * 60
    if unit == "h":
        return val * 3600
    if unit == "d":
        return val * 86400
    if unit == "w":
        return val * 604800
    return 900


def parse_period_to_days(period: Optional[str]) -> Optional[int]:
    """Parses human period strings ('30d', '12w', '6mo', '1y') into calendar days."""
    if not period:
        return None
    p = str(period).strip().lower()
    m = _re.fullmatch(r"(\d+)\s*(d|day|days|w|wk|week|weeks|mo|mon|month|months|y|yr|year|years)", p)
    if not m:
        return None
    val = int(m.group(1))
    unit = m.group(2)
    if unit.startswith("d"):
        return val
    if unit.startswith("w"):
        return val * 7
    if unit.startswith("mo"):
        return val * 30
    if unit.startswith("y"):
        return val * 365
    return None


def bars_for_days(
    timeframe: str,
    days: int,
    buffer: float = 1.15,
    min_bars: int = 500,
    max_bars: int = 15000,
) -> int:
    """
    Single Source of Truth bar-count calculator shared by scan_edge.py and backtest_engine.py.
    Dynamically derives bar depth from `_timeframe_to_seconds` for ANY timeframe (30m, 2h, 4h, 1d, etc.).
    """
    tf_sec = max(60, _timeframe_to_seconds(timeframe))
    days_req = max(1, int(days or 30))
    bars_per_day = 86400.0 / float(tf_sec)
    raw_bars = int(days_req * bars_per_day * float(buffer))
    return max(int(min_bars), min(int(max_bars), raw_bars))


def resample_candles(candles: List[Dict[str, Any]], target_timeframe: str) -> List[Dict[str, Any]]:
    """
    Vectorized, deterministic candlestick resampling from base bars (e.g. 1m)
    to any higher timeframe (3m, 5m, 15m, 1h, 2h, 4h, 1d).
    Strictly aligns candle time boundaries to epoch modulo: (t // step_sec) * step_sec.
    Preserves full float price precision (never truncates FX or low-priced assets to 2 decimals).
    """
    if not candles:
        return []

    step_sec = _timeframe_to_seconds(target_timeframe)
    if step_sec <= 60:
        return candles

    buckets: Dict[int, Dict[str, Any]] = {}
    for c in candles:
        raw_t = int(c.get("timestamp") or c.get("time") or 0)
        if raw_t <= 0:
            continue
        bucket_t = (raw_t // step_sec) * step_sec
        o = float(c["open"])
        h = float(c["high"])
        l = float(c["low"])
        cl = float(c["close"])
        v = float(c.get("volume", 0.0))

        if bucket_t not in buckets:
            buckets[bucket_t] = {
                "time": bucket_t,
                "timestamp": bucket_t,
                "open": o,
                "high": h,
                "low": l,
                "close": cl,
                "volume": v
            }
        else:
            b = buckets[bucket_t]
            b["high"] = max(b["high"], h)
            b["low"] = min(b["low"], l)
            b["close"] = cl
            b["volume"] = b["volume"] + v

    return list(buckets.values())


def fetch_candles_via_tv(symbol: str, timeframe: str = "1m", count: int = 2000) -> List[Dict[str, Any]]:
    """
    Pulls authentic institutional historical bars using TradingViewWebSocket for ANY symbol/timeframe.
    """
    if not HAS_TV_WS:
        return []

    tv_sym = resolve_market_symbol(symbol)
    tv_tf = _tf_to_tv_resolution(timeframe)
    logger.info(f"[DataManager] Fetching {count} bars for {tv_sym} ({timeframe} -> {tv_tf}) via TradingView WebSocket...")

    try:
        ws = TradingViewWebSocket(tv_sym, tv_tf, count)
        ws.connect()
        ws.run()
        raw_bars = ws.result_data
        if not raw_bars:
            logger.warning(f"[DataManager] No bars returned from TradingView WS for {tv_sym}")
            return []

        candles = []
        for b in raw_bars:
            v = b.get("v", [])
            if len(v) >= 5:
                candles.append({
                    "time": int(v[0]),
                    "timestamp": int(v[0]),
                    "open": float(v[1]),
                    "high": float(v[2]),
                    "low": float(v[3]),
                    "close": float(v[4]),
                    "volume": float(v[5] or 0.0)
                })

        logger.info(f"[DataManager] Successfully received {len(candles)} authentic bars for {tv_sym}")
        return candles
    except Exception as e:
        logger.warning(f"[DataManager] TradingView WS fetch error for {tv_sym}: {e}")
        return []


def _save_canonical_and_legacy(symbol: str, timeframe: str, df: pd.DataFrame, legacy_path: Optional[str] = None, source: str = "live") -> None:
    """Persists OHLCV DataFrame atomically under a per-dataset file lock and updates catalog."""
    slug = canonical_market_slug(symbol)
    tf = (timeframe or "15m").lower().strip()
    canon_path = get_market_dataset_path(symbol, timeframe, check_legacy=False)
    os.makedirs(os.path.dirname(canon_path), exist_ok=True)

    with _market_lock(f".{slug}_{tf}.lock"):
        # Protect deep historical datasets from being truncated by short live slices:
        if os.path.exists(canon_path):
            try:
                df_existing = pd.read_csv(canon_path)
                if not df_existing.empty:
                    df_merged = pd.concat([df_existing, df], ignore_index=True)
                    df_merged.drop_duplicates(subset=["timestamp"], keep="last", inplace=True)
                    df_merged.sort_values(by="timestamp", inplace=True)
                    df = df_merged
            except Exception:
                pass

        tmp_canon = f"{canon_path}.{os.getpid()}.tmp"
        df.to_csv(tmp_canon, index=False)
        os.replace(tmp_canon, canon_path)

        if legacy_path and os.path.abspath(legacy_path) != os.path.abspath(canon_path):
            try:
                os.makedirs(os.path.dirname(legacy_path), exist_ok=True)
                df_leg = df
                if os.path.exists(legacy_path):
                    try:
                        df_leg_existing = pd.read_csv(legacy_path)
                        if not df_leg_existing.empty:
                            df_leg_merged = pd.concat([df_leg_existing, df], ignore_index=True).drop_duplicates(subset=["timestamp"], keep="last")
                            df_leg_merged.sort_values(by="timestamp", inplace=True)
                            df_leg = df_leg_merged
                    except Exception:
                        pass
                tmp_leg = f"{legacy_path}.{os.getpid()}.tmp"
                df_leg.to_csv(tmp_leg, index=False)
                os.replace(tmp_leg, legacy_path)
            except Exception:
                pass

    update_market_catalog(symbol, timeframe, canon_path, df, source=source)


def fetch_real_oanda_candles(interval: str = "1m", count: int = 2880, force_refresh: bool = False) -> List[Dict[str, Any]]:
    """
    Fetches genuine OANDA:XAUUSD spot candles.
    Reads persistent clean CSV cache from disk, or refreshes from TradingView WebSocket.
    Resamples cleanly to 5m, 15m, 1h as needed.
    """
    csv_path = get_market_dataset_path("XAU/USD", "1m")
    legacy_1m = os.path.join(_ROOT, "data", "xauusd_candles_1m.csv")
    csv_5m_path = get_market_dataset_path("XAU/USD", "5m")
    legacy_5m = os.path.join(_ROOT, "data", "xauusd_candles_5m.csv")
    now_ts = int(time.time())

    # 1. For 5m interval, return cached 5m dataset directly if available
    if interval == "5m":
        for p in (csv_5m_path, legacy_5m):
            if os.path.exists(p) and os.path.getsize(p) > 50000:
                try:
                    df_5m = pd.read_csv(p)
                    time_col = "timestamp" if "timestamp" in df_5m.columns else "time"
                    df_5m = df_5m.dropna(subset=[time_col, "close"]).reset_index(drop=True)
                    if len(df_5m) >= 500:
                        bars_5m = [
                            {
                                "time": int(r.get("timestamp", r.get("time", 0))),
                                "timestamp": int(r.get("timestamp", r.get("time", 0))),
                                "open": round(float(r["open"]), 2),
                                "high": round(float(r["high"]), 2),
                                "low": round(float(r["low"]), 2),
                                "close": round(float(r["close"]), 2),
                                "volume": round(float(r.get("volume", 10.0)), 2)
                            }
                            for r in df_5m.to_dict(orient="records")
                        ]
                        return bars_5m[-count:] if count else bars_5m
                except Exception:
                    pass

    # 2. Check if cached 1m CSV exists and is fresh (within 120 seconds)
    if not force_refresh and os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path)
            time_col = "timestamp" if "timestamp" in df.columns else "time"
            df = df.dropna(subset=[time_col, "close"]).reset_index(drop=True)
            if len(df) >= 100:
                last_ts = int(df.iloc[-1][time_col])
                if (now_ts - last_ts) <= 120:
                    try:
                        has_deep_5m = (os.path.exists(legacy_5m) and os.path.getsize(legacy_5m) > 100000) or (os.path.exists(csv_5m_path) and os.path.getsize(csv_5m_path) > 100000)
                        if not has_deep_5m and (not os.path.exists(csv_5m_path) or (os.path.getmtime(csv_path) > os.path.getmtime(csv_5m_path))):
                            full_records = df.to_dict(orient="records")
                            full_bars = [
                                {
                                    "time": int(r.get("timestamp", r.get("time", 0))),
                                    "timestamp": int(r.get("timestamp", r.get("time", 0))),
                                    "open": round(float(r["open"]), 2),
                                    "high": round(float(r["high"]), 2),
                                    "low": round(float(r["low"]), 2),
                                    "close": round(float(r["close"]), 2),
                                    "volume": round(float(r.get("volume", 10.0)), 2)
                                }
                                for r in full_records
                            ]
                            resampled_full_5m = resample_candles(full_bars, "5m")
                            if resampled_full_5m and len(resampled_full_5m) > 50:
                                df_new_5m = pd.DataFrame(resampled_full_5m)
                                if os.path.exists(legacy_5m):
                                    try:
                                        df_old_5m = pd.read_csv(legacy_5m)
                                        if len(df_old_5m) > len(df_new_5m):
                                            df_merged_5m = pd.concat([df_old_5m, df_new_5m], ignore_index=True)
                                            df_merged_5m.drop_duplicates(subset=["timestamp"], keep="last", inplace=True)
                                            df_merged_5m.sort_values(by="timestamp", inplace=True)
                                            df_new_5m = df_merged_5m
                                    except Exception:
                                        pass
                                _save_canonical_and_legacy("XAU/USD", "5m", df_new_5m, legacy_5m, source="resampled_1m")
                    except Exception as e_full_5m:
                        logger.warning(f"[DataManager] Could not sync 5m resampled cache: {e_full_5m}")

                    records = df.tail(count * 5).to_dict(orient="records") if (count and count > 0) else df.to_dict(orient="records")
                    candles_1m = [
                        {
                            "time": int(r.get("timestamp", r.get("time", 0))),
                            "timestamp": int(r.get("timestamp", r.get("time", 0))),
                            "open": round(float(r["open"]), 2),
                            "high": round(float(r["high"]), 2),
                            "low": round(float(r["low"]), 2),
                            "close": round(float(r["close"]), 2),
                            "volume": round(float(r.get("volume", 10.0)), 2)
                        }
                        for r in records
                    ]
                    if interval == "1m":
                        return candles_1m[-count:] if count else candles_1m
                    else:
                        resampled = resample_candles(candles_1m, interval)
                        return resampled[-count:] if count else resampled
        except Exception as e:
            logger.warning(f"[DataManager] Error reading cached OANDA 1m CSV: {e}")

    # 2. Fetch fresh authentic bars via TradingView WebSocket (OANDA:XAUUSD)
    fresh = fetch_candles_via_tv("OANDA:XAUUSD", "1m", max(count or 2880, 5000))

    if fresh and len(fresh) >= 50:
        try:
            df_fresh = pd.DataFrame(fresh)
            if "time" in df_fresh.columns and "timestamp" not in df_fresh.columns:
                df_fresh.rename(columns={"time": "timestamp"}, inplace=True)
            if os.path.exists(csv_path) and os.path.getsize(csv_path) > 10:
                try:
                    df_old = pd.read_csv(csv_path)
                    clean_old = df_old[df_old.get("volume", 10.0) > 1.5] if "volume" in df_old.columns else df_old
                    df_merged = pd.concat([clean_old, df_fresh], ignore_index=True)
                except Exception:
                    df_merged = df_fresh
                df_merged.drop_duplicates(subset=["timestamp"], keep="last", inplace=True)
                df_merged.sort_values(by="timestamp", inplace=True)
            else:
                df_merged = df_fresh

            _save_canonical_and_legacy("XAU/USD", "1m", df_merged, legacy_1m, source="oanda_tv")

            df_to_return = df_merged if not df_merged.empty else df_fresh
            records = df_to_return.tail(count * 5).to_dict(orient="records") if (count and count * 5 < len(df_to_return)) else df_to_return.to_dict(orient="records")
            all_bars = [
                {
                    "time": int(r.get("timestamp", r.get("time", 0))),
                    "timestamp": int(r.get("timestamp", r.get("time", 0))),
                    "open": round(float(r["open"]), 2),
                    "high": round(float(r["high"]), 2),
                    "low": round(float(r["low"]), 2),
                    "close": round(float(r["close"]), 2),
                    "volume": round(float(r.get("volume", 10.0)), 2)
                }
                for r in records
            ]

            try:
                full_records = df_to_return.to_dict(orient="records")
                full_bars = [
                    {
                        "time": int(r.get("timestamp", r.get("time", 0))),
                        "timestamp": int(r.get("timestamp", r.get("time", 0))),
                        "open": round(float(r["open"]), 2),
                        "high": round(float(r["high"]), 2),
                        "low": round(float(r["low"]), 2),
                        "close": round(float(r["close"]), 2),
                        "volume": round(float(r.get("volume", 10.0)), 2)
                    }
                    for r in full_records
                ]
                resampled_5m = resample_candles(full_bars, "5m")
                if resampled_5m:
                    df_5m = pd.DataFrame(resampled_5m)
                    _save_canonical_and_legacy("XAU/USD", "5m", df_5m, legacy_5m, source="resampled_1m")
            except Exception as e_5m:
                logger.warning(f"[DataManager] Could not save resampled 5m cache: {e_5m}")

            if interval == "1m":
                return all_bars[-count:] if count else all_bars
            else:
                resampled = resample_candles(all_bars, interval)
                return resampled[-count:] if count else resampled
        except Exception as e_save:
            logger.warning(f"[DataManager] Error saving fresh OANDA 1m cache: {e_save}")
            if interval == "1m":
                return fresh[-count:] if count else fresh
            else:
                return resample_candles(fresh, interval)[-count:]

    # 3. Fallback to existing disk CSV
    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
        records = df.tail(count * 5).to_dict(orient="records") if (count and count > 0) else df.to_dict(orient="records")
        candles = [
            {
                "time": int(r.get("timestamp", r.get("time", 0))),
                "timestamp": int(r.get("timestamp", r.get("time", 0))),
                "open": round(float(r["open"]), 2),
                "high": round(float(r["high"]), 2),
                "low": round(float(r["low"]), 2),
                "close": round(float(r["close"]), 2),
                "volume": round(float(r.get("volume", 10.0)), 2)
            }
            for r in records
        ]
        if interval == "1m":
            return candles[-count:] if count else candles
        return resample_candles(candles, interval)[-count:]

    return []


def fetch_real_sp500_candles(interval: str = "1m", count: int = 2880) -> List[Dict[str, Any]]:
    """
    Fetches genuine S&P 500 E-mini futures (ES) candles.
    Reads clean CSV cache or pulls from TradingView WS (CME_MINI:ES1!).
    """
    csv_path = get_market_dataset_path("SP500", interval)
    legacy_path = os.path.join(_ROOT, "data", "sp500_candles_1m.csv")
    now_ts = int(time.time())

    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path)
            time_col = "timestamp" if "timestamp" in df.columns else "time"
            if len(df) >= 100:
                last_ts = int(df.iloc[-1][time_col])
                if (now_ts - last_ts) <= 120:
                    records = df.tail(count).to_dict(orient="records")
                    return [
                        {
                            "time": int(r.get("timestamp", r.get("time", 0))),
                            "timestamp": int(r.get("timestamp", r.get("time", 0))),
                            "open": round(float(r["open"]), 2),
                            "high": round(float(r["high"]), 2),
                            "low": round(float(r["low"]), 2),
                            "close": round(float(r["close"]), 2),
                            "volume": round(float(r.get("volume", 50.0)), 2)
                        }
                        for r in records
                    ]
        except Exception:
            pass

    # Fetch from TradingView WS
    fresh = fetch_candles_via_tv("CME_MINI:ES1!", interval, count)
    if fresh:
        try:
            df_fresh = pd.DataFrame(fresh)
            if "time" in df_fresh.columns and "timestamp" not in df_fresh.columns:
                df_fresh.rename(columns={"time": "timestamp"}, inplace=True)
            if os.path.exists(csv_path):
                df_old = pd.read_csv(csv_path)
                df_merged = pd.concat([df_old, df_fresh], ignore_index=True)
                df_merged.drop_duplicates(subset=["timestamp"], keep="last", inplace=True)
                df_merged.sort_values(by="timestamp", inplace=True)
            else:
                df_merged = df_fresh
            _save_canonical_and_legacy("SP500", interval, df_merged, legacy_path if interval == "1m" else None, source="cme_tv")
            df_to_return = df_merged if not df_merged.empty else df_fresh
            records = df_to_return.tail(count).to_dict(orient="records") if (count and count < len(df_to_return)) else df_to_return.to_dict(orient="records")
            return [
                {
                    "time": int(r.get("timestamp", r.get("time", 0))),
                    "timestamp": int(r.get("timestamp", r.get("time", 0))),
                    "open": round(float(r["open"]), 2),
                    "high": round(float(r["high"]), 2),
                    "low": round(float(r["low"]), 2),
                    "close": round(float(r["close"]), 2),
                    "volume": round(float(r.get("volume", 50.0)), 2)
                }
                for r in records
            ]
        except Exception:
            return fresh[-count:] if count else fresh

    # Fallback to existing disk CSV
    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
        records = df.tail(count).to_dict(orient="records")
        return [
            {
                "time": int(r.get("timestamp", r.get("time", 0))),
                "timestamp": int(r.get("timestamp", r.get("time", 0))),
                "open": round(float(r["open"]), 2),
                "high": round(float(r["high"]), 2),
                "low": round(float(r["low"]), 2),
                "close": round(float(r["close"]), 2),
                "volume": round(float(r.get("volume", 50.0)), 2)
            }
            for r in records
        ]
    return []


def fetch_real_binance_klines(symbol: str = "BTC/USDT", interval: str = "15m", count: int = 2880) -> List[Dict[str, Any]]:
    """
    Fetches real OHLCV candles for any symbol.
    Seamlessly routes Gold to OANDA:XAUUSD and S&P 500 to CME_MINI:ES1!.
    """
    clean_sym = resolve_market_symbol(symbol)
    if clean_sym == "OANDA:XAUUSD":
        return fetch_real_oanda_candles(interval=interval, count=count)
    elif clean_sym == "CME_MINI:ES1!":
        return fetch_real_sp500_candles(interval=interval, count=count)

    # 1. Check local disk CSV if available
    csv_path = get_market_dataset_path(symbol, interval)
    # Only write legacy BTC filenames when the symbol actually IS BTCUSDT (never clobber BTC with ETH/SOL/etc.)
    if clean_sym == "BINANCE:BTCUSDT":
        legacy_path = os.path.join(_ROOT, "data", "candles_15m.csv") if interval == "15m" else os.path.join(_ROOT, "data", f"btc_candles_{interval}.csv")
    else:
        legacy_path = None
    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path)
            time_col = "timestamp" if "timestamp" in df.columns else "time"
            now_ts = int(time.time())
            if len(df) >= 100 and (now_ts - int(df.iloc[-1][time_col])) <= 300:
                records = df.tail(count).to_dict(orient="records")
                return [
                    {
                        "time": int(r.get("timestamp", r.get("time", 0))),
                        "timestamp": int(r.get("timestamp", r.get("time", 0))),
                        "open": float(r["open"]),
                        "high": float(r["high"]),
                        "low": float(r["low"]),
                        "close": float(r["close"]),
                        "volume": float(r.get("volume", 0.0))
                    }
                    for r in records
                ]
        except Exception:
            pass

    # 2. Pull from TradingView WS
    fresh = fetch_candles_via_tv(clean_sym, interval, count)
    if fresh:
        try:
            df_fresh = pd.DataFrame(fresh)
            if "time" in df_fresh.columns and "timestamp" not in df_fresh.columns:
                df_fresh.rename(columns={"time": "timestamp"}, inplace=True)
            _save_canonical_and_legacy(symbol, interval, df_fresh, legacy_path, source="binance_tv")
        except Exception:
            pass
        return fresh[-count:] if count else fresh

    # 3. Direct Binance REST API fallback (full float precision — never truncate to 2 decimals)
    pair = clean_sym.split(":", 1)[1].upper() if ":" in clean_sym else clean_sym.upper()
    url = f"https://api.binance.com/api/v3/klines?symbol={pair}&interval={interval}&limit={min(1000, count)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
            candles = [
                {
                    "time": int(item[0] // 1000),
                    "timestamp": int(item[0] // 1000),
                    "open": float(item[1]),
                    "high": float(item[2]),
                    "low": float(item[3]),
                    "close": float(item[4]),
                    "volume": float(item[5])
                }
                for item in raw
            ]
            if candles:
                df_rest = pd.DataFrame(candles)
                _save_canonical_and_legacy(symbol, interval, df_rest, legacy_path, source="binance_rest")
            return candles
    except Exception as e:
        logger.warning(f"[DataManager] Binance REST fallback error for {pair}: {e}")

    # Fallback to cached CSV
    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
        records = df.tail(count).to_dict(orient="records")
        return [
            {
                "time": int(r.get("timestamp", r.get("time", 0))),
                "timestamp": int(r.get("timestamp", r.get("time", 0))),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r.get("volume", 0.0))
            }
            for r in records
        ]
    return []


def sync_30d_candles(symbol: str = "BTC/USDT", output_path: str = "", timeframe: str = "15m") -> str:
    """Synchronizes real market data (10,000+ candles) and updates canonical + output_path CSV."""
    if not output_path:
        output_path = get_market_dataset_path(symbol, timeframe, check_legacy=False)
    candles = fetch_candles_via_tv(resolve_market_symbol(symbol), timeframe, 10000)
    if not candles:
        candles = fetch_real_binance_klines(symbol=symbol, interval=timeframe, count=5000)
    if candles:
        df = pd.DataFrame(candles)
        if "time" in df.columns and "timestamp" not in df.columns:
            df.rename(columns={"time": "timestamp"}, inplace=True)
        _save_canonical_and_legacy(symbol, timeframe, df, output_path, source="sync_30d")
        logger.info(f"[DataManager] Synchronized {output_path} with {len(df)} authentic candles")
    return output_path


def sync_xauusd_scalp_candles(output_path: str = "") -> str:
    """Synchronizes real institutional OANDA Cash Spot Gold (XAUUSD) 1m scalping dataset."""
    if not output_path:
        output_path = get_market_dataset_path("XAU/USD", "1m", check_legacy=False)
    candles = fetch_candles_via_tv("OANDA:XAUUSD", "1m", 10000)
    if candles:
        df = pd.DataFrame(candles)
        if "time" in df.columns and "timestamp" not in df.columns:
            df.rename(columns={"time": "timestamp"}, inplace=True)
        _save_canonical_and_legacy("XAU/USD", "1m", df, output_path, source="sync_xauusd_1m")
        logger.info(f"[DataManager] Synchronized {output_path} with {len(df)} authentic 1m OANDA Gold candles")
    return output_path


def fetch_ohlcv(symbol: str, timeframe: str = "15m", count: int = 1500, period: Optional[str] = None, use_cache: bool = True):
    """Unified SSOT candle fetcher with dynamic period, timeframe, and disk-cache support."""
    resolved = resolve_market_symbol(symbol)
    eff_count = int(count) if count else 1500
    period_days = parse_period_to_days(period)
    if period_days is not None:
        period_bars = bars_for_days(timeframe, period_days)
        eff_count = max(eff_count, period_bars)

    candles = fetch_candles_via_tv(resolved, timeframe, count=eff_count)
    if not candles and resolved == "OANDA:XAUUSD":
        candles = fetch_real_oanda_candles(interval=timeframe, count=eff_count)
    if not candles and (resolved.startswith("BINANCE:") or resolved.endswith(("USDT", "USDC", "BUSD"))):
        candles = fetch_real_binance_klines(symbol=resolved, interval=timeframe, count=eff_count)
    if not candles:
        # Check canonical local cache before giving up
        csv_path = get_market_dataset_path(resolved, timeframe, check_legacy=True)
        if os.path.exists(csv_path):
            try:
                df_disk = pd.read_csv(csv_path)
                if not df_disk.empty:
                    df_disk = df_disk.tail(eff_count).copy()
                    ts_col = "timestamp" if "timestamp" in df_disk.columns else ("time" if "time" in df_disk.columns else None)
                    if ts_col and use_cache:
                        df_disk.index = pd.to_datetime(df_disk[ts_col], unit="s", utc=True)
                        df_disk.index.name = "dt"
                    return df_disk if use_cache else df_disk.to_dict(orient="records")
            except Exception:
                pass
        if not HAS_TV_WS:
            logger.error(
                f"[DataManager] Cannot fetch '{resolved}' ({timeframe}): `tradingview_websocket` is not installed "
                "and no local cache exists. Install `tradingview_websocket` (`pip install -r requirements.txt`)."
            )

    if candles and use_cache:
        try:
            df = pd.DataFrame(candles)
            if not df.empty:
                ts_col = "timestamp" if "timestamp" in df.columns else ("time" if "time" in df.columns else None)
                if ts_col:
                    df.index = pd.to_datetime(df[ts_col], unit="s", utc=True)
                    df.index.name = "dt"
                return df
        except Exception:
            pass
    return candles
