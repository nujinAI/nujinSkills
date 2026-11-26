"""
tests/test_multi_account_broker.py
─────────────────────────────────────────────────────────────
Generic, broker-agnostic unit tests for multi-account broker architecture:
1. Generic AccountsStore (encryption, isolation, thread safety, masking)
2. Telegram Listener interactive commands & session wizard
3. Paper & Evaluator lot-size handling
4. Discovery-only listing & status surfaces never triggering broker connect()
"""

import asyncio
import contextlib
import importlib.util
import io
import os
import sys
import types
import unittest
from unittest.mock import patch
from urllib.error import URLError

from server.accounts_store import accounts_store, SecretCipher
from server.brokers.base import BaseExecutionBroker
from server.brokers.registry import broker_registry
from server.telegram_listener import telegram_listener


class _MockLiveBroker(BaseExecutionBroker):
    """Generic in-test broker plugin stub implementing the BaseExecutionBroker contract."""

    def __init__(self, broker_id: str = "mock_live", name: str = "Mock Live Broker"):
        super().__init__(broker_id=broker_id, name=name)
        self.balance = 0.0
        self.equity = 0.0

    @property
    def supports_multi_account(self) -> bool:
        return True

    def connect(self, config=None) -> bool:
        self.is_connected = True
        return True

    def disconnect(self) -> None:
        self.is_connected = False

    def get_account_info(self):
        accs = accounts_store.get_all_active_accounts(decrypt=False)
        matching = [a for a in accs if a.get("broker_id") == self.broker_id]
        return {
            "broker_id": self.broker_id,
            "connected": self.is_connected,
            "balance": self.balance if self.is_connected else 0.0,
            "equity": self.equity if self.is_connected else 0.0,
            "free_margin": self.equity if self.is_connected else 0.0,
            "currency": "USD",
            "is_demo": True,
            "accounts_configured": bool(matching),
            "multi_account_count": len(matching),
        }

    def execute_order(self, signal):
        return {"status": "FILLED", "order_id": "mock-1", "filled_price": float(signal.get("price", 0.0)), "filled_lots": 0.1}

    def close_position(self, position_id, reason="MANUAL", current_price=None, symbol=None):
        return {"status": "CLOSED", "position_id": position_id, "exit_price": current_price or 0.0, "realized_pnl": 0.0}

    def get_open_positions(self, symbol=None):
        return []


def _blocked_network_attempts() -> int:
    """Number of outbound connections the session guard has blocked so far."""
    import conftest
    return len(conftest._BLOCKED_ATTEMPTS)


def _tools_module(name: str):
    """Imports a `tools/` script by path (that directory is a namespace package)."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"nujin_tool_under_test_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMultiAccountBroker(unittest.TestCase):

    def test_secret_cipher_roundtrip(self):
        cipher = SecretCipher()
        secret = "my_super_secret_broker_password_123!"
        encrypted = cipher.encrypt(secret)
        self.assertNotEqual(encrypted, secret)
        self.assertGreater(len(encrypted), len(secret))
        decrypted = cipher.decrypt(encrypted)
        self.assertEqual(decrypted, secret)

    def test_secret_cipher_format_does_not_depend_on_optional_packages(self):
        """Secret format must be deterministic regardless of whether cryptography is installed."""
        def _explode(*_args, **_kwargs):
            raise AssertionError("encrypt() must not depend on the optional 'cryptography' package")

        fake_crypto = types.ModuleType("cryptography")
        fake_fernet = types.ModuleType("cryptography.fernet")
        fake_fernet.Fernet = _explode  # type: ignore[attr-defined]
        fake_crypto.fernet = fake_fernet

        with patch.dict(sys.modules, {"cryptography": fake_crypto, "cryptography.fernet": fake_fernet}):
            payload = SecretCipher().encrypt("hunter2")

        self.assertTrue(payload.startswith("sl:"), f"unexpected payload format: {payload[:8]!r}")
        self.assertEqual(SecretCipher().decrypt(payload), "hunter2")

    def test_legacy_fernet_payload_fails_loudly_without_the_package(self):
        """A legacy `fn:` secret must name its missing dependency instead of failing silently."""
        with patch.dict(sys.modules, {"cryptography": None, "cryptography.fernet": None}), \
                self.assertLogs("AccountsStore", level="ERROR") as captured:
            self.assertEqual(SecretCipher().decrypt("fn:gAAAAA-not-really-a-token"), "")

        self.assertTrue(
            any("cryptography" in line for line in captured.output), captured.output,
        )

    def test_accounts_store_crud(self):
        user_id = "test_user_99"
        chat_id = "test_chat_99"

        acc = accounts_store.add_account(
            broker_id="custom_broker",
            telegram_user_id=user_id,
            telegram_chat_id=chat_id,
            login="trader99@example.com",
            password="securepass99",
            server="Demo Server",
            acc_num="ACC-99",
            default_lots=0.20,
        )
        acc_id = acc["id"]
        self.assertTrue(acc_id.startswith("cust_"))
        self.assertEqual(acc["default_lots"], 0.20)

        user_accs = accounts_store.get_accounts_by_user(user_id, mask=True)
        self.assertGreaterEqual(len(user_accs), 1)
        found = [a for a in user_accs if a["id"] == acc_id][0]
        self.assertEqual(found["login_masked"], "tr***@example.com")
        self.assertNotIn("password_encrypted", found)

        decrypted_acc = accounts_store.get_account_by_id(acc_id, decrypt=True)
        self.assertIsNotNone(decrypted_acc)
        self.assertEqual(decrypted_acc["password"], "securepass99")

        self.assertTrue(accounts_store.update_account_risk(acc_id, user_id, 0.50))
        updated = accounts_store.get_account_by_id(acc_id, decrypt=False)
        self.assertEqual(updated["default_lots"], 0.50)

        self.assertTrue(accounts_store.toggle_account_active(acc_id, user_id, is_active=False))
        toggled = accounts_store.get_account_by_id(acc_id, decrypt=False)
        self.assertFalse(toggled["is_active"])

        self.assertTrue(accounts_store.delete_account(acc_id, user_id))
        self.assertIsNone(accounts_store.get_account_by_id(acc_id))

    def test_telegram_listener_helpers(self):
        self.assertTrue(telegram_listener._is_float("0.25"))
        self.assertFalse(telegram_listener._is_float("invalid"))
        self.assertTrue(telegram_listener._is_float("1"))

    def test_bot_lotsize_support(self):
        """Tests that PaperExecutionBroker and SignalStore record strategy lots."""
        from server.state_manager import signal_store
        from server.brokers.paper import PaperExecutionBroker

        broker = PaperExecutionBroker()
        sig = {
            "strategy": "TestMockStrategy",
            "pair": "XAU/USD",
            "action": "BUY",
            "price": 4400.0,
            "stop_loss": 4390.0,
            "take_profit": 4425.0,
            "lots": 0.50,
        }

        res = broker.execute_order(sig)
        self.assertEqual(res["status"], "FILLED")
        self.assertEqual(res["filled_lots"], 0.50)

        signals = signal_store.add(sig)
        latest = signals[0]
        self.assertEqual(latest["lots"], 0.50)
        self.assertEqual(latest["lot_size"], 0.50)

        signal_store.clear("TestMockStrategy")

    def test_strategy_evaluator_lots(self):
        """Tests that StrategyEvaluator parses lots and lot_size from strategy signals."""
        from server.strategy_executor import StrategyEvaluator
        from unittest.mock import MagicMock

        with patch("server.backtest_engine.load_strategy_instance") as mock_load:
            mock_strat = MagicMock()
            mock_strat.can_short = True
            mock_strat.stoploss = -0.0025
            mock_strat.minimal_roi = {"0": 0.005}
            mock_strat.atr_sl_mult = None
            mock_strat.atr_tp_mult = None
            mock_strat.min_bars = 1
            mock_strat.max_bars = 4
            del mock_strat.generate_signals

            def mock_pop_ind(df, meta):
                df["volume_zscore"] = 1.0
                df["atr_14"] = 2.5
                return df

            def mock_pop_entry(df, meta):
                df["enter_long"] = 0
                df["enter_short"] = 0
                df["structural_sl"] = float("nan")
                df["structural_tp"] = float("nan")
                df["lot_size"] = 0.50
                df.iloc[-1, df.columns.get_loc("enter_long")] = 1
                return df

            mock_strat.populate_indicators.side_effect = mock_pop_ind
            mock_strat.populate_entry_trend.side_effect = mock_pop_entry
            mock_strat.calculate_lot_size.return_value = 0.50
            mock_load.return_value = mock_strat

            candles = [
                {
                    "time": 1700000000 + i * 300,
                    "open": 4400.0,
                    "high": 4405.0,
                    "low": 4395.0,
                    "close": 4402.0,
                    "volume": 100.0,
                }
                for i in range(30)
            ]
            sig = StrategyEvaluator.evaluate("TestMockStrategy", "XAU/USD", candles)
            self.assertIsNotNone(sig)
            self.assertEqual(sig["lots"], 0.50)
            self.assertEqual(sig["lot_size"], 0.50)
            self.assertIn("0.50 lots", sig["annotation"])


class TestBrokerDiscoveryIsNotAuthentication(unittest.TestCase):
    """Listing installed adapters must not authenticate against a broker gateway."""

    def setUp(self):
        self._acc = accounts_store.add_account(
            broker_id="mock_live",
            telegram_user_id="discovery-test",
            telegram_chat_id="discovery-test",
            login="live@example.com",
            password="live-password",
            server="Live-Server",
            acc_num="9",
            default_lots=0.10,
        )
        self._saved_cls = broker_registry._broker_classes.get("mock_live")
        self._saved_inst = broker_registry._instances.pop("mock_live", None)
        broker_registry.register("mock_live", _MockLiveBroker)

    def tearDown(self):
        broker_registry._instances.pop("mock_live", None)
        if self._saved_inst is not None:
            broker_registry._instances["mock_live"] = self._saved_inst
        if self._saved_cls is not None:
            broker_registry._broker_classes["mock_live"] = self._saved_cls
        else:
            broker_registry._broker_classes.pop("mock_live", None)
        accounts_store.delete_account(self._acc["id"], "discovery-test")

    def test_listing_adapters_does_not_connect_them(self):
        before = _blocked_network_attempts()
        listed = broker_registry.list_available_brokers(connect=False)

        self.assertEqual(
            _blocked_network_attempts(), before,
            "discovery must not open a broker session",
        )
        ids = sorted(b["broker_id"] for b in listed)
        self.assertIn("paper", ids)
        self.assertIn("mock_live", ids)
        for broker in listed:
            self.assertIn("broker_id", broker.get("account_info", {}), broker)

    def test_discovery_never_caches_an_unconnected_adapter(self):
        first = broker_registry.get_broker("mock_live", connect=False)
        second = broker_registry.get_broker("mock_live", connect=False)

        self.assertNotIn("mock_live", broker_registry._instances)
        self.assertIsNot(first, second)
        self.assertFalse(first.is_connected)


class TestStatusSurfacesNeverAuthenticate(unittest.TestCase):
    """Read-only status surfaces (/api/brokers, Telegram /brokers, bot_control status) never call connect()."""

    def setUp(self):
        self._acc = accounts_store.add_account(
            broker_id="mock_live",
            telegram_user_id="status-test",
            telegram_chat_id="status-test",
            login="live@example.com",
            password="live-password",
            server="Live-Server",
            acc_num="9",
            default_lots=0.10,
        )
        self._saved_cls = broker_registry._broker_classes.get("mock_live")
        self._saved_inst = broker_registry._instances.pop("mock_live", None)
        broker_registry.register("mock_live", _MockLiveBroker)
        self.addCleanup(self._restore_registry)

    def _restore_registry(self):
        broker_registry._instances.pop("mock_live", None)
        if self._saved_inst is not None:
            broker_registry._instances["mock_live"] = self._saved_inst
        if self._saved_cls is not None:
            broker_registry._broker_classes["mock_live"] = self._saved_cls
        else:
            broker_registry._broker_classes.pop("mock_live", None)
        accounts_store.delete_account(self._acc["id"], "status-test")

    @contextlib.contextmanager
    def _connect_forbidden(self):
        def _explode(*args, **kwargs):
            raise AssertionError("a read-only status surface called connect()")

        with patch.object(_MockLiveBroker, "connect", _explode), \
             patch.object(_MockLiveBroker, "disconnect", lambda *_a, **_k: None):
            yield _MockLiveBroker

    def test_bare_listing_defaults_to_discovery(self):
        before = _blocked_network_attempts()
        with self._connect_forbidden():
            listed = broker_registry.list_available_brokers()

        self.assertEqual(_blocked_network_attempts(), before)
        entries = {b["broker_id"]: b["account_info"] for b in listed}
        self.assertIn("mock_live", entries)
        info = entries["mock_live"]
        self.assertFalse(info["connected"])
        self.assertEqual(info["balance"], 0.0)
        self.assertEqual(info["equity"], 0.0)
        self.assertTrue(info["accounts_configured"])
        self.assertEqual(info["multi_account_count"], 1)

    def test_api_brokers_endpoint_does_not_log_in(self):
        from server.main import list_brokers

        with self._connect_forbidden():
            payload = asyncio.run(list_brokers())

        ids = [b["broker_id"] for b in payload["brokers"]]
        self.assertIn("mock_live", ids)
        self.assertIn("paper", ids)

    def test_telegram_brokers_card_does_not_log_in(self):
        with self._connect_forbidden(), \
             patch("server.telegram_listener.telegram_gateway.send_message") as send:
            asyncio.run(telegram_listener._cmd_brokers(chat_id=4242))

        self.assertTrue(send.called)
        rendered = send.call_args[0][0]
        self.assertIn("mock_live", rendered)
        self.assertIn("paper", rendered)

    def test_bot_control_status_fallback_does_not_log_in(self):
        bot_control = _tools_module("bot_control")
        output = io.StringIO()

        with self._connect_forbidden(), \
             patch.object(bot_control.opener, "open", side_effect=URLError("server offline")), \
             contextlib.redirect_stdout(output):
            bot_control.show_broker_status("http://127.0.0.1:8000")

        text = output.getvalue()
        self.assertIn("mock_live", text)
        self.assertIn("not connected", text)
        self.assertNotIn("Balance: $0.00", text)

    def test_a_live_session_is_reused_without_a_new_login(self):
        with self._connect_forbidden():
            live = _MockLiveBroker()
            live.is_connected = True
            live.balance = 12_345.67
            live.equity = 12_456.78
            broker_registry._instances["mock_live"] = live

            listed = broker_registry.list_available_brokers()

        info = {b["broker_id"]: b["account_info"] for b in listed}["mock_live"]
        self.assertTrue(info["connected"])
        self.assertEqual(info["balance"], 12_345.67)
        self.assertEqual(info["equity"], 12_456.78)


if __name__ == "__main__":
    unittest.main()
