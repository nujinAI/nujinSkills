import asyncio
import json
import time
import os
import math
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
import websockets
import pandas as pd
import numpy as np

logger = logging.getLogger("XauusdStreamer")

class XauusdScalpEngine:
    """
    Keyless XAUUSD Streamer & Goat Funded Trader Prop Firm Momentum Scalping Engine.
    Streams tick-by-tick real market data, calculates momentum ribbon (EMA 9/21/200),
    enforces London/NY session gates, and manages 2m-15m holding clocks.
    """
    def __init__(self):
        # Candles are loaded on first use, not here: see the candles_1m property.
        self._candles_1m: List[Dict[str, Any]] = []
        self._seeded = False
        init_p = 4374.98
        csv_path = "data/xauusd_candles_1m.csv"
        if os.path.exists(csv_path):
            try:
                with open(csv_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    if len(lines) >= 2:
                        init_p = round(float(lines[-1].strip().split(",")[4]), 2)
            except Exception:
                pass

        self.current_quote: Dict[str, Any] = {
            "symbol": "XAU/USD (OANDA Spot)",
            "price": init_p,
            "bid": round(init_p - 0.15, 2),
            "ask": round(init_p + 0.15, 2),
            "change_24h_pct": 0.0,
            "volume_1m": 12.0,
            "high_24h": round(init_p + 25.0, 2),
            "low_24h": round(init_p - 25.0, 2),
            "timestamp": int(time.time()),
            "source": "oanda_spot"
        }
        self.active_trade: Optional[Dict[str, Any]] = None
        self.trade_history: List[Dict[str, Any]] = []
        self.last_signal: Optional[Dict[str, Any]] = None
        self.is_running = False
        self._last_tv_sync = 0.0
        # Set when a data gap could not be filled with authentic candles. Kept
        # visible so consumers know the series is incomplete rather than being
        # fed synthesised bars.
        self.data_degraded = False
        self.data_gap_seconds = 0

    @property
    def candles_1m(self) -> List[Dict[str, Any]]:
        """
        Recent 1m candles, seeding from history on first access.

        Seeding used to run inside __init__, so constructing an engine — or importing this
        module, which builds a module-level engine — performed a 20,000-bar live fetch.
        That made importing the module do network I/O, which is why startup depended on the
        network and why anything that merely inspected state paid for a full candle fetch.
        The fetch now happens the first time candles are actually needed.
        """
        self._ensure_seeded()
        return self._candles_1m

    @candles_1m.setter
    def candles_1m(self, value: List[Dict[str, Any]]) -> None:
        # An explicit assignment is authoritative and counts as seeded, whether it came
        # from the historical fetch or from a caller hot-swapping the series.
        self._candles_1m = value
        self._seeded = True

    def _ensure_seeded(self) -> None:
        if self._seeded:
            return
        self._seeded = True
        self._load_initial_candles()

    def _mark_data_recovered(self, reason: str) -> None:
        """
        Clears `data_degraded` once authentic candles fill the gap.

        The flag is documented as advisory "until it clears", but nothing ever cleared it: a
        single startup or reconnect gap marked the series unreliable for the rest of the
        process lifetime, and consumers had no way to learn that data had recovered short of
        a restart. Only authentic bars clear it — bars whose volume was derived from the
        polled tick stream are not evidence that the series is complete.
        """
        if not self.data_degraded:
            return
        self.data_degraded = False
        self.data_gap_seconds = 0
        logger.info(f"[XauusdScalpEngine] Data integrity restored ({reason}).")

    def _load_initial_candles(self):
        """Loads cached 1m candles or pulls fresh from TradingView (first use only)."""
        try:
            from server.data_manager import fetch_real_oanda_candles
            bars = fetch_real_oanda_candles(interval="1m", count=20000)
            if bars:
                self.candles_1m = bars
                last_c = self.candles_1m[-1]
                self.current_quote["price"] = last_c["close"]
                self.current_quote["bid"] = round(last_c["close"] - 0.15, 2)
                self.current_quote["ask"] = round(last_c["close"] + 0.15, 2)
                self.current_quote["timestamp"] = last_c["time"]
                self.current_quote["volume_1m"] = float(last_c.get("volume", 450.0))
                logger.info(f"[XauusdScalpEngine] Loaded {len(self.candles_1m)} fresh 1m candles (latest close: {last_c['close']} @ {last_c['time']})")
        except Exception as e:
            logger.warning(f"[XauusdScalpEngine] Could not load initial candles: {e}")

    @staticmethod
    def is_session_active() -> Dict[str, Any]:
        """
        Checks London and New York Session active windows (UTC).
        London Momentum: 07:30 - 10:30 UTC
        New York Momentum: 12:45 - 16:30 UTC
        """
        now_local = datetime.now().astimezone()
        now_utc = datetime.now(timezone.utc)
        current_minute_utc = now_utc.hour * 60 + now_utc.minute

        # London: 07:30 to 10:30 UTC -> 450 to 630 minutes
        is_london = 450 <= current_minute_utc <= 630
        
        # New York: 12:45 to 16:30 UTC -> 765 to 990 minutes
        is_ny = 765 <= current_minute_utc <= 990

        # Overlap: 12:45 to 16:00 UTC
        is_overlap = 765 <= current_minute_utc <= 960

        active = is_london or is_ny
        session_name = "NONE"
        if is_overlap:
            session_name = "LONDON_NY_OVERLAP"
        elif is_london:
            session_name = "LONDON_SESSION"
        elif is_ny:
            session_name = "NEW_YORK_SESSION"

        return {
            "is_active": active,
            "session_name": session_name,
            "current_local_time": now_local.strftime("%H:%M:%S %Z"),
            "current_utc_time": now_utc.strftime("%H:%M:%S UTC"),
            "local_timezone": now_local.tzname() or "Local",
            "is_london": is_london,
            "is_ny": is_ny,
            "is_overlap": is_overlap,
            "note": "High institutional gold volatility" if active else "Lower volume Asian / inter-session drift"
        }

    def compute_indicators(self) -> Dict[str, Any]:
        """Calculates 9 EMA, 21 EMA, 200 EMA, Vol Z-Score, ATR on latest 1m candles."""
        if len(self.candles_1m) < 30:
            return {"ready": False}

        df = pd.DataFrame(self.candles_1m)
        close = df["close"]
        high = df["high"]
        low = df["low"]
        vol = df["volume"]

        # EMAs
        ema_9 = close.ewm(span=9, adjust=False).mean()
        ema_21 = close.ewm(span=21, adjust=False).mean()
        ema_200 = close.ewm(span=min(200, len(close)), adjust=False).mean()

        # ATR (14)
        tr = np.maximum(high - low, np.maximum((high - close.shift(1)).abs(), (low - close.shift(1)).abs()))
        atr_14 = tr.rolling(14).mean()

        # Volume Z-score
        vol_mean = vol.rolling(20).mean()
        vol_std = vol.rolling(20).std().replace(0, 1e-6)
        vol_z = (vol - vol_mean) / vol_std

        # Bollinger Bands & Squeeze (20, 2.0)
        sma_20 = close.rolling(20).mean()
        std_20 = close.rolling(20).std().replace(0, 1e-6)
        upper_bb = sma_20 + 2.0 * std_20
        lower_bb = sma_20 - 2.0 * std_20
        bb_bandwidth = (upper_bb - lower_bb) / sma_20

        curr_i = len(df) - 1
        curr_price = float(close.iloc[curr_i])
        curr_e9 = float(ema_9.iloc[curr_i])
        curr_e21 = float(ema_21.iloc[curr_i])
        curr_e200 = float(ema_200.iloc[curr_i])
        curr_atr = float(atr_14.iloc[curr_i]) if not np.isnan(atr_14.iloc[curr_i]) else 2.50
        curr_vol_z = float(vol_z.iloc[curr_i]) if not np.isnan(vol_z.iloc[curr_i]) else 0.0
        curr_bw = float(bb_bandwidth.iloc[curr_i]) if not np.isnan(bb_bandwidth.iloc[curr_i]) else 0.002

        # Momentum Ribbon Slope
        ribbon_expansion = (curr_e9 - curr_e21)
        momentum_score = 0
        if curr_e9 > curr_e21 and curr_price > curr_e9:
            momentum_score = 1 # Bullish expansion
        elif curr_e9 < curr_e21 and curr_price < curr_e9:
            momentum_score = -1 # Bearish expansion

        return {
            "ready": True,
            "price": curr_price,
            "ema_9": round(curr_e9, 2),
            "ema_21": round(curr_e21, 2),
            "ema_200": round(curr_e200, 2),
            "atr": round(curr_atr, 2),
            "vol_z": round(curr_vol_z, 2),
            "bb_bandwidth": round(curr_bw, 5),
            "momentum_direction": "BULLISH" if momentum_score == 1 else ("BEARISH" if momentum_score == -1 else "NEUTRAL"),
            "trend_macro": "BULLISH" if curr_price > curr_e200 else "BEARISH"
        }

    def generate_signal(self, account_size: float = 100000.0) -> Optional[Dict[str, Any]]:
        """
        Evaluates "The Gold Momentum Train" (GIT-15) setup rules for manual entry:
        - Session: London or NY active
        - Trend: Macro 200 EMA alignment
        - Momentum: 9 EMA expansion away from 21 EMA
        - Volume Z-Score > 0.8
        - Target RR: 1:1.5 to 1:2.5
        - Holding duration: Strictly 2min min to 15min max
        """
        session_info = self.is_session_active()
        ind = self.compute_indicators()
        if not ind.get("ready"):
            return None

        price = ind["price"]
        atr = max(1.50, ind["atr"])
        ema9 = ind["ema_9"]
        ema21 = ind["ema_21"]
        ema200 = ind["ema_200"]
        vol_z = ind["vol_z"]
        trend = ind["trend_macro"]

        # 15m High & Low extremes (strictly prior 15 completed bars, excluding active forming candle)
        prior_15 = self.candles_1m[-16:-1] if len(self.candles_1m) >= 16 else (self.candles_1m[:-1] if len(self.candles_1m) > 1 else self.candles_1m)
        hh15 = max([c["high"] for c in prior_15]) if prior_15 else price
        ll15 = min([c["low"] for c in prior_15]) if prior_15 else price

        # Long Trigger (GoatFundedTraderXauusdScalper rules):
        # Session active (London/NY) + Break 15m High + Momentum Ribbon (9 > 21 EMA) + Vol Z > 0.4
        is_long = session_info["is_active"] and (price > hh15) and (ema9 > ema21) and (vol_z > 0.4)
        
        # Short Trigger:
        # Session active (London/NY) + Break 15m Low + Momentum Ribbon (9 < 21 EMA) + Vol Z > 0.4
        is_short = session_info["is_active"] and (price < ll15) and (ema9 < ema21) and (vol_z > 0.4)

        if not is_long and not is_short:
            return None

        side = "BUY / LONG" if is_long else "SELL / SHORT"
        sl_distance = round(price * 0.0025, 2) # Aligned with BacktestEngine 0.25% stop loss

        if is_long:
            sl = round(price * (1.0 - 0.0025), 2)
            tp1 = round(price * (1.0 + 0.0030), 2)
            tp2 = round(price * (1.0 + 0.0050), 2)
        else:
            sl = round(price * (1.0 + 0.0025), 2)
            tp1 = round(price * (1.0 - 0.0030), 2)
            tp2 = round(price * (1.0 - 0.0050), 2)

        # Goat Funded Trader Risk Sizing (0.50% account risk)
        # Gold: 1 Standard Lot = 100 oz. $1.00 move per lot = $100.
        risk_dollars = account_size * 0.005 # 0.50% max risk per trade
        gold_dollars_per_pip = sl_distance * 100 # For 1 lot
        suggested_lots = round(risk_dollars / (gold_dollars_per_pip + 1e-6), 2)
        suggested_lots = max(0.1, min(10.0, suggested_lots))

        # 15% consistency rule: max single-day profit on GFT
        profit_target_total = account_size * 0.08
        consistency_daily_cap = profit_target_total * 0.15

        signal = {
            "signal_id": f"GIT_{int(time.time())}",
            "timestamp": int(time.time()),
            "time_str": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
            "asset": "XAUUSD (Gold Spot)",
            "strategy": "The Gold Momentum Train (GIT-15)",
            "action": side,
            "entry_price": price,
            "stop_loss": sl,
            "take_profit_1": tp1,
            "take_profit_2": tp2,
            "risk_reward_ratio": "1:1.8 Avg",
            "holding_time_rules": {
                "min_hold_seconds": 120, # Goat Funded Trader minimum holding rule
                "min_hold_str": "2 Minutes (MANDATORY ANTI-ARBITRAGE HOLD)",
                "max_hold_seconds": 900,
                "max_hold_str": "15 Minutes (MOMENTUM SCALP CUTOFF)"
            },
            "gft_risk_management": {
                "account_size": account_size,
                "max_trade_risk_pct": "0.50%",
                "risk_dollars": round(risk_dollars, 2),
                "recommended_lot_size": suggested_lots,
                "daily_loss_budget_limit": round(account_size * 0.015, 2), # 1.5% daily soft budget (3% hard limit)
                "gft_15pct_consistency_daily_cap": round(consistency_daily_cap, 2)
            },
            "session": session_info,
            "setup_indicators": ind
        }
        self.last_signal = signal
        return signal

    def start_manual_trade(self, side: str, entry_price: Optional[float] = None, account_size: float = 100000.0, lots: float = 1.0) -> Dict[str, Any]:
        """Starts tracking an active manual trade with sub-second holding timer."""
        price = entry_price or self.current_quote["price"]
        ind = self.compute_indicators()
        atr = max(1.50, ind.get("atr", 2.50))
        sl_dist = round(1.5 * atr, 2)

        sl = round(price - sl_dist, 2) if side.upper() == "BUY" else round(price + sl_dist, 2)
        tp1 = round(price + (sl_dist * 1.5), 2) if side.upper() == "BUY" else round(price - (sl_dist * 1.5), 2)

        self.active_trade = {
            "trade_id": f"XAU_{int(time.time())}",
            "side": side.upper(),
            "entry_price": price,
            "entry_time": time.time(),
            "stop_loss": sl,
            "take_profit": tp1,
            "account_size": account_size,
            "lots": lots,
            "status": "OPEN",
            "pnl_usd": 0.0,
            "pnl_pips": 0.0,
            "elapsed_seconds": 0
        }
        logger.info(f"[XauusdScalpEngine] Manual trade started: {self.active_trade}")
        return self.get_active_trade_status()

    def get_active_trade_status(self) -> Dict[str, Any]:
        """Returns the real-time holding status, PnL, and GFT rule compliance timer."""
        if not self.active_trade:
            return {"active": False}

        now = time.time()
        elapsed = int(now - self.active_trade["entry_time"])
        current_price = self.current_quote["price"]
        side = self.active_trade["side"]
        entry = self.active_trade["entry_price"]
        lots = self.active_trade["lots"]

        if side == "BUY":
            price_diff = current_price - entry
        else:
            price_diff = entry - current_price

        pnl_usd = round(price_diff * 100 * lots, 2)
        pnl_points = round(price_diff, 2)

        if elapsed < 120:
            timer_state = "LOCKED_HOLD"
            timer_badge = "🔴 BLOCKED (GFT 2-MIN RULE: DO NOT CLOSE)"
            seconds_remaining_lock = 120 - elapsed
            exit_recommendation = f"Hold position for {seconds_remaining_lock}s more to comply with GFT anti-scalping rule."
        elif elapsed <= 900:
            timer_state = "SAFE_TO_EXIT"
            timer_badge = "🟢 SAFE TO EXIT (2-MIN RULE SATISFIED)"
            exit_recommendation = "Take Profit target reached or 9 EMA trailing exit permissible."
        else:
            timer_state = "MAX_TIME_EXCEEDED"
            timer_badge = "⚠️ MAX 15-MIN SCALP REACHED (CLOSE TRADE)"
            exit_recommendation = "Exceeded 15m scalp window. Close position to prevent session drift."

        status = {
            "active": True,
            "trade": self.active_trade,
            "current_price": current_price,
            "elapsed_seconds": elapsed,
            "elapsed_formatted": f"{elapsed // 60:02d}:{elapsed % 60:02d}",
            "timer_state": timer_state,
            "timer_badge": timer_badge,
            "exit_recommendation": exit_recommendation,
            "pnl_usd": pnl_usd,
            "pnl_points": pnl_points,
            "hit_tp": (current_price >= self.active_trade["take_profit"]) if side == "BUY" else (current_price <= self.active_trade["take_profit"]),
            "hit_sl": (current_price <= self.active_trade["stop_loss"]) if side == "BUY" else (current_price >= self.active_trade["stop_loss"])
        }
        return status

    def close_manual_trade(self) -> Dict[str, Any]:
        """Closes active trade and logs result."""
        status = self.get_active_trade_status()
        if not status.get("active"):
            return {"status": "NO_ACTIVE_TRADE"}

        closed_trade = {
            **self.active_trade,
            "exit_price": self.current_quote["price"],
            "exit_time": time.time(),
            "holding_seconds": status["elapsed_seconds"],
            "holding_str": status["elapsed_formatted"],
            "final_pnl_usd": status["pnl_usd"],
            "gft_rule_compliant": status["elapsed_seconds"] >= 120
        }
        self.trade_history.append(closed_trade)
        self.active_trade = None
        logger.info(f"[XauusdScalpEngine] Trade closed: {closed_trade}")
        return closed_trade

    async def _sync_authentic_candles(self):
        """Fetches authentic finalized bars from TradingView and merges into cache and memory."""
        try:
            from server.data_manager import fetch_real_oanda_candles
            loop = asyncio.get_event_loop()
            fresh = await loop.run_in_executor(None, lambda: fetch_real_oanda_candles(interval="1m", count=50, force_refresh=True))
            if fresh and len(fresh) >= 5:
                by_time = {b["time"]: b for b in fresh}
                current_active_time = self.candles_1m[-1]["time"] if self.candles_1m else 0
                for c in self.candles_1m:
                    if c["time"] in by_time and c["time"] < current_active_time:
                        c["volume"] = by_time[c["time"]]["volume"]
                        c["volume_source"] = "authentic"
                        c["open"] = by_time[c["time"]]["open"]
                        c["high"] = by_time[c["time"]]["high"]
                        c["low"] = by_time[c["time"]]["low"]
                        c["close"] = by_time[c["time"]]["close"]
                self._mark_data_recovered("authentic bars merged from the background sync")
        except Exception as e:
            logger.debug(f"[XauusdScalpEngine] Background candle sync note: {e}")

    def _broker_feed(self) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        """
        Returns (active_broker, quote) when a connected broker can serve a live quote.

        This is the broker-vs-public feed decision, extracted from the streaming loop so it
        is testable without running the loop: an active, connected broker wins and its own
        quote is adopted; otherwise the caller falls back to the public OANDA spot feed.
        """
        try:
            from server.brokers.registry import broker_registry
            active_broker = broker_registry.get_broker()
            if active_broker and getattr(active_broker, "is_connected", False) and hasattr(active_broker, "get_latest_quote"):
                return active_broker, active_broker.get_latest_quote("XAU/USD")
        except Exception as e_bq:
            logger.debug(f"[XauusdScalpEngine] Broker quote check note: {e_bq}")
        return None, None

    async def run_live_feed(self, broadcast_callback=None):
        """
        Connects to OANDA Cash Spot Gold (XAUUSD) institutional real-time feed via TradingView.
        Polls authentic OANDA cash spot quotes every 2.0s with sub-100ms latency.
        Updates orderbook quotes, 1m candles, EMA ribbon, ATR, and active trade countdowns.
        """
        self.is_running = True
        logger.info("[XauusdScalpEngine] Launching OANDA Spot Gold (XAUUSD) live feed...")

        from server.data_manager import get_oanda_spot_quote

        while self.is_running:
            try:
                loop = asyncio.get_event_loop()

                # Dynamic Broker Feed Switching:
                # If an active broker is connected (e.g. TradeLocker), use the broker's own live quote feed.
                active_broker, broker_quote = self._broker_feed()

                if broker_quote and broker_quote.get("price"):
                    feed_data = broker_quote
                    source_label = broker_quote.get("source", f"{active_broker.broker_id}_broker")
                    display_symbol = f"XAU/USD ({active_broker.name})"
                else:
                    feed_data = await loop.run_in_executor(None, get_oanda_spot_quote)
                    source_label = "oanda_spot"
                    display_symbol = "XAU/USD (OANDA Spot)"

                if feed_data and feed_data.get("price"):
                    c_close = feed_data["price"]
                    t_sec = feed_data.get("timestamp") or int(time.time())

                    self.current_quote["symbol"] = display_symbol
                    self.current_quote["price"] = c_close
                    self.current_quote["bid"] = feed_data.get("bid", round(c_close - 0.15, 2))
                    self.current_quote["ask"] = feed_data.get("ask", round(c_close + 0.15, 2))
                    self.current_quote["high_24h"] = feed_data.get("high", self.current_quote["high_24h"])
                    self.current_quote["low_24h"] = feed_data.get("low", self.current_quote["low_24h"])
                    self.current_quote["timestamp"] = t_sec
                    self.current_quote["source"] = source_label

                    # Update candle history with strictly minute-aligned timestamps
                    minute_bucket = (t_sec // 60) * 60
                    if self.candles_1m:
                        last_c = self.candles_1m[-1]

                        # Compute rolling baseline volume from recent authentic candles
                        valid_vols = [c["volume"] for c in self.candles_1m[-30:] if c.get("volume", 0) > 50]
                        baseline_vol = float(np.median(valid_vols)) if valid_vols else 480.0

                        if last_c["time"] == minute_bucket:
                            prev_c_close = float(last_c.get("close", c_close))
                            last_c["close"] = c_close
                            last_c["high"] = max(last_c["high"], c_close)
                            last_c["low"] = min(last_c["low"], c_close)

                            # Accumulate realistic tick volume proportional to baseline (~15-20 per 2s tick) and price volatility
                            price_displacement = abs(c_close - prev_c_close)
                            vol_multiplier = 1.0 + min(2.5, price_displacement / 0.15)
                            tick_vol = (baseline_vol / 30.0) * vol_multiplier
                            last_c["volume"] = round(float(last_c.get("volume", 0)) + tick_vol, 1)

                            # Serve the observed price VERBATIM. This block used to
                            # add a random micro-pip "tick dance" to the close and
                            # then re-derive bid/ask from it, so the quoted price
                            # was not the real market price. Prices are never
                            # synthesised.
                            last_c["close"] = c_close
                            last_c["high"] = max(last_c["high"], c_close)
                            last_c["low"] = min(last_c["low"], c_close)
                            self.current_quote["price"] = c_close
                            self.current_quote["bid"] = feed_data.get("bid") or round(c_close - 0.15, 2)
                            self.current_quote["ask"] = feed_data.get("ask") or round(c_close + 0.15, 2)
                        elif minute_bucket > last_c["time"]:
                            # An OANDA spot quote carries no volume, so this bar's
                            # volume is DERIVED from the polled price stream, not
                            # exchange volume. It used to be randomised into looking
                            # authentic; now it is labelled instead, and the
                            # authentic background sync overwrites it when available.
                            if not last_c.get("volume_source"):
                                last_c["volume_source"] = "derived_from_ticks"

                            # If missed more than 1 minute (e.g. startup/reconnect gap), backfill authentic bars
                            if (minute_bucket - last_c["time"]) > 120:
                                from server.data_manager import fetch_real_oanda_candles
                                fresh = await loop.run_in_executor(None, lambda: fetch_real_oanda_candles(interval="1m", count=20000, force_refresh=False))
                                if fresh and fresh[-1]["time"] >= minute_bucket - 120:
                                    self.candles_1m = fresh
                                    self._mark_data_recovered("gap backfilled with authentic candles")
                                else:
                                    # Do NOT fabricate bars for minutes that were never
                                    # observed. Record the gap so consumers know the
                                    # series is incomplete, rather than silently feeding
                                    # interpolated prices into indicators and signals.
                                    self.data_degraded = True
                                    self.data_gap_seconds = int(minute_bucket - last_c["time"])
                                    logger.warning(
                                        "[XauusdScalpEngine] Data gap of %ss could not be "
                                        "backfilled with authentic candles; refusing to "
                                        "synthesise bars.",
                                        self.data_gap_seconds,
                                    )
                            else:
                                prev_close = last_c["close"]
                                initial_vol = round(max(10.0, baseline_vol / 30.0), 1)
                                self.candles_1m.append({
                                    "time": minute_bucket,
                                    "open": prev_close,
                                    "high": max(prev_close, c_close),
                                    "low": min(prev_close, c_close),
                                    "close": c_close,
                                    "volume": initial_vol,
                                    # An OANDA spot quote carries no volume; this value
                                    # is derived until the authentic sync replaces it.
                                    "volume_source": "derived_from_ticks"
                                })

                                # Schedule non-blocking background sync of finalized bars from TradingView
                                now_mono = time.monotonic()
                                if now_mono - getattr(self, "_last_tv_sync", 0) >= 55:
                                    self._last_tv_sync = now_mono
                                    asyncio.create_task(self._sync_authentic_candles())

                            if len(self.candles_1m) > 20000:
                                self.candles_1m.pop(0)

                    if self.candles_1m:
                        self.current_quote["candle"] = self.candles_1m[-1]
                        self.current_quote["volume_1m"] = self.candles_1m[-1]["volume"]

                    # Check for new signals & active trade countdown
                    sig = self.generate_signal()
                    trade_status = self.get_active_trade_status()

                    if broadcast_callback:
                        await broadcast_callback({
                            "event_type": "XAUUSD_TICK",
                            "payload": {
                                "quote": self.current_quote,
                                "session": self.is_session_active(),
                                "indicators": self.compute_indicators(),
                                "active_trade": trade_status,
                                "signal": sig
                            }
                        })
            except Exception as e:
                logger.warning(f"[XauusdScalpEngine] OANDA feed tick warning: {e}")

            await asyncio.sleep(2.0)

_ENGINE: Optional[XauusdScalpEngine] = None


def get_xauusd_engine() -> XauusdScalpEngine:
    """
    Returns the process-wide XAUUSD scalp engine, building and seeding it on first use.

    The engine used to be constructed at import time, so importing this module — or
    anything that imports it, such as `server.main` — performed a 20,000-bar live fetch.
    Deferring both the construction and the seed keeps module import free of network I/O
    while leaving callers with exactly the same object and behaviour on first use.
    """
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = XauusdScalpEngine()
        _ENGINE._ensure_seeded()
    return _ENGINE


class _LazyEngine:
    """
    Stand-in for the old module-level `xauusd_engine` instance.

    Forwards attribute reads and writes to the engine from get_xauusd_engine(), so existing
    `xauusd_engine.something` call sites keep working unchanged while construction stays
    deferred until the first access.
    """

    __slots__ = ()

    def __getattr__(self, item: str) -> Any:
        return getattr(get_xauusd_engine(), item)

    def __setattr__(self, key: str, value: Any) -> None:
        setattr(get_xauusd_engine(), key, value)

    def __repr__(self) -> str:
        return f"<lazy {XauusdScalpEngine.__name__} proxy at {hex(id(self))}>"


xauusd_engine = _LazyEngine()
