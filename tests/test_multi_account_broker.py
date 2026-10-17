"""
tests/test_multi_account_broker.py
─────────────────────────────────────────────────────────────
Comprehensive unit tests for multi-account broker architecture:
1. Generic AccountsStore (encryption, isolation, thread safety, masking)
2. Telegram Listener interactive commands & session wizard
3. TradeLockerBroker concurrent multi-account order execution
"""

import asyncio
import contextlib
import importlib.util
import io
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from server.accounts_store import accounts_store, SecretCipher
from server.brokers.registry import broker_registry
from server.telegram_listener import telegram_listener


class _FakeTradeLockerClient:
    """Records orders instead of sending them to a broker gateway."""

    def __init__(self, order_log):
        self.order_log = order_log
        self.closed_positions = []

    def get_account_state(self):
        return {"balance": 50_000.0, "equity": 50_000.0, "currency": "USD"}

    def create_order(self, **kwargs):
        self.order_log.append(kwargs)
        return {"id": f"order-{len(self.order_log)}", "price": kwargs.get("price") or 4400.0}

    def get_all_positions(self):
        return [{"id": "555001", "tradableInstrumentId": "6310"}]

    def close_position(self, position_id):
        self.closed_positions.append(position_id)
        return {"pnl": 12.5}


def _live_account(acc_id="acc-live", **overrides):
    account = {
        "id": acc_id, "broker_id": "tradelocker", "is_active": True, "environment": "live",
        "server": "Live-Server", "login": "live@test.com", "password": "p", "acc_num": "9",
        "default_lots": 0.10, "initial_balance": 50_000.0, "telegram_chat_id": None,
    }
    account.update(overrides)
    return account


_SIGNAL = {
    "action": "BUY", "symbol": "XAU/USD", "price": 4400.0,
    "stop_loss": 4390.0, "take_profit": 4425.0,
}


def _no_gateway_credentials(extra=None):
    """Env that cannot trigger a real gateway login, plus any NUJIN_* overrides."""
    env = {
        "TRADELOCKER_EMAIL": "", "TRADELOCKER_PASSWORD": "",
        "TRADELOCKER_SERVER": "", "TRADELOCKER_ACCOUNT_ID": "",
    }
    env.update(extra or {})
    return env


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
        """
        The stored format must be a property of this code, not of the environment.

        `encrypt()` used to prefer Fernet whenever `cryptography` happened to be importable,
        so the same account was persisted as `fn:` on one machine and `sl:` on another — and
        the machine without the package could not read the other's secret at all (it decrypted
        to an empty string, leaving the broker with no password). Credentials are written once
        and read by whichever process starts next, so a stray `pip install` must not be able to
        change the on-disk format.
        """
        def _explode(*_args, **_kwargs):
            raise AssertionError("encrypt() must not depend on the optional 'cryptography' package")

        fake_crypto = types.ModuleType("cryptography")
        fake_fernet = types.ModuleType("cryptography.fernet")
        fake_fernet.Fernet = _explode  # type: ignore[attr-defined]
        fake_crypto.fernet = fake_fernet

        with patch.dict(sys.modules, {"cryptography": fake_crypto, "cryptography.fernet": fake_fernet}):
            payload = SecretCipher().encrypt("hunter2")

        self.assertTrue(payload.startswith("sl:"), f"unexpected payload format: {payload[:8]!r}")
        # And it must be readable with no third-party package present at all.
        self.assertEqual(SecretCipher().decrypt(payload), "hunter2")

    def test_legacy_fernet_payload_fails_loudly_without_the_package(self):
        """
        A legacy `fn:` secret must name its missing dependency instead of looking like garbage.

        These blobs can only be read where `cryptography` is installed. An operator whose
        account suddenly stops connecting needs the cause in the log — the old bare
        `Decryption error: No module named 'cryptography'` reads like corrupt data.
        """
        with patch.dict(sys.modules, {"cryptography": None, "cryptography.fernet": None}), \
                self.assertLogs("AccountsStore", level="ERROR") as captured:
            self.assertEqual(SecretCipher().decrypt("fn:gAAAAA-not-really-a-token"), "")

        self.assertTrue(
            any("cryptography" in line for line in captured.output), captured.output,
        )

    def test_accounts_store_crud(self):
        user_id = "test_user_99"
        chat_id = "test_chat_99"

        # Add account
        acc = accounts_store.add_account(
            broker_id="tradelocker",
            telegram_user_id=user_id,
            telegram_chat_id=chat_id,
            login="trader99@example.com",
            password="securepass99",
            server="FunderPro Demo",
            acc_num="ACC-99",
            default_lots=0.20
        )
        acc_id = acc["id"]
        self.assertTrue(acc_id.startswith("trad_"))
        self.assertEqual(acc["default_lots"], 0.20)

        # Retrieve by user (masked)
        user_accs = accounts_store.get_accounts_by_user(user_id, mask=True)
        self.assertGreaterEqual(len(user_accs), 1)
        found = [a for a in user_accs if a["id"] == acc_id][0]
        self.assertEqual(found["login_masked"], "tr***@example.com")
        self.assertNotIn("password_encrypted", found)

        # Retrieve with decrypt
        decrypted_acc = accounts_store.get_account_by_id(acc_id, decrypt=True)
        self.assertIsNotNone(decrypted_acc)
        self.assertEqual(decrypted_acc["password"], "securepass99")

        # Update risk
        ok = accounts_store.update_account_risk(acc_id, user_id, 0.50)
        self.assertTrue(ok)
        updated = accounts_store.get_account_by_id(acc_id, decrypt=False)
        self.assertEqual(updated["default_lots"], 0.50)

        # Toggle active
        ok_toggle = accounts_store.toggle_account_active(acc_id, user_id, is_active=False)
        self.assertTrue(ok_toggle)
        toggled = accounts_store.get_account_by_id(acc_id, decrypt=False)
        self.assertFalse(toggled["is_active"])

        # Delete account
        ok_del = accounts_store.delete_account(acc_id, user_id)
        self.assertTrue(ok_del)
        self.assertIsNone(accounts_store.get_account_by_id(acc_id))

    def test_telegram_listener_helpers(self):
        self.assertTrue(telegram_listener._is_float("0.25"))
        self.assertFalse(telegram_listener._is_float("invalid"))
        self.assertTrue(telegram_listener._is_float("1"))

    @staticmethod
    def _tradelocker_broker():
        """
        Returns the TradeLocker broker, or skips the test.

        The execution adapter lives in the proprietary nujinPro plugin. Without it the
        registry logs a warning and falls back to the paper broker, so multi-account
        behaviour simply cannot be exercised — say so instead of asserting against paper.
        """
        broker = broker_registry.get_broker("tradelocker")
        if getattr(broker, "broker_id", "") != "tradelocker":
            raise unittest.SkipTest(
                "nujinPro TradeLocker broker not installed "
                f"(registry fell back to '{getattr(broker, 'broker_id', None)}')"
            )
        return broker

    def test_concurrent_multi_account_execution(self):
        """
        execute_order() must fan out to every active account, sized per account.

        Safety note: TradeLockerBroker.execute_order() sends an order for *every* active
        account it finds in accounts_store. The previous version of this test called it on
        the real broker instance against the real store, so on a machine with a funded
        TradeLocker account and the 'tradelocker' package installed it would have placed
        real market orders. The broker client and the account list are both stubbed here;
        only the fan-out logic is under test.
        """
        env = {
            "TRADELOCKER_EMAIL": "", "TRADELOCKER_PASSWORD": "",
            "TRADELOCKER_SERVER": "", "TRADELOCKER_ACCOUNT_ID": "",
        }
        orders = []
        accounts = [
            {
                "id": "acc-a", "broker_id": "tradelocker", "is_active": True,
                "server": "Server 1", "login": "a1@test.com", "password": "p1",
                "acc_num": "1", "default_lots": 0.10, "initial_balance": 100_000.0,
                "telegram_chat_id": None,
            },
            {
                "id": "acc-b", "broker_id": "tradelocker", "is_active": True,
                "server": "Server 2", "login": "a2@test.com", "password": "p2",
                "acc_num": "2", "default_lots": 0.30, "initial_balance": 50_000.0,
                "telegram_chat_id": None,
            },
        ]

        sig = {
            "action": "BUY",
            "symbol": "XAU/USD",
            "price": 4400.0,
            "stop_loss": 4390.0,
            "take_profit": 4425.0,
        }

        # Clearing the environment credentials before the broker is resolved means
        # get_broker() cannot attempt a real gateway login, whatever the developer has
        # exported in their shell or stored in their own accounts file.
        with patch.dict(os.environ, env):
            broker = self._tradelocker_broker()
            self.assertTrue(broker.supports_multi_account)
            with patch(
                "server.accounts_store.accounts_store.get_all_active_accounts",
                return_value=accounts,
            ), patch.object(
                broker, "_get_or_create_client", lambda acc: _FakeTradeLockerClient(orders)
            ):
                res = broker.execute_order(sig)

        self.assertEqual(res["status"], "FILLED")
        self.assertEqual(res["accounts_count"], 2)
        self.assertEqual(res["filled_count"], 2)
        self.assertEqual(res["preview_count"], 0)
        self.assertEqual({d["account_id"] for d in res["details"]}, {"acc-a", "acc-b"})

        # One order per account, sized from that account's own default_lots.
        self.assertEqual(len(orders), 2)
        self.assertEqual(sorted(o["quantity"] for o in orders), [0.10, 0.30])
        for order in orders:
            self.assertEqual(order["instrument_id"], 6310, "XAU/USD must resolve to the gold instrument")
            self.assertEqual(order["side"], "buy")
            self.assertEqual(order["type_"], "market")
            self.assertEqual(order["stop_loss"], 4390.0)
            self.assertEqual(order["stop_loss_type"], "absolute")
            self.assertEqual(order["take_profit"], 4425.0)

    def test_execute_order_simulates_when_no_active_account(self):
        """With no active account and no live client, nothing may reach the broker."""
        with patch.dict(os.environ, {
            "TRADELOCKER_EMAIL": "", "TRADELOCKER_PASSWORD": "",
            "TRADELOCKER_SERVER": "", "TRADELOCKER_ACCOUNT_ID": "",
        }), patch(
            "server.accounts_store.accounts_store.get_all_active_accounts",
            return_value=[],
        ):
            broker = self._tradelocker_broker()

        with patch(
            "server.accounts_store.accounts_store.get_all_active_accounts",
            return_value=[],
        ), patch.object(broker, "_client", None):
            res = broker.execute_order({
                "action": "BUY", "symbol": "XAU/USD", "price": 4400.0,
                "stop_loss": 4390.0, "take_profit": 4425.0,
            })

        self.assertEqual(res["status"], "SIMULATED_PREVIEW")
        self.assertGreater(res["filled_lots"], 0)
        self.assertEqual(res["filled_price"], 4400.0)

    # ── Live-order arming interlock ──────────────────────────────────────────

    def _execute_with_accounts(self, accounts, env_overrides):
        """Runs execute_order against stubbed accounts/clients; returns (result, orders, clients)."""
        orders = []
        built_clients = []

        def _client(acc):
            built_clients.append(acc.get("id"))
            return _FakeTradeLockerClient(orders)

        with patch.dict(os.environ, _no_gateway_credentials(env_overrides)), patch(
            "server.accounts_store.accounts_store.get_all_active_accounts",
            return_value=accounts,
        ):
            broker = self._tradelocker_broker()
            with patch.object(broker, "_get_or_create_client", _client):
                res = broker.execute_order(dict(_SIGNAL))

        return res, orders, built_clients

    def test_live_entries_are_refused_until_armed(self):
        """
        A live account must not receive an order unless the process is explicitly armed.

        Nothing else in the execution path distinguishes "the operator intended this live
        entry" from "some code path called execute_order()", so this is the last line of
        defence in front of a funded account.
        """
        res, orders, built_clients = self._execute_with_accounts([_live_account()], {"NUJIN_LIVE_TRADING": ""})

        self.assertEqual(res["status"], "BLOCKED_NOT_ARMED")
        self.assertEqual(res["filled_count"], 0)
        self.assertEqual(res["blocked_count"], 1)
        self.assertEqual(orders, [], "an order must never be sent while disarmed")
        self.assertEqual(
            built_clients, [],
            "a disarmed entry must not even build a broker client session",
        )

    def test_armed_live_account_receives_the_order(self):
        """With the switch set, the live path behaves as before."""
        res, orders, built_clients = self._execute_with_accounts([_live_account()], {"NUJIN_LIVE_TRADING": "1"})

        self.assertEqual(res["status"], "FILLED")
        self.assertEqual(res["filled_count"], 1)
        self.assertEqual(len(orders), 1)
        self.assertEqual(built_clients, ["acc-live"])

    def test_demo_accounts_are_unaffected_by_the_interlock(self):
        """Demo routing keeps working with the switch unset — no behaviour change."""
        res, orders, _clients = self._execute_with_accounts(
            [_live_account("acc-demo", environment="demo")], {"NUJIN_LIVE_TRADING": ""},
        )

        self.assertEqual(res["status"], "FILLED")
        self.assertEqual(len(orders), 1)

    def test_mixed_accounts_report_which_one_was_blocked(self):
        """One disarmed live account must not hide behind a demo account's fill."""
        res, orders, built_clients = self._execute_with_accounts(
            [_live_account(), _live_account("acc-demo", environment="demo")],
            {"NUJIN_LIVE_TRADING": ""},
        )

        self.assertEqual(res["status"], "FILLED", "the demo account still traded")
        self.assertEqual(res["blocked_count"], 1)
        blocked = [d for d in res["details"] if d["status"] == "BLOCKED_NOT_ARMED"]
        self.assertEqual([d["account_id"] for d in blocked], ["acc-live"])
        self.assertEqual(built_clients, ["acc-demo"])
        self.assertEqual(len(orders), 1)

    def test_arming_flag_parsing(self):
        """Only explicit truthy values arm live routing."""
        broker = self._tradelocker_broker()
        module = sys.modules[type(broker).__module__]

        for value, expected in (("1", True), ("true", True), ("YES", True), ("on", True),
                                ("0", False), ("", False), ("no", False), ("maybe", False)):
            with patch.dict(os.environ, {"NUJIN_LIVE_TRADING": value}), self.subTest(value=value):
                self.assertEqual(module.live_trading_armed(), expected)

    def test_disarming_never_blocks_position_management(self):
        """Exits must stay available: an operator has to be able to flatten a live position."""
        broker = self._tradelocker_broker()
        client = _FakeTradeLockerClient([])
        accounts = [_live_account()]

        with patch.dict(os.environ, _no_gateway_credentials({"NUJIN_LIVE_TRADING": ""})), patch(
            "server.accounts_store.accounts_store.get_all_active_accounts",
            return_value=accounts,
        ), patch.object(broker, "_get_or_create_client", lambda acc: client):
            res = broker.close_position(position_id="ALL", symbol="XAU/USD")

        self.assertNotEqual(res["status"], "BLOCKED_NOT_ARMED")
        self.assertEqual(res["status"], "CLOSED")
        # The broker casts numeric position ids to int for the TradeLocker API.
        self.assertEqual(client.closed_positions, [555001])

    def test_strategy_smart_lotsizer(self):
        """Tests that GoldPropSniperPro computes smart lot sizes dynamically by design."""
        try:
            from plugins.pro.strategies.GoldPropSniperPro import GoldPropSniperPro
        except ImportError as exc:
            # The proprietary strategy sources are not part of the open-source repo and are
            # not present on every machine (in this checkout only gitignored bytecode is
            # left), so this skips rather than fails. Say *why* it skipped, though: a bare
            # "plugin not available" hid the real cause for a while.
            self.skipTest(f"pro strategy source unavailable: {exc}")

        strat = GoldPropSniperPro()
        self.assertTrue(hasattr(strat, "calculate_lot_size"))

        # $100k account, Gold price 4400, 10 pt stop loss (risk = $500 on $1000/lot -> 0.50 lots)
        lots_100k = strat.calculate_lot_size(
            account_balance=100000.0,
            entry_price=4400.0,
            stop_loss=4390.0,
            symbol="XAU/USD"
        )
        self.assertEqual(lots_100k, 0.50)

        # $50k account -> 0.25 lots
        lots_50k = strat.calculate_lot_size(
            account_balance=50000.0,
            entry_price=4400.0,
            stop_loss=4390.0,
            symbol="XAU/USD"
        )
        self.assertEqual(lots_50k, 0.25)

        # $200k account -> 1.00 lots
        lots_200k = strat.calculate_lot_size(
            account_balance=200000.0,
            entry_price=4400.0,
            stop_loss=4390.0,
            symbol="XAU/USD"
        )
        self.assertEqual(lots_200k, 1.00)

        # High conviction (z_score >= 2.0) expands position
        lots_conviction = strat.calculate_lot_size(
            account_balance=100000.0,
            entry_price=4400.0,
            stop_loss=4390.0,
            symbol="XAU/USD",
            z_score=2.5
        )
        self.assertGreater(lots_conviction, lots_100k)
        self.assertEqual(lots_conviction, 0.57)

    def test_bot_lotsize_support(self):
        """Tests that PaperExecutionBroker and SignalStore record strategy lots."""
        from server.state_manager import signal_store
        from server.brokers.paper import PaperExecutionBroker

        broker = PaperExecutionBroker()
        sig = {
            "strategy": "GoldPropSniperPro",
            "pair": "XAU/USD",
            "action": "BUY",
            "price": 4400.0,
            "stop_loss": 4390.0,
            "take_profit": 4425.0,
            "lots": 0.50
        }

        # Verify paper broker fills with the strategy's lot size
        res = broker.execute_order(sig)
        self.assertEqual(res["status"], "FILLED")
        self.assertEqual(res["filled_lots"], 0.50)

        # Verify signal store records the strategy's lot size
        signals = signal_store.add(sig)
        latest = signals[0]
        self.assertEqual(latest["lots"], 0.50)
        self.assertEqual(latest["lot_size"], 0.50)

        # Clean up created test signal
        signal_store.clear("GoldPropSniperPro")

    def test_strategy_evaluator_lots(self):
        """Tests that StrategyEvaluator parses lots and lot_size from strategy signals."""
        from server.strategy_executor import StrategyEvaluator
        from unittest.mock import MagicMock, patch

        with patch("server.backtest_engine.load_strategy_instance") as mock_load:
            mock_strat = MagicMock()
            mock_strat.can_short = True
            mock_strat.stoploss = -0.0025
            mock_strat.minimal_roi = {"0": 0.005}
            mock_strat.atr_sl_mult = None
            mock_strat.atr_tp_mult = None
            mock_strat.min_bars = 1
            mock_strat.max_bars = 4

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
                    "volume": 100.0
                }
                for i in range(30)
            ]
            sig = StrategyEvaluator.evaluate("GoldPropSniperPro", "XAU/USD", candles)
            self.assertIsNotNone(sig)
            self.assertIn("lots", sig)
            self.assertIn("lot_size", sig)
            self.assertEqual(sig["lots"], 0.50)
            self.assertEqual(sig["lot_size"], 0.50)
            self.assertIn("0.50 lots", sig["annotation"])


class TestBrokerDiscoveryIsNotAuthentication(unittest.TestCase):
    """
    Listing the installed adapters must not authenticate against a broker gateway.

    `list_available_brokers()` used to instantiate *and connect* every registered adapter, so
    a read-only question — `/api/brokers`, the Telegram broker card, `bot_control.py status`,
    and this suite's own offline import audit — logged in to a live account using the
    credentials decrypted from the accounts store.

    The tests below therefore run with live-looking credentials *present* in the environment
    and a live account in the store, which is exactly the state that used to trigger a real
    login. `tests/conftest.py` blocks and records any outbound connection, so a regression
    fails here instead of reaching the gateway.
    """

    _LIVE_ENV = {
        "TRADELOCKER_ENVIRONMENT": "live",
        "TRADELOCKER_EMAIL": "live@example.com",
        "TRADELOCKER_PASSWORD": "live-password",
        "TRADELOCKER_SERVER": "Live-Server",
        "TRADELOCKER_ACCOUNT_ID": "9",
    }

    def setUp(self):
        self._acc = accounts_store.add_account(
            broker_id="tradelocker",
            telegram_user_id="discovery-test",
            telegram_chat_id="discovery-test",
            login="live@example.com",
            password="live-password",
            server="Live-Server",
            acc_num="9",
            default_lots=0.10,
        )

    def tearDown(self):
        accounts_store.delete_account(self._acc["id"], "discovery-test")

    @staticmethod
    def _network_attempts() -> int:
        """Number of outbound connections the session guard has blocked so far."""
        return _blocked_network_attempts()

    @staticmethod
    def _require_tradelocker_adapter() -> None:
        """Skips when the proprietary adapter is not installed (public checkout)."""
        broker_registry.scan_plugin_brokers()
        if "tradelocker" not in broker_registry._broker_classes:
            raise unittest.SkipTest("nujinPro TradeLocker broker adapter is not installed")

    def test_listing_adapters_does_not_connect_them(self):
        before = self._network_attempts()
        with patch.dict(os.environ, self._LIVE_ENV):
            listed = broker_registry.list_available_brokers(connect=False)

        self.assertEqual(
            self._network_attempts(), before,
            "discovery must not open a broker session, even with live credentials available",
        )
        ids = sorted(b["broker_id"] for b in listed)
        self.assertIn("paper", ids, "the built-in broker must always be discovered")
        # Discovery still reports the adapter's account info, which is store-backed.
        for broker in listed:
            self.assertIn("broker_id", broker.get("account_info", {}), broker)

    def test_discovery_never_caches_an_unconnected_adapter(self):
        """
        A throwaway adapter must not end up in the execution cache.

        `get_broker()` is what the executor asks for right before placing an order. If a
        discovery call cached an instance whose `connect()` never ran, that order would go to
        an adapter that merely *looks* healthy because the object exists.
        """
        self._require_tradelocker_adapter()
        saved = broker_registry._instances.pop("tradelocker", None)
        self.addCleanup(
            lambda: broker_registry._instances.update({"tradelocker": saved}) if saved else None
        )

        with patch.dict(os.environ, _no_gateway_credentials()):
            first = broker_registry.get_broker("tradelocker", connect=False)
            second = broker_registry.get_broker("tradelocker", connect=False)

        self.assertNotIn(
            "tradelocker", broker_registry._instances,
            "an unconnected adapter must never be cached for the executor to pick up",
        )
        self.assertIsNot(first, second, "each discovery call builds its own adapter")
        self.assertFalse(first.is_connected)


class TestStatusSurfacesNeverAuthenticate(unittest.TestCase):
    """
    The status surfaces are exercised through their real call sites, not the registry alone.

    Asserting only on `list_available_brokers(connect=False)` would prove the registry can be
    called safely while leaving `/api/brokers`, the Telegram `/brokers` card and
    `bot_control.py status` free to log in with a bare call. Here the TradeLocker adapter's
    `connect()` is replaced with an exploding stub — `connect()` is the login — so any of
    those paths reaching for a session fails on the spot instead of authenticating a funded
    account.
    """

    _LIVE_ENV = {
        "TRADELOCKER_ENVIRONMENT": "live",
        "TRADELOCKER_EMAIL": "live@example.com",
        "TRADELOCKER_PASSWORD": "live-password",
        "TRADELOCKER_SERVER": "Live-Server",
        "TRADELOCKER_ACCOUNT_ID": "9",
    }

    def setUp(self):
        self._acc = accounts_store.add_account(
            broker_id="tradelocker",
            telegram_user_id="status-test",
            telegram_chat_id="status-test",
            login="live@example.com",
            password="live-password",
            server="Live-Server",
            acc_num="9",
            default_lots=0.10,
        )
        # Start from a cold cache so a discovery surface has to build the adapter itself.
        self._saved = broker_registry._instances.pop("tradelocker", None)
        self.addCleanup(self._restore_instances)

    def _restore_instances(self):
        broker_registry._instances.pop("tradelocker", None)
        if self._saved is not None:
            broker_registry._instances["tradelocker"] = self._saved
        accounts_store.delete_account(self._acc["id"], "status-test")

    def _require_tradelocker_adapter(self) -> None:
        broker_registry.scan_plugin_brokers()
        if "tradelocker" not in broker_registry._broker_classes:
            raise unittest.SkipTest("nujinPro TradeLocker broker adapter is not installed")

    @contextlib.contextmanager
    def _connect_forbidden(self):
        """Makes any attempt to authenticate fail loudly, and asserts none was made."""
        self._require_tradelocker_adapter()
        adapter = broker_registry._broker_classes["tradelocker"]

        def _explode(*args, **kwargs):
            raise AssertionError(
                "a read-only status surface called connect(), which authenticates against "
                "the broker gateway with the account decrypted from the accounts store"
            )

        with patch.dict(os.environ, self._LIVE_ENV), \
             patch.object(adapter, "connect", _explode), \
             patch.object(adapter, "disconnect", lambda *_a, **_k: None):
            yield adapter

    def test_bare_listing_defaults_to_discovery(self):
        """The default must be read-only — a silent `connect=True` is how this began."""
        before = _blocked_network_attempts()
        with self._connect_forbidden():
            listed = broker_registry.list_available_brokers()  # deliberately no argument

        self.assertEqual(_blocked_network_attempts(), before)
        entries = {b["broker_id"]: b["account_info"] for b in listed}
        self.assertIn("tradelocker", entries)
        info = entries["tradelocker"]
        self.assertFalse(info["connected"], "nothing authenticated, so nothing is connected")
        self.assertEqual(info["balance"], 0.0)
        self.assertEqual(info["equity"], 0.0)
        # The configured accounts are still reported — that part is store-backed.
        self.assertTrue(info["accounts_configured"])
        self.assertEqual(info["multi_account_count"], 1)

    def test_api_brokers_endpoint_does_not_log_in(self):
        from server.main import list_brokers

        with self._connect_forbidden():
            payload = asyncio.run(list_brokers())

        ids = [b["broker_id"] for b in payload["brokers"]]
        self.assertIn("tradelocker", ids)
        self.assertIn("paper", ids)

    def test_telegram_brokers_card_does_not_log_in(self):
        with self._connect_forbidden(), \
             patch("server.telegram_listener.telegram_gateway.send_message") as send:
            asyncio.run(telegram_listener._cmd_brokers(chat_id=4242))

        self.assertTrue(send.called, "the card must still render")
        rendered = send.call_args[0][0]
        self.assertIn("tradelocker", rendered)
        self.assertIn("paper", rendered)

    def test_bot_control_status_fallback_does_not_log_in(self):
        bot_control = _tools_module("bot_control")
        output = io.StringIO()

        with self._connect_forbidden(), \
             patch.object(bot_control.opener, "open", side_effect=URLError("server offline")), \
             contextlib.redirect_stdout(output):
            bot_control.show_broker_status("http://127.0.0.1:8000")

        text = output.getvalue()
        self.assertIn("tradelocker", text)
        # No session exists offline, so the CLI says so instead of printing 0.00 as a figure.
        self.assertIn("not connected", text)
        self.assertNotIn("Balance: $0.00", text)

    def test_a_live_session_is_reused_without_a_new_login(self):
        """
        Status must still show real figures when the bot already has a session.

        The adapter the executor connected lives in the registry's instance cache, so the
        status surfaces read that session instead of opening one of their own — which is what
        makes discovery-only the honest default rather than a loss of information.
        """
        with self._connect_forbidden() as adapter:
            live = adapter()
            live.is_connected = True
            live.balance = 12_345.67
            live.equity = 12_456.78
            broker_registry._instances["tradelocker"] = live

            listed = broker_registry.list_available_brokers()

        info = {b["broker_id"]: b["account_info"] for b in listed}["tradelocker"]
        self.assertTrue(info["connected"])
        self.assertEqual(info["balance"], 12_345.67)
        self.assertEqual(info["equity"], 12_456.78)


if __name__ == "__main__":
    unittest.main()
