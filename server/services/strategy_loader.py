"""
server/services/strategy_loader.py - Dynamic Strategy Discovery & Reflection.
Single Source of Truth for resolving strategy metadata and instantiating strategy classes
from core strategies/ directory or installed plugins with Freqtrade interface shimming.
"""
import os
import sys
import types
import importlib.util
import logging
from typing import Optional, Any, Dict

from server.state_manager import state_manager, strategy_registry

try:
    from server.plugin_loader import plugin_manager
except ImportError:
    plugin_manager = None

logger = logging.getLogger("StrategyLoader")
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_PARENT = os.path.abspath(os.path.join(_ROOT, ".."))
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)
_ZILLIONS = os.path.join(_PARENT, "zillionsAlpha")
if os.path.exists(_ZILLIONS) and _ZILLIONS not in sys.path:
    sys.path.insert(0, _ZILLIONS)


def _ensure_freqtrade_shim():
    """Ensures freqtrade.strategy mocks are available in sys.modules so strategy files can be imported cleanly."""
    if "freqtrade" not in sys.modules:
        ft_mod = types.ModuleType("freqtrade")
        ft_strat_mod = types.ModuleType("freqtrade.strategy")

        class _IStrategy:
            INTERFACE_VERSION = 3
            timeframe = '15m'
            can_short = True
            stoploss = -0.02
            minimal_roi = {}

            def populate_indicators(self, df, metadata):
                return df

            def populate_entry_trend(self, df, metadata):
                return df

            def populate_exit_trend(self, df, metadata):
                return df

        class _Parameter:
            def __init__(self, *args, **kwargs):
                self.value = kwargs.get('default', args[0] if len(args) > 0 else 0)

            def __int__(self):
                return int(self.value)

            def __float__(self):
                return float(self.value)

            def __repr__(self):
                return str(self.value)

        ft_strat_mod.DecimalParameter = _Parameter
        ft_strat_mod.IntParameter = _Parameter
        ft_strat_mod.CategoricalParameter = lambda choices, default=None: default or choices[0]
        ft_strat_mod.BooleanParameter = bool
        sys.modules["freqtrade"] = ft_mod
        sys.modules["freqtrade.strategy"] = ft_strat_mod


def load_strategy_instance(strategy_name: str) -> Optional[Any]:
    """
    Dynamically loads and instantiates a strategy class from core strategies/ or installed plugins.
    Single Source of Truth: Executes the actual Python class implementing the strategy.
    """
    _ensure_freqtrade_shim()
    clean_name = strategy_name.replace(".py", "")
    strat_path = os.path.join(_ROOT, "strategies", f"{clean_name}.py")

    # If not in core, check plugin paths
    if not os.path.exists(strat_path) and plugin_manager:
        resolved = plugin_manager.resolve_strategy_path(clean_name)
        if resolved and os.path.exists(resolved):
            strat_path = resolved

    if not os.path.exists(strat_path):
        logger.warning(f"[StrategyLoader] Strategy file not found at {strat_path}")
        return None

    try:
        mod_name = f"edge_strategy_{clean_name}"
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        spec = importlib.util.spec_from_file_location(mod_name, strat_path)
        if not spec or not spec.loader:
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)

        # Locate strategy class in module
        for attr_name in dir(mod):
            if attr_name in ("IStrategy", "type"):
                continue
            obj = getattr(mod, attr_name)
            if isinstance(obj, type) and ((hasattr(obj, "populate_indicators") and hasattr(obj, "populate_entry_trend")) or hasattr(obj, "generate_signals")):
                logger.info(f"[StrategyLoader] Successfully loaded strategy class: {attr_name} from {strat_path}")
                return obj()
    except Exception as e:
        logger.error(f"[StrategyLoader] Failed to load strategy instance for '{clean_name}': {e}")
    return None


def resolve_strategy_metadata(strategy_name: str, timeframe_override: Optional[str] = None) -> dict:
    """
    Resolves strategy metadata dynamically using data/strategies.json and data/state.json
    as the Single Source of Truth.
    """
    clean_name = strategy_name.replace(".py", "")

    # 1. Query data/strategies.json via strategy_registry
    strat_record = strategy_registry.get(clean_name)
    if not strat_record:
        # Sync with filesystem and retry
        strategy_registry.sync_with_filesystem()
        strat_record = strategy_registry.get(clean_name)

    # 2. Query data/state.json via state_manager
    curr_state = state_manager.get()

    symbol = None
    timeframe = timeframe_override
    thesis_props = {}

    if strat_record:
        cron_cfg = strat_record.get("cron_config", {})
        symbol = cron_cfg.get("symbol") or strat_record.get("symbol")
        if not timeframe:
            timeframe = cron_cfg.get("timeframe") or strat_record.get("timeframe")
        thesis_props = strat_record.get("thesis_props", {})

    # Fallback to state.json if still unpopulated
    if not symbol:
        symbol = curr_state.get("symbol", "OANDA:XAUUSD")
    if not timeframe:
        timeframe = curr_state.get("timeframe", "15m")
    if not thesis_props:
        thesis_props = curr_state.get("thesis_props", {})

    # Ensure required thesis properties
    if not thesis_props.get("title"):
        thesis_props["title"] = strat_record.get("name", clean_name) if strat_record else clean_name
    if not thesis_props.get("hypothesis"):
        thesis_props["hypothesis"] = strat_record.get("description", "Systematic Alpha Model") if strat_record else "Systematic Alpha Model"
    if not thesis_props.get("market"):
        thesis_props["market"] = symbol
    if not thesis_props.get("target_profile"):
        thesis_props["target_profile"] = curr_state.get("target_profile", "conservative")

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "thesis_props": thesis_props,
        "strat_record": strat_record
    }
