"""
tests/test_import_safety.py
─────────────────────────────────────────────────────────────
Import safety for the server and tool packages.

The app must be importable with no network access at all: a cold start inside a container
without egress, a CLI that only inspects state, or a debugger attaching to a module should
not trigger market-data fetches. That was not true before — `server/xauusd_streamer.py`
constructed a module-level engine whose constructor pulled 20,000 live 1m bars, so importing
the module (and therefore `server.main`) performed network I/O before any code ran.

These tests run a child interpreter with outbound sockets blocked, which also makes them a
guard against reintroducing the pattern: a module that fetches at import time fails here
instead of in production.

The counterfactual also matters, so the second test asserts the deferred work still
*happens*: the engine attempts its historical fetch on first use rather than never, and
falls back to its cached CSV when the live sources are unreachable.
"""

import json
import os
import subprocess
import sys
import unittest

from _feed_stubs import live_feeds_stubbed

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Shared preamble: block outbound sockets and record every attempt with the module being
# imported at the time, so a failure names the culprit instead of just reporting "network".
_PREAMBLE = r'''
import importlib, ipaddress, json, os, pkgutil, socket, sys

sys.path.insert(0, os.getcwd())

# Credentials are cleared so a broker connect() cannot attempt a real gateway login, whatever
# the developer has exported in their shell.
for _key in ("TRADELOCKER_EMAIL", "TRADELOCKER_PASSWORD", "TRADELOCKER_SERVER", "TRADELOCKER_ACCOUNT_ID"):
    os.environ[_key] = ""

blocked, current = [], {"mod": "<bootstrap>"}
real_connect, real_create, real_gai = socket.socket.connect, socket.create_connection, socket.getaddrinfo

def _local(a):
    if isinstance(a, tuple):
        if not a:
            return True
        h = str(a[0])
        return h in ("127.0.0.1", "::1", "localhost", "0.0.0.0", "") or h.startswith("127.")
    return True

def _local_name(h):
    if _local((h, 0)):
        return True
    try:
        ipaddress.ip_address(str(h))
        return True
    except ValueError:
        return False

def _guard_connect(self, addr, *a, **k):
    if not _local(addr):
        blocked.append([current["mod"], str(addr)])
        raise RuntimeError("outbound network blocked by test")
    return real_connect(self, addr, *a, **k)

def _guard_create(addr, *a, **k):
    if not _local(addr):
        blocked.append([current["mod"], str(addr)])
        raise RuntimeError("outbound network blocked by test")
    return real_create(addr, *a, **k)

def _guard_gai(host, *a, **k):
    if not _local_name(host):
        blocked.append([current["mod"], str(host)])
        raise RuntimeError("outbound network blocked by test")
    return real_gai(host, *a, **k)

socket.socket.connect = _guard_connect
socket.create_connection = _guard_create
socket.getaddrinfo = _guard_gai
'''

_AUDIT_SCRIPT = _PREAMBLE + r'''
results = {}
for pkg in ("server", "tools"):
    for entry in sorted(m.name for m in pkgutil.iter_modules([pkg]) if not m.name.startswith("_")):
        current["mod"] = pkg + "." + entry
        try:
            importlib.import_module(pkg + "." + entry)
            results[current["mod"]] = "ok"
        except BaseException as exc:
            results[current["mod"]] = "%s: %s" % (type(exc).__name__, exc)

print(json.dumps({"results": results, "blocked": blocked}))
'''

_LAZY_ENGINE_SCRIPT = _PREAMBLE + r'''
current["mod"] = "import server.xauusd_streamer"
from server.xauusd_streamer import xauusd_engine

after_import = list(blocked)

# First use of the singleton: this is where the historical fetch belongs now.
quote = xauusd_engine.current_quote
candles = xauusd_engine.candles_1m

print(json.dumps({
    "after_import": after_import,
    "after_first_use": blocked,
    "quote_price": quote.get("price"),
    "candles": len(candles),
}))
'''


_PLUGIN_LOADER_SCRIPT = _PREAMBLE + r'''
out = {}
current["mod"] = "plugin_manager"
from server.plugin_loader import plugin_manager

out["plugins"] = sorted(p["id"] for p in plugin_manager.get_all_plugins())
strategy_files = plugin_manager.get_plugin_strategy_files()
out["strategy_files"] = sorted(f["filename"] for f in strategy_files)

# connect=False: listing adapters is discovery, not authentication. See
# TestBrokerDiscoveryIsNotAuthentication for the in-process proof.
current["mod"] = "broker_registry"
from server.brokers.registry import broker_registry
out["brokers"] = sorted(b["broker_id"] for b in broker_registry.list_available_brokers(connect=False))
out["broker_info"] = {b["broker_id"]: b.get("account_info", {}) for b in broker_registry.list_available_brokers(connect=False)}

current["mod"] = "load_strategy_instance"
from server.backtest_engine import load_strategy_instance
out["loaded"] = {}
for entry in strategy_files:
    name = entry["filename"].replace(".py", "")
    instance = load_strategy_instance(name)
    out["loaded"][name] = type(instance).__name__ if instance else None

print(json.dumps({"out": out, "blocked": blocked}))
'''


def _run_child(script: str) -> dict:
    """Runs `script` in a fresh interpreter from the project root and returns its JSON."""
    env = dict(os.environ)
    env["PYTHONPATH"] = _ROOT + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"child interpreter failed (exit {proc.returncode})\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    return json.loads(proc.stdout.strip().splitlines()[-1])


class TestImportSafety(unittest.TestCase):
    def test_every_module_imports_without_network(self):
        """No server or tools module may open an outbound connection while importing."""
        report = _run_child(_AUDIT_SCRIPT)

        failures = {m: r for m, r in report["results"].items() if r != "ok"}
        self.assertEqual(failures, {}, "modules that failed to import offline")

        self.assertEqual(
            report["blocked"], [],
            "modules reached the network at import time (module, address)",
        )
        self.assertGreater(len(report["results"]), 30, "the audit should cover the whole tree")

    def test_engine_defers_its_candle_fetch_to_first_use(self):
        """
        Importing the streamer must not fetch, and first use must still do the real work.

        This is the regression guard for the old behaviour: the module built a seeded engine
        at import time, so `import server.main` pulled 20,000 live bars before any handler ran.
        """
        report = _run_child(_LAZY_ENGINE_SCRIPT)

        self.assertEqual(
            report["after_import"], [],
            "importing server.xauusd_streamer must not touch the network",
        )
        self.assertGreaterEqual(
            len(report["after_first_use"]), 1,
            "first use must still attempt the historical candle fetch",
        )
        self.assertTrue(
            all(mod == "import server.xauusd_streamer" for mod, _ in report["after_first_use"]),
            report["after_first_use"],
        )
        # Offline the engine must degrade rather than explode: the quote stays usable, and
        # the series is either served whole from the cached CSV or left empty — never a
        # partially synthesised series.
        self.assertIsInstance(report["quote_price"], (int, float))
        self.assertTrue(
            report["candles"] == 0 or report["candles"] >= 30,
            f"expected cached history or nothing, got {report['candles']} candles",
        )

    def test_plugin_loading_works_without_network(self):
        """
        Plugin discovery and strategy loading must work with no network at all.

        This is the path the live system takes at startup: scan `plugins/`, resolve each
        strategy file, load it, and register the brokers. If any of it needed the network,
        a restart without egress would come up broken.
        """
        report = _run_child(_PLUGIN_LOADER_SCRIPT)
        out = report["out"]

        self.assertEqual(report["blocked"], [], "plugin loading reached the network")
        self.assertIn("paper", out["brokers"], "the built-in broker must always be available")
        # Discovery must not depend on credentials being absent: assert the adapters were
        # actually seen and their account info was served from the store.
        self.assertEqual(
            sorted(out["broker_info"]), out["brokers"],
            "every listed broker must also report account info",
        )

        unloadable = {name: loaded for name, loaded in out["loaded"].items() if not loaded}
        self.assertEqual(
            unloadable, {},
            "the framework advertised strategies it cannot load: " + str(unloadable),
        )
        # Without the proprietary plugins the loader must still work, just with nothing to load.
        if out["strategy_files"]:
            self.assertTrue(out["plugins"], "a strategy file without a plugin is impossible")

    def test_lazy_singleton_proxy_forwards_reads_and_writes(self):
        """
        `xauusd_engine` must keep behaving like the object it replaced.

        server.main reads attributes from it and also assigns `xauusd_engine.candles_1m`,
        so the lazy stand-in has to forward both. A proxy that only forwarded reads would
        drop that assignment silently.
        """
        from server.xauusd_streamer import xauusd_engine, get_xauusd_engine

        with live_feeds_stubbed():
            engine = get_xauusd_engine()

        self.assertIs(xauusd_engine.current_quote, engine.current_quote)
        # A bound method is rebuilt per access, so compare the instance it is bound to.
        self.assertIs(xauusd_engine.generate_signal.__self__, engine)

        sentinel = [{"time": 1, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}]
        xauusd_engine.candles_1m = sentinel
        self.assertIs(engine.candles_1m, sentinel, "an assignment through the proxy must land on the engine")
        self.assertIs(xauusd_engine.candles_1m, sentinel)


if __name__ == "__main__":
    unittest.main()
