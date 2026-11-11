from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import string
import time
from typing import Dict, Any, List, Optional

from server.providers.base import BaseMarketDataProvider
from server import data_manager

logger = logging.getLogger("TradingViewProvider")


class TradingViewMarketDataProvider(BaseMarketDataProvider):
    """
    Unified Dynamic Market Data Provider backed by TradingView WebSocket.
    Maintains a persistent, event-driven WebSocket connection to receive real-time
    intrabar ticks and finalized OHLCV candles as they happen (zero polling latency).
    Open and universal: any extension or subscriber receives real-time ticks via subscribe_tick().
    """

    def __init__(self, symbol: str, timeframe: str = "5m"):
        super().__init__(symbol=symbol, timeframe=timeframe)
        self.tv_symbol = data_manager.resolve_market_symbol(symbol)
        self.bar_step = data_manager._timeframe_to_seconds(timeframe)
        self._last_bar_time = 0
        self._last_bar_vol = 0.0
        self._last_full_sync_time = 0.0
        self._task: Optional[asyncio.Task] = None
        self._load_initial_candles()

    def _load_initial_candles(self):
        """Pulls authentic historical bars via TradingView WebSocket."""
        try:
            logger.info(f"[TradingViewProvider] Loading initial candles for {self.tv_symbol} ({self.timeframe})...")
            candles = data_manager.fetch_candles_via_tv(self.tv_symbol, self.timeframe, count=2000)
            if not candles and ("XAU" in self.symbol.upper() or "GOLD" in self.symbol.upper()):
                # Broker Spot Fallback only if TV websocket has a temporary timeout
                candles = data_manager.fetch_real_broker_spot_gold_candles(interval=self.timeframe, count=1000)

            if candles:
                self._candles = candles
                self._last_full_sync_time = time.time()
                last_c = self._candles[-1]
                self._last_bar_time = int(last_c.get("timestamp") or last_c.get("time", 0))
                self._last_bar_vol = float(last_c.get("volume", 0.0))
                from core.data import get_market_price_precision
                prec = get_market_price_precision(self.tv_symbol)
                spread_val = 0.00015 if prec > 2 else 0.15
                self._latest_quote = {
                    "symbol": self.symbol,
                    "price": last_c["close"],
                    "bid": round(last_c["close"] - spread_val, prec),
                    "ask": round(last_c["close"] + spread_val, prec),
                    "open": last_c["open"],
                    "high": last_c["high"],
                    "low": last_c["low"],
                    "volume": last_c["volume"],
                    "delta_volume": 0.0,
                    "timestamp": self._last_bar_time,
                    "source": "tradingview_ws",
                    "candle": last_c,
                }
                logger.info(
                    f"[TradingViewProvider] Ready with {len(self._candles)} authentic {self.timeframe} candles for {self.tv_symbol} (Latest: {last_c['close']} @ {self._last_bar_time})"
                )
        except Exception as e:
            logger.warning(f"[TradingViewProvider] Error loading initial candles for {self.tv_symbol}: {e}")

    def get_latest_quote(self) -> Dict[str, Any]:
        return self._latest_quote

    def get_candles(self, count: Optional[int] = None) -> List[Dict[str, Any]]:
        now = time.time()
        # If candles are not yet loaded, load them
        if not self._candles:
            self._load_initial_candles()
        else:
            # Self-healing freshness check: if the last cached bar is older than 2 bar intervals
            # and we haven't synced within the last 60 seconds, refresh from TradingView
            last_ts = int(self._candles[-1].get("timestamp") or self._candles[-1].get("time", 0))
            if (now - last_ts) > max(900, self.bar_step * 2) and (now - self._last_full_sync_time) > 60:
                self._last_full_sync_time = now
                try:
                    fresh = data_manager.fetch_candles_via_tv(self.tv_symbol, self.timeframe, count=count or 2000)
                    if fresh and int(fresh[-1].get("timestamp", 0)) > last_ts:
                        self._candles = fresh
                        last_c = fresh[-1]
                        self._last_bar_time = int(last_c.get("timestamp") or last_c.get("time", 0))
                        self._last_bar_vol = float(last_c.get("volume", 0.0))
                        logger.info(
                            f"[TradingViewProvider] Refreshed {len(self._candles)} candles for {self.tv_symbol} up to {self._last_bar_time}"
                        )
                except Exception as e_refresh:
                    logger.debug(f"[TradingViewProvider] Background refresh note for {self.tv_symbol}: {e_refresh}")

        if count and len(self._candles) > count:
            return self._candles[-count:]
        return self._candles

    async def start(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self._task = asyncio.create_task(self._stream_loop())
        logger.info(f"[TradingViewProvider] Provider started real-time stream for {self.tv_symbol} ({self.timeframe}).")

    async def stop(self) -> None:
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info(f"[TradingViewProvider] Provider stopped for {self.tv_symbol} ({self.timeframe}).")

    @staticmethod
    def _create_ws_msg(func: str, param_list: list) -> str:
        msg = json.dumps({"m": func, "p": param_list}, separators=(",", ":"))
        return f"~m~{len(msg)}~m~{msg}"

    async def _stream_loop(self) -> None:
        """
        Persistent event-driven WebSocket listener for TradingView.
        Streams real-time intrabar ticks and bar closures with zero polling.
        """
        import websocket

        tv_tf = data_manager._tf_to_tv_resolution(self.timeframe)
        from core.data import get_market_price_precision
        prec = get_market_price_precision(self.tv_symbol)
        spread_val = 0.00015 if prec > 2 else 0.15
        loop = asyncio.get_event_loop()

        while self.is_running:
            ws = None
            try:
                headers = {
                    "Origin": "https://data.tradingview.com",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                }
                ws = await loop.run_in_executor(
                    None,
                    lambda: websocket.create_connection(
                        "wss://data.tradingview.com/socket.io/websocket",
                        headers=headers,
                        timeout=15,
                    ),
                )

                chart_s = "cs_" + "".join(random.choice(string.ascii_lowercase) for _ in range(12))
                sym_str = '={\"symbol\":\"' + self.tv_symbol + '\",\"adjustment\":\"splits\"}'

                # Request recent 300 bars on connect/reconnect to guarantee no gaps
                init_msgs = [
                    self._create_ws_msg("set_auth_token", ["unauthorized_user_token"]),
                    self._create_ws_msg("chart_create_session", [chart_s, ""]),
                    self._create_ws_msg("resolve_symbol", [chart_s, "symbol_1", sym_str]),
                    self._create_ws_msg("create_series", [chart_s, "s1", "s1", "symbol_1", str(tv_tf), 300]),
                ]
                for m in init_msgs:
                    await loop.run_in_executor(None, ws.send, m)

                while self.is_running:
                    raw_res = await loop.run_in_executor(None, ws.recv)
                    if not raw_res:
                        break

                    parts = re.split(r"~m~\d+~m~", raw_res)
                    for part in parts:
                        part = part.strip()
                        if not part:
                            continue
                        if "~h~" in part:
                            # Frame heartbeat properly according to TradingView socket.io protocol
                            hb_msg = f"~m~{len(part)}~m~{part}"
                            await loop.run_in_executor(None, ws.send, hb_msg)
                            continue

                        try:
                            parsed = json.loads(part)
                        except Exception:
                            continue

                        m = parsed.get("m")
                        if m == "du":
                            series_data = parsed.get("p", [None, {}])[1].get("s1", {}).get("s", [])
                            if series_data:
                                v = series_data[0].get("v", [])
                                if len(v) >= 5:
                                    b_ts = int(v[0])
                                    o, h, l, c = float(v[1]), float(v[2]), float(v[3]), float(v[4])
                                    vol = float(v[5]) if len(v) > 5 and v[5] is not None else 0.0

                                    delta_vol = (
                                        max(0.0, round(vol - self._last_bar_vol, 4))
                                        if b_ts == self._last_bar_time
                                        else vol
                                    )
                                    self._last_bar_vol = vol

                                    from core.data import get_market_price_precision
                                    prec = get_market_price_precision(self.tv_symbol)
                                    spread_val = 0.00015 if prec > 2 else 0.15

                                    quote = {
                                        "symbol": self.symbol,
                                        "price": round(c, prec),
                                        "bid": round(c - spread_val, prec),
                                        "ask": round(c + spread_val, prec),
                                        "open": round(o, prec),
                                        "high": round(h, prec),
                                        "low": round(l, prec),
                                        "volume": vol,
                                        "delta_volume": delta_vol,
                                        "timestamp": b_ts,
                                        "source": "tradingview_ws_live",
                                        "candle": {
                                            "time": b_ts,
                                            "timestamp": b_ts,
                                            "open": round(o, prec),
                                            "high": round(h, prec),
                                            "low": round(l, prec),
                                            "close": round(c, prec),
                                            "volume": vol,
                                        },
                                    }
                                    self._latest_quote = quote
                                    await self._notify_tick(quote)

                                    if not self._candles:
                                        self._candles = [quote["candle"]]
                                        self._last_bar_time = b_ts
                                    else:
                                        last_candle_ts = int(
                                            self._candles[-1].get("timestamp") or self._candles[-1].get("time", 0)
                                        )
                                        if b_ts > last_candle_ts:
                                            # Previous candle has finalized!
                                            finalized_bar = dict(self._candles[-1])
                                            self._last_bar_time = b_ts
                                            # Append newly opened candle
                                            self._candles.append(quote["candle"])
                                            # Keep memory bounded to latest 2500 bars
                                            if len(self._candles) > 2500:
                                                self._candles = self._candles[-2500:]

                                            logger.info(
                                                f"[TradingViewProvider] 🔔 New {self.timeframe} bar finalized for {self.tv_symbol}: {finalized_bar.get('close')} @ {last_candle_ts}"
                                            )
                                            await self._notify_bar(finalized_bar)
                                        else:
                                            # In-progress update for the current forming candle
                                            self._candles[-1]["high"] = max(self._candles[-1].get("high", h), h)
                                            self._candles[-1]["low"] = min(self._candles[-1].get("low", l), l)
                                            self._candles[-1]["close"] = c
                                            self._candles[-1]["volume"] = vol

                        elif m == "timescale_update":
                            s_list = parsed.get("p", [None, {}])[1].get("s1", {}).get("s", [])
                            if s_list:
                                new_bars = []
                                for item in s_list:
                                    iv = item.get("v", [])
                                    if len(iv) >= 5:
                                        ts = int(iv[0])
                                        new_bars.append(
                                            {
                                                "time": ts,
                                                "timestamp": ts,
                                                "open": round(float(iv[1]), prec),
                                                "high": round(float(iv[2]), prec),
                                                "low": round(float(iv[3]), prec),
                                                "close": round(float(iv[4]), prec),
                                                "volume": round(
                                                    float(iv[5] if len(iv) > 5 and iv[5] is not None else 10.0), 2
                                                ),
                                            }
                                        )
                                if new_bars:
                                    # Merge into self._candles to ensure unbroken historical sequence
                                    by_time = {
                                        int(c.get("timestamp") or c.get("time", 0)): c for c in (self._candles or [])
                                    }
                                    for nb in new_bars:
                                        by_time[nb["timestamp"]] = nb
                                    self._candles = sorted(
                                        by_time.values(),
                                        key=lambda x: int(x.get("timestamp") or x.get("time", 0)),
                                    )
                                    if len(self._candles) > 2500:
                                        self._candles = self._candles[-2500:]

                                    latest_item = s_list[-1].get("v", [])
                                    self._last_bar_time = int(latest_item[0])
                                    self._last_bar_vol = (
                                        float(latest_item[5])
                                        if len(latest_item) > 5 and latest_item[5] is not None
                                        else 0.0
                                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"[TradingViewProvider] Stream reconnect notice for {self.tv_symbol}: {e}")
                await asyncio.sleep(2.0)
            finally:
                if ws:
                    try:
                        ws.close()
                    except Exception:
                        pass
