"""
tests/test_tradelocker_provider.py
─────────────────────────────────────────────────────────────
Tests for dynamic broker price feed switching and TradeLockerMarketDataProvider:
1. ProviderRegistry routing when broker is disconnected/paper (default public feeds)
2. ProviderRegistry routing when TradeLocker broker is active and connected
3. TradeLockerMarketDataProvider live tick ingestion & candle updates
4. TradeLocker snapshot quote retrieval & XauusdScalpEngine broker feed switching
"""

import asyncio
import time
import unittest
from unittest.mock import MagicMock, patch

from server.providers.base import ProviderRegistry, BaseMarketDataProvider
from server.brokers.registry import broker_registry

from _feed_stubs import live_feeds_stubbed


class TestTradeLockerPriceFeed(unittest.TestCase):

    def setUp(self):
        # Reset provider registry
        ProviderRegistry._providers.clear()

    def tearDown(self):
        ProviderRegistry._providers.clear()

    def test_default_public_provider_when_paper(self):
        """When active broker is paper/disconnected, default providers are used."""
        # Provider constructors seed themselves from live feeds. Stub that: this test is
        # about routing, and conftest.py fails the session if a test reaches the network.
        with live_feeds_stubbed(), \
             patch.object(broker_registry, "get_active_broker_id", return_value="paper"):
            p_gold = ProviderRegistry.get_provider("XAU/USD", "1m")
            self.assertEqual(p_gold.symbol, "XAU/USD")
            self.assertIn("OandaGoldProvider", p_gold.__class__.__name__)

            p_btc = ProviderRegistry.get_provider("BTC/USDT", "15m")
            self.assertEqual(p_btc.symbol, "BTC/USDT")
            self.assertIn("BinanceSpotProvider", p_btc.__class__.__name__)

    def test_broker_first_routing_when_connected(self):
        """When broker is connected and provides market data, ProviderRegistry uses broker provider."""
        mock_broker = MagicMock()
        mock_broker.broker_id = "tradelocker"
        mock_broker.is_connected = True
        mock_broker.name = "TradeLocker Institutional Gateway [PRO]"

        mock_provider = MagicMock(spec=BaseMarketDataProvider)
        mock_provider.symbol = "XAU/USD"
        mock_provider.timeframe = "5m"
        mock_provider.is_running = False
        mock_broker.get_market_data_provider.return_value = mock_provider

        with patch.object(broker_registry, "get_broker", return_value=mock_broker):
            provider = ProviderRegistry.get_provider("XAU/USD", "5m")
            self.assertEqual(provider, mock_provider)
            mock_broker.get_market_data_provider.assert_called_once_with("XAU/USD", "5m")

    @staticmethod
    def _seed_candles(last_close: float = 4410.20, count: int = 120) -> list:
        """
        A deterministic 1m OHLCV series used to seed the provider.

        The provider seeds itself from a live OANDA/TradingView fetch on init, which made these
        tests depend on network state and on whatever price the market happened to be at: a
        hardcoded tick far from the seeded close is correctly rejected by the provider's 2%
        outlier guard, so the assertion failed for the wrong reason. Patching the seed keeps the
        test hermetic and keeps the outlier guard under test instead of tripping over it.
        """
        base = int(time.time()) - count * 60
        first = round(last_close - 0.60, 2)
        series = []
        for i in range(count - 1):
            series.append({
                "time": base + i * 60,
                "timestamp": base + i * 60,
                "open": first,
                "high": round(last_close - 0.20, 2),
                "low": round(first - 0.20, 2),
                "close": round(last_close - 0.30, 2),
                "volume": 250.0,
            })
        series.append({
            "time": base + (count - 1) * 60,
            "timestamp": base + (count - 1) * 60,
            "open": round(last_close - 0.30, 2),
            "high": round(last_close + 0.20, 2),
            "low": round(last_close - 0.60, 2),
            "close": last_close,
            "volume": 300.0,
        })
        return series

    def _provider_class(self):
        """Loads TradeLockerMarketDataProvider from the pro plugin, or skips the test."""
        import sys, os
        pro_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "plugins", "pro"))
        if pro_path not in sys.path:
            sys.path.insert(0, pro_path)

        try:
            from brokers.tradelocker_provider import TradeLockerMarketDataProvider
        except ImportError:
            self.skipTest("TradeLocker provider not found in path")
        return TradeLockerMarketDataProvider

    @staticmethod
    def _mock_broker():
        mock_broker = MagicMock()
        mock_broker.is_connected = True
        mock_broker._resolve_instrument_id.return_value = "inst_xau_123"

        mock_client = MagicMock()
        mock_client.get_quote.return_value = {
            "bp": 4410.20,
            "ap": 4410.50,
            "lp": 4410.35
        }
        mock_broker.client = mock_client
        return mock_broker

    def _make_provider(self, seed_last_close: float = 4410.20):
        """Builds a provider whose historical seed is patched, never fetched."""
        provider_cls = self._provider_class()
        mock_broker = self._mock_broker()
        seed = self._seed_candles(last_close=seed_last_close)
        with patch("server.data_manager.fetch_real_oanda_candles", return_value=seed), \
             patch("server.data_manager.fetch_candles_via_tv", return_value=seed):
            provider = provider_cls(
                broker_instance=mock_broker, symbol="XAU/USD", timeframe="1m"
            )
            # Seeding is lazy, so the first read is what fetches: pull it inside the patch.
            provider.get_candles()
        return provider, mock_broker

    def test_constructing_provider_does_not_fetch_candles(self):
        """
        Construction must be side-effect free; the first read is what seeds history.

        The constructor used to run a 2,000-bar OANDA/TradingView fetch, which is why every
        test touching a provider depended on the live market price and why building one was
        slow and behaved differently offline.
        """
        provider_cls = self._provider_class()
        mock_broker = self._mock_broker()
        fetch_calls = []

        def _record(*args, **kwargs):
            fetch_calls.append(kwargs or args)
            return []

        with patch("server.data_manager.fetch_real_oanda_candles", side_effect=_record), \
             patch("server.data_manager.fetch_candles_via_tv", side_effect=_record):
            provider = provider_cls(
                broker_instance=mock_broker, symbol="XAU/USD", timeframe="1m"
            )
            self.assertEqual(fetch_calls, [], "the constructor must not fetch historical candles")
            self.assertEqual(provider._candles, [])

            provider.get_candles()

        self.assertGreaterEqual(len(fetch_calls), 1, "the first read must seed from history")

    def test_tradelocker_provider_tick_processing(self):
        """Tests that TradeLockerMarketDataProvider processes live broker quotes and forms candles."""
        provider, mock_broker = self._make_provider(seed_last_close=4410.20)

        quote = provider.fetch_snapshot_quote()
        self.assertIsNotNone(quote)
        self.assertEqual(quote["price"], 4410.35)
        self.assertEqual(quote["bid"], 4410.20)
        self.assertEqual(quote["ask"], 4410.50)
        self.assertEqual(quote["source"], "tradelocker_broker")

        # Process a live tick synchronously
        async def run_tick():
            await provider.process_live_tick(
                price=quote["price"],
                timestamp=quote["timestamp"],
                bid=quote["bid"],
                ask=quote["ask"],
                source="tradelocker_stream"
            )
        asyncio.run(run_tick())

        candles = provider.get_candles()
        self.assertGreaterEqual(len(candles), 1)
        self.assertEqual(candles[-1]["close"], 4410.35)

    def test_tradelocker_provider_rejects_outlier_tick(self):
        """A tick spiking >2% from the last close must be rejected rather than written into the candle."""
        provider, _ = self._make_provider(seed_last_close=4410.20)

        baseline = provider.get_candles()[-1]["close"]
        outlier = round(baseline * 1.05, 2)  # +5%, well past the 2% guard

        async def run_outlier_tick():
            await provider.process_live_tick(
                price=outlier,
                timestamp=int(time.time()) + 1,
                source="tradelocker_stream"
            )
        asyncio.run(run_outlier_tick())

        self.assertEqual(
            provider.get_candles()[-1]["close"], baseline,
            "an outlier tick must not overwrite the candle close"
        )

    def test_tradelocker_provider_accepts_in_band_tick(self):
        """A tick within the 2% guard must advance the candle close."""
        provider, _ = self._make_provider(seed_last_close=4410.20)

        baseline = provider.get_candles()[-1]["close"]
        tick = round(baseline * 1.005, 2)  # +0.5%, inside the guard

        async def run_tick():
            await provider.process_live_tick(
                price=tick,
                timestamp=int(time.time()) + 1,
                source="tradelocker_stream"
            )
        asyncio.run(run_tick())

        self.assertEqual(provider.get_candles()[-1]["close"], tick)

    def test_xauusd_streamer_switches_to_broker_feed(self):
        """Tests that XauusdScalpEngine checks and adopts active connected broker quote."""
        # The import itself builds a module-level engine, and the engine seeds its first
        # candles from the live OANDA/TradingView feed — so the import has to sit inside
        # the stub too, not just the constructor call.
        with live_feeds_stubbed():
            from server.xauusd_streamer import XauusdScalpEngine
            engine = XauusdScalpEngine()

        mock_broker = MagicMock()
        mock_broker.broker_id = "tradelocker"
        mock_broker.is_connected = True
        mock_broker.name = "TradeLocker Institutional Gateway [PRO]"
        mock_broker.get_latest_quote.return_value = {
            "symbol": "XAU/USD",
            "price": 4425.80,
            "bid": 4425.65,
            "ask": 4425.95,
            "timestamp": int(time.time()),
            "source": "tradelocker_stream"
        }

        # The engine itself must resolve the broker feed: a connected broker wins.
        with patch.object(broker_registry, "get_broker", return_value=mock_broker):
            broker, quote = engine._broker_feed()
        self.assertIs(broker, mock_broker)
        self.assertEqual(quote["price"], 4425.80)
        self.assertEqual(quote["source"], "tradelocker_stream")

        # A disconnected broker must yield no broker feed, so the public feed is used.
        mock_broker.is_connected = False
        with patch.object(broker_registry, "get_broker", return_value=mock_broker):
            broker, quote = engine._broker_feed()
        self.assertIsNone(broker)
        self.assertIsNone(quote)

    def test_tradelocker_provider_initial_candles_seed(self):
        """Tests that TradeLockerMarketDataProvider adopts the historical candles fetched on init."""
        provider, _ = self._make_provider(seed_last_close=4410.20)

        candles = provider.get_candles(count=1000)
        self.assertGreater(len(candles), 25, "TradeLockerMarketDataProvider must seed >25 candles so strategy evaluation succeeds")

        # The seed is adopted verbatim: the last seeded close drives the initial quote.
        self.assertEqual(candles[-1]["close"], 4410.20)
        self.assertEqual(provider.get_latest_quote()["source"], "tradelocker_initial_seed")

    def test_broker_registry_autodetect_tradelocker_account(self):
        """Tests that BrokerRegistry.get_active_broker_id auto-detects active TradeLocker accounts in accounts_store."""
        mock_accounts = [{"broker_id": "tradelocker", "is_active": True, "id": "tl_123"}]
        with patch("os.environ.get", return_value=""), \
             patch("server.accounts_store.accounts_store.get_all_active_accounts", return_value=mock_accounts):
            active_id = broker_registry.get_active_broker_id()
            self.assertEqual(active_id, "tradelocker", "BrokerRegistry should auto-detect 'tradelocker' when active account exists in store")


if __name__ == "__main__":
    unittest.main()
