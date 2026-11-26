from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Callable, Tuple

import numpy as np
import pandas as pd

from server.state_manager import state_manager, signal_store, strategy_registry
from server.accounts_store import accounts_store
from server.telegram_bot import telegram_gateway
from server.providers.base import BaseMarketDataProvider, ProviderRegistry
from server.brokers.registry import broker_registry

logger = logging.getLogger("StrategyExecutor")

# Per-loop execution mutex preventing concurrent strategies from racing past
# allow_pyramiding / cannibalization guards on simultaneous bar rollovers.
_EXEC_LOCKS: Dict[int, asyncio.Lock] = {}


def _get_execution_lock() -> asyncio.Lock:
    loop_id = id(asyncio.get_running_loop())
    lock = _EXEC_LOCKS.get(loop_id)
    if lock is None:
        lock = asyncio.Lock()
        _EXEC_LOCKS[loop_id] = lock
    return lock


def _resolve_contract_size(symbol: str, price: float = 0.0) -> float:
    """
    Resolves account-currency point value per 1.00 lot from the active broker
    when connected, falling back to core.friction.default_paper_contract_size
    for paper/offline mode only.
    """
    try:
        broker = broker_registry.get_broker(connect=False)
        if broker and getattr(broker, "is_connected", False):
            if hasattr(broker, "get_point_value") and price and float(price) > 0:
                pv = broker.get_point_value(symbol, float(price))
                if pv is not None and float(pv) > 0:
                    return float(pv)
            if hasattr(broker, "get_contract_size"):
                cs = broker.get_contract_size(symbol)
                if cs is not None and float(cs) > 0:
                    return float(cs)
    except Exception:
        pass
    from core.friction import default_paper_contract_size
    return default_paper_contract_size(symbol)


def _resolve_max_allowed_spread(symbol: str, price: float, stop_loss: float, strat_inst: Any) -> float:
    """
    Universal asset-agnostic spread-spike ceiling derived from core.friction
    and stop-loss geometry (with optional per-strategy `max_allowed_spread` override).
    """
    if strat_inst is not None:
        explicit = getattr(strat_inst, "max_allowed_spread", None)
        if explicit is not None and float(explicit) > 0:
            return float(explicit)
    from core.friction import resolve_asset_friction
    px = max(float(price or 0.0), 1e-9)
    baseline_spread, _, _ = resolve_asset_friction(symbol, px)
    base_cap = max(baseline_spread * 3.5, px * 0.0002)
    stop_dist = abs(px - float(stop_loss)) if (price and stop_loss and float(stop_loss) > 0) else 0.0
    if stop_dist > 0:
        stop_cap = stop_dist * 0.15
        if stop_cap > baseline_spread * 1.5:
            base_cap = min(base_cap, stop_cap)
    return float(base_cap)

class StrategyEvaluator:
    """
    Evaluates algorithmic trading rules against incoming market candles.
    Supports generic systematic alpha strategies across any requested asset class.
    """
    @staticmethod
    def is_session_active(strategy_name: str, timestamp: Optional[int] = None) -> Dict[str, Any]:
        """London Momentum: 07:30 - 10:30 UTC | New York Momentum: 12:45 - 16:30 UTC."""
        if timestamp and timestamp > 0:
            now_utc = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        else:
            now_utc = datetime.now(timezone.utc)
        current_minute_utc = now_utc.hour * 60 + now_utc.minute

        is_london = 450 <= current_minute_utc <= 630
        is_ny = 765 <= current_minute_utc <= 990
        active = is_london or is_ny

        session_name = "NONE"
        if is_london and is_ny:
            session_name = "LONDON_NY_OVERLAP"
        elif is_london:
            session_name = "LONDON_SESSION"
        elif is_ny:
            session_name = "NEW_YORK_SESSION"

        return {
            "is_active": active,
            "session_name": session_name,
            "is_london": is_london,
            "is_ny": is_ny
        }

    @staticmethod
    def evaluate(
        strategy_name: str,
        symbol: str,
        candles: List[Dict[str, Any]],
        strat_inst: Any = None,
        prefetched_equity: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates candle indicators and checks for LONG or SHORT entry signals.
        Returns signal dictionary if triggered, else None.
        """
        if not candles or len(candles) < 25:
            return None

        clean_name = strategy_name.replace(".py", "")
        df = pd.DataFrame(candles)
        close = df["close"]
        high = df["high"]
        low = df["low"]
        vol = df["volume"]

        curr_i = len(df) - 1
        curr_bar = df.iloc[curr_i]
        curr_p = float(close.iloc[curr_i])
        bar_ts = int(curr_bar.get("time", curr_bar.get("timestamp", 0)))
        is_xau = "XAU" in symbol.upper() or "GOLD" in symbol.upper()

        from core.data import get_market_price_precision
        price_prec = get_market_price_precision(symbol)

        # Dynamic evaluation via strategy class Single Source of Truth
        try:
            if strat_inst is None:
                from server.backtest_engine import load_strategy_instance
                strat_inst = load_strategy_instance(clean_name)
            if not strat_inst:
                logger.warning(f"[StrategyEvaluator] Strategy '{clean_name}' class could not be loaded from strategies/{clean_name}.py. No signal.")
                return None

            from core.execution_engine import StrategyContract, extract_latest_signal
            contract = StrategyContract.from_strategy(strat_inst)

            curr_vz = 0.0
            curr_atr = float("nan")

            if hasattr(strat_inst, "generate_signals"):
                intent, sig_df, last_sig = extract_latest_signal(strat_inst, df, price_prec=price_prec)
                if intent is None or last_sig is None:
                    return None

                is_l = bool(intent.direction == 1)
                is_s = bool(intent.direction == -1)
                side = "BUY" if is_l else "SELL"
                sl = intent.stop_loss
                tp = intent.target
                limit_p = intent.limit_price
                is_limit_order = (intent.order_type == "LIMIT")

                found_sig_atr = False
                for atr_col in ("atr", "atr_14", "ATR", "ATR_14"):
                    if sig_df is not None and atr_col in sig_df.columns and not np.isnan(sig_df[atr_col].iloc[-1]):
                        atr_v = float(sig_df[atr_col].iloc[-1])
                        found_sig_atr = True
                        break
                if not found_sig_atr and hasattr(strat_inst, "compute_indicators"):
                    try:
                        df_idx = df.copy()
                        if "time" in df_idx.columns:
                            df_idx["dt"] = pd.to_datetime(df_idx["time"], unit="s", utc=True)
                        elif "timestamp" in df_idx.columns:
                            df_idx["dt"] = pd.to_datetime(df_idx["timestamp"], unit="s", utc=True)
                        else:
                            df_idx["dt"] = pd.to_datetime(df_idx.index, utc=True)
                        df_idx = df_idx.set_index("dt")
                        ind_df = strat_inst.compute_indicators(df_idx)
                        for atr_col in ("atr", "atr_14", "ATR", "ATR_14"):
                            if atr_col in ind_df.columns and not np.isnan(ind_df[atr_col].iloc[-1]):
                                atr_v = float(ind_df[atr_col].iloc[-1])
                                found_sig_atr = True
                                break
                    except Exception:
                        pass
                if not found_sig_atr:
                    tr = np.maximum(high - low, np.maximum((high - close.shift(1)).abs(), (low - close.shift(1)).abs()))
                    atr_14 = tr.rolling(14).mean()
                    curr_atr = float(atr_14.iloc[curr_i]) if not np.isnan(atr_14.iloc[curr_i]) else (curr_p * 0.005)
                    atr_v = curr_atr if curr_atr > 0 else (curr_p * 0.005)
                last_row = last_sig
            else:
                tr = np.maximum(high - low, np.maximum((high - close.shift(1)).abs(), (low - close.shift(1)).abs()))
                atr_14 = tr.rolling(14).mean()
                curr_atr = float(atr_14.iloc[curr_i]) if not np.isnan(atr_14.iloc[curr_i]) else 2.50
                vol_mean = vol.rolling(20).mean()
                vol_std = vol.rolling(20).std().replace(0, 1e-6)
                vol_z = (vol - vol_mean) / vol_std
                curr_vz = float(vol_z.iloc[curr_i]) if not np.isnan(vol_z.iloc[curr_i]) else 0.0

                df_dyn = strat_inst.populate_indicators(df.copy(), {})
                df_dyn = strat_inst.populate_entry_trend(df_dyn, {})
                last_row = df_dyn.iloc[-1]

                is_l = bool(last_row.get("enter_long", 0) == 1)
                is_s = bool(last_row.get("enter_short", 0) == 1) if getattr(strat_inst, "can_short", True) else False

                # Prevent simultaneous long/short whipsaw
                if is_l and is_s:
                    is_s = False

                if not is_l and not is_s:
                    return None

                side = "BUY" if is_l else "SELL"
                stoploss_pct = abs(float(getattr(strat_inst, "stoploss", -0.02)))
                minimal_roi = getattr(strat_inst, "minimal_roi", {})
                roi_0 = float(minimal_roi.get("0", minimal_roi.get(0, 0.035 if not is_xau else 0.005))) if minimal_roi else (stoploss_pct * 1.5)
                atr_sl = getattr(strat_inst, "atr_sl_mult", None)
                atr_tp = getattr(strat_inst, "atr_tp_mult", None)
                atr_v = float(df_dyn['atr_14'].iloc[-1]) if ('atr_14' in df_dyn.columns and not np.isnan(df_dyn['atr_14'].iloc[-1])) else (curr_p * 0.005)

                # 1. Structural or Dynamic Stop Loss
                if "structural_sl" in last_row and not np.isnan(last_row["structural_sl"]):
                    sl = round(float(last_row["structural_sl"]), price_prec)
                elif atr_sl is not None and atr_v > 0:
                    sl = round(curr_p - atr_sl * atr_v if is_l else curr_p + atr_sl * atr_v, price_prec)
                else:
                    sl = round(curr_p * (1.0 - stoploss_pct) if is_l else curr_p * (1.0 + stoploss_pct), price_prec)

                # 2. Structural or Dynamic Take Profit
                if "structural_tp" in last_row and not np.isnan(last_row["structural_tp"]):
                    tp = round(float(last_row["structural_tp"]), price_prec)
                elif atr_tp is not None and atr_v > 0:
                    tp = round(curr_p + atr_tp * atr_v if is_l else curr_p - atr_tp * atr_v, price_prec)
                elif minimal_roi:
                    tp = round(curr_p * (1.0 + roi_0) if is_l else curr_p * (1.0 - roi_0), price_prec)
                else:
                    tp = round(curr_p * (1.0 + stoploss_pct * 1.5) if is_l else curr_p * (1.0 - stoploss_pct * 1.5), price_prec)

                raw_limit_p = last_row.get("limit_price", 0.0)
                limit_p = round(float(raw_limit_p), price_prec) if (raw_limit_p is not None and not np.isnan(raw_limit_p) and float(raw_limit_p) > 0) else None
                sig_order_t = str(last_row.get("order_type", "")).upper()
                is_limit_order = (sig_order_t == "LIMIT") or (limit_p is not None and limit_p > 0)

            # 3. Strict Quantitative Sanity Bounds (Universal Risk Enforcement)
            ref_entry = limit_p if (is_limit_order and limit_p is not None and limit_p > 0) else curr_p
            if is_l:
                if sl >= ref_entry or tp <= ref_entry:
                    logger.error(f"[StrategyEvaluator] REJECTED inverted LONG signal for {clean_name}: Entry={ref_entry}, SL={sl}, TP={tp}")
                    return None
            else:
                if sl <= ref_entry or tp >= ref_entry:
                    logger.error(f"[StrategyEvaluator] REJECTED inverted SHORT signal for {clean_name}: Entry={ref_entry}, SL={sl}, TP={tp}")
                    return None

            from core.data import resolve_market_symbol
            is_sp = resolve_market_symbol(symbol) == "CME_MINI:ES1!"
            if is_sp and abs(sl - ref_entry) > 50.0:
                logger.error(f"[StrategyEvaluator] REJECTED excessive S&P stop loss ({abs(sl - ref_entry):.2f} pts > 50 pts) for {clean_name}")
                return None
            if is_xau and abs(sl - ref_entry) > 25.0:
                logger.error(f"[StrategyEvaluator] REJECTED excessive Gold stop loss (${abs(sl - ref_entry):.2f} > $25) for {clean_name}")
                return None

            # Dynamic bar duration resolution (Single Source of Truth)
            bar_sec = None
            if len(df) >= 2 and "time" in df.columns:
                try:
                    diffs = df["time"].diff().dropna()
                    valid_diffs = diffs[diffs > 0]
                    if len(valid_diffs) > 0:
                        bar_sec = int(valid_diffs.median())
                except Exception:
                    pass

            if not bar_sec or bar_sec <= 0:
                tf_str = getattr(strat_inst, "timeframe", "")
                if not tf_str:
                    try:
                        from server.backtest_engine import resolve_strategy_metadata
                        tf_str = resolve_strategy_metadata(clean_name).get("timeframe", "")
                    except Exception:
                        pass
                
                tf_map = {
                    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
                    "1h": 3600, "2h": 7200, "4h": 14400, "1d": 86400
                }
                bar_sec = tf_map.get(str(tf_str).lower(), 300 if ("5m" in clean_name.lower()) else (60 if "1m" in symbol.lower() else 900))

            min_bars = contract.min_hold_bars
            min_hold_seconds = (min_bars * bar_sec) if (min_bars is not None and min_bars > 0) else 0

            # 4. Strategy-Designed Smart Lot Sizer
            target_equity = float(prefetched_equity) if (prefetched_equity is not None and float(prefetched_equity) > 0) else None
            if target_equity is None:
                try:
                    broker = broker_registry.get_broker()
                    is_paper_broker = getattr(broker, "broker_id", "paper") == "paper"
                    if broker and getattr(broker, "is_connected", False) and not is_paper_broker:
                        acc_info = (
                            broker.get_cached_account_info(max_age=15.0)
                            if hasattr(broker, "get_cached_account_info")
                            else broker.get_account_info()
                        )
                        bal = float(acc_info.get("balance") or 0.0)
                        eq = float(acc_info.get("equity") or bal or 0.0)
                        if eq > 0:
                            target_equity = eq
                        active_broker_id = getattr(broker, "broker_id", "")
                        if bal > 0 and active_broker_id and accounts_store and hasattr(accounts_store, "update_account_balance"):
                            accounts_store.update_account_balance(
                                broker_id=active_broker_id,
                                balance=bal,
                                equity=eq,
                            )
                except Exception:
                    pass

            if target_equity is None:
                try:
                    if accounts_store:
                        all_accs = accounts_store.get_all_active_accounts(decrypt=False) if hasattr(accounts_store, "get_all_active_accounts") else []
                        if not all_accs and hasattr(accounts_store, "get_all_accounts"):
                            all_accs = accounts_store.get_all_accounts(decrypt=False)
                        if not all_accs and hasattr(accounts_store, "_read_raw"):
                            all_accs = accounts_store._read_raw().get("accounts", [])
                        if all_accs:
                            target_equity = float(all_accs[0].get("initial_balance") or all_accs[0].get("balance") or 0.0)
                except Exception:
                    pass

            if not target_equity or target_equity <= 0:
                target_equity = float(getattr(strat_inst, "benchmark_equity", 5000.0))

            lots = None
            if "lot_size" in last_row and not np.isnan(last_row["lot_size"]) and float(last_row["lot_size"]) > 0:
                lots = float(last_row["lot_size"])
            elif hasattr(strat_inst, "calculate_lot_size") and callable(getattr(strat_inst, "calculate_lot_size")):
                try:
                    import inspect
                    sig = inspect.signature(strat_inst.calculate_lot_size)
                    sig_params = sig.parameters
                    call_kwargs = {}
                    if "entry_price" in sig_params:
                        call_kwargs["entry_price"] = curr_p
                    if "stop_loss" in sig_params:
                        call_kwargs["stop_loss"] = sl
                    if "account_balance" in sig_params:
                        call_kwargs["account_balance"] = target_equity
                    if "symbol" in sig_params:
                        call_kwargs["symbol"] = symbol
                    if "atr" in sig_params:
                        call_kwargs["atr"] = atr_v
                    if "z_score" in sig_params:
                        if curr_vz == 0.0 and len(vol) >= 20:
                            vol_mean = vol.rolling(20).mean()
                            vol_std = vol.rolling(20).std().replace(0, 1e-6)
                            vz_series = (vol - vol_mean) / vol_std
                            if not np.isnan(vz_series.iloc[curr_i]):
                                curr_vz = float(vz_series.iloc[curr_i])
                        call_kwargs["z_score"] = curr_vz

                    raw_lots = float(strat_inst.calculate_lot_size(**call_kwargs))
                    if "account_balance" not in sig_params:
                        base_size = float(getattr(strat_inst, "account_size", target_equity))
                        scale = (target_equity / base_size) if base_size > 0 else 1.0
                        lots = raw_lots * scale
                    else:
                        lots = raw_lots
                except Exception as e_lots:
                    logger.warning(f"[StrategyEvaluator] Error calculating lot size via strategy lotsizer: {e_lots}")

            if lots is None or lots <= 0:
                # Dynamic 1R risk sizing arithmetic (Zero hardcoded lots)
                dollar_risk_1r = target_equity * float(getattr(strat_inst, "risk_pct_1r", 0.0035))
                stop_dist = abs(ref_entry - sl) if sl > 0 else (atr_v * 1.5 if atr_v > 0 else ref_entry * 0.005)
                if stop_dist > 0:
                    multiplier = _resolve_contract_size(symbol, ref_entry)
                    lots = dollar_risk_1r / (stop_dist * multiplier)
                else:
                    lots = 0.01

            lots = max(0.01, round(lots, 2))

            strat_max_bars = contract.max_hold_bars
            max_hold_seconds = (strat_max_bars * bar_sec) if strat_max_bars is not None else None

            raw_lim_exp = last_row.get("limit_expiry_bars", None) if hasattr(last_row, "get") else None
            if raw_lim_exp is not None and not np.isnan(raw_lim_exp) and int(raw_lim_exp) > 0:
                limit_expiry_bars = int(raw_lim_exp)
            else:
                strat_lim_exp = getattr(strat_inst, "limit_expiry_bars", None)
                limit_expiry_bars = int(strat_lim_exp) if (strat_lim_exp is not None and int(strat_lim_exp) > 0) else None
            limit_expiry_seconds = (limit_expiry_bars * bar_sec) if (is_limit_order and limit_expiry_bars) else None

            # 5. Dynamic Trailing Stop Configuration
            use_trailing = getattr(strat_inst, "trailing_stop", False)
            trail_pos = float(getattr(strat_inst, "trailing_stop_positive", 0.0002))
            trail_offset = float(getattr(strat_inst, "trailing_stop_positive_offset", 0.0003))
            atr_trail_m = float(getattr(strat_inst, "atr_trail_mult", 1.0))

            order_action_type = "LIMIT" if is_limit_order else "MARKET"
            dispatch_price = limit_p if (is_limit_order and limit_p is not None and limit_p > 0) else curr_p
            signal_bar_close_ts = (bar_ts + bar_sec) if (bar_ts > 0 and bar_sec > 0) else bar_ts

            return {
                "strategy": clean_name,
                "pair": symbol,
                "action": side,
                "order_type": order_action_type,
                "type": order_action_type.lower(),
                "price": dispatch_price,
                "entry_price": dispatch_price,
                "market_price": curr_p,
                "time": signal_bar_close_ts if signal_bar_close_ts > 0 else int(time.time()),
                "signal_bar_time": bar_ts,
                "signal_bar_close_ts": signal_bar_close_ts,
                "bar_step_seconds": bar_sec,
                "stop_loss": sl,
                "take_profit": tp,
                "lots": lots,
                "lot_size": lots,
                "atr": float(atr_v if atr_v and atr_v > 0 else 0.0),
                "atr_trail_mult": atr_trail_m,
                "min_hold_seconds": min_hold_seconds,
                "max_hold_seconds": max_hold_seconds,
                "limit_expiry_seconds": limit_expiry_seconds,
                "trailing_stop": use_trailing,
                "trailing_offset": trail_offset,
                "trailing_buffer": trail_pos,
                "annotation": f"{clean_name} {order_action_type} Signal ({lots:.2f} lots)",
                "reasoning_md": f"Systematic {order_action_type} signal generated by {clean_name} ({side} {lots:.2f} lots @ ${dispatch_price:,.2f}) with SL: ${sl:,.2f}, TP: ${tp:,.2f}."
            }
        except Exception as e_dyn:
            logger.warning(f"[StrategyEvaluator] Error evaluating dynamic strategy {clean_name}: {e_dyn}")
            return None


class NativeStrategyRunner:
    """
    Active 24/7 Strategy Execution Runner.
    Listens to live market data from its assigned MarketDataProvider,
    evaluates strategy conditions on each bar/tick, triggers trade signals,
    and manages active open positions with automated SL/TP and time cutoff exits.
    """
    def __init__(self, strategy_name: str, broadcast_callback: Optional[Callable] = None):
        self.strategy_name = strategy_name.replace(".py", "")
        self.broadcast_callback = broadcast_callback
        self.is_running = False

        # Dynamically retrieve symbol and timeframe from Single Source of Truth
        from server.backtest_engine import resolve_strategy_metadata
        meta = resolve_strategy_metadata(self.strategy_name)
        self.symbol = meta["symbol"]
        self.timeframe = meta["timeframe"]

        self.provider: BaseMarketDataProvider = ProviderRegistry.get_provider(self.symbol, self.timeframe)
        self._last_evaluated_bar_time: int = 0
        self._stopped: bool = False
        self._supports_structural_sl: Optional[bool] = None
        self._last_struct_sl_bar_ts: int = 0
        self._exit_lock: asyncio.Lock = asyncio.Lock()
        self._reconcile_in_flight: bool = False
        self._subscribed_broker: Optional[Any] = None

    def _get_strategy_instance(self) -> Any:
        strat_inst = getattr(self, "_cached_strat_inst", None)
        if strat_inst is None:
            try:
                from server.backtest_engine import load_strategy_instance
                strat_inst = load_strategy_instance(self.strategy_name)
                if strat_inst is not None:
                    self._cached_strat_inst = strat_inst
            except Exception as e_st:
                logger.debug(f"[NativeStrategyRunner] Could not load strategy instance for {self.strategy_name}: {e_st}")
        return strat_inst

    def _fetch_broker_snapshot(self) -> Tuple[Optional[Dict[str, Any]], Optional[List[Dict[str, Any]]]]:
        """Fetches a single cached broker snapshot (account info + open positions) off the event loop."""
        try:
            broker = broker_registry.get_broker()
            is_paper = getattr(broker, "broker_id", "paper") == "paper"
            if not broker or not getattr(broker, "is_connected", False) or is_paper:
                return None, None
            info = (
                broker.get_cached_account_info(max_age=15.0)
                if hasattr(broker, "get_cached_account_info")
                else broker.get_account_info()
            )
            positions = None
            if hasattr(broker, "get_cached_open_positions"):
                positions = broker.get_cached_open_positions(max_age=4.0)
            elif hasattr(broker, "get_open_positions"):
                positions = broker.get_open_positions()
            return info, positions
        except Exception as e_snap:
            logger.debug(f"[NativeStrategyRunner] Broker snapshot note: {e_snap}")
            return None, None

    async def start(self) -> None:
        if self._stopped or self.is_running:
            return
        self.is_running = True

        # Ensure market data provider is running
        if not self.provider.is_running:
            await self.provider.start()

        if self._stopped or not self.is_running:
            self.is_running = False
            return

        # Subscribe callbacks
        self.provider.subscribe_tick(self._on_market_tick)
        self.provider.subscribe_bar(self._on_market_bar)
        try:
            broker = broker_registry.get_broker(connect=False)
            if broker and hasattr(broker, "subscribe_execution_events"):
                broker.subscribe_execution_events(self._on_broker_execution_event)
                self._subscribed_broker = broker
        except Exception:
            pass
        logger.info(f"[NativeStrategyRunner] Active for '{self.strategy_name}' on {self.symbol} ({self.timeframe})")

    async def stop(self) -> None:
        self._stopped = True
        self.is_running = False
        self.provider.unsubscribe_tick(self._on_market_tick)
        self.provider.unsubscribe_bar(self._on_market_bar)
        try:
            if self._subscribed_broker and hasattr(self._subscribed_broker, "unsubscribe_execution_events"):
                self._subscribed_broker.unsubscribe_execution_events(self._on_broker_execution_event)
            self._subscribed_broker = None
        except Exception:
            pass
        logger.info(f"[NativeStrategyRunner] Stopped for '{self.strategy_name}'")

    def _is_pyramiding_blocked(self, prefetched_positions: Optional[List[Dict[str, Any]]] = None) -> Tuple[bool, str]:
        """Return (True, reason) if allow_pyramiding is False and another signal/position is active."""
        allow_pyramiding = False
        try:
            if accounts_store:
                active_accs = accounts_store.get_all_active_accounts(decrypt=False)
                if not active_accs and hasattr(accounts_store, "_read_raw"):
                    active_accs = accounts_store._read_raw().get("accounts", [])
                if active_accs:
                    risk_profile = active_accs[0].get("risk_profile") or {}
                    allow_pyramiding = bool(risk_profile.get("allow_pyramiding", False))
        except Exception:
            pass

        if allow_pyramiding:
            return False, ""

        # 1. Check local active signals across all strategies (includes pending limit orders)
        try:
            active_signals = signal_store.get_active_signals() if hasattr(signal_store, "get_active_signals") else []
            for s in active_signals:
                other_strat = s.get("strategy") or s.get("strategy_name") or "unknown"
                if other_strat != self.strategy_name:
                    return True, f"Pyramiding disabled: active signal already open for '{other_strat}'"
        except Exception:
            pass

        # 2. Check live broker open positions (protects against manual or untracked positions)
        if prefetched_positions is not None:
            if len(prefetched_positions) > 0:
                return True, f"Pyramiding disabled: {len(prefetched_positions)} open position(s) already on broker"
            return False, ""

        try:
            broker = broker_registry.get_broker()
            is_paper = getattr(broker, "broker_id", "paper") == "paper"
            if broker and getattr(broker, "is_connected", False) and not is_paper and hasattr(broker, "get_open_positions"):
                positions = broker.get_open_positions()
                if positions:
                    return True, f"Pyramiding disabled: {len(positions)} open position(s) already on broker"
        except Exception:
            pass

        return False, ""

    def check_drawdown_safety(self, prefetched_broker_info: Optional[Dict[str, Any]] = None) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Active Live Risk & Drawdown Circuit Breaker.
        Strictly enforces strategy-configured max_daily_drawdown_pct and max_total_drawdown_pct
        across connected broker accounts (e.g. Prop Firm or custom broker limits).
        Prevents funded account breaches by halting new entries when daily or total loss limits
        are reached, or when the remaining daily budget is less than 2.5x single trade risk ($75 safety buffer).
        """
        strat_inst = getattr(self, "_cached_strat_inst", None)
        if strat_inst is None:
            try:
                from server.backtest_engine import load_strategy_instance
                strat_inst = load_strategy_instance(self.strategy_name)
                if strat_inst is not None:
                    self._cached_strat_inst = strat_inst
            except Exception as e_st:
                logger.debug(f"[DrawdownGuard] Could not load strategy instance for {self.strategy_name}: {e_st}")

        # 1. Resolve Account & Pluggable Risk Profile
        primary_acc = None
        initial_balance = None
        try:
            if accounts_store:
                active_accs = accounts_store.get_all_active_accounts(decrypt=False)
                if not active_accs and hasattr(accounts_store, "_read_raw"):
                    active_accs = accounts_store._read_raw().get("accounts", [])
                if active_accs:
                    primary_acc = active_accs[0]
                    initial_balance = float(primary_acc.get("initial_balance") or primary_acc.get("balance") or 0.0)
        except Exception:
            pass

        if not initial_balance or initial_balance <= 0:
            initial_balance = float(getattr(strat_inst, "benchmark_equity", 5000.0))

        # Preserve authentic starting capital separately from live balance/equity
        # so total drawdown tracks closed + floating losses from initial_balance accurately.
        account_initial_balance = float(initial_balance)

        risk_profile = (primary_acc.get("risk_profile") if primary_acc else None) or {}
        now_utc = datetime.now(timezone.utc)
        today_utc_str = now_utc.strftime("%Y-%m-%d")
        daily_guard_bypassed = (
            risk_profile.get("disable_daily_guard") is True
            or risk_profile.get("bypass_guard_date") == today_utc_str
        )

        # Respect account-level risk profile, falling back to strategy configuration, then generic defaults
        max_daily_dd_pct = float(risk_profile.get("max_daily_drawdown_pct") or getattr(strat_inst, "max_daily_drawdown_pct", 0.03))
        max_total_dd_pct = float(risk_profile.get("max_total_drawdown_pct") or getattr(strat_inst, "max_total_drawdown_pct", 0.05))
        trade_risk_pct = float(risk_profile.get("risk_per_trade_pct") or getattr(strat_inst, "max_risk_pct", getattr(strat_inst, "risk_per_trade_pct", getattr(strat_inst, "risk_pct_1r", 0.0060))))
        from core.execution_engine import StrategyContract
        strat_max_daily_losses = StrategyContract.from_strategy(strat_inst).max_daily_losses

        # 2. Check live broker equity/balance (ONLY IF not in paper mode, avoiding $100k paper mismatch)
        broker_equity = None
        broker_balance = None
        broker_today_net = None
        try:
            if prefetched_broker_info is not None:
                info = prefetched_broker_info
                eq = float(info.get("equity") or 0.0)
                bal = float(info.get("balance") or 0.0)
                if eq > 0:
                    broker_equity = eq
                    broker_balance = bal if bal > 0 else eq
                if info.get("today_net_usd") is not None:
                    broker_today_net = float(info["today_net_usd"])
            else:
                broker = broker_registry.get_broker()
                is_paper = getattr(broker, "broker_id", "paper") == "paper"
                if broker and getattr(broker, "is_connected", False) and not is_paper:
                    info = broker.get_account_info()
                    eq = float(info.get("equity") or 0.0)
                    bal = float(info.get("balance") or 0.0)
                    if eq > 0:
                        broker_equity = eq
                        broker_balance = bal if bal > 0 else eq
                    if info.get("today_net_usd") is not None:
                        broker_today_net = float(info["today_net_usd"])
                    active_broker_id = getattr(broker, "broker_id", "")
                    if bal > 0 and active_broker_id and accounts_store and hasattr(accounts_store, "update_account_balance"):
                        accounts_store.update_account_balance(
                            broker_id=active_broker_id,
                            balance=bal,
                            equity=eq if eq > 0 else bal,
                        )
        except Exception as e_b:
            logger.debug(f"[DrawdownGuard] Broker info error: {e_b}")

        # 3. Calculate today's PnL from closed signals
        signals = signal_store.get_all()
        today_realized_usd = 0.0
        today_losses_count = 0
        strategy_today_losses_count = 0
        current_strat_clean = (self.strategy_name or "").replace(".py", "").lower()

        for s in signals:
            t = s.get("exit_time") or s.get("executed_at") or s.get("time") or s.get("entry_time") or 0
            if not t:
                continue
            dt = datetime.fromtimestamp(float(t), tz=timezone.utc)
            if dt.strftime("%Y-%m-%d") == today_utc_str:
                if s.get("status") == "CLOSED":
                    pnl = 0.0
                    if s.get("pnl_usd") is not None:
                        pnl = float(s["pnl_usd"])
                    else:
                        entry_p = float(s.get("price") or s.get("entry_price") or 0.0)
                        exit_p = float(s.get("exit_price") or 0.0)
                        lots = float(s.get("lots") or s.get("lot_size") or 0.01)
                        pair = s.get("pair") or s.get("symbol") or "XAU/USD"
                        c_mult = _resolve_contract_size(pair, entry_p)
                        action = (s.get("action") or "BUY").upper()
                        if entry_p > 0 and exit_p > 0:
                            diff = (exit_p - entry_p) if action in ("BUY", "LONG") else (entry_p - exit_p)
                            pnl = (diff * lots * c_mult)
                    today_realized_usd += pnl
                    if pnl < 0:
                        today_losses_count += 1
                        strat_name_sig = (s.get("strategy") or "").replace(".py", "").lower()
                        if current_strat_clean and strat_name_sig == current_strat_clean:
                            strategy_today_losses_count += 1

        # 4. Losses and budget calculation (authentic initial balance for total DD, live equity & broker daily PnL for daily DD)
        current_balance = broker_balance if (broker_balance and broker_balance > 0) else account_initial_balance
        current_equity = broker_equity if (broker_equity and broker_equity > 0) else max(0.0, current_balance + min(0.0, today_realized_usd))
        daily_ref_balance = max(current_balance, account_initial_balance)

        max_daily_loss_usd = round(daily_ref_balance * max_daily_dd_pct, 2)
        max_total_loss_usd = round(account_initial_balance * max_total_dd_pct, 2)
        single_trade_risk_usd = round(daily_ref_balance * trade_risk_pct, 2)

        total_drawdown_usd = round(max(0.0, account_initial_balance - current_equity), 2)
        floating_loss_usd = (
            max(0.0, broker_balance - broker_equity)
            if (broker_balance and broker_balance > 0 and broker_equity and broker_equity > 0)
            else 0.0
        )
        broker_daily_loss_usd = (abs(broker_today_net) if (broker_today_net is not None and broker_today_net < 0) else 0.0) + floating_loss_usd
        signals_daily_loss_usd = (abs(today_realized_usd) if today_realized_usd < 0 else 0.0) + floating_loss_usd
        today_loss_usd = round(max(broker_daily_loss_usd, signals_daily_loss_usd), 2)
        remaining_budget_usd = round(max(0.0, max_daily_loss_usd - today_loss_usd), 2)

        # Single-source-of-truth daily realized PnL: MUST match the exact basis driving today_loss_usd
        # and remaining_budget_usd (prevents UI contradiction when broker server resets todayNet on a different timezone).
        if broker_today_net is not None and broker_daily_loss_usd > signals_daily_loss_usd:
            effective_today_realized_pnl = round(broker_today_net, 2)
        elif today_losses_count > 0 or today_realized_usd != 0.0:
            effective_today_realized_pnl = round(today_realized_usd, 2)
        elif broker_today_net is not None:
            effective_today_realized_pnl = round(broker_today_net, 2)
        else:
            effective_today_realized_pnl = 0.0

        # Dynamically calculate required safety buffer strictly from 1R trade risk (2.5x safety buffer):
        buffer_required_usd = round(single_trade_risk_usd * 2.5, 2)

        details = {
            "strategy": self.strategy_name,
            "day_key": today_utc_str,
            "initial_balance": account_initial_balance,
            "current_balance": current_balance,
            "current_equity": current_equity,
            "total_drawdown_usd": total_drawdown_usd,
            "max_total_loss_usd": max_total_loss_usd,
            "max_total_dd_pct": max_total_dd_pct,
            "today_loss_usd": today_loss_usd,
            "today_realized_pnl_usd": effective_today_realized_pnl,
            "broker_today_net_usd": round(broker_today_net, 2) if broker_today_net is not None else None,
            "today_losses_count": today_losses_count,
            "strategy_today_losses_count": strategy_today_losses_count,
            "max_daily_losses": strat_max_daily_losses,
            "max_daily_loss_usd": max_daily_loss_usd,
            "max_daily_dd_pct": max_daily_dd_pct,
            "remaining_budget_usd": remaining_budget_usd,
            "single_trade_risk_usd": single_trade_risk_usd,
            "buffer_required_usd": buffer_required_usd,
            "daily_guard_bypassed": daily_guard_bypassed,
            "message": ""
        }

        # 5. HARD ACCOUNT BLOW-UP GUARD: Total drawdown is ALWAYS enforced (even if daily guard is bypassed).
        if total_drawdown_usd >= max_total_loss_usd:
            details["message"] = (
                f"Total drawdown limit reached: -${total_drawdown_usd:.2f} >= -${max_total_loss_usd:.2f} "
                f"({max_total_dd_pct*100:.1f}% of ${account_initial_balance:.2f})"
            )
            return False, "TOTAL_DRAWDOWN_LIMIT_EXCEEDED", details

        # If user explicitly bypassed the DAILY guard, return SAFE with full real budget telemetry (never Budget: $0 lie!)
        if daily_guard_bypassed:
            details["status"] = "BYPASSED"
            details["message"] = f"Daily guard bypassed; total DD safe (-${total_drawdown_usd:.2f} / -${max_total_loss_usd:.2f})"
            return True, f"Drawdown guard bypassed for today ({today_utc_str})", details

        if today_loss_usd >= max_daily_loss_usd:
            details["message"] = f"Daily drawdown limit reached: -${today_loss_usd:.2f} >= -${max_daily_loss_usd:.2f} ({max_daily_dd_pct*100:.1f}%)"
            return False, "DAILY_DRAWDOWN_LIMIT_EXCEEDED", details

        if strat_max_daily_losses is not None and strategy_today_losses_count >= strat_max_daily_losses:
            details["message"] = (
                f"Strategy daily loss count reached: {strategy_today_losses_count} / {strat_max_daily_losses} losses today"
            )
            return False, "MAX_DAILY_LOSSES_REACHED", details

        if remaining_budget_usd < buffer_required_usd:
            details["message"] = f"Daily drawdown safety buffer exhausted: remaining ${remaining_budget_usd:.2f} < required safety buffer ${buffer_required_usd:.2f}"
            return False, "DAILY_DRAWDOWN_BUFFER_EXHAUSTED", details

        details["message"] = f"Safe: Remaining daily budget ${remaining_budget_usd:.2f}"
        return True, "OK", details

    def _send_drawdown_alert(self, reason: str, details: Dict[str, Any]) -> None:
        """Dispatches an urgent Telegram alert and broadcasts circuit breaker trigger."""
        today_key = details.get("day_key", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        if getattr(self, "_last_alerted_dd_day", "") == today_key:
            return
        self._last_alerted_dd_day = today_key

        if "COUNT" in reason or "MAX_DAILY_LOSSES" in reason:
            reason_title = "MAX DAILY LOSS COUNT REACHED"
            sub_title = (
                f"🛑 <b>Loss Count Gate:</b> <code>{details.get('today_losses_count', 0)} / {details.get('max_daily_losses', 2)} Losses</code>\n"
                f"📉 <b>Today's Net Realized PnL:</b> <b>${details.get('today_realized_pnl_usd', 0.0):+.2f}</b>\n"
            )
        elif "TOTAL" in reason:
            reason_title = "TOTAL DRAWDOWN LIMIT REACHED"
            sub_title = (
                f"🛑 <b>Max Total Loss Limit:</b> <code>-${details.get('max_total_loss_usd', 250.0):.2f}</code> (5.0% Max DD)\n"
                f"📉 <b>Account Drawdown:</b> <b>-${details.get('today_loss_usd', 0.0):.2f}</b>\n"
            )
        else:
            reason_title = "DAILY DRAWDOWN LIMIT REACHED"
            sub_title = (
                f"🛑 <b>Max Daily Loss Limit:</b> <code>-${details.get('max_daily_loss_usd', 150.0):.2f}</code> ({details.get('max_daily_dd_pct', 0.03)*100:.1f}% Max DD)\n"
                f"📉 <b>Today's Net Loss:</b> <b>-${details.get('today_loss_usd', 0.0):.2f}</b>\n"
            )

        msg = (
            f"🛡️ <b>[CIRCUIT BREAKER] {reason_title}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ <b>Time:</b> <code>{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}</code>\n"
            f"📊 <b>Strategy:</b> <code>{self.strategy_name}</code>\n"
            f"{sub_title}"
            f"💼 <b>Remaining Daily Dollar Buffer:</b> <code>${details.get('remaining_budget_usd', 0.0):.2f}</code>\n\n"
            f"🔒 <b>Protection Status:</b> <b>AUTOMATED TRADING LOCKED FOR TODAY</b>\n"
            f"<i>Your funded account is strictly protected. New signal entries are halted until daily rollover at 00:00 UTC.</i>"
        )
        telegram_gateway.send_message(msg, parse_mode="HTML")

    def check_alpha_degradation(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Monitors live trade performance via CUSUM (Page's Cumulative Sum) test.
        Flags edge decay if rolling cumulative losses exceed statistical bounds (2.5 sigma).
        """
        try:
            closed_signals = [
                s for s in signal_store.get_all()
                if (s.get("strategy") == self.strategy_name and (s.get("status") == "CLOSED" or s.get("exit_price")))
            ]
            if len(closed_signals) < 8:
                return True, {"status": "HEALTHY", "reason": "Insufficient closed trades (< 8)"}

            # Extract return percentages
            returns = []
            for s in closed_signals:
                if s.get("pnl_pct") is not None:
                    returns.append(float(s["pnl_pct"]) / 100.0)
                else:
                    entry_p = float(s.get("price") or s.get("entry_price") or 0.0)
                    exit_p = float(s.get("exit_price") or 0.0)
                    act = (s.get("action") or "BUY").upper()
                    if entry_p > 0 and exit_p > 0:
                        ret = (exit_p - entry_p) / entry_p if act in ("BUY", "LONG") else (entry_p - exit_p) / entry_p
                        returns.append(ret)

            if len(returns) < 8:
                return True, {"status": "HEALTHY", "reason": "Insufficient return samples"}

            from core.cynic_gates import compute_cusum_degradation
            res = compute_cusum_degradation(np.array(returns[-30:]), threshold_sigma=2.5)
            healthy = (res.get("status") != "DEGRADED")
            return healthy, res
        except Exception as e_decay:
            logger.debug(f"[AlphaDriftGuard] Error evaluating CUSUM: {e_decay}")
            return True, {"status": "ERROR", "error": str(e_decay)}

    def _send_alpha_decay_alert(self, details: Dict[str, Any]) -> None:
        """Dispatches an urgent Telegram alert when strategy edge decay is detected."""
        today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if getattr(self, f"_last_alerted_decay_{today_key}", False):
            return
        setattr(self, f"_last_alerted_decay_{today_key}", True)

        msg = (
            f"📉 <b>[ALPHA DRIFT DETECTED] EDGE DECAY GUARD ACTIVE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⏰ <b>Time:</b> <code>{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}</code>\n"
            f"📊 <b>Strategy:</b> <code>{self.strategy_name}</code>\n"
            f"⚠️ <b>Status:</b> <b>PERFORMANCE DRIFT &gt; 2.5σ</b>\n"
            f"📉 <b>CUSUM Score:</b> <code>{details.get('max_cusum', 0.0):.4f}</code> (Threshold: {details.get('threshold', 0.0):.4f})\n"
            f"🛑 <b>Action Taken:</b> <b>NEW ENTRIES PAUSED</b>\n\n"
            f"<i>The strategy's forward performance has drifted significantly from out-of-sample expectations. New entries are halted to protect account equity while you re-evaluate or re-mine.</i>"
        )
        telegram_gateway.send_message(msg, parse_mode="HTML")

    async def _on_market_tick(self, quote: Dict[str, Any]) -> None:
        """Called on every real-time price tick. Checks open position exits."""
        try:
            if not self.is_running:
                return

            # Lifecycle Guard: If strategy is deactivated, only monitor exit of active position, then stop
            strat_record = strategy_registry.get(self.strategy_name)
            if not strat_record or strat_record.get("status") != "ACTIVE_LIVE":
                active_pos = signal_store.get_active(self.strategy_name)
                if active_pos:
                    current_price = float(quote.get("price") or 0.0)
                    if current_price > 0:
                        if active_pos.get("status") == "PENDING_LIMIT":
                            await self._evaluate_pending_order(active_pos, current_price, quote=quote)
                        else:
                            await self._evaluate_position_exit(active_pos, current_price, quote=quote)
                else:
                    await self.stop()
                return

            current_price = float(quote.get("price") or 0.0)
            if current_price <= 0:
                return

            # 1. Monitor resting pending LIMIT order OR open position exit triggers
            active_pos = signal_store.get_active(self.strategy_name)
            if active_pos:
                if active_pos.get("status") == "PENDING_LIMIT":
                    await self._evaluate_pending_order(active_pos, current_price, quote=quote)
                else:
                    await self._evaluate_position_exit(active_pos, current_price, quote=quote)
        except Exception as e_tick:
            logger.error(f"[NativeStrategyRunner] Error in _on_market_tick for {self.strategy_name}: {e_tick}", exc_info=True)

    async def _on_market_bar(self, bar: Dict[str, Any]) -> None:
        """Called when a candle bar finalizes. Checks for new strategy entry signals."""
        try:
            if not self.is_running:
                return

            # Strict Lifecycle Guard: If strategy is no longer ACTIVE_LIVE, immediately halt runner
            strat_record = strategy_registry.get(self.strategy_name)
            if not strat_record or strat_record.get("status") != "ACTIVE_LIVE":
                logger.info(f"[NativeStrategyRunner] Strategy '{self.strategy_name}' is not ACTIVE_LIVE (status: {strat_record.get('status') if strat_record else 'None'}). Halting runner.")
                await self.stop()
                return

            bar_time = int(bar.get("time") or bar.get("timestamp") or 0)
            if bar_time <= self._last_evaluated_bar_time:
                return
            self._last_evaluated_bar_time = bar_time

            # Check if there is already an active position for this strategy
            active_pos = signal_store.get_active(self.strategy_name)
            if active_pos:
                # Already in position — enforce 1 concurrent trade per strategy
                return

            # Single non-blocking broker snapshot (cached) reused across pyramiding, drawdown, and sizing
            broker_info, open_positions = await asyncio.to_thread(self._fetch_broker_snapshot)

            # Cross-Strategy Pyramiding Guard (default: allow_pyramiding=False)
            pyr_blocked, pyr_reason = self._is_pyramiding_blocked(prefetched_positions=open_positions)
            if pyr_blocked:
                logger.info(f"[NativeStrategyRunner] {pyr_reason} — skipping entry for '{self.strategy_name}'")
                return

            # Prop Firm Risk Guard: Daily Drawdown Circuit Breaker
            safe, reason, dd_details = self.check_drawdown_safety(prefetched_broker_info=broker_info)
            if not safe:
                today_key = dd_details.get("day_key", "today")
                if not getattr(self, f"_halted_{today_key}", False):
                    setattr(self, f"_halted_{today_key}", True)
                    logger.warning(
                        f"[NativeStrategyRunner] 🛡️ CIRCUIT BREAKER ACTIVE: Halting new entries for '{self.strategy_name}' on {self.symbol}. "
                        f"Reason: {reason} | Today's loss: -${dd_details['today_loss_usd']:.2f} / ${dd_details['max_daily_loss_usd']:.2f} limit. "
                        f"Remaining budget: ${dd_details['remaining_budget_usd']:.2f}."
                    )
                    self._send_drawdown_alert(reason, dd_details)
                return

            # Institutional Alpha Drift Guard: CUSUM Edge Decay Circuit Breaker
            healthy, decay_details = self.check_alpha_degradation()
            if not healthy:
                logger.warning(
                    f"[NativeStrategyRunner] ⚠️ ALPHA DECAY DETECTED: Pausing entries for '{self.strategy_name}'. "
                    f"CUSUM score: {decay_details.get('max_cusum', 0.0):.4f} >= threshold {decay_details.get('threshold', 0.0):.4f}."
                )
                self._send_alpha_decay_alert(decay_details)
                return

            # Evaluate strategy entry strictly on completed bars up to bar_time
            candles = self.provider.get_candles(count=1000)
            completed_candles = [
                c for c in candles
                if int(c.get("time", c.get("timestamp", 0))) <= bar_time
            ]
            if not completed_candles or len(completed_candles) < 25:
                completed_candles = candles

            strat_inst = self._get_strategy_instance()
            prefetched_equity = None
            if broker_info:
                eq_val = float(broker_info.get("equity") or broker_info.get("balance") or 0.0)
                if eq_val > 0:
                    prefetched_equity = eq_val

            sig = await asyncio.to_thread(
                StrategyEvaluator.evaluate,
                self.strategy_name,
                self.symbol,
                completed_candles,
                strat_inst,
                prefetched_equity,
            )
            if sig:
                logger.info(f"[NativeStrategyRunner] 🔥 SIGNAL TRIGGERED on finalized bar {bar_time}: {sig.get('action')} @ {sig.get('price')}")
            else:
                logger.info(f"[NativeStrategyRunner] ⏱️ Evaluated finalized bar {bar_time} for '{self.strategy_name}' (Close: {completed_candles[-1].get('close')}) — No setup conditions met.")
            if sig:
                # Enforce Signal Cannibalization Guard: Prevent opposing wash trades across active strategies on same asset
                from server.bot_runner import check_signal_cannibalization
                conflict = check_signal_cannibalization(sig)
                if conflict:
                    logger.warning(
                        f"[SignalConflictGuard] ⚠️ CANNIBALIZATION BLOCKED: Strategy '{self.strategy_name}' signaled {sig['action']} on {self.symbol}, "
                        f"but strategy '{conflict.get('strategy')}' already holds opposing position #{conflict.get('id')} ({conflict.get('action')}). "
                        f"Suppressing order."
                    )
                    sig["status"] = "CANCELLED_CONFLICT"
                    sig["exit_reason"] = f"CONFLICT_WITH_{conflict.get('strategy')}"
                    sig["annotation"] = f"Cannibalization Suppressed ({conflict.get('strategy')})"
                    signal_store.add(sig)
                    if self.broadcast_callback:
                        await self.broadcast_callback({
                            "event_type": "SIGNAL_CONFLICT_SUPPRESSED",
                            "payload": {
                                "incoming_strategy": self.strategy_name,
                                "conflicting_strategy": conflict.get("strategy"),
                                "symbol": self.symbol,
                                "action": sig["action"],
                                "conflicting_action": conflict.get("action")
                            }
                        })
                    return

                await self._trigger_new_signal(
                    sig,
                    prefetched_broker_info=broker_info,
                    prefetched_positions=open_positions,
                )
        except Exception as e_bar:
            logger.error(f"[NativeStrategyRunner] Error in _on_market_bar for {self.strategy_name}: {e_bar}", exc_info=True)

    async def _trigger_new_signal(
        self,
        sig: Dict[str, Any],
        prefetched_broker_info: Optional[Dict[str, Any]] = None,
        prefetched_positions: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Serialized entry point preventing concurrent strategies from racing past pyramiding/conflict guards."""
        async with _get_execution_lock():
            await self._trigger_new_signal_locked(
                sig,
                prefetched_broker_info=prefetched_broker_info,
                prefetched_positions=prefetched_positions,
            )

    async def _trigger_new_signal_locked(
        self,
        sig: Dict[str, Any],
        prefetched_broker_info: Optional[Dict[str, Any]] = None,
        prefetched_positions: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Saves signal to store, alerts Telegram, plays sound, and broadcasts to UI."""
        # Re-check single-position-per-strategy inside the execution lock
        if signal_store.get_active(self.strategy_name):
            logger.info(f"[NativeStrategyRunner] Active position/order already exists for '{self.strategy_name}' — skipping duplicate entry.")
            return

        # Cross-Strategy Pyramiding Guard (double defense inside execution lock)
        pyr_blocked, pyr_reason = self._is_pyramiding_blocked(prefetched_positions=prefetched_positions)
        if pyr_blocked:
            logger.warning(f"[NativeStrategyRunner] ORDER EXECUTION BLOCKED: {pyr_reason}")
            sig["status"] = "BLOCKED_PYRAMIDING"
            sig["exit_reason"] = pyr_reason
            sig["annotation"] = f"Blocked: {pyr_reason}"
            signal_store.add(sig)
            return

        # Double defense: check drawdown safety before executing order
        safe, reason, dd_details = self.check_drawdown_safety(prefetched_broker_info=prefetched_broker_info)
        if not safe:
            logger.warning(f"[NativeStrategyRunner] 🛡️ ORDER EXECUTION BLOCKED by {reason}: {dd_details.get('message', reason)}")
            sig["status"] = "BLOCKED_DRAWDOWN_LIMIT"
            sig["exit_reason"] = reason
            sig["annotation"] = f"Blocked: {reason}"
            signal_store.add(sig)
            self._send_drawdown_alert(reason, dd_details)
            return

        # Triple defense: Live Quote Freshness, Spread Guard, Pre-Trade SL/TP Orientation, & Max-Slippage ("No-Chase") Interlock
        strat_inst = self._get_strategy_instance()
        try:
            active_broker = broker_registry.get_broker()
            is_paper_precheck = getattr(active_broker, "broker_id", "paper") == "paper"
        except Exception:
            active_broker = None
            is_paper_precheck = True

        # Preserve immutable signal benchmark telemetry before live fill reconciliation
        signal_price = float(sig.get("signal_price") or sig.get("price") or 0.0)
        sig["signal_price"] = signal_price
        bar_step = int(sig.get("bar_step_seconds") or getattr(self.provider, "bar_step_seconds", 0) or 0) if hasattr(self, "provider") and self.provider else int(sig.get("bar_step_seconds") or 0)
        if not sig.get("signal_bar_close_ts"):
            raw_sig_bar_t = int(sig.get("signal_bar_time") or sig.get("time") or 0)
            if raw_sig_bar_t > 0 and bar_step > 0:
                sig["signal_bar_close_ts"] = raw_sig_bar_t + bar_step if sig.get("signal_bar_time") else raw_sig_bar_t

        order_type_u = str(sig.get("order_type") or sig.get("type") or "MARKET").upper()
        latest_quote = self.provider.get_latest_quote() if hasattr(self, "provider") and self.provider else None
        now_check = time.time()
        quote_ts = float((latest_quote or {}).get("timestamp") or 0.0)
        # For live MARKET orders, refresh if quote is older than 4.0s so slippage checks use real-time bid/ask
        refresh_threshold = 4.0 if (not is_paper_precheck and order_type_u == "MARKET") else 30.0
        needs_refresh = (not latest_quote) or (quote_ts <= 0) or (abs(now_check - quote_ts) > refresh_threshold)

        if not is_paper_precheck and needs_refresh and active_broker and hasattr(active_broker, "get_latest_quote"):
            try:
                def _fetch_q():
                    try:
                        return active_broker.get_latest_quote(self.symbol, max_age=1.5)
                    except TypeError:
                        return active_broker.get_latest_quote(self.symbol)
                refreshed_q = await asyncio.to_thread(_fetch_q)
                if refreshed_q and refreshed_q.get("price"):
                    latest_quote = refreshed_q
                    quote_ts = float(latest_quote.get("timestamp") or 0.0)
            except Exception as e_rq:
                logger.debug(f"[NativeStrategyRunner] Broker quote refresh note: {e_rq}")

        quote_stale = (not latest_quote) or (quote_ts <= 0) or (abs(time.time() - quote_ts) > 30.0)
        live_bid = float((latest_quote or {}).get("bid") or 0.0)
        live_ask = float((latest_quote or {}).get("ask") or 0.0)

        if not is_paper_precheck and (quote_stale or live_bid <= 0 or live_ask <= 0 or live_ask < live_bid):
            age_str = f"{int(abs(time.time() - quote_ts))}s" if quote_ts > 0 else "missing"
            stale_msg = f"Broker quote unavailable or stale ({age_str}) for {self.symbol}"
            logger.warning(f"[NativeStrategyRunner] 🛡️ QUOTE FRESHNESS BLOCKED: {stale_msg}. Order suppressed.")
            sig["status"] = "BLOCKED_STALE_QUOTE"
            sig["exit_reason"] = f"STALE_OR_MISSING_BROKER_QUOTE ({age_str})"
            sig["annotation"] = f"Stale Quote ({age_str})"
            signal_store.add(sig)
            return

        try:
            if live_bid > 0 and live_ask > 0 and live_ask >= live_bid:
                from core.data import get_market_price_precision
                price_prec = get_market_price_precision(self.symbol)
                current_spread = round(live_ask - live_bid, price_prec)
                sig["live_spread"] = current_spread
                ref_price = float(signal_price or (latest_quote or {}).get("price") or 0.0)
                ref_sl = float(sig.get("stop_loss") or 0.0)
                ref_tp = float(sig.get("take_profit") or 0.0)
                max_allowed_spread = _resolve_max_allowed_spread(self.symbol, ref_price, ref_sl, strat_inst)
                if current_spread > max_allowed_spread:
                    spread_msg = f"Live spread (${current_spread:.{price_prec}f}) exceeds maximum threshold (${max_allowed_spread:.{price_prec}f})"
                    logger.warning(f"[NativeStrategyRunner] 🛡️ SPREAD GUARD BLOCKED: {spread_msg}. Order suppressed.")
                    sig["status"] = "BLOCKED_SPREAD_SPIKE"
                    sig["exit_reason"] = f"SPREAD_SPIKE: ${current_spread:.{price_prec}f} > ${max_allowed_spread:.{price_prec}f}"
                    sig["annotation"] = f"Spread Spike (${current_spread:.{price_prec}f})"
                    signal_store.add(sig)
                    return

                # Verify MARKET order SL/TP orientation & Max Adverse Slippage ("No-Chase") against live Ask (BUY) / Bid (SELL)
                if not is_paper_precheck and order_type_u == "MARKET":
                    is_long_sig = str(sig.get("action") or "BUY").upper() in ("BUY", "LONG")
                    exec_px = live_ask if is_long_sig else live_bid

                    if ref_sl > 0 or ref_tp > 0:
                        sl_bad = (ref_sl > 0) and ((ref_sl >= exec_px) if is_long_sig else (ref_sl <= exec_px))
                        tp_bad = (ref_tp > 0) and ((ref_tp <= exec_px) if is_long_sig else (ref_tp >= exec_px))
                        if sl_bad or tp_bad:
                            move_msg = f"Live price ({exec_px:.{price_prec}f}) already moved past SL ({ref_sl:.{price_prec}f}) / TP ({ref_tp:.{price_prec}f})"
                            logger.warning(f"[NativeStrategyRunner] 🛡️ PRE-TRADE ORIENTATION BLOCKED: {move_msg}. Order suppressed.")
                            sig["status"] = "BLOCKED_PRICE_MOVED"
                            sig["exit_reason"] = f"PRICE_MOVED_PAST_SL_TP (exec={exec_px:.{price_prec}f}, sl={ref_sl:.{price_prec}f}, tp={ref_tp:.{price_prec}f})"
                            sig["annotation"] = "Blocked: Price Moved Past SL/TP"
                            signal_store.add(sig)
                            return

                    # Universal Max Adverse Slippage ("No-Chase") Interlock:
                    # Never chase a market order if live executable price already ran away from the signal bar close.
                    if signal_price > 0:
                        adverse_slip = (exec_px - signal_price) if is_long_sig else (signal_price - exec_px)
                        strat_slip_cap = getattr(strat_inst, "max_entry_slippage_pts", None) if strat_inst else None
                        if strat_slip_cap is not None and float(strat_slip_cap) > 0:
                            max_adverse_slip = float(strat_slip_cap)
                        else:
                            caps = []
                            tp_dist = abs(ref_tp - signal_price) if ref_tp > 0 else 0.0
                            sl_dist = abs(signal_price - ref_sl) if ref_sl > 0 else 0.0
                            if tp_dist > 0:
                                caps.append(max(current_spread * 1.5, tp_dist * 0.20))
                            if sl_dist > 0:
                                caps.append(max(current_spread * 1.5, sl_dist * 0.15))
                            max_adverse_slip = min(caps) if caps else max(current_spread * 2.5, signal_price * 0.0005)

                        if adverse_slip > max_adverse_slip:
                            slip_msg = (
                                f"Adverse slippage {adverse_slip:.{price_prec}f} pts > max {max_adverse_slip:.{price_prec}f} pts "
                                f"(signal={signal_price:.{price_prec}f}, live_exec={exec_px:.{price_prec}f})"
                            )
                            logger.warning(f"[NativeStrategyRunner] 🛡️ NO-CHASE SLIPPAGE BLOCKED: {slip_msg}. Order suppressed.")
                            sig["status"] = "BLOCKED_EXCESSIVE_SLIPPAGE"
                            sig["live_exec_price"] = exec_px
                            sig["adverse_slippage_pts"] = round(adverse_slip, price_prec)
                            sig["max_allowed_slippage_pts"] = round(max_adverse_slip, price_prec)
                            sig["exit_reason"] = f"EXCESSIVE_SLIPPAGE: {adverse_slip:.{price_prec}f} > {max_adverse_slip:.{price_prec}f}"
                            sig["annotation"] = f"Blocked: Chased Slippage ({adverse_slip:.{price_prec}f})"
                            signal_store.add(sig)
                            return

                    # Pass live executable price so broker sizes lots against actual entry distance to SL
                    sig["live_exec_price"] = exec_px
        except Exception as e_spread:
            logger.debug(f"[NativeStrategyRunner] Live spread/orientation/slippage check bypassed: {e_spread}")

        logger.info(f"[NativeStrategyRunner] 🚀 SIGNAL TRIGGERED for {self.strategy_name}: {sig['action']} @ {sig['price']}")

        # 1. Execute order via Active Execution Broker (Paper or any registered broker plugin)
        now_ts = time.time()
        sig["executed_at"] = now_ts
        sig["entry_time_ts"] = now_ts
        try:
            broker = broker_registry.get_broker()
            is_paper_broker = getattr(broker, "broker_id", "paper") == "paper"
            order_res = await asyncio.to_thread(broker.execute_order, sig)
            sig["broker_order"] = order_res
            
            if order_res.get("status") in ("REJECTED", "FAILED", "ERROR"):
                err_msg = order_res.get("error") or "Order rejected by broker"
                if not is_paper_broker:
                    logger.error(f"[NativeStrategyRunner] ❌ Live broker rejected order for {self.strategy_name}: {err_msg}. Order halted.")
                    sig["status"] = "FAILED_BROKER_ORDER"
                    sig["exit_reason"] = f"BROKER_REJECTED: {err_msg}"
                    sig["annotation"] = f"Rejected: {err_msg}"
                    sig["execution_mode"] = "LIVE_BROKER"
                    signal_store.add(sig)
                    
                    reject_alert = (
                        f"❌ <b>[BROKER ORDER REJECTED]</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━\n"
                        f"📊 <b>Strategy:</b> <code>{self.strategy_name}</code>\n"
                        f"⚠️ <b>Action:</b> {sig.get('action')} @ {sig.get('price')}\n"
                        f"🛑 <b>Reason:</b> <code>{err_msg}</code>\n\n"
                        f"<i>No live position was opened. Internal state remains clean and unblocked.</i>"
                    )
                    telegram_gateway.send_message(reject_alert, parse_mode="HTML")
                    return
                else:
                    sig["status"] = "ACTIVE_IN_POSITION"
                    sig["execution_mode"] = "PAPER_SIMULATED"
                    sig["annotation"] = f"{sig.get('annotation', '')} (Simulated Paper)"
            elif order_res.get("status") == "BLOCKED_NOT_ARMED":
                # Live order routing is disarmed, so nothing was sent and no position exists.
                # This must never fall through to the simulated-fill branch below, which marks
                # the signal ACTIVE_IN_POSITION and would manage a position that is not there.
                err_msg = order_res.get("error") or "Live trading is disarmed"
                logger.warning(f"[NativeStrategyRunner] ⛔ Live entry blocked for {self.strategy_name}: {err_msg}")
                sig["status"] = "BLOCKED_NOT_ARMED"
                sig["execution_mode"] = "NONE"
                sig["exit_reason"] = f"NOT_ARMED: {err_msg}"
                sig["annotation"] = "Entry blocked (live trading disarmed)"
                signal_store.add(sig)
                telegram_gateway.send_message(
                    f"⛔ <b>[LIVE ENTRY BLOCKED]</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 <b>Strategy:</b> <code>{self.strategy_name}</code>\n"
                    f"⚠️ <b>Action:</b> {sig.get('action')} @ {sig.get('price')}\n"
                    f"🛑 <b>Reason:</b> <code>{err_msg}</code>\n\n"
                    f"<i>No live position was opened, and none is tracked.</i>",
                    parse_mode="HTML",
                )
                return
            elif order_res.get("status") in ("REJECTED", "ERROR", "FAILED"):
                err_msg = order_res.get("error") or "Order rejected by broker"
                logger.error(f"[NativeStrategyRunner] ❌ Order rejected by broker for {self.strategy_name}: {err_msg}")
                sig["status"] = "REJECTED"
                sig["execution_mode"] = "NONE"
                sig["exit_reason"] = f"BROKER_REJECTED: {err_msg}"
                sig["annotation"] = f"Rejected: {err_msg}"
                signal_store.add(sig)
                telegram_gateway.send_message(
                    f"❌ <b>[BROKER ORDER REJECTED]</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 <b>Strategy:</b> <code>{self.strategy_name}</code>\n"
                    f"⚠️ <b>Action:</b> {sig.get('action')} @ {sig.get('price')}\n"
                    f"🛑 <b>Reason:</b> <code>{err_msg}</code>\n\n"
                    f"<i>Order was rejected by broker. No position is tracked.</i>",
                    parse_mode="HTML",
                )
                return
            elif order_res.get("status") == "SIMULATED_PREVIEW":
                if not is_paper_broker:
                    logger.warning(f"[NativeStrategyRunner] Broker returned preview for {self.strategy_name} while on live broker.")
                sig["status"] = "ACTIVE_IN_POSITION"
                sig["execution_mode"] = "PAPER_SIMULATED"
                sig["annotation"] = f"{sig.get('annotation', '')} (Simulated Paper)"
            elif order_res.get("status") == "PENDING_ORDER":
                sig["status"] = "PENDING_LIMIT"
                sig["execution_mode"] = "PAPER_SIMULATED" if is_paper_broker else "LIVE_BROKER"
                sig["placed_at"] = now_ts
                if not is_paper_broker and order_res.get("needs_reconcile"):
                    sig["broker_sync_state"] = "PENDING_FILL_SYNC"
                b_lots = float(order_res.get("filled_lots") or 0.0)
                if b_lots > 0:
                    sig["lots"] = b_lots
                    sig["lot_size"] = b_lots
                b_details = order_res.get("details", [])
                if b_details and isinstance(b_details, list):
                    first_det = b_details[0]
                    if first_det.get("order_id"):
                        sig["broker_order_id"] = str(first_det.get("order_id"))
                    det_lots = float(first_det.get("filled_lots") or 0.0)
                    if det_lots > 0:
                        sig["lots"] = det_lots
                        sig["lot_size"] = det_lots
                elif order_res.get("order_id"):
                    sig["broker_order_id"] = str(order_res.get("order_id"))
                logger.info(
                    f"[ExecutionAudit] PENDING_LIMIT {self.strategy_name} {sig.get('action')} {self.symbol} "
                    f"@ {sig.get('price')} (lots={sig.get('lots')}, order_id={sig.get('broker_order_id')}, "
                    f"expiry={sig.get('limit_expiry_seconds')}s)"
                )
            elif order_res.get("status") == "FILLED":
                sig["status"] = "ACTIVE_IN_POSITION"
                sig["execution_mode"] = "PAPER_SIMULATED" if is_paper_broker else "LIVE_BROKER"
                if not is_paper_broker:
                    sig["broker_sync_state"] = "PENDING_FILL_SYNC" if order_res.get("needs_reconcile") else "CONFIRMED"
                # If broker returned an authentic fill price/lots, synchronize with broker truth
                b_price = float(order_res.get("filled_price") or 0.0)
                if b_price > 0:
                    sig["price"] = b_price
                    sig["entry_price"] = b_price
                b_lots = float(order_res.get("filled_lots") or 0.0)
                if b_lots > 0:
                    sig["lots"] = b_lots
                    sig["lot_size"] = b_lots
                b_details = order_res.get("details", [])
                if b_details and isinstance(b_details, list):
                    first_det = b_details[0]
                    if first_det.get("position_id"):
                        sig["broker_position_id"] = str(first_det.get("position_id"))
                    det_price = float(first_det.get("filled_price") or 0.0)
                    if det_price > 0:
                        sig["price"] = det_price
                        sig["entry_price"] = det_price
                    det_lots = float(first_det.get("filled_lots") or 0.0)
                    if det_lots > 0:
                        sig["lots"] = det_lots
                        sig["lot_size"] = det_lots
                # Execution audit telemetry (positive slippage = adverse, negative = price improvement)
                try:
                    from core.data import get_market_price_precision
                    p_prec = get_market_price_precision(self.symbol)
                    fill_px = float(sig.get("price") or 0.0)
                    ref_sig_px = float(sig.get("signal_price") or fill_px)
                    is_l_fill = str(sig.get("action") or "BUY").upper() in ("BUY", "LONG")
                    slip_pts = round((fill_px - ref_sig_px) if is_l_fill else (ref_sig_px - fill_px), p_prec)
                    sig["entry_slippage_pts"] = slip_pts
                    close_ts = int(sig.get("signal_bar_close_ts") or 0)
                    lat_ms = int(max(0.0, (time.time() - close_ts) * 1000.0)) if close_ts > 0 else 0
                    if close_ts > 0:
                        sig["execution_latency_ms"] = lat_ms
                    logger.info(
                        f"[ExecutionAudit] FILLED {self.strategy_name} {sig.get('action')} {self.symbol} | "
                        f"signal={ref_sig_px:.{p_prec}f} -> fill={fill_px:.{p_prec}f} (slip={slip_pts:+.{p_prec}f} pts, latency={lat_ms}ms) | "
                        f"lots={sig.get('lots')} | SL={sig.get('stop_loss')} TP={sig.get('take_profit')}"
                    )
                except Exception:
                    pass
            else:
                logger.error(f"[NativeStrategyRunner] Unrecognized order status from broker: {order_res.get('status')}")
                sig["status"] = "REJECTED"
                sig["execution_mode"] = "NONE"
                sig["exit_reason"] = f"UNKNOWN_STATUS: {order_res.get('status')}"
                signal_store.add(sig)
                return
        except Exception as e_broker:
            logger.error(
                f"[NativeStrategyRunner] Error executing order with broker: {e_broker}",
                exc_info=True
            )
            is_paper = False
            try:
                is_paper = getattr(broker_registry.get_broker(), "broker_id", "paper") == "paper"
            except Exception:
                pass
            if not is_paper:
                sig["status"] = "FAILED_BROKER_ORDER"
                sig["exit_reason"] = f"EXECUTION_EXCEPTION: {e_broker}"
                sig["annotation"] = f"Failed: {e_broker}"
                sig["execution_mode"] = "LIVE_BROKER"
                signal_store.add(sig)
                telegram_gateway.send_message(
                    f"❌ <b>[BROKER EXECUTION ERROR]</b>\n\nStrategy: <code>{self.strategy_name}</code>\nError: <code>{e_broker}</code>\nPosition was NOT opened.",
                    parse_mode="HTML"
                )
                return
            else:
                sig["broker_order"] = {"status": "SIMULATED_PREVIEW", "error": str(e_broker)}
                sig["status"] = "ACTIVE_IN_POSITION"
                sig["execution_mode"] = "PAPER_SIMULATED"
                sig["annotation"] = f"{sig.get('annotation', '')} (Simulated Paper)"

        # 2. Add to SignalStore (writes to data/signals.json & state.json)
        updated_signals = signal_store.add(sig)
        new_signal_entry = updated_signals[0]

        # 3. Dispatch to Telegram
        telegram_gateway.format_and_send_signal(new_signal_entry)

        # 4. Play desktop sound chime
        try:
            from server.main import play_system_alert
            play_system_alert(new_signal_entry.get("action", ""))
        except Exception:
            pass

        # 5. Broadcast to WebSocket clients
        if self.broadcast_callback:
            await self.broadcast_callback({
                "event_type": "SIGNAL_TRIGGERED",
                "payload": new_signal_entry
            })
            # Also broadcast updated portfolio & strategies stats
            all_strats = strategy_registry.get_all(sync=False)
            portfolio = strategy_registry.get_portfolio_summary()
            dist = strategy_registry.get_distribution_analytics()
            await self.broadcast_callback({
                "event_type": "STRATEGIES_UPDATED",
                "payload": {
                    "strategies": all_strats,
                    "portfolio_summary": portfolio,
                    "distribution_analytics": dist
                }
            })

        # 6. Asynchronous live broker fill reconciliation (never blocks order dispatch or UI broadcast)
        try:
            broker = broker_registry.get_broker()
            is_paper_b = getattr(broker, "broker_id", "paper") == "paper" if broker else True
            if (
                not is_paper_b
                and new_signal_entry.get("status") in ("ACTIVE_IN_POSITION", "PENDING_LIMIT")
                and (
                    new_signal_entry.get("broker_sync_state") == "PENDING_FILL_SYNC"
                    or (new_signal_entry.get("status") == "ACTIVE_IN_POSITION" and not new_signal_entry.get("broker_position_id"))
                )
            ):
                asyncio.create_task(self._reconcile_entry_fill_async(dict(new_signal_entry)))
        except Exception:
            pass

    async def _reconcile_entry_fill_async(self, sig_entry: Dict[str, Any]) -> None:
        """Asynchronously reconciles authentic broker fill price & position_id after fast order placement."""
        if self._reconcile_in_flight:
            return
        self._reconcile_in_flight = True
        try:
            broker = broker_registry.get_broker()
            if not broker or getattr(broker, "broker_id", "paper") == "paper" or not getattr(broker, "is_connected", False):
                return
            b_order = sig_entry.get("broker_order") or {}
            b_details = b_order.get("details") or []
            first_det = b_details[0] if (b_details and isinstance(b_details, list)) else {}
            ord_id = str(sig_entry.get("broker_order_id") or first_det.get("order_id") or b_order.get("order_id") or "")
            side = str(sig_entry.get("action") or "BUY").upper()
            is_long = side in ("BUY", "LONG")

            rec = None
            for delay in (0.15, 0.45):
                await asyncio.sleep(delay)
                if hasattr(broker, "reconcile_order_fill"):
                    rec = await asyncio.to_thread(broker.reconcile_order_fill, ord_id, self.symbol, side)
                if rec and (rec.get("position_id") or float(rec.get("filled_price") or 0.0) > 0):
                    break

            if not rec:
                return

            updates: Dict[str, Any] = {"broker_sync_state": "CONFIRMED"}
            rec_pid = rec.get("position_id")
            rec_px = float(rec.get("filled_price") or 0.0)
            rec_status = str(rec.get("status") or "").upper()

            if rec_pid:
                updates["broker_position_id"] = str(rec_pid)
            if rec_status == "FILLED" and sig_entry.get("status") == "PENDING_LIMIT":
                now_f = time.time()
                updates["status"] = "ACTIVE_IN_POSITION"
                updates["executed_at"] = now_f
                updates["entry_time_ts"] = now_f
            if rec_px > 0:
                from core.data import get_market_price_precision
                p_prec = get_market_price_precision(self.symbol)
                updates["price"] = rec_px
                updates["entry_price"] = rec_px
                ref_sig_px = float(sig_entry.get("signal_price") or rec_px)
                updates["entry_slippage_pts"] = round((rec_px - ref_sig_px) if is_long else (ref_sig_px - rec_px), p_prec)

            updated = signal_store.update_signal(sig_entry["id"], updates)
            if updated and self.broadcast_callback:
                await self.broadcast_callback({"event_type": "SIGNAL_UPDATED", "payload": updated})
        except Exception as e_rec:
            logger.debug(f"[NativeStrategyRunner] Async entry fill reconcile note: {e_rec}")
        finally:
            self._reconcile_in_flight = False

    async def _reconcile_exit_fill_async(
        self,
        closed_sig: Dict[str, Any],
        expected_close_side: str,
        b_pos_id: Optional[str],
        b_ord_id: Optional[str],
    ) -> None:
        """Asynchronously refines closed trade exit_price & PnL with authentic broker execution fill."""
        try:
            broker = broker_registry.get_broker()
            if not broker or getattr(broker, "broker_id", "paper") == "paper" or not hasattr(broker, "get_latest_position_execution"):
                return
            await asyncio.sleep(0.35)
            exec_data = await asyncio.to_thread(
                broker.get_latest_position_execution,
                b_pos_id,
                b_ord_id,
            )
            if not exec_data or float(exec_data.get("price") or 0.0) <= 0:
                return
            ex_side = str(exec_data.get("side") or "").upper()
            if ex_side and ex_side != expected_close_side:
                return
            real_ex = float(exec_data["price"])
            entry_p = float(closed_sig.get("price") or closed_sig.get("entry_price") or 0.0)
            lots = float(closed_sig.get("lots") or closed_sig.get("lot_size") or 0.01)
            is_long = str(closed_sig.get("action") or "BUY").upper() in ("BUY", "LONG")
            updates: Dict[str, Any] = {"exit_price": real_ex, "broker_sync_state": "CONFIRMED"}
            if entry_p > 0:
                raw_pct = ((real_ex - entry_p) / entry_p * 100.0) if is_long else ((entry_p - real_ex) / entry_p * 100.0)
                updates["pnl_pct"] = round(raw_pct, 2)
                c_val = _resolve_contract_size(self.symbol, entry_p)
                diff = (real_ex - entry_p) if is_long else (entry_p - real_ex)
                updates["pnl_usd"] = round(diff * lots * c_val, 2)
            updated = signal_store.update_signal(closed_sig["id"], updates)
            if updated and self.broadcast_callback:
                await self.broadcast_callback({"event_type": "SIGNAL_UPDATED", "payload": updated})
                logger.info(
                    f"[NativeStrategyRunner] 🎯 Async reconciled authentic broker exit fill for #{closed_sig['id']}: "
                    f"local={closed_sig.get('exit_price')} -> broker={real_ex} (pos_id={b_pos_id})"
                )
        except Exception as e_ex_rec:
            logger.debug(f"[NativeStrategyRunner] Async exit fill reconcile note: {e_ex_rec}")

    async def _on_broker_execution_event(self, event: Dict[str, Any]) -> None:
        """Handles real-time push execution events from WebSocket-capable broker plugins."""
        try:
            if not self.is_running or not isinstance(event, dict):
                return
            ev_type = str(event.get("event_type") or "").upper()
            active_pos = signal_store.get_active(self.strategy_name)
            if not active_pos:
                return

            ev_pos_id = str(event.get("position_id") or "")
            ev_ord_id = str(event.get("order_id") or "")
            pos_bid = str(active_pos.get("broker_position_id") or "")
            pos_oid = str(active_pos.get("broker_order_id") or "")
            matches = (
                (ev_pos_id and pos_bid and ev_pos_id == pos_bid)
                or (ev_ord_id and pos_oid and ev_ord_id == pos_oid)
            )
            if not matches:
                return

            async with self._exit_lock:
                fresh_pos = signal_store.get_active(self.strategy_name)
                if not fresh_pos or fresh_pos.get("id") != active_pos.get("id"):
                    return
                if ev_type == "ORDER_FILLED" and fresh_pos.get("status") == "PENDING_LIMIT":
                    fill_px = float(event.get("price") or fresh_pos.get("price") or 0.0)
                    now_f = time.time()
                    bar_step = int(fresh_pos.get("bar_step_seconds") or getattr(self.provider, "bar_step_seconds", 0) or 0)
                    fill_bar_t = (int(now_f) // bar_step) * bar_step if bar_step > 0 else int(now_f)
                    updates = {
                        "status": "ACTIVE_IN_POSITION",
                        "price": fill_px,
                        "entry_price": fill_px,
                        "time": fill_bar_t,
                        "executed_at": now_f,
                        "entry_time_ts": now_f,
                        "broker_sync_state": "CONFIRMED",
                    }
                    if ev_pos_id:
                        updates["broker_position_id"] = ev_pos_id
                    updated = signal_store.update_signal(fresh_pos["id"], updates)
                    if updated and self.broadcast_callback:
                        await self.broadcast_callback({"event_type": "SIGNAL_UPDATED", "payload": updated})
                elif ev_type in ("POSITION_CLOSED", "ORDER_CANCELLED"):
                    exit_px = float(event.get("price") or 0.0)
                    reason = str(event.get("reason") or ("CANCELLED_ORDER" if ev_type == "ORDER_CANCELLED" else "BROKER_CLOSED"))
                    closed = signal_store.close_position(
                        signal_id=fresh_pos["id"],
                        strategy=self.strategy_name,
                        exit_price=exit_px,
                        exit_reason=reason,
                    )
                    if closed:
                        telegram_gateway.format_and_send_trade_close(closed)
                        if self.broadcast_callback:
                            await self.broadcast_callback({"event_type": "SIGNAL_CLOSED", "payload": closed})
        except Exception as e_ev:
            logger.debug(f"[NativeStrategyRunner] Broker execution event note: {e_ev}")

    async def _evaluate_pending_order(self, pos: Dict[str, Any], current_price: float, quote: Optional[Dict[str, Any]] = None) -> None:
        """
        Tracks a resting PENDING_LIMIT order against real broker truth:
          1. Promotes to ACTIVE_IN_POSITION (with authentic avgPrice & fresh executed_at) once filled.
          2. Enforces `limit_expiry_seconds` by cancelling expired resting orders on the broker (zero orphan GTC orders).
          3. Reconciles if cancelled externally or filled-and-closed between polls.
        """
        if self._exit_lock.locked():
            return
        async with self._exit_lock:
            await self._evaluate_pending_order_locked(pos, current_price, quote=quote)

    async def _evaluate_pending_order_locked(self, pos: Dict[str, Any], current_price: float, quote: Optional[Dict[str, Any]] = None) -> None:
        now_f = time.time()
        now_ts = int(now_f)
        placed_at = int(pos.get("placed_at") or pos.get("executed_at") or pos.get("time") or now_ts)
        elapsed_sec = max(0, now_ts - placed_at)
        expiry_raw = pos.get("limit_expiry_seconds")
        expiry_sec = int(expiry_raw) if (expiry_raw is not None and int(expiry_raw) > 0) else None

        side = str(pos.get("action") or "BUY").upper()
        is_long = side in ("BUY", "LONG")
        limit_px = float(pos.get("price") or pos.get("entry_price") or 0.0)
        sl_px = float(pos.get("stop_loss") or 0.0)
        bid_p = float((quote or {}).get("bid") or current_price)
        ask_p = float((quote or {}).get("ask") or current_price)
        bar_step = int(pos.get("bar_step_seconds") or getattr(self.provider, "bar_step_seconds", 0) or 0) if hasattr(self, "provider") and self.provider else int(pos.get("bar_step_seconds") or 0)

        broker = None
        is_paper_broker = True
        try:
            broker = broker_registry.get_broker()
            is_paper_broker = getattr(broker, "broker_id", "paper") == "paper"
        except Exception:
            pass

        # Paper mode simulated limit fill / SL invalidation / expiry
        if is_paper_broker or not broker or not getattr(broker, "is_connected", False):
            # Invalidate resting limit if SL is breached before limit fills (matches core.simulation)
            sl_breached = (sl_px > 0) and ((bid_p <= sl_px) if is_long else (ask_p >= sl_px))
            if sl_breached:
                closed = signal_store.close_position(signal_id=pos["id"], strategy=self.strategy_name, exit_price=0.0, exit_reason="SL_INVALIDATED_LIMIT")
                if closed and self.broadcast_callback:
                    await self.broadcast_callback({"event_type": "SIGNAL_CLOSED", "payload": closed})
                return
            filled_paper = (limit_px > 0) and ((ask_p <= limit_px) if is_long else (bid_p >= limit_px))
            if filled_paper:
                fill_bar_t = (now_ts // bar_step) * bar_step if bar_step > 0 else now_ts
                updates = {
                    "status": "ACTIVE_IN_POSITION",
                    "price": limit_px,
                    "entry_price": limit_px,
                    "time": fill_bar_t,
                    "executed_at": now_f,
                    "entry_time_ts": now_f,
                }
                pos.update(updates)
                signal_store.update_signal(pos["id"], updates)
                logger.info(f"[NativeStrategyRunner] ✅ Paper PENDING_LIMIT #{pos['id']} filled @ {limit_px}")
                if self.broadcast_callback:
                    await self.broadcast_callback({"event_type": "SIGNAL_UPDATED", "payload": pos})
                return
            if expiry_sec is not None and elapsed_sec >= expiry_sec:
                closed = signal_store.close_position(signal_id=pos["id"], strategy=self.strategy_name, exit_price=0.0, exit_reason="EXPIRED_LIMIT")
                if closed and self.broadcast_callback:
                    await self.broadcast_callback({"event_type": "SIGNAL_CLOSED", "payload": closed})
            return

        # Live broker mode: adaptive poll (1.0s when price crossed limit or past expiry, 3.0s otherwise)
        price_crossed = (limit_px > 0) and ((ask_p <= limit_px) if is_long else (bid_p >= limit_px))
        poll_interval = 1.0 if (price_crossed or (expiry_sec is not None and elapsed_sec >= expiry_sec)) else 3.0
        last_chk = getattr(self, "_last_pending_check_ts", 0.0)
        if (now_f - last_chk) < poll_interval:
            return
        self._last_pending_check_ts = now_f

        from core.data import resolve_market_symbol
        my_canon = resolve_market_symbol(self.symbol)
        broker_order = pos.get("broker_order", {})
        b_details = broker_order.get("details", [])
        first_det = b_details[0] if (b_details and isinstance(b_details, list)) else {}
        b_ord_id = str(pos.get("broker_order_id") or first_det.get("order_id") or broker_order.get("order_id") or "")

        # 1. Check if resting order has filled into an open position on the broker
        try:
            open_positions = await asyncio.to_thread(broker.get_open_positions, self.symbol) if hasattr(broker, "get_open_positions") else None
        except Exception as e_op:
            logger.debug(f"[NativeStrategyRunner] Pending order position check note: {e_op}")
            open_positions = None

        if open_positions is not None:
            pos_matches = [
                bp for bp in open_positions
                if bp.get("symbol") == self.symbol
                or (bp.get("symbol") and resolve_market_symbol(str(bp.get("symbol"))) == my_canon)
            ]
            if pos_matches:
                live_bp = pos_matches[0]
                fill_px = float(live_bp.get("avg_price") or limit_px)
                bp_id = str(live_bp.get("id") or "")
                fill_bar_t = (now_ts // bar_step) * bar_step if bar_step > 0 else now_ts
                updates = {
                    "status": "ACTIVE_IN_POSITION",
                    "price": fill_px,
                    "entry_price": fill_px,
                    "time": fill_bar_t,
                    "broker_position_id": bp_id,
                    "broker_sync_state": "CONFIRMED",
                    "executed_at": now_f,
                    "entry_time_ts": now_f,
                }
                pos.update(updates)
                signal_store.update_signal(pos["id"], updates)
                logger.info(
                    f"[NativeStrategyRunner] ✅ Broker PENDING_LIMIT #{pos['id']} ({self.strategy_name}) "
                    f"FILLED @ {fill_px} (pos_id={bp_id}). Promoted to ACTIVE_IN_POSITION."
                )
                if self.broadcast_callback:
                    await self.broadcast_callback({"event_type": "SIGNAL_UPDATED", "payload": pos})
                return

        # 2. Check resting pending orders on broker
        try:
            pending_orders = await asyncio.to_thread(broker.get_pending_orders, self.symbol) if hasattr(broker, "get_pending_orders") else None
        except Exception as e_po:
            logger.debug(f"[NativeStrategyRunner] Pending orders query note: {e_po}")
            pending_orders = None

        if pending_orders is None:
            return  # API hiccup; wait for next poll instead of assuming order vanished

        ord_matches = [
            o for o in pending_orders
            if (b_ord_id and str(o.get("id") or "") == b_ord_id)
            or (o.get("symbol") and resolve_market_symbol(str(o.get("symbol"))) == my_canon)
        ]

        if ord_matches:
            pos["_pending_missing_confirmations"] = 0
            if expiry_sec is not None and elapsed_sec >= expiry_sec:
                cancel_oid = str(ord_matches[0].get("id") or b_ord_id)
                logger.info(
                    f"[NativeStrategyRunner] ⏱️ Resting LIMIT order #{pos['id']} ({self.strategy_name}, "
                    f"broker_order={cancel_oid}) expired after {elapsed_sec}s >= {expiry_sec}s. Cancelling on broker..."
                )
                cancel_res = await asyncio.to_thread(broker.cancel_order, cancel_oid, self.symbol) if hasattr(broker, "cancel_order") else {"status": "CANCELLED"}
                if cancel_res.get("status") in ("CANCELLED", "NOT_FOUND", "CANCELLED_PREVIEW"):
                    closed = signal_store.close_position(
                        signal_id=pos["id"],
                        strategy=self.strategy_name,
                        exit_price=0.0,
                        exit_reason="EXPIRED_LIMIT",
                    )
                    if closed and self.broadcast_callback:
                        await self.broadcast_callback({"event_type": "SIGNAL_CLOSED", "payload": closed})
                else:
                    logger.warning(f"[NativeStrategyRunner] Failed cancelling expired limit order {cancel_oid}: {cancel_res}")
            return

        # 3. Neither in open positions nor in pending orders -> confirm twice before finalizing
        if open_positions is not None:
            missing = int(pos.get("_pending_missing_confirmations", 0)) + 1
            pos["_pending_missing_confirmations"] = missing
            if missing >= 2:
                exec_data = None
                if b_ord_id and hasattr(broker, "get_latest_position_execution"):
                    try:
                        exec_data = await asyncio.to_thread(broker.get_latest_position_execution, None, b_ord_id)
                    except Exception:
                        pass
                if exec_data and float(exec_data.get("price") or 0.0) > 0:
                    eff_exit = float(exec_data["price"])
                    reason = ("STOP_LOSS" if eff_exit < limit_px else "TAKE_PROFIT") if is_long else ("STOP_LOSS" if eff_exit > limit_px else "TAKE_PROFIT")
                    signal_store.update_signal(pos["id"], {"status": "ACTIVE_IN_POSITION"})
                    closed = signal_store.close_position(signal_id=pos["id"], strategy=self.strategy_name, exit_price=eff_exit, exit_reason=reason)
                else:
                    closed = signal_store.close_position(signal_id=pos["id"], strategy=self.strategy_name, exit_price=0.0, exit_reason="CANCELLED_ORDER")
                if closed and self.broadcast_callback:
                    await self.broadcast_callback({"event_type": "SIGNAL_CLOSED", "payload": closed})

    async def _evaluate_position_exit(self, pos: Dict[str, Any], current_price: float, quote: Optional[Dict[str, Any]] = None) -> None:
        """Monitors active trade against Take Profit, Stop Loss, and Holding Rules with bid/ask spread awareness."""
        if self._exit_lock.locked():
            return
        async with self._exit_lock:
            await self._evaluate_position_exit_locked(pos, current_price, quote=quote)

    async def _evaluate_position_exit_locked(self, pos: Dict[str, Any], current_price: float, quote: Optional[Dict[str, Any]] = None) -> None:
        now_ts = int(time.time())
        # Measure elapsed time strictly from actual order fill execution time, not candle open timestamp
        entry_time = int(pos.get("executed_at") or pos.get("entry_time_ts") or pos.get("time") or now_ts)
        elapsed_sec = max(0, now_ts - entry_time)

        side = pos.get("action", "BUY").upper()
        is_long = side in ("BUY", "LONG")
        entry_price = float(pos.get("price") or pos.get("entry_price") or current_price)
        tp = float(pos.get("take_profit") or 0.0)
        sl = float(pos.get("stop_loss") or 0.0)

        # Spread-Aware Market Price:
        # A LONG closes at the BID price (selling into the bid).
        # A SHORT closes at the ASK price (buying back at the ask).
        bid_price = float(quote.get("bid") or 0.0) if quote else 0.0
        ask_price = float(quote.get("ask") or 0.0) if quote else 0.0
        if bid_price <= 0: bid_price = current_price
        if ask_price <= 0: ask_price = current_price

        eval_exit_price = bid_price if is_long else ask_price

        # Holding constraints (strictly from signal payload or StrategyContract SSOT, zero hidden 10s fallback)
        min_hold_raw = pos.get("min_hold_seconds")
        min_hold = int(min_hold_raw) if (min_hold_raw is not None and int(min_hold_raw) > 0) else 0
        max_hold_raw = pos.get("max_hold_seconds")
        max_hold = int(max_hold_raw) if (max_hold_raw is not None and max_hold_raw != 0) else None

        strat_inst = self._get_strategy_instance()

        # Trailing stop configuration: strictly from StrategyContract SSOT (False unless strategy opts in)
        from core.execution_engine import StrategyContract
        contract = StrategyContract.from_strategy(strat_inst)
        use_trailing = pos.get("trailing_stop")
        if use_trailing is None:
            use_trailing = contract.trailing_stop

        trail_offset = float(pos.get("trailing_offset") or contract.trailing_stop_positive_offset)
        trail_buffer = float(pos.get("trailing_buffer") or contract.trailing_stop_positive)

        highest_price = float(pos.get("highest_price") or entry_price)
        lowest_price = float(pos.get("lowest_price") or entry_price)

        new_sl = None
        from core.data import get_market_price_precision, resolve_market_symbol
        price_prec = get_market_price_precision(self.symbol)

        if is_long:
            if bid_price > highest_price:
                pos["highest_price"] = bid_price
                highest_price = bid_price
            gain_pct = (highest_price - entry_price) / entry_price
            if use_trailing and gain_pct >= trail_offset:
                candidate_sl = round(highest_price * (1.0 - trail_buffer), price_prec)
                if candidate_sl > sl:
                    new_sl = candidate_sl
        else:
            if ask_price < lowest_price:
                pos["lowest_price"] = ask_price
                lowest_price = ask_price
            gain_pct = (entry_price - lowest_price) / entry_price
            if use_trailing and gain_pct >= trail_offset:
                candidate_sl = round(lowest_price * (1.0 + trail_buffer), price_prec)
                if sl == 0.0 or candidate_sl < sl:
                    new_sl = candidate_sl

        # Dynamic Structural SL Ratchet: evaluate at most once per newly closed bar (never on every tick)
        if strat_inst and hasattr(self, "provider") and self.provider and self._supports_structural_sl is not False:
            try:
                calc_fn = getattr(strat_inst, "compute_indicators", getattr(strat_inst, "populate_indicators", None))
                if calc_fn and callable(calc_fn):
                    candles = self.provider.get_candles(count=50)
                    if candles:
                        latest_bar_ts = int(candles[-1].get("timestamp") or candles[-1].get("time") or 0)
                        if latest_bar_ts != self._last_struct_sl_bar_ts:
                            self._last_struct_sl_bar_ts = latest_bar_ts
                            df_c = pd.DataFrame(candles)
                            if "time" in df_c.columns:
                                df_c["dt"] = pd.to_datetime(df_c["time"], unit="s", utc=True)
                            elif "timestamp" in df_c.columns:
                                df_c["dt"] = pd.to_datetime(df_c["timestamp"], unit="s", utc=True)
                            else:
                                df_c["dt"] = pd.to_datetime(df_c.index, utc=True)
                            df_c = df_c.set_index("dt")
                            df_c = calc_fn(df_c)
                            has_struct = ("structural_sl_long" in df_c.columns) or ("structural_sl_short" in df_c.columns)
                            self._supports_structural_sl = has_struct
                            if has_struct:
                                last_c = df_c.iloc[-1]
                                if is_long:
                                    struct_sl = float(last_c.get("structural_sl_long", 0.0))
                                    if struct_sl > 0 and struct_sl > sl and struct_sl < bid_price:
                                        new_sl = max(new_sl or sl, round(struct_sl, price_prec))
                                else:
                                    struct_sl = float(last_c.get("structural_sl_short", 0.0))
                                    if struct_sl > 0 and (sl == 0.0 or struct_sl < sl) and struct_sl > ask_price:
                                        new_sl = min(new_sl or sl, round(struct_sl, price_prec))
            except Exception as e_struct:
                logger.debug(f"[NativeStrategyRunner] Structural SL ratchet error: {e_struct}")

        if new_sl and new_sl != sl:
            pos["stop_loss"] = new_sl
            sl = new_sl
            signal_store.update_signal(pos["id"], {
                "stop_loss": new_sl,
                "highest_price": highest_price,
                "lowest_price": lowest_price
            })
            if self.broadcast_callback:
                await self.broadcast_callback({
                    "event_type": "SIGNAL_UPDATED",
                    "payload": pos
                })
            asyncio.create_task(self._sync_broker_sl(pos, new_sl))


        exit_reason: Optional[str] = None
        reconciled_exit_price: Optional[float] = None
        broker_already_closed = False

        broker = None
        is_paper_broker = True
        try:
            broker = broker_registry.get_broker()
            is_paper_broker = getattr(broker, "broker_id", "paper") == "paper" if broker else True
        except Exception:
            pass

        is_live_connected = bool(broker and getattr(broker, "is_connected", False) and not is_paper_broker)
        has_server_brackets = bool(
            is_live_connected
            and getattr(broker, "supports_server_side_brackets", False)
            and (sl > 0 or tp > 0)
        )

        sl_crossed = (sl > 0) and ((eval_exit_price <= sl) if is_long else (eval_exit_price >= sl))
        tp_crossed = (tp > 0) and ((eval_exit_price >= tp) if is_long else (eval_exit_price <= tp)) and (elapsed_sec >= min_hold)
        live_spread = abs(ask_price - bid_price) if (ask_price > bid_price > 0) else 0.0

        # 1. Broker Server-Side Execution Reconciliation (Priority 1 if connected):
        # Fast adaptive polling (1.5s when price crossed SL/TP, 4.0s otherwise), starting at 2s after entry.
        if is_live_connected and elapsed_sec >= 2 and hasattr(broker, "get_open_positions"):
            now_f = time.time()
            poll_interval = 1.5 if (sl_crossed or tp_crossed) else 4.0
            last_reconcile = float(getattr(self, "_last_broker_reconcile_ts", 0.0))
            if (now_f - last_reconcile) >= poll_interval:
                self._last_broker_reconcile_ts = now_f
                try:
                    broker_positions = await asyncio.to_thread(broker.get_open_positions, self.symbol)
                    if broker_positions is not None:
                        my_canon = resolve_market_symbol(self.symbol)
                        matches = [
                            bp for bp in broker_positions
                            if bp.get("symbol") == self.symbol
                            or (bp.get("symbol") and resolve_market_symbol(str(bp.get("symbol"))) == my_canon)
                        ]
                        if len(matches) == 0:
                            empty_count = int(pos.get("_broker_empty_confirmations", 0)) + 1
                            pos["_broker_empty_confirmations"] = empty_count
                            required_confirmations = 1 if (sl_crossed or tp_crossed) else 2
                            if empty_count >= required_confirmations:
                                broker_already_closed = True
                                logger.info(f"[NativeStrategyRunner] 🛡️ Confirmed: Broker server closed position #{pos['id']} ({pos['strategy']}). Reconciling authentic broker execution!")
                                broker_order = pos.get("broker_order", {})
                                b_details = broker_order.get("details", [])
                                first_det = b_details[0] if (b_details and isinstance(b_details, list)) else {}
                                b_ord_id = first_det.get("order_id") or broker_order.get("order_id")
                                b_pos_id = pos.get("broker_position_id") or first_det.get("position_id") or pos.get("position_id")

                                exec_data = None
                                if hasattr(broker, "get_latest_position_execution"):
                                    exec_data = await asyncio.to_thread(
                                        broker.get_latest_position_execution,
                                        b_pos_id,
                                        b_ord_id,
                                    )

                                expected_close_s = "SELL" if is_long else "BUY"
                                if exec_data and float(exec_data.get("price") or 0.0) > 0:
                                    ex_s = str(exec_data.get("side") or "").upper()
                                    if not ex_s or ex_s == expected_close_s:
                                        reconciled_exit_price = float(exec_data["price"])
                                        logger.info(f"[NativeStrategyRunner] 🎯 Matched broker execution fill price: {reconciled_exit_price} (order: {b_ord_id}, position: {b_pos_id})")

                                eff_exit_price = reconciled_exit_price or eval_exit_price
                                if is_long:
                                    exit_reason = "STOP_LOSS" if eff_exit_price < entry_price else "TAKE_PROFIT"
                                else:
                                    exit_reason = "STOP_LOSS" if eff_exit_price > entry_price else "TAKE_PROFIT"
                        else:
                            pos["_broker_empty_confirmations"] = 0
                            # Synchronize authentic broker entry avg_price & position_id if internal record drifted
                            live_bp = matches[0]
                            bp_avg = float(live_bp.get("avg_price") or 0.0)
                            bp_id = str(live_bp.get("id") or "")
                            sync_updates: Dict[str, Any] = {}
                            if bp_id and not pos.get("broker_position_id"):
                                pos["broker_position_id"] = bp_id
                                sync_updates["broker_position_id"] = bp_id
                            if bp_avg > 0 and abs(bp_avg - entry_price) > (10.0 ** (-price_prec)):
                                if not pos.get("signal_price"):
                                    pos["signal_price"] = entry_price
                                    sync_updates["signal_price"] = entry_price
                                pos["price"] = bp_avg
                                pos["entry_price"] = bp_avg
                                entry_price = bp_avg
                                sync_updates["price"] = bp_avg
                                sync_updates["entry_price"] = bp_avg
                                sig_px = float(pos.get("signal_price") or bp_avg)
                                sync_updates["entry_slippage_pts"] = round(
                                    (bp_avg - sig_px) if is_long else (sig_px - bp_avg), price_prec
                                )
                                logger.info(
                                    f"[NativeStrategyRunner] 🔄 Reconciled live broker entry price for #{pos['id']}: "
                                    f"{sig_px:.{price_prec}f} -> {bp_avg:.{price_prec}f} (pos_id={bp_id})"
                                )
                            if sync_updates:
                                signal_store.update_signal(pos["id"], sync_updates)
                except Exception as e_rec:
                    logger.debug(f"[NativeStrategyRunner] Broker reconciliation check note: {e_rec}")

        # 2. Stop Loss / Trailing Stop / Take Profit evaluation
        # When broker enforces server-side SL/TP brackets natively, defer normal SL/TP execution
        # to the broker to avoid double-close races, while keeping an Emergency SL Safety Backstop
        # if price blows past SL and the broker still reports the position open.
        if not exit_reason:
            if has_server_brackets:
                if sl_crossed and elapsed_sec >= 5:
                    sl_dist = abs(entry_price - sl)
                    backstop_tol = max(live_spread * 2.0, sl_dist * 0.05)
                    breach = (sl - eval_exit_price) if is_long else (eval_exit_price - sl)
                    if breach > backstop_tol:
                        exit_reason = "STOP_LOSS_BACKSTOP"
                        logger.warning(
                            f"[NativeStrategyRunner] 🚨 Emergency SL Backstop triggered for #{pos['id']}: "
                            f"eval={eval_exit_price}, SL={sl}, breach={breach:.{price_prec}f} > tol={backstop_tol:.{price_prec}f}"
                        )
            else:
                if sl_crossed:
                    exit_reason = "TRAIL_STOP" if ((is_long and sl > entry_price) or (not is_long and sl < entry_price)) else "STOP_LOSS"
                elif tp_crossed:
                    exit_reason = "TAKE_PROFIT"

        # 3. Broker-unaware exits: Maximum holding duration & Strategy-declared EOD close
        if not exit_reason:
            if max_hold is not None and elapsed_sec >= max_hold:
                exit_reason = "TIME_CUTOFF"
            elif contract.close_eod:
                now_utc = datetime.now(timezone.utc)
                if now_utc.hour >= contract.eod_close_hour_utc:
                    exit_reason = "EOD"

        if exit_reason:
            final_exit_price = reconciled_exit_price if reconciled_exit_price is not None else eval_exit_price
            expected_close_side = "SELL" if is_long else "BUY"

            broker_order = pos.get("broker_order", {})
            b_details = broker_order.get("details", [])
            first_det = b_details[0] if (b_details and isinstance(b_details, list)) else {}
            b_ord_id = first_det.get("order_id") or broker_order.get("order_id")
            b_pos_id = pos.get("broker_position_id") or first_det.get("position_id") or pos.get("position_id")

            # Route exit through Active Execution Broker (skip if broker already closed server-side)
            if not broker_already_closed and broker:
                try:
                    broker_pos_or_ord = b_pos_id or b_ord_id or str(pos.get("id"))
                    await asyncio.to_thread(
                        broker.close_position,
                        broker_pos_or_ord,
                        exit_reason,
                        final_exit_price,
                        self.symbol,
                    )
                except Exception as e_broker_close:
                    logger.error(f"[NativeStrategyRunner] Error closing position on broker: {e_broker_close}")

            logger.info(f"[NativeStrategyRunner] 🏁 Closing position #{pos['id']} ({pos['strategy']}): {exit_reason} @ {final_exit_price}")

            closed = signal_store.close_position(
                signal_id=pos["id"],
                strategy=self.strategy_name,
                exit_price=final_exit_price,
                exit_reason=exit_reason
            )
            if closed:
                # Dispatch Telegram alert for closed trade
                telegram_gateway.format_and_send_trade_close(closed)

                # Broadcast to UI immediately (two-phase: refine exit fill asynchronously on live brokers)
                if self.broadcast_callback:
                    await self.broadcast_callback({"event_type": "SIGNAL_CLOSED", "payload": closed})
                    all_strats = strategy_registry.get_all(sync=False)
                    portfolio = strategy_registry.get_portfolio_summary()
                    dist = strategy_registry.get_distribution_analytics()
                    await self.broadcast_callback({
                        "event_type": "STRATEGIES_UPDATED",
                        "payload": {
                            "strategies": all_strats,
                            "portfolio_summary": portfolio,
                            "distribution_analytics": dist
                        }
                    })

                if reconciled_exit_price is None and is_live_connected and hasattr(broker, "get_latest_position_execution"):
                    asyncio.create_task(
                        self._reconcile_exit_fill_async(dict(closed), expected_close_side, b_pos_id, b_ord_id)
                    )

    async def _sync_broker_sl(self, pos: Dict[str, Any], new_sl: float) -> None:
        """Propagates updated Trailing Stop Loss to the live execution broker server."""
        try:
            broker = broker_registry.get_broker()
            if broker and hasattr(broker, "modify_position"):
                broker_order_id = (
                    pos.get("broker_position_id")
                    or pos.get("broker_order", {}).get("order_id")
                    or str(pos.get("id"))
                )
                loop = asyncio.get_running_loop()
                res = await loop.run_in_executor(
                    None,
                    lambda: broker.modify_position(
                        position_id=broker_order_id,
                        stop_loss=new_sl,
                        symbol=self.symbol
                    )
                )
                # If broker reports position was NOT_FOUND and position has been open > 25s:
                if res and res.get("status") in ("NOT_FOUND", "PARTIAL") and res.get("modified_count", 0) == 0:
                    details = res.get("details", [])
                    if details and all(d.get("status") == "NOT_FOUND" for d in details):
                        now_ts = int(time.time())
                        if (now_ts - int(pos.get("time") or now_ts)) >= 25:
                            logger.info(f"[NativeStrategyRunner] 🛡️ Broker reported position #{pos['id']} NOT_FOUND during SL ratchet. Position was executed/closed on broker server.")
                            side = pos.get("action", "BUY").upper()
                            is_long = side in ("BUY", "LONG")
                            entry_p = float(pos.get("price") or pos.get("entry_price") or 0.0)
                            r_exit = "STOP_LOSS" if (is_long and new_sl <= entry_p) or (not is_long and new_sl >= entry_p) else "TRAIL_STOP"
                            closed = signal_store.close_position(
                                signal_id=pos["id"],
                                strategy=self.strategy_name,
                                exit_price=new_sl,
                                exit_reason=r_exit
                            )
                            if closed:
                                telegram_gateway.format_and_send_trade_close(closed)
                                if self.broadcast_callback:
                                    await self.broadcast_callback({"event_type": "SIGNAL_CLOSED", "payload": closed})
                                    all_strats = strategy_registry.get_all(sync=False)
                                    portfolio = strategy_registry.get_portfolio_summary()
                                    dist = strategy_registry.get_distribution_analytics()
                                    await self.broadcast_callback({
                                        "event_type": "STRATEGIES_UPDATED",
                                        "payload": {"strategies": all_strats, "portfolio_summary": portfolio, "distribution_analytics": dist}
                                    })
                            return
            signal_store.save()
            logger.info(f"[NativeStrategyRunner] 🛡️ Trailing Stop ratcheted to {new_sl} for #{pos['id']} ({self.symbol}). Broker synced.")
        except Exception as e_mod:
            logger.warning(f"[NativeStrategyRunner] Failed to sync trailed SL {new_sl} to broker: {e_mod}")




