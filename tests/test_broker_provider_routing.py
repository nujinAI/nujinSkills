"""
tests/test_broker_provider_routing.py
─────────────────────────────────────────────────────────────
Tests for generic plugin-agnostic ProviderRegistry and BrokerRegistry routing:
1. Default public feed routing when active broker is paper/disconnected
2. Broker-first market data routing when any broker plugin is connected
3. BrokerRegistry.get_active_broker_id auto-detection from accounts_store
"""

import unittest
from unittest.mock import MagicMock, patch

from server.providers.base import ProviderRegistry, BaseMarketDataProvider
from server.brokers.registry import broker_registry

from _feed_stubs import live_feeds_stubbed


class TestBrokerProviderRouting(unittest.TestCase):

    def setUp(self):
        ProviderRegistry._providers.clear()

    def tearDown(self):
        ProviderRegistry._providers.clear()

    def test_default_public_provider_when_paper(self):
        """When active broker is paper/disconnected, default public feed providers are used."""
        with live_feeds_stubbed(), \
             patch.object(broker_registry, "get_active_broker_id", return_value="paper"):
            p_gold = ProviderRegistry.get_provider("XAU/USD", "1m")
            self.assertEqual(p_gold.symbol, "XAU/USD")
            self.assertIn("TradingViewMarketDataProvider", p_gold.__class__.__name__)

            p_btc = ProviderRegistry.get_provider("BTC/USDT", "15m")
            self.assertEqual(p_btc.symbol, "BTC/USDT")
            self.assertIn("TradingViewMarketDataProvider", p_btc.__class__.__name__)

    def test_broker_first_routing_when_connected(self):
        """When a broker plugin is connected and supplies market data, ProviderRegistry prefers it."""
        mock_broker = MagicMock()
        mock_broker.broker_id = "custom_broker"
        mock_broker.is_connected = True
        mock_broker.name = "Custom Broker Plugin"

        mock_provider = MagicMock(spec=BaseMarketDataProvider)
        mock_provider.symbol = "XAU/USD"
        mock_provider.timeframe = "5m"
        mock_provider.is_running = False
        mock_broker.get_market_data_provider.return_value = mock_provider

        with patch.object(broker_registry, "get_broker", return_value=mock_broker):
            provider = ProviderRegistry.get_provider("XAU/USD", "5m")
            self.assertEqual(provider, mock_provider)
            mock_broker.get_market_data_provider.assert_called_once_with("XAU/USD", "5m")

    def test_broker_registry_autodetect_active_account(self):
        """Tests that BrokerRegistry.get_active_broker_id auto-detects active non-paper accounts."""
        mock_accounts = [{"broker_id": "custom_broker", "is_active": True, "id": "cust_123"}]
        with patch("os.environ.get", return_value=""), \
             patch("server.accounts_store.accounts_store.get_all_active_accounts", return_value=mock_accounts):
            active_id = broker_registry.get_active_broker_id()
            self.assertEqual(active_id, "custom_broker")


if __name__ == "__main__":
    unittest.main()
