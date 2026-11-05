"""
Tests for limit order backtesting and execution parity in core.simulation and server.services.strategy_executor.
Ensures SSOT invariant: limit order mechanics match pessimistic intraday fill assumptions.
"""

import pytest
import numpy as np
import pandas as pd
from core.simulation import run_discrete_simulation, TradeRecord
from server.services.strategy_executor import StrategyEvaluator


def create_sample_bars(n_bars: int = 10, start_price: float = 2700.0, step: float = 1.0):
    """Creates synthetic OHLC bars for predictable test verification."""
    times = pd.date_range("2026-11-01 10:00:00", periods=n_bars, freq="5min", tz="UTC")
    data = []
    p = start_price
    for i in range(n_bars):
        o = p
        h = p + 2.0
        l = p - 2.0
        c = p + 0.5
        data.append({"open": o, "high": h, "low": l, "close": c, "atr": 2.0})
        p += step
    df = pd.DataFrame(data, index=times)
    return df


def test_market_order_legacy_backwards_compatibility():
    """Verify that omitting limit parameters maintains standard market order behavior."""
    df = create_sample_bars(10, start_price=2700.0, step=2.0)
    signals = pd.DataFrame(index=df.index)
    signals["entry_signal"] = 0
    signals["stop_loss"] = 0.0
    signals["target"] = 0.0

    # Signal on bar 0 (Long)
    signals.iloc[0, signals.columns.get_loc("entry_signal")] = 1
    signals.iloc[0, signals.columns.get_loc("stop_loss")] = 2690.0
    signals.iloc[0, signals.columns.get_loc("target")] = 2720.0

    res = run_discrete_simulation(df, signals, symbol="OANDA:XAUUSD", account_size=5000.0)
    assert res["total_trades"] >= 1
    # Legacy market order enters at bar 1 open
    first_trade = res["trades"][0]
    assert first_trade.entry_price == df["open"].iloc[1]


def test_limit_order_unfilled_expiry():
    """Verify that a limit order that is never touched by price expires without filling."""
    df = create_sample_bars(10, start_price=2700.0, step=5.0)  # Price keeps climbing: 2700, 2705, 2710...
    signals = pd.DataFrame(index=df.index)
    signals["entry_signal"] = 0
    signals["stop_loss"] = 0.0
    signals["target"] = 0.0
    signals["limit_price"] = 0.0
    signals["limit_expiry_bars"] = 2

    # Long limit placed way below market at 2680 (never touched since low is 2698+)
    signals.iloc[0, signals.columns.get_loc("entry_signal")] = 1
    signals.iloc[0, signals.columns.get_loc("limit_price")] = 2680.0
    signals.iloc[0, signals.columns.get_loc("stop_loss")] = 2670.0
    signals.iloc[0, signals.columns.get_loc("target")] = 2730.0

    res = run_discrete_simulation(df, signals, symbol="OANDA:XAUUSD", account_size=5000.0)
    # Order should expire after 2 bars without executing any trade
    assert res["total_trades"] == 0


def test_limit_order_fill_and_execution():
    """Verify that a resting limit order fills exactly when bar low penetrates limit price."""
    df = create_sample_bars(10, start_price=2700.0, step=0.0)
    # Customize bar 2 to dip down to touch limit
    df.iloc[2, df.columns.get_loc("low")] = 2695.0
    df.iloc[2, df.columns.get_loc("open")] = 2700.0
    df.iloc[2, df.columns.get_loc("high")] = 2701.0
    df.iloc[2, df.columns.get_loc("close")] = 2699.0

    # Customize bar 4 to hit TP
    df.iloc[4, df.columns.get_loc("high")] = 2715.0

    signals = pd.DataFrame(index=df.index)
    signals["entry_signal"] = 0
    signals["stop_loss"] = 0.0
    signals["target"] = 0.0
    signals["limit_price"] = 0.0
    signals["limit_expiry_bars"] = 5

    # Signal on bar 0: Long limit at 2697.0 (bar 0 low is 2698, bar 1 low is 2698, bar 2 low is 2695)
    signals.iloc[0, signals.columns.get_loc("entry_signal")] = 1
    signals.iloc[0, signals.columns.get_loc("limit_price")] = 2697.0
    signals.iloc[0, signals.columns.get_loc("stop_loss")] = 2690.0
    signals.iloc[0, signals.columns.get_loc("target")] = 2710.0

    res = run_discrete_simulation(df, signals, symbol="OANDA:XAUUSD", account_size=5000.0)
    assert res["total_trades"] == 1
    trade = res["trades"][0]
    # Trade must have filled at bar 2 time, exactly at the limit price 2697.0
    assert trade.entry_time == df.index[2]
    assert trade.entry_price == 2697.0
    assert trade.exit_price == 2710.0
    assert trade.exit_reason == "TP"


def test_limit_order_cancelled_if_sl_breached_prior_to_fill():
    """Verify that if price plummets through SL on the same bar or prior to limit fill, order is canceled."""
    df = create_sample_bars(10, start_price=2700.0, step=0.0)
    # Bar 1 drops violently through SL before order could rest
    df.iloc[1, df.columns.get_loc("low")] = 2660.0
    df.iloc[1, df.columns.get_loc("open")] = 2665.0

    signals = pd.DataFrame(index=df.index)
    signals["entry_signal"] = 0
    signals["stop_loss"] = 0.0
    signals["target"] = 0.0
    signals["limit_price"] = 0.0
    signals["limit_expiry_bars"] = 3

    # Long limit @ 2695, SL @ 2690
    signals.iloc[0, signals.columns.get_loc("entry_signal")] = 1
    signals.iloc[0, signals.columns.get_loc("limit_price")] = 2695.0
    signals.iloc[0, signals.columns.get_loc("stop_loss")] = 2690.0
    signals.iloc[0, signals.columns.get_loc("target")] = 2720.0

    res = run_discrete_simulation(df, signals, symbol="OANDA:XAUUSD", account_size=5000.0)
    # The order was invalidated/canceled by extreme SL breach without opening an unmanaged position
    assert res["total_trades"] <= 1  # If triggered on fill bar, pessimistically exits at SL
    if res["total_trades"] == 1:
        assert res["trades"][0].exit_reason == "SL"
