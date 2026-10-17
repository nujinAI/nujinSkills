"""
tests/conftest.py
─────────────────────────────────────────────────────────────
Session-wide isolation for the test suite.

Regression history: this suite used to run against whatever real state the developer's
machine happened to hold.

  * It added and deleted accounts in the live data/broker_accounts.json.
  * It appended a signal to the live data/signals.json and then called
    signal_store.clear("GoldPropSniperPro"), which deletes that strategy's real signals.
  * The TradeLocker tests constructed providers that performed live candle fetches on
    init, so they passed or failed depending on where the market happened to be.
  * broker.execute_order() places an order for every *active* account in the store, so
    test_concurrent_multi_account_execution was one funded account away from trading real
    money on the developer's broker.

Two invariants are enforced here instead:

  1. Every on-disk store the suite touches is redirected into a throwaway directory.
  2. Outbound network access fails loudly, so a test that reaches for live market data or
     a broker gateway fails on the spot instead of silently flapping with the market.

Set ``NUJIN_ALLOW_NETWORK_TESTS=1`` to opt out of (2) when deliberately exercising a live
feed. Tests that need a live connection should also be explicit about it rather than
inheriting it from the developer's environment.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

_ALLOW_NETWORK = os.environ.get("NUJIN_ALLOW_NETWORK_TESTS") == "1"

# ─────────────────────────────────────────────────────────────────────────────
# 1. Outbound network guard
# ─────────────────────────────────────────────────────────────────────────────

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", ""}


def _is_local(address: Any) -> bool:
    """Loopback and unix-socket targets are allowed; everything else is not."""
    if isinstance(address, tuple):
        if not address:
            return True
        host = str(address[0])
        return host in _LOCAL_HOSTS or host.startswith("127.")
    # AF_UNIX paths arrive as str/bytes and never leave the machine.
    return True


def _is_local_name(host: str) -> bool:
    """Local machine names are allowed; a literal IP is left to the connect guard."""
    if host in _LOCAL_HOSTS or host.startswith("127."):
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


class _BlockedOutboundNetwork(RuntimeError):
    """Raised when a test tries to reach the network."""


# Attempts are recorded as well as raised. Broker adapters wrap their connect calls in
# try/except, so an attempt can be swallowed and the test would still pass while quietly
# depending on a live gateway. Failing the session when anything was attempted closes that
# hole.
_BLOCKED_ATTEMPTS: List[Any] = []


def _deny(target: Any) -> None:
    _BLOCKED_ATTEMPTS.append(target)
    if os.environ.get("NUJIN_TRACE_NETWORK") == "1":
        # Debug aid: a swallowed attempt is otherwise hard to attribute. Run with
        # NUJIN_TRACE_NETWORK=1 to print the call site that reached for the network.
        import traceback
        traceback.print_stack()
    raise _BlockedOutboundNetwork(
        f"Blocked outbound connection to {target!r} during tests. "
        "Tests must not depend on live market data, broker gateways or remote APIs — "
        "patch the fetch/client instead. To run against a live feed on purpose, set "
        "NUJIN_ALLOW_NETWORK_TESTS=1."
    )


# The guard is installed when this conftest is imported rather than from a fixture: several
# modules seed providers from a live feed in *module-level* code, so merely importing them
# during collection would fetch before any fixture runs. conftest.py is imported before the
# test modules in this directory are collected, which closes that window.
_ORIGINALS: Dict[str, Any] = {}


def _install_socket_guard() -> None:
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_sendto = socket.socket.sendto
    real_create_connection = socket.create_connection
    real_getaddrinfo = socket.getaddrinfo
    real_gethostbyname = socket.gethostbyname
    _ORIGINALS.update(
        connect=real_connect,
        connect_ex=real_connect_ex,
        sendto=real_sendto,
        create_connection=real_create_connection,
        getaddrinfo=real_getaddrinfo,
        gethostbyname=real_gethostbyname,
    )

    def guard_connect(self, address, *args, **kwargs):
        if not _is_local(address):
            _deny(address)
        return real_connect(self, address, *args, **kwargs)

    def guard_connect_ex(self, address, *args, **kwargs):
        if not _is_local(address):
            _deny(address)
        return real_connect_ex(self, address, *args, **kwargs)

    def guard_sendto(self, data, *args, **kwargs):
        # sendto(data, address) or sendto(data, flags, address)
        candidates = [a for a in args if isinstance(a, (tuple, str, bytes))]
        for candidate in candidates:
            if isinstance(candidate, tuple) and not _is_local(candidate):
                _deny(candidate)
        return real_sendto(self, data, *args, **kwargs)

    def guard_create_connection(address, *args, **kwargs):
        if not _is_local(address):
            _deny(address)
        return real_create_connection(address, *args, **kwargs)

    def guard_getaddrinfo(host, *args, **kwargs):
        # Name resolution is the first network step for most clients, and it catches
        # callers that would otherwise fail later in a way tests rarely notice.
        if not _is_local_name(str(host)):
            _deny(host)
        return real_getaddrinfo(host, *args, **kwargs)

    def guard_gethostbyname(host):
        if not _is_local_name(str(host)):
            _deny(host)
        return real_gethostbyname(host)

    socket.socket.connect = guard_connect            # type: ignore[assignment]
    socket.socket.connect_ex = guard_connect_ex      # type: ignore[assignment]
    socket.socket.sendto = guard_sendto              # type: ignore[assignment]
    socket.create_connection = guard_create_connection  # type: ignore[assignment]
    socket.getaddrinfo = guard_getaddrinfo           # type: ignore[assignment]
    socket.gethostbyname = guard_gethostbyname       # type: ignore[assignment]


def _remove_socket_guard() -> None:
    socket.socket.connect = _ORIGINALS["connect"]          # type: ignore[assignment]
    socket.socket.connect_ex = _ORIGINALS["connect_ex"]    # type: ignore[assignment]
    socket.socket.sendto = _ORIGINALS["sendto"]            # type: ignore[assignment]
    socket.create_connection = _ORIGINALS["create_connection"]  # type: ignore[assignment]
    socket.getaddrinfo = _ORIGINALS["getaddrinfo"]        # type: ignore[assignment]
    socket.gethostbyname = _ORIGINALS["gethostbyname"]    # type: ignore[assignment]


if not _ALLOW_NETWORK:
    _install_socket_guard()


@pytest.fixture(scope="session", autouse=True)
def _block_outbound_network():
    if _ALLOW_NETWORK:
        yield
        return

    try:
        yield
    finally:
        _remove_socket_guard()
        if _BLOCKED_ATTEMPTS:
            attempted = ", ".join(sorted({str(t) for t in _BLOCKED_ATTEMPTS}))
            raise AssertionError(
                "the suite attempted outbound network access to "
                f"{attempted}, which means live market data, a broker gateway or a remote "
                "API leaked into a test (the failure may have been swallowed by a "
                "try/except). Patch the call instead, or set NUJIN_ALLOW_NETWORK_TESTS=1 "
                "when deliberately using a live feed."
            )


# ─────────────────────────────────────────────────────────────────────────────
# 2. On-disk state isolation
# ─────────────────────────────────────────────────────────────────────────────

# (object, attribute, sandbox filename) — every store the suite can reach.
def _redirects(sandbox: Path) -> List[Tuple[Any, str, Path]]:
    from server.accounts_store import accounts_store
    from server.state_manager import signal_store, state_manager, strategy_registry

    return [
        (accounts_store, "file_path", sandbox / "broker_accounts.json"),
        (accounts_store.cipher, "key_path", sandbox / ".secret_key"),
        (state_manager, "_path", sandbox / "state.json"),
        (signal_store, "_path", sandbox / "signals.json"),
        (strategy_registry, "_path", sandbox / "strategies.json"),
    ]


@pytest.fixture(scope="session", autouse=True)
def _isolate_live_state():
    """
    Points every persisted store at a temp directory for the whole session.

    Attribute-level redirection (rather than swapping module constants) matters: the
    singletons were built at import time with their real paths as bound defaults, so
    patching the module constant alone would leave the live file in use.
    """
    with tempfile.TemporaryDirectory(prefix="nujin-test-state-") as tmp:
        sandbox = Path(tmp)
        originals: Dict[Tuple[int, str], Tuple[Any, str, Any]] = {}
        for obj, attr, new_path in _redirects(sandbox):
            originals[(id(obj), attr)] = (obj, attr, getattr(obj, attr))
            setattr(obj, attr, new_path)
        yield sandbox
        for obj, attr, original in originals.values():
            setattr(obj, attr, original)
