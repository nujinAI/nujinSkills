"""
tests/test_data_integrity.py
─────────────────────────────────────────────────────────────
The XAU/USD feed must report data gaps and, just as importantly, stop reporting them once
authentic candles close the gap.

`references/bot_operations.md` states that consumers should treat signals as unreliable while
`data_degraded` is set, "until it clears" — but nothing ever cleared it. A single startup or
reconnect gap therefore marked the series unreliable for the rest of the process lifetime, and
every consumer that respected the flag stayed suspicious forever. These tests pin the recovery
half of that contract.

Only authentic bars may clear the flag: bars whose volume the engine derived from the polled
tick stream are not evidence that the series is complete.
"""

import asyncio
import unittest
from unittest.mock import patch

from _feed_stubs import live_feeds_stubbed
from server.xauusd_streamer import XauusdScalpEngine


def _candles(start: int, count: int, volume: float = 10.0) -> list:
    return [
        {
            "time": start + i * 60, "open": 4400.0, "high": 4401.0,
            "low": 4399.0, "close": 4400.5, "volume": volume,
        }
        for i in range(count)
    ]


class TestDataDegradedLifecycle(unittest.TestCase):
    def _engine(self) -> XauusdScalpEngine:
        # Constructing the engine seeds it from the live feed; stub that so the test is offline.
        with live_feeds_stubbed():
            return XauusdScalpEngine()

    def test_health_flag_starts_clear(self):
        engine = self._engine()
        self.assertFalse(engine.data_degraded)
        self.assertEqual(engine.data_gap_seconds, 0)

    def test_recovery_clears_the_flag_and_the_gap(self):
        engine = self._engine()
        engine.data_degraded = True
        engine.data_gap_seconds = 900

        with self.assertLogs("XauusdStreamer", level="INFO") as captured:
            engine._mark_data_recovered("test recovery")

        self.assertFalse(engine.data_degraded)
        self.assertEqual(engine.data_gap_seconds, 0)
        self.assertTrue(any("restored" in line for line in captured.output), captured.output)

    def test_recovery_is_not_reported_when_nothing_was_degraded(self):
        engine = self._engine()
        engine._mark_data_recovered("no-op")
        self.assertFalse(engine.data_degraded)

    def test_authentic_sync_clears_the_flag(self):
        """The real background sync must clear degradation once authentic bars merge."""
        engine = self._engine()
        engine.candles_1m = _candles(start=1_700_000_000, count=10)
        engine.data_degraded = True
        engine.data_gap_seconds = 600

        authentic = _candles(start=1_700_000_000, count=10, volume=900.0)
        with patch("server.data_manager.fetch_real_oanda_candles", return_value=authentic):
            asyncio.run(engine._sync_authentic_candles())

        self.assertFalse(engine.data_degraded, "the gap was filled with authentic bars")
        self.assertEqual(engine.data_gap_seconds, 0)
        # Merged bars are relabelled; the still-forming last bar is left alone.
        self.assertEqual(engine.candles_1m[0]["volume_source"], "authentic")
        self.assertEqual(engine.candles_1m[0]["volume"], 900.0)
        self.assertNotEqual(engine.candles_1m[-1].get("volume_source"), "authentic")

    def test_failed_backfill_does_not_clear_the_flag(self):
        """Only real data clears degradation: an empty fetch must leave it set."""
        engine = self._engine()
        engine.candles_1m = _candles(start=1_700_000_000, count=10)
        engine.data_degraded = True
        engine.data_gap_seconds = 600

        with patch("server.data_manager.fetch_real_oanda_candles", return_value=[]):
            asyncio.run(engine._sync_authentic_candles())

        self.assertTrue(engine.data_degraded)
        self.assertEqual(engine.data_gap_seconds, 600)


if __name__ == "__main__":
    unittest.main()
