"""
tests/test_realtime_execution_parity.py
─────────────────────────────────────────────────────────────
Regression tests for real-time execution speed, safety interlocks,
and Backtest ↔ Live Single Source of Truth parity across all universal
brokers (Paper and custom broker plugins).
"""

import asyncio
import json
import os
import sys
import time
import types
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from core.execution_engine import StrategyContract, evaluate_bar_exit
from core.simulation import run_discrete_simulation
from server.brokers.base import BaseExecutionBroker
from server.brokers.paper import PaperExecutionBroker
from server.providers.base import BaseMarketDataProvider
from server.services.strategy_executor import NativeStrategyRunner, StrategyEvaluator
from server.services.strategy_loader import load_strategy_instance
from server.state.state_manager import SignalStore, StrategyRegistry

from _feed_stubs import live_feeds_stubbed


def _make_candles(n: int = 40, start_ts: int = 1_700_000_000, step: int = 300, base: float = 3500.0):
    out = []
    for i in range(n):
        ts = start_ts + i * step
        p = base + i * 0.5
        out.append({
            "time": ts,
            "timestamp": ts,
            "open": p,
            "high": p + 1.5,
            "low": p - 1.5,
            "close": p + 0.4,
            "volume": 100.0 + i,
        })
    return out


def test_min_hold_bars_ssot_parity():
    """Backtest & Live share StrategyContract.min_hold_bars; None allows immediate TP, SL never blocked."""
    class _NoMinHold:
        pass

    class _ExplicitMinHold:
        min_hold_bars = 2

    c_default = StrategyContract.from_strategy(_NoMinHold())
    assert c_default.min_hold_bars is None

    c_explicit = StrategyContract.from_strategy(_ExplicitMinHold())
    assert c_explicit.min_hold_bars == 2

    # Immediate TP triggers when min_hold_bars is None
    dec = evaluate_bar_exit(
        direction=1, stop_loss=95.0, target=105.0, bars_held=1,
        bar_high=106.0, bar_low=99.0, bar_close=104.0, bar_time=None,
        min_hold_bars=c_default.min_hold_bars,
    )
    assert dec is not None and dec.exit_reason == "TP"

    # TP is blocked before min_hold_bars=2, but SL always fires immediately
    dec_blocked = evaluate_bar_exit(
        direction=1, stop_loss=95.0, target=105.0, bars_held=1,
        bar_high=106.0, bar_low=99.0, bar_close=104.0, bar_time=None,
        min_hold_bars=c_explicit.min_hold_bars,
    )
    assert dec_blocked is None

    dec_sl = evaluate_bar_exit(
        direction=1, stop_loss=95.0, target=105.0, bars_held=1,
        bar_high=106.0, bar_low=94.0, bar_close=94.5, bar_time=None,
        min_hold_bars=c_explicit.min_hold_bars,
    )
    assert dec_sl is not None and dec_sl.exit_reason == "SL"

    # Discrete simulation honors min_hold_bars identically
    times = pd.date_range("2026-11-01 10:00", periods=6, freq="5min", tz="UTC")
    df = pd.DataFrame({
        "open": [100.0] * 6,
        "high": [101.0, 106.0, 101.0, 106.0, 101.0, 101.0],
        "low": [99.0] * 6,
        "close": [100.5] * 6,
    }, index=times)
    sigs = pd.DataFrame({
        "entry_signal": [1, 0, 0, 0, 0, 0],
        "stop_loss": [95.0] * 6,
        "target": [105.0] * 6,
    }, index=times)
    res_no_hold = run_discrete_simulation(df, sigs, symbol="OANDA:XAUUSD", min_hold_bars=None)
    res_hold_2 = run_discrete_simulation(df, sigs, symbol="OANDA:XAUUSD", min_hold_bars=2)
    assert res_no_hold["trades"][0].bars_held == 1
    assert res_hold_2["trades"][0].bars_held == 3


def test_strategy_evaluator_canonical_bar_close_timestamp_and_min_hold():
    """Live signal timestamp equals bar_open + bar_step (matching backtest entry_time) with zero phantom min_hold."""
    candles = _make_candles(n=35, start_ts=1_700_000_000, step=300)
    last_bar_open = candles[-1]["time"]

    class _DummyStrat:
        can_short = True
        risk_pct_1r = 0.005

        def generate_signals(self, df):
            out = df.copy()
            out["entry_signal"] = 0
            out["stop_loss"] = 0.0
            out["target"] = 0.0
            out["atr"] = 2.0
            c = float(out["close"].iloc[-1])
            out.iloc[-1, out.columns.get_loc("entry_signal")] = 1
            out.iloc[-1, out.columns.get_loc("stop_loss")] = c - 5.0
            out.iloc[-1, out.columns.get_loc("target")] = c + 10.0
            return out

    sig = StrategyEvaluator.evaluate(
        "DummyStrat", "XAU/USD", candles, strat_inst=_DummyStrat(), prefetched_equity=5000.0
    )
    assert sig is not None
    assert sig["signal_bar_time"] == last_bar_open
    assert sig["signal_bar_close_ts"] == last_bar_open + 300
    assert sig["time"] == last_bar_open + 300
    assert sig["min_hold_seconds"] == 0


def test_paper_broker_limit_order_lifecycle(tmp_path):
    """PaperExecutionBroker rests LIMIT orders when not yet touched and fills when crossed."""
    paper = PaperExecutionBroker()

    # Non-crossing BUY LIMIT -> PENDING_ORDER
    pending_res = paper.execute_order({
        "id": 101,
        "strategy": "LimTest",
        "symbol": "XAU/USD",
        "action": "BUY",
        "order_type": "LIMIT",
        "price": 3500.0,
        "market_price": 3505.0,
        "lots": 0.1,
    })
    assert pending_res["status"] == "PENDING_ORDER"

    # Immediately marketable BUY LIMIT -> FILLED at limit or better
    fill_res = paper.execute_order({
        "id": 102,
        "strategy": "LimTest",
        "symbol": "XAU/USD",
        "action": "BUY",
        "order_type": "LIMIT",
        "price": 3505.0,
        "market_price": 3504.0,
        "lots": 0.1,
    })
    assert fill_res["status"] == "FILLED"
    assert fill_res["filled_price"] == 3504.0

    # Cancel hook works cleanly
    assert paper.cancel_order("paper_lim_101", "XAU/USD")["status"] == "CANCELLED"

    # NativeStrategyRunner paper pending order fills on cross and aligns time to fill bar
    tmp_sig_file = str(tmp_path / "signals.json")
    store = SignalStore(path=tmp_sig_file)
    with live_feeds_stubbed(), \
         patch("server.services.strategy_executor.signal_store", store), \
         patch("server.services.strategy_executor.broker_registry") as mock_reg:
        mock_reg.get_broker.return_value = paper
        runner = NativeStrategyRunner("DummyLimStrat")
        pos = {
            "id": 1,
            "strategy": "DummyLimStrat",
            "pair": "XAU/USD",
            "action": "BUY",
            "status": "PENDING_LIMIT",
            "price": 3500.0,
            "entry_price": 3500.0,
            "stop_loss": 3490.0,
            "take_profit": 3520.0,
            "bar_step_seconds": 300,
            "limit_expiry_seconds": 900,
            "placed_at": int(time.time()) - 10,
        }
        store.add(pos)
        # First tick breaches SL? No, above limit -> stays pending
        asyncio.run(runner._evaluate_pending_order(pos, 3503.0, quote={"bid": 3502.8, "ask": 3503.0}))
        assert store.get_active("DummyLimStrat")["status"] == "PENDING_LIMIT"

        # Second tick crosses limit ask <= 3500 -> promoted to ACTIVE_IN_POSITION
        asyncio.run(runner._evaluate_pending_order(pos, 3499.5, quote={"bid": 3499.3, "ask": 3499.5}))
        active = store.get_active("DummyLimStrat")
        assert active["status"] == "ACTIVE_IN_POSITION"
        assert active["time"] % 300 == 0


def test_parallel_bar_fanout_does_not_block_sibling():
    """Slow subscriber on BaseMarketDataProvider must not delay sibling subscribers."""
    class _StubProvider(BaseMarketDataProvider):
        async def start(self): self.is_running = True
        async def stop(self): self.is_running = False

    prov = _StubProvider("XAU/USD", "5m")
    finish_times = {}

    async def slow_cb(_bar):
        await asyncio.sleep(0.25)
        finish_times["slow"] = time.monotonic()

    async def fast_cb(_bar):
        await asyncio.sleep(0.01)
        finish_times["fast"] = time.monotonic()

    prov.subscribe_bar(slow_cb)
    prov.subscribe_bar(fast_cb)

    t0 = time.monotonic()
    asyncio.run(prov._notify_bar({"time": 1_700_000_000, "close": 3500.0}))
    assert (finish_times["fast"] - t0) < 0.12
    assert finish_times["fast"] < finish_times["slow"]


def test_runner_single_snapshot_and_no_gold_sleep(tmp_path):
    """_on_market_bar evaluates XAU/USD without sleeping 1.2s and fetches broker snapshot once."""
    class _CountingLiveBroker(BaseExecutionBroker):
        def __init__(self):
            super().__init__("mock_fast", "Mock Fast")
            self.is_connected = True
            self.acct_calls = 0
            self.pos_calls = 0
            self.exec_calls = 0

        def connect(self, config=None): return True
        def disconnect(self): pass
        def get_account_info(self):
            self.acct_calls += 1
            return {"balance": 10000.0, "equity": 10000.0, "connected": True}
        def get_cached_account_info(self, max_age=15.0):
            return self.get_account_info()
        def get_open_positions(self, symbol=None):
            self.pos_calls += 1
            return []
        def get_cached_open_positions(self, symbol=None, max_age=5.0):
            return self.get_open_positions(symbol=symbol)
        def get_latest_quote(self, symbol, max_age=1.5):
            return {"symbol": symbol, "price": 3517.4, "bid": 3517.3, "ask": 3517.5, "timestamp": int(time.time())}
        def execute_order(self, signal):
            self.exec_calls += 1
            return {"status": "FILLED", "order_id": "ord-1", "position_id": "pos-1", "filled_price": 3517.5, "filled_lots": 0.1}
        def close_position(self, position_id, reason="MANUAL", current_price=None, symbol=None):
            return {"status": "CLOSED"}

    class _DummyStrat:
        can_short = True
        risk_pct_1r = 0.005

        def generate_signals(self, df):
            out = df.copy()
            out["entry_signal"] = 0
            out["stop_loss"] = 0.0
            out["target"] = 0.0
            out["atr"] = 2.0
            c = float(out["close"].iloc[-1])
            out.iloc[-1, out.columns.get_loc("entry_signal")] = 1
            out.iloc[-1, out.columns.get_loc("stop_loss")] = c - 5.0
            out.iloc[-1, out.columns.get_loc("target")] = c + 10.0
            return out

    broker = _CountingLiveBroker()
    candles = _make_candles(n=35, start_ts=1_700_000_000, step=300)
    store = SignalStore(path=str(tmp_path / "signals.json"))

    with live_feeds_stubbed(), \
         patch("server.services.strategy_executor.signal_store", store), \
         patch("server.services.strategy_executor.broker_registry") as mock_reg, \
         patch("server.services.strategy_executor.strategy_registry") as mock_sreg, \
         patch("server.services.strategy_executor.telegram_gateway"), \
         patch("server.backtest_engine.load_strategy_instance", return_value=_DummyStrat()):
        mock_reg.get_broker.return_value = broker
        mock_sreg.get.return_value = {"name": "GoldFastTest", "status": "ACTIVE_LIVE"}
        mock_sreg.get_status.return_value = "ACTIVE_LIVE"
        mock_sreg.get_all.return_value = []
        mock_sreg.get_portfolio_summary.return_value = {}
        mock_sreg.get_distribution_analytics.return_value = {}

        runner = NativeStrategyRunner("GoldFastTest")
        runner.symbol = "XAU/USD"
        runner.timeframe = "5m"
        runner.is_running = True
        runner.provider._candles = candles
        runner.provider._latest_quote = {"symbol": "XAU/USD", "price": 3517.4, "bid": 3517.3, "ask": 3517.5, "timestamp": int(time.time())}

        t0 = time.monotonic()
        asyncio.run(runner._on_market_bar(candles[-1]))
        elapsed = time.monotonic() - t0

    assert elapsed < 0.5, f"Gold bar evaluation took {elapsed:.2f}s (expected <0.5s with zero sleep)"
    assert broker.acct_calls == 1
    assert broker.pos_calls == 1
    assert broker.exec_calls == 1


def test_server_bracket_reconciliation_and_emergency_backstop(tmp_path):
    """Fail-closed on None; 1-confirm fast close when SL/TP crossed; emergency backstop when broker lags."""
    class _BracketBroker(BaseExecutionBroker):
        def __init__(self):
            super().__init__("bracket_live", "Bracket Live")
            self.is_connected = True
            self.positions_return = [{"id": "999001", "symbol": "XAU/USD", "avg_price": 3500.0}]
            self.close_calls = 0

        @property
        def supports_server_side_brackets(self): return True
        def connect(self, config=None): return True
        def disconnect(self): pass
        def get_account_info(self): return {"balance": 10000.0, "equity": 10000.0}
        def execute_order(self, signal): return {"status": "FILLED"}
        def close_position(self, position_id, reason="MANUAL", current_price=None, symbol=None):
            self.close_calls += 1
            return {"status": "CLOSED", "position_id": position_id}
        def get_open_positions(self, symbol=None):
            return self.positions_return

    broker = _BracketBroker()
    store = SignalStore(path=str(tmp_path / "signals.json"))

    with live_feeds_stubbed(), \
         patch("server.services.strategy_executor.signal_store", store), \
         patch("server.services.strategy_executor.broker_registry") as mock_reg, \
         patch("server.services.strategy_executor.strategy_registry") as mock_sreg, \
         patch("server.services.strategy_executor.telegram_gateway"):
        mock_reg.get_broker.return_value = broker
        mock_sreg.get_all.return_value = []
        mock_sreg.get_portfolio_summary.return_value = {}
        mock_sreg.get_distribution_analytics.return_value = {}

        runner = NativeStrategyRunner("BracketStrat")
        runner.symbol = "XAU/USD"
        pos = {
            "id": 1,
            "strategy": "BracketStrat",
            "pair": "XAU/USD",
            "action": "BUY",
            "status": "ACTIVE_IN_POSITION",
            "price": 3500.0,
            "entry_price": 3500.0,
            "stop_loss": 3495.0,
            "take_profit": 3510.0,
            "broker_position_id": "999001",
            "executed_at": int(time.time()) - 10,
            "min_hold_seconds": 0,
        }
        store.add(pos)

        # 1. API failure (None) must NEVER falsely assume broker_already_closed even when price crosses SL/TP
        broker.positions_return = None
        asyncio.run(runner._evaluate_position_exit(pos, 3494.9, quote={"bid": 3494.9, "ask": 3495.1}))
        assert store.get_active("BracketStrat") is not None
        assert broker.close_calls == 0

        # 2. Normal SL touch while broker still open (within backstop tolerance) defers to server-side bracket
        runner._last_broker_reconcile_ts = 0.0
        broker.positions_return = [{"id": "999001", "symbol": "XAU/USD", "avg_price": 3500.0}]
        asyncio.run(runner._evaluate_position_exit(pos, 3494.9, quote={"bid": 3494.9, "ask": 3495.1}))
        assert store.get_active("BracketStrat") is not None
        assert broker.close_calls == 0

        # 3. Severe SL breach beyond backstop tolerance -> Emergency Backstop actively closes
        runner._last_broker_reconcile_ts = 0.0
        asyncio.run(runner._evaluate_position_exit(pos, 3493.0, quote={"bid": 3493.0, "ask": 3493.2}))
        assert broker.close_calls == 1
        assert store.get_active("BracketStrat") is None
        assert store.get_all()[0]["exit_reason"] == "STOP_LOSS_BACKSTOP"

        # 4. Re-open and test 1-confirmation fast close when server already closed on TP
        pos2 = dict(pos, id=2, executed_at=int(time.time()) - 10)
        store.add(pos2)
        runner._last_broker_reconcile_ts = 0.0
        broker.close_calls = 0
        broker.positions_return = []
        asyncio.run(runner._evaluate_position_exit(pos2, 3510.5, quote={"bid": 3510.5, "ask": 3510.7}))
        assert broker.close_calls == 0  # already closed server-side
        assert store.get_active("BracketStrat") is None
        assert store.get_all()[0]["exit_reason"] == "TAKE_PROFIT"


def test_tradingview_provider_quote_timestamp_is_wall_clock():
    """TradingViewMarketDataProvider stamps quote timestamp with wall-clock time, not bar open."""
    from server.providers.tradingview_provider import TradingViewMarketDataProvider

    old_bar_open = int(time.time()) - 240
    du_payload = json.dumps({"m": "du", "p": ["cs_x", {"s1": {"s": [{"v": [old_bar_open, 3500.0, 3501.0, 3499.0, 3500.5, 42.0]}]}}]})
    du_frame = f"~m~{len(du_payload)}~m~{du_payload}"

    class _FakeWS:
        def __init__(self):
            self._calls = 0
        def send(self, _msg): pass
        def recv(self):
            self._calls += 1
            if self._calls == 1:
                return du_frame
            return ""
        def close(self): pass

    with live_feeds_stubbed(), \
         patch("websocket.create_connection", return_value=_FakeWS()):
        prov = TradingViewMarketDataProvider("XAU/USD", "5m")

        async def _run_once():
            prov.is_running = True
            task = asyncio.create_task(prov._stream_loop())
            await asyncio.sleep(0.05)
            prov.is_running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(_run_once())
        q = prov.get_latest_quote()
        assert q["candle"]["time"] == old_bar_open
        assert abs(time.time() - q["timestamp"]) < 5.0


def test_state_manager_and_strategy_loader_cache_coherency(tmp_path):
    """SignalStore JSON cache detects external atomic writes; StrategyLoader reloads on file edit."""
    sig_path = str(tmp_path / "signals.json")
    store = SignalStore(path=sig_path)
    assert store.get_all() == []

    # External writer uses atomic replace
    tmp_ext = str(tmp_path / "signals.json.ext")
    with open(tmp_ext, "w") as f:
        json.dump([{"id": 99, "strategy": "Ext", "status": "CLOSED"}], f)
    os.replace(tmp_ext, sig_path)
    assert store.get_all()[0]["id"] == 99

    # Returned objects are isolated copies
    got = store.get_all()
    got[0]["status"] = "MUTATED"
    assert store.get_all()[0]["status"] == "CLOSED"

    # StrategyLoader caches class and reloads when file changes
    strat_dir = tmp_path / "strategies"
    strat_dir.mkdir()
    strat_file = strat_dir / "TmpCacheStrat.py"
    strat_file.write_text(
        "class TmpCacheStrat:\n"
        "    val = 1\n"
        "    def generate_signals(self, df): return df\n"
    )
    with patch("server.services.strategy_loader._ROOT", str(tmp_path)):
        s1 = load_strategy_instance("TmpCacheStrat")
        s2 = load_strategy_instance("TmpCacheStrat")
        assert s1 is not None and s2 is not None
        assert s1 is not s2
        assert type(s1) is type(s2)
        assert s1.val == 1

        # Modify file (bump mtime_ns + size)
        time.sleep(0.01)
        strat_file.write_text(
            "class TmpCacheStrat:\n"
            "    val = 222\n"
            "    def generate_signals(self, df): return df\n"
        )
        s3 = load_strategy_instance("TmpCacheStrat")
        assert s3.val == 222


def test_strategy_registry_o1_status_and_lightweight_summary(tmp_path):
    """StrategyRegistry.get_status() is O(1) and include_heavy=False omits trades_detail/trade_markers."""
    reg_file = str(tmp_path / "strategies.json")
    s_dir = str(tmp_path / "strategies")
    os.makedirs(s_dir, exist_ok=True)
    with open(reg_file, "w") as f:
        json.dump([{
            "name": "FastStrat",
            "file": "FastStrat.py",
            "status": "ACTIVE_LIVE",
            "trades_detail": [{"id": i} for i in range(10)],
            "trade_markers": [{"time": i} for i in range(10)],
        }], f)

    reg = StrategyRegistry(path=reg_file, strategies_dir=s_dir)
    with patch("server.state.state_manager.signal_store.get_all", return_value=[]):
        assert reg.get_status("FastStrat") == "ACTIVE_LIVE"
        assert reg.get_status("FastStrat.py") == "ACTIVE_LIVE"
        assert reg.get_status("UnknownStrat") is None
        light = reg.get_all(sync=False, include_heavy=False)
        assert len(light) == 1
        assert "trades_detail" not in light[0]
        assert "trade_markers" not in light[0]

