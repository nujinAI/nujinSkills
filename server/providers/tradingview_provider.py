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
                last_c = self._candles[-1]
                self._last_bar_time = int(last_c.get("timestamp") or last_c.get("time", 0))
                self._last_bar_vol = float(last_c.get("volume", 0.0))
                self._latest_quote = {
                    "symbol": self.symbol,
                    "price": last_c["close"],
                    "bid": round(last_c["close"] - 0.15, 2),
                    "ask": round(last_c["close"] + 0.15, 2),
                    "open": last_c["open"],
                    "high": last_c["high"],
                    "low": last_c["low"],
                    "volume": last_c["volume"],
                    "delta_volume": 0.0,
                    "timestamp": self._last_bar_time,
                    "source": "tradingview_ws",
                    "candle": last_c
                }
                logger.info(f"[TradingViewProvider] Ready with {len(self._candles)} authentic {self.timeframe} candles for {self.tv_symbol} (Latest: {last_c['close']} @ {self._last_bar_time})")
        except Exception as e:
            logger.warning(f"[TradingViewProvider] Error loading initial candles for {self.tv_symbol}: {e}")

    def get_latest_quote(self) -> Dict[str, Any]:
        return self._latest_quote

    def get_candles(self, count: Optional[int] = None) -> List[Dict[str, Any]]:
        if not self._candles:
            self._load_initial_candles()
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

                init_msgs = [
                    self._create_ws_msg("set_auth_token", ["unauthorized_user_token"]),
                    self._create_ws_msg("chart_create_session", [chart_s, ""]),
                    self._create_ws_msg("resolve_symbol", [chart_s, "symbol_1", sym_str]),
                    self._create_ws_msg("create_series", [chart_s, "s1", "s1", "symbol_1", str(tv_tf), 10]),
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
                            await loop.run_in_executor(None, ws.send, part)
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
                                    vol = float(v[5]) if len(v) > 5 else 0.0

                                    delta_vol = max(0.0, round(vol - self._last_bar_vol, 4)) if b_ts == self._last_bar_time else vol
                                    self._last_bar_vol = vol

                                    quote = {
                                        "symbol": self.symbol,
                                        "price": c,
                                        "bid": round(c - 0.15, 2),
                                        "ask": round(c + 0.15, 2),
                                        "open": o,
                                        "high": h,
                                        "low": l,
                                        "volume": vol,
                                        "delta_volume": delta_vol,
                                        "timestamp": b_ts,
                                        "source": "tradingview_ws_live",
                                        "candle": {
                                            "time": b_ts,
                                            "timestamp": b_ts,
                                            "open": o,
                                            "high": h,
                                            "low": l,
                                            "close": c,
                                            "volume": vol,
                                        },
                                    }
                                    self._latest_quote = quote
                                    await self._notify_tick(quote)

                                    if b_ts > self._last_bar_time:
                                        self._last_bar_time = b_ts
                                        candle_dict = quote["candle"]
                                        if not self._candles:
                                            self._candles = [candle_dict]
                                        else:
                                            self._candles = [bar for bar in self._candles if int(bar.get("timestamp", bar.get("time", 0))) < b_ts]
                                            self._candles.append(candle_dict)

                                        logger.info(f"[TradingViewProvider] 🔔 New {self.timeframe} bar finalized for {self.tv_symbol}: {c} @ {b_ts}")
                                        await self._notify_bar(candle_dict)

                        elif m == "timescale_update":
                            s_list = parsed.get("p", [None, {}])[1].get("s1", {}).get("s", [])
                            if s_list:
                                latest_item = s_list[-1].get("v", [])
                                if len(latest_item) >= 5:
                                    self._last_bar_time = int(latest_item[0])
                                    self._last_bar_vol = float(latest_item[5]) if len(latest_item) > 5 else 0.0

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
