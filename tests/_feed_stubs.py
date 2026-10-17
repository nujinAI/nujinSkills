"""
tests/_feed_stubs.py
─────────────────────────────────────────────────────────────
Context manager that stubs every live market-data entry point the framework reaches for
while constructing market-data providers and streaming engines.

Why this exists: several constructors seed themselves from OANDA/TradingView/Binance and
wrap the fetch in ``try/except``, so the failure is swallowed and the test passes while
quietly depending on the network. ``tests/conftest.py`` blocks outbound connections and
fails the session when one is attempted; tests that must build those objects offline wrap
themselves in ``live_feeds_stubbed()`` and stay honest about it.

Every consumer now reaches these through the ``server.data_manager`` module object rather
than binding them at import time, so patching the module is sufficient — one interception
seam. ``test_framework_consistency`` enforces that, because a module-level
``from server.data_manager import fetch_x`` would silently defeat this stub.
"""

from contextlib import ExitStack, contextmanager
from typing import Any, Dict
from unittest.mock import patch

# Target -> value the stub returns. Every caller already treats an empty result as its
# offline path; no test in this suite asserts on live market data.
_STUBBED: Dict[str, Any] = {
    "server.data_manager.fetch_real_oanda_candles": [],
    "server.data_manager.fetch_real_comex_gold_candles": [],
    "server.data_manager.fetch_real_sp500_candles": [],
    "server.data_manager.fetch_real_binance_klines": [],
    "server.data_manager.fetch_candles_via_tv": [],
    "server.data_manager.get_oanda_spot_quote": {},
    "server.data_manager.sync_30d_candles": "",
    "server.data_manager.sync_xauusd_scalp_candles": "",
}

@contextmanager
def live_feeds_stubbed():
    """Stubs all live market-data fetches for the duration of the block."""
    with ExitStack() as stack:
        for target, empty in _STUBBED.items():
            stack.enter_context(patch(target, return_value=empty))
        yield
