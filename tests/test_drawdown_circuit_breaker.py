"""
tests/test_drawdown_circuit_breaker.py
─────────────────────────────────────────────────────────────
Tests the live drawdown circuit breaker in NativeStrategyRunner.check_drawdown_safety().

The breaker is the last line of defence before real capital is risked, so these tests
inject a controlled account and signal book rather than reading whatever live state
happens to be on disk. Reading live state made the suite non-deterministic: it passed
or failed depending on today's realised P&L.

Canonical behaviour under test (with a $5,000 account and default risk):
    max_daily_loss_usd  = 3.0%  -> $150.00   (DAILY_DRAWDOWN_LIMIT_EXCEEDED at or above)
    max_total_loss_usd  = 5.0%  -> $250.00   (TOTAL_DRAWDOWN_LIMIT_EXCEEDED at or above)
    single_trade_risk   = 0.6%  -> $30.00
    buffer_required_usd = 2.5x single trade risk -> $75.00 (BUFFER_EXHAUSTED below)
"""

import time
import unittest
from unittest.mock import MagicMock, patch

from server.strategy_executor import NativeStrategyRunner
from server.state_manager import signal_store

from _feed_stubs import live_feeds_stubbed

BALANCE = 5000.0


def _closed_signal(pnl_usd: float, age_seconds: int = 0) -> dict:
    """A CLOSED XAU/USD signal booked `age_seconds` ago with a realised P&L."""
    ts = int(time.time()) - age_seconds
    return {
        "id": "dd-test-signal",
        "time": ts,
        "entry_time": ts,
        "status": "CLOSED",
        "pnl_usd": pnl_usd,
        "pair": "XAU/USD",
        "action": "BUY",
    }


class TestDrawdownCircuitBreaker(unittest.TestCase):
    def setUp(self):
        # Constructing a runner seeds its market-data provider from live OANDA/TradingView
        # candles. That fetch used to be attempted on every run with its failure swallowed,
        # so the test quietly needed network access to behave like production.
        with live_feeds_stubbed():
            self.runner = NativeStrategyRunner("zillions_mtfvdmr")

    def _evaluate(self, signals, balance: float = BALANCE):
        """
        Runs check_drawdown_safety() against a fully controlled environment:
          - a single TradeLocker account with a known balance and no risk-profile overrides
          - a paper (disconnected) broker, so broker equity never masks the signal-based P&L
          - an explicit signal book
          - no loadable strategy instance, so the documented default risk percentages apply
        """
        account = {
            "broker_id": "tradelocker",
            "is_active": True,
            "initial_balance": balance,
            "risk_profile": {},
        }
        accounts = MagicMock()
        accounts.get_all_active_accounts.return_value = [account]

        paper_broker = MagicMock()
        paper_broker.broker_id = "paper"
        paper_broker.is_connected = False
        broker_reg = MagicMock()
        broker_reg.get_broker.return_value = paper_broker

        with patch("server.backtest_engine.load_strategy_instance", return_value=None), \
             patch("server.strategy_executor.accounts_store", accounts), \
             patch("server.strategy_executor.broker_registry", broker_reg), \
             patch.object(signal_store, "get_all", return_value=signals):
            return self.runner.check_drawdown_safety()

    def test_circuit_breaker_halts_when_budget_exhausted(self):
        """An -$80 day on a $5,000 account leaves $70, below the $75 safety buffer, so entries must halt."""
        safe, reason, details = self._evaluate([_closed_signal(-80.0)])

        self.assertIn("today_loss_usd", details)
        self.assertIn("max_daily_loss_usd", details)
        self.assertIn("remaining_budget_usd", details)

        self.assertEqual(details["today_loss_usd"], 80.0)
        self.assertEqual(details["max_daily_loss_usd"], 150.0)
        self.assertEqual(details["remaining_budget_usd"], 70.0)
        self.assertEqual(details["buffer_required_usd"], 75.0)

        self.assertFalse(safe)
        self.assertEqual(reason, "DAILY_DRAWDOWN_BUFFER_EXHAUSTED")
        self.assertTrue("exhausted" in details["message"].lower())

    def test_circuit_breaker_allows_entries_with_healthy_budget(self):
        """An -$50 day leaves $100 of the $150 daily budget, above the $75 buffer, so entries are allowed."""
        safe, reason, details = self._evaluate([_closed_signal(-50.0)])

        self.assertEqual(details["today_loss_usd"], 50.0)
        self.assertEqual(details["remaining_budget_usd"], 100.0)
        self.assertTrue(safe)
        self.assertEqual(reason, "OK")

    def test_circuit_breaker_halts_at_daily_loss_limit(self):
        """A -$160 day breaches the $150 daily loss limit outright and must halt with the limit reason."""
        safe, reason, details = self._evaluate([_closed_signal(-160.0)])

        self.assertFalse(safe)
        self.assertEqual(reason, "DAILY_DRAWDOWN_LIMIT_EXCEEDED")
        self.assertTrue("daily drawdown limit" in details["message"].lower())

    def test_circuit_breaker_ignores_previous_days_losses(self):
        """Yesterday's -$160 must not count against today's budget: the guard is day-scoped."""
        safe, reason, details = self._evaluate([_closed_signal(-160.0, age_seconds=26 * 3600)])

        self.assertEqual(details["today_loss_usd"], 0.0)
        self.assertEqual(details["remaining_budget_usd"], 150.0)
        self.assertTrue(safe)
        self.assertEqual(reason, "OK")

    def test_circuit_breaker_halts_when_daily_limit_scales_with_balance(self):
        """The daily limit is a percentage of account size, so a bigger account tolerates a bigger loss."""
        safe, reason, details = self._evaluate([_closed_signal(-160.0)], balance=20000.0)

        self.assertEqual(details["max_daily_loss_usd"], 600.0)
        self.assertEqual(details["remaining_budget_usd"], 440.0)
        self.assertTrue(safe)
        self.assertEqual(reason, "OK")


if __name__ == "__main__":
    unittest.main()
