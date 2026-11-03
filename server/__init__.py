"""
server package root.
Provides transparent backward-compatible aliases for legacy module paths.
"""
from __future__ import annotations

import sys
import importlib
import importlib.util
from importlib.abc import MetaPathFinder

_LEGACY_MODULE_MAP = {
    "server.data_manager": "server.services.data_manager",
    "server.backtest_engine": "server.services.backtest_engine",
    "server.strategy_executor": "server.services.strategy_executor",
    "server.bot_runner": "server.services.bot_runner",
    "server.risk_governor": "server.services.risk_governor",
    "server.drift_monitor": "server.services.drift_monitor",
    "server.cynic_gates": "core.cynic_gates",
    "server.indicators": "core.indicators",
    "server.market_structure": "server.services.market_structure",
    "server.chart_primitives": "server.services.chart_primitives",
    "server.alpha_models": "server.services.alpha_models",
    "server.state_manager": "server.state.state_manager",
    "server.accounts_store": "server.state.accounts_store",
    "server.session_store": "server.state.session_store",
    "server.trial_ledger": "server.state.trial_ledger",
    "server.telegram_bot": "server.telegram.telegram_bot",
    "server.telegram_listener": "server.telegram.telegram_listener",
    "server.websocket": "server.api.websocket",
}


class _LegacyServerAliasLoader:
    def __init__(self, target_mod_name: str):
        self.target_mod_name = target_mod_name

    def create_module(self, spec):
        mod = importlib.import_module(self.target_mod_name)
        sys.modules[spec.name] = mod
        return mod

    def exec_module(self, module):
        pass


class _LegacyServerAliasFinder(MetaPathFinder):
    """Transparently resolves legacy flat module imports to their new subpackage paths."""
    def find_spec(self, fullname, path, target=None):
        if fullname in _LEGACY_MODULE_MAP:
            target_mod = _LEGACY_MODULE_MAP[fullname]
            import importlib.machinery
            return importlib.machinery.ModuleSpec(
                fullname,
                _LegacyServerAliasLoader(target_mod),
                origin=target_mod
            )
        return None


if not any(isinstance(f, _LegacyServerAliasFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _LegacyServerAliasFinder())


def __getattr__(name: str):
    full_name = f"server.{name}"
    if full_name in _LEGACY_MODULE_MAP:
        mod = importlib.import_module(_LEGACY_MODULE_MAP[full_name])
        sys.modules[full_name] = mod
        return mod
    raise AttributeError(f"module 'server' has no attribute '{name}'")
