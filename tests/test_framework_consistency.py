"""
Guards against the framework drifting out of sync again.

Each test here corresponds to a real defect that existed in this repository:
  * annualisation hardcoded per-tool instead of per-timeframe
  * thresholds copy-pasted into ~8 modules (3.0% vs 4.5%)
  * DSR's trial count derived from the number of trades
  * documentation claiming gate counts and limits the code did not enforce
"""

import ast
import builtins
import os
import re
import symtable

import pytest

from server import constants as C
from server.cynic_gates import DSR_THRESHOLD, compute_dsr, evaluate_gates
from server.trial_ledger import (
    MIN_TRIALS,
    count_trials,
    fingerprint,
    n_trials_for_dsr,
    record_trial,
)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# The invariants below apply to every module that runs in the bot's process, which includes
# installed plugins — a proprietary strategy or broker adapter executes the same gate
# mathematics and can hide the same copy-paste defect. Plugin directories are gitignored, so
# on a public checkout this list is just the framework itself.
_PLUGIN_MARKERS = ("plugin.json", "strategies")


def _audited_roots():
    roots = ["server", "tools"]
    plugins_dir = os.path.join(ROOT, "plugins")
    if os.path.isdir(plugins_dir):
        for entry in sorted(os.listdir(plugins_dir)):
            path = os.path.join(plugins_dir, entry)
            if not os.path.isdir(path):
                continue
            if any(os.path.exists(os.path.join(path, marker)) for marker in _PLUGIN_MARKERS):
                roots.append(os.path.join("plugins", entry))
    return roots


def _iter_sources():
    """Every audited .py file. Follows the plugin symlinks so their sources are covered."""
    for sub in _audited_roots():
        base = os.path.join(ROOT, sub)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base, followlinks=True):
            dirnames[:] = [
                d for d in dirnames if d not in {"__pycache__", ".git", "node_modules", ".venv"}
            ]
            for name in sorted(filenames):
                if name.endswith(".py"):
                    yield os.path.join(dirpath, name)


# ── Annualisation ────────────────────────────────────────────────────────────

def test_annualisation_is_timeframe_derived():
    assert C.bars_per_year("15m") == 252 * 24 * 4
    assert C.annualization_factor("15m") == pytest.approx(155.5362, rel=1e-4)
    assert C.annualization_factor("1h") == pytest.approx(77.7681, rel=1e-4)
    # Trade-sampled series use the house convention, not the bar factor.
    assert C.trade_annualization_factor() == pytest.approx(15.8745, rel=1e-4)
    # The bar factor and trade factor must not be interchangeable.
    assert C.annualization_factor("15m") / C.trade_annualization_factor() == pytest.approx(9.7979, rel=1e-3)


def test_unknown_timeframe_is_rejected():
    with pytest.raises(ValueError):
        C.bars_per_year("7m")


def test_no_annualisation_literals_outside_constants():
    """
    Every annualisation factor must come from server/constants.py.

    A stray `np.sqrt(252)` or `252 * 24 * 4` in some other module is exactly how the
    bar-vs-trade mix-up was born, so no other file may contain those numbers as code.
    Parsed with ast rather than grepped, so prose in docstrings/comments that explains
    the historical mistake does not trip the guard.
    """
    forbidden = {252, 24192}
    offenders = []

    for path in _iter_sources():
        if os.path.basename(path) == "constants.py":
            continue
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        try:
            tree = ast.parse(source)
        except SyntaxError as e:  # pragma: no cover - would fail other tests too
            offenders.append(f"{os.path.relpath(path, ROOT)}: unparsable ({e})")
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, int)
                and not isinstance(node.value, bool)
                and node.value in forbidden
            ):
                rel = os.path.relpath(path, ROOT)
                offenders.append(f"{rel}:{node.lineno}: literal {node.value}")

    assert not offenders, (
        "annualisation literals found outside server/constants.py:\n  "
        + "\n  ".join(sorted(offenders))
    )


# ── Single source of truth for thresholds ────────────────────────────────────

def test_gate_thresholds_come_from_constants():
    assert DSR_THRESHOLD is C.DSR_THRESHOLD
    assert C.MAX_DRAWDOWN == 0.030
    assert C.MIN_SHARPE == 1.80
    assert C.MIN_R2 == 0.85


def test_dsr_uses_the_trade_convention():
    rng = pytest.importorskip("numpy").random.default_rng(7)
    returns = rng.normal(0.0015, 0.01, size=60)
    assert compute_dsr(returns, 10)["annualization_periods"] == C.TRADE_PERIODS_PER_YEAR


# ── Trial ledger ─────────────────────────────────────────────────────────────

def test_trial_ledger_counts_distinct_hypotheses(tmp_path):
    ledger = str(tmp_path / "ledger.jsonl")

    record_trial("backtest", fingerprint="alpha", path=ledger)
    record_trial("backtest", fingerprint="beta", path=ledger)
    record_trial("backtest", fingerprint="alpha", path=ledger)  # re-audit, same hypothesis

    assert count_trials(path=ledger) == 2
    assert n_trials_for_dsr(path=ledger) == 2


def test_trial_ledger_floors_at_two(tmp_path):
    ledger = str(tmp_path / "empty.jsonl")
    # log(1) == 0 degenerates the expected-max-Sharpe term, so never report < 2.
    assert n_trials_for_dsr(path=ledger) == MIN_TRIALS


def test_fingerprint_is_stable_and_order_independent():
    assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})
    assert fingerprint({"a": 1}) != fingerprint({"a": 2})


# ── Generated strategy code ──────────────────────────────────────────────────

def _doc_files():
    docs = []
    for sub in (ROOT, os.path.join(ROOT, "references")):
        if not os.path.isdir(sub):
            continue
        for name in os.listdir(sub):
            if name.endswith(".md"):
                docs.append(os.path.join(sub, name))
    return docs

def test_docs_contain_no_stale_gate_claims():
    # Docs may *discuss* the historical mistake (e.g. the old 4.5% ceiling), so
    # this only forbids the unambiguous stale gate-count claims. The code side is
    # covered by test_emitter_uses_shared_constants, which asserts the emitted
    # strategy carries the real ceiling.
    stale = re.compile(r"\b(?:5|6)-Gate\b|5 Cynic|/5 Gates")
    offenders = []
    for path in _doc_files():
        with open(path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                if stale.search(line):
                    offenders.append(f"{os.path.relpath(path, ROOT)}:{lineno}")
    assert not offenders, f"stale gate claims remain: {offenders}"


def test_docs_state_the_canonical_drawdown_ceiling():
    """The documented drawdown limit must be the one the code enforces."""
    audit_doc = os.path.join(ROOT, "references", "cynic_audit.md")
    with open(audit_doc, "r", encoding="utf-8") as f:
        text = f.read()
    assert f"{C.MAX_MDD_99 * 100:.1f}\\%" in text


def test_docs_describe_the_canonical_gate_count():
    audit_doc = os.path.join(ROOT, "references", "cynic_audit.md")
    with open(audit_doc, "r", encoding="utf-8") as f:
        text = f.read()
    assert "8 Canonical Gates" in text
    assert "INCONCLUSIVE" in text
    assert "cynic_gates.py" in text


# ── One interception seam for live market data ───────────────────────────────

# Names in server/data_manager.py that reach the network. Pure helpers such as
# `_timeframe_to_seconds` and `resample_candles` may still be imported directly.
NETWORK_FETCHERS = ("fetch_", "sync_", "get_oanda_spot_quote")


def _module_level_data_manager_binds(path):
    """(name, lineno) for every name bound from data_manager at module scope."""
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    binds = []
    for node in tree.body:  # module scope only; function-local imports are fine
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("data_manager"):
            binds.extend((alias.name, node.lineno) for alias in node.names)
    return binds


def test_live_fetches_are_reached_through_the_data_manager_module():
    """
    Live fetchers must not be frozen into another module's namespace.

    `from server.data_manager import fetch_x` at import time copies the function object into
    the importing module, so patching `server.data_manager` — which is what the test stubs
    and the offline import audit rely on — no longer intercepts the call. That is exactly
    how live fetches used to escape both. `import server.data_manager` and call
    `data_manager.fetch_x(...)` instead; a function-local import resolves through the module
    at call time and is therefore fine.
    """
    offenders = []
    for path in _iter_sources():
        if os.path.abspath(path) == os.path.join(ROOT, "server", "data_manager.py"):
            continue
        rel = os.path.relpath(path, ROOT)
        for bound, lineno in _module_level_data_manager_binds(path):
            if bound.startswith(NETWORK_FETCHERS):
                offenders.append(f"{rel}:{lineno} binds {bound}")

    assert offenders == [], (
        "route these through the data_manager module so a single seam intercepts them: "
        + "; ".join(sorted(offenders))
    )


# ── Discovery must not authenticate ──────────────────────────────────────────

def test_adapter_listing_always_states_whether_it_connects():
    """
    Listing adapters is a read-only question, so no call site may rely on the default.

    `list_available_brokers()` used to default to `connect=True`, and `connect()` is the
    login: `/api/brokers`, the Telegram `/brokers` card and `tools/bot_control.py status` each
    authenticated a funded account just to print which adapters were installed. The default
    is discovery-only now, but a silent default is exactly what let that happen unnoticed —
    so every call site must name the behaviour it wants. Wanting a live session has to be
    written down as `connect=True`.
    """
    offenders = []
    for path in _iter_sources():
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name != "list_available_brokers":
                continue
            if not any(kw.arg == "connect" for kw in node.keywords):
                offenders.append(f"{os.path.relpath(path, ROOT)}:{node.lineno}")

    assert offenders == [], (
        "pass connect=False for discovery, or connect=True to ask for a live session "
        "explicitly: " + "; ".join(sorted(offenders))
    )


# ── Every name a function reads must exist ───────────────────────────────────

_ALWAYS_DEFINED = set(dir(builtins)) | {
    "__file__", "__name__", "__doc__", "__builtins__", "__spec__", "__package__",
    "__loader__", "__debug__", "__annotations__",
}


def _undefined_globals(path):
    """Names a function/class scope reads as a global that the module never defines."""
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    table = symtable.symtable(source, path, "exec")
    allowed = _ALWAYS_DEFINED | {sym.get_name() for sym in table.get_symbols()}

    offenders = set()

    def visit(scope):
        for sym in scope.get_symbols():
            if sym.is_global() and not sym.is_assigned() and sym.get_name() not in allowed:
                offenders.add(sym.get_name())
        for child in scope.get_children():
            if child.get_type() in ("function", "class"):
                visit(child)

    visit(table)
    return sorted(offenders)


def test_no_function_reads_an_undefined_global():
    """
    Catches the copy-paste class of defect: an error handler naming another scope's variable.

    Two real bugs were found this way. `server/state_manager.py` logged `py_path` — a name
    that only exists in `remove_strategy()` — from inside `_infer_metadata()`'s exception
    handler, so the handler itself raised NameError and the error escaped. And
    `server/telegram_listener.py` used `json` and `time` without importing them, which
    silently disabled daily-report state persistence because both call sites sit in
    `try/except` blocks that swallowed the NameError.

    `symtable` resolves scopes properly, so closures, class bodies and module-level
    `__main__` blocks are not reported as offenders.
    """
    offenders = []
    for path in _iter_sources():
        rel = os.path.relpath(path, ROOT)
        offenders.extend(f"{rel} reads undefined global {bad}" for bad in _undefined_globals(path))

    assert offenders == [], "; ".join(offenders)


def test_plugin_sources_are_covered_by_these_guards():
    """
    Guard the guard: the audits must actually reach installed plugin code.

    Plugin sources live behind symlinks under `plugins/`. If the traversal silently stopped
    descending (or the marker check stopped matching), every plugin would quietly drop out of
    the annualisation, interception-seam and undefined-global audits while still passing.
    """
    relative = [os.path.relpath(path, ROOT) for path in _iter_sources()]
    audited = {tuple(rel.split(os.sep)[:2]) for rel in relative}

    assert any(
        rel[0] == "server" for rel in audited
    ), "the framework itself must always be audited"

    plugins_dir = os.path.join(ROOT, "plugins")
    installed = [
        entry for entry in sorted(os.listdir(plugins_dir))
        if os.path.isdir(os.path.join(plugins_dir, entry))
        and entry != "__pycache__"
        and any(os.path.exists(os.path.join(plugins_dir, entry, marker)) for marker in _PLUGIN_MARKERS)
    ] if os.path.isdir(plugins_dir) else []

    for plugin in installed:
        assert any(rel[0] == "plugins" and rel[1] == plugin for rel in audited), (
            f"plugin '{plugin}' is installed but no source file was audited — "
            "the traversal no longer follows it"
        )

    if installed:
        assert any(
            rel.startswith("plugins" + os.sep) and f"{os.sep}brokers{os.sep}" in rel
            for rel in relative
        ), "plugin subpackages (brokers/, strategies/) must be traversed, not just plugin roots"
