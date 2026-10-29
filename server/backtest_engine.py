import os
import sys
import json
import time
import types
import importlib.util
import subprocess
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from server.state_manager import state_manager, strategy_registry
# Imported as a module, never as bound names: a module-level `from server.data_manager import
# sync_x` freezes the function into this namespace, which defeats monkeypatching
# server.data_manager and hides live fetches from anything that intercepts them there.
from server import data_manager
from server.cynic_gates import compute_dsr, verify_monte_carlo, evaluate_gates
from server.trial_ledger import record_trial, n_trials_for_dsr
from server.constants import trade_annualization_factor

try:
    from server.plugin_loader import plugin_manager
except ImportError:
    plugin_manager = None

logger = logging.getLogger("BacktestEngine")
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
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
            def populate_indicators(self, df, metadata): return df
            def populate_entry_trend(self, df, metadata): return df
            def populate_exit_trend(self, df, metadata): return df
        class _Parameter:
            def __init__(self, *args, **kwargs):
                self.value = kwargs.get('default', args[0] if len(args) > 0 else 0)
            def __int__(self): return int(self.value)
            def __float__(self): return float(self.value)
            def __repr__(self): return str(self.value)
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
        logger.warning(f"[BacktestEngine] Strategy file not found at {strat_path}")
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
                logger.info(f"[BacktestEngine] Successfully loaded strategy class: {attr_name} from {strat_path}")
                return obj()
    except Exception as e:
        logger.error(f"[BacktestEngine] Failed to load strategy instance for '{clean_name}': {e}")
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
    is_active_sys = (clean_name == curr_state.get("active_strategy"))

    strat_inst = load_strategy_instance(clean_name)
    strat_inst_symbol = getattr(strat_inst, "symbol", None) if strat_inst else None
    strat_inst_timeframe = getattr(strat_inst, "timeframe", None) if strat_inst else None

    # Single Source of Truth: Strategy class attributes have primary authority
    symbol = strat_inst_symbol or \
             (strat_record.get("symbol") if strat_record else None) or \
             (curr_state.get("symbol") if is_active_sys else None) or \
             "OANDA:XAUUSD"

    timeframe = timeframe_override or \
                strat_inst_timeframe or \
                (strat_record.get("timeframe") if strat_record else None) or \
                (curr_state.get("timeframe") if is_active_sys else None) or \
                "5m"

    target_profile = (strat_record.get("target_profile") if strat_record else None) or \
                     (curr_state.get("target_profile") if is_active_sys else None) or \
                     f"{clean_name} Profile"

    thesis = (strat_record.get("thesis") if strat_record else None) or \
             (curr_state.get("thesis_props", {}).get("thesis") if is_active_sys else None) or \
             f"Autonomous Alpha Model: {clean_name}"

    saved_thesis_props = curr_state.get("thesis_props", {}) if is_active_sys else {}
    thesis_props = {
        "thesis": thesis,
        "counterparty": saved_thesis_props.get("counterparty", "Trapped breakout liquidity / volatility expansion"),
        "invalidation": saved_thesis_props.get("invalidation", "Stop-loss triggered beyond structural extreme"),
        "target_profile": target_profile
    }

    return {
        "clean_name": clean_name,
        "symbol": symbol,
        "timeframe": timeframe,
        "target_profile": target_profile,
        "thesis": thesis,
        "thesis_props": thesis_props,
        "strat_record": strat_record or {}
    }

def resolve_asset_friction(symbol: str, price: float) -> Tuple[float, float, float]:
    """
    Returns (spread_pts, taker_fee_pct, slippage_pts) for realistic backtest friction.
    Asset-agnostic execution reality model:
    - Gold / Commodities (XAUUSD): typical spread $0.40, slippage $0.10.
    - Crypto (BTC/ETH): typical spread ~3 bps, taker fee 5 bps, slippage 1 bps.
    - Indices (SP500/NAS100): typical spread 0.50 pts, slippage 0.25 pts.
    - Forex (EURUSD/GBPUSD): typical spread ~1.5 pips, slippage 0.5 pips.
    """
    sym = (symbol or "").upper()
    if "XAU" in sym or "GOLD" in sym:
        spread_pts = 0.40
        fee_pct = 0.00005
        slippage_pts = 0.10
    elif any(k in sym for k in ["BTC", "ETH", "SOL", "USDT", "PERP"]):
        spread_pts = max(price * 0.0003, 0.5)
        fee_pct = 0.0005  # 5 bps
        slippage_pts = price * 0.0001
    elif any(k in sym for k in ["SP", "ES", "US500", "S&P", "NAS", "NQ", "US100"]):
        spread_pts = 0.50
        fee_pct = 0.00005
        slippage_pts = 0.25
    elif any(k in sym for k in ["EUR", "GBP", "USD", "JPY", "AUD", "CAD"]):
        spread_pts = price * 0.00015
        fee_pct = 0.00005
        slippage_pts = price * 0.00005
    else:
        spread_pts = price * 0.0004
        fee_pct = 0.0005
        slippage_pts = price * 0.0001
    return spread_pts, fee_pct, slippage_pts

def compute_strategy_parameter_stability_matrix(
    df_c: pd.DataFrame,
    strat_inst: Any,
    observed_sr: float,
    symbol: str = "BTC/USDT",
) -> Optional[np.ndarray]:
    """
    Computes a genuine 2x2 perturbed Sharpe matrix around the strategy's
    entry/exit signals and stop/target parameters so Gate 2
    (`gate_2_parameter_stability`) can be evaluated from real perturbed runs.
    """
    if strat_inst is None or len(df_c) < 60:
        return None
    try:
        if hasattr(strat_inst, "generate_signals"):
            from tools.core.backtest_engine import run_discrete_backtest
            df_idx = df_c.copy()
            if 'timestamp' in df_idx.columns:
                df_idx['dt'] = pd.to_datetime(df_idx['timestamp'], unit='s', utc=True)
                df_idx = df_idx.set_index('dt')
            sl_base = float(getattr(strat_inst, "sl_atr_mult", 1.0))
            tp_base = float(getattr(strat_inst, "tp_atr_mult", 1.5))
            matrix: List[List[float]] = []
            for sl_f in [0.92, 1.08]:
                row: List[float] = []
                for tp_f in [0.92, 1.08]:
                    try:
                        kwargs = {
                            "risk_pct_1r": getattr(strat_inst, "risk_pct_1r", 0.0035),
                            "sl_atr_mult": sl_base * sl_f,
                            "tp_atr_mult": tp_base * tp_f,
                            "max_hold_bars": getattr(strat_inst, "max_hold_bars", 6)
                        }
                        if hasattr(strat_inst, "max_daily_losses"):
                            kwargs["max_daily_losses"] = getattr(strat_inst, "max_daily_losses")
                        if hasattr(strat_inst, "daily_profit_cap_pct"):
                            kwargs["daily_profit_cap_pct"] = getattr(strat_inst, "daily_profit_cap_pct")
                        strat_copy = strat_inst.__class__(**kwargs)
                        sig = strat_copy.generate_signals(df_idx)
                        test_acct_size = 100000.0
                        test_dollar_risk = test_acct_size * getattr(strat_copy, "risk_pct_1r", 0.0035)
                        test_daily_cap = (test_acct_size * strat_copy.daily_profit_cap_pct) if getattr(strat_copy, "daily_profit_cap_pct", None) else None
                        res = run_discrete_backtest(
                            df=df_idx,
                            signals=sig,
                            symbol="OANDA:XAUUSD" if ("XAU" in symbol.upper() or "GOLD" in symbol.upper()) else symbol,
                            account_size=test_acct_size,
                            dollar_risk_1r=test_dollar_risk,
                            max_daily_losses=getattr(strat_copy, "max_daily_losses", 1),
                            daily_profit_cap=test_daily_cap,
                            max_hold_bars=getattr(strat_copy, "max_hold_bars", 6),
                            close_eod=True
                        )
                        rets = [t.pnl_dollars / test_acct_size for t in res["trades"]]
                        if len(rets) >= 5:
                            m_r = float(np.mean(rets))
                            s_r = float(np.std(rets, ddof=1)) or 1e-6
                            sr_p = float((m_r / s_r) * trade_annualization_factor())
                        else:
                            sr_p = 0.0
                    except Exception:
                        sr_p = 0.0
                    row.append(sr_p)
                matrix.append(row)
            return np.asarray(matrix, dtype=float)

        from tools.vectorized_screener import simulate_trades_fast

        enter_long = (df_c.get("enter_long", pd.Series(0, index=df_c.index)) == 1)
        enter_short = (df_c.get("enter_short", pd.Series(0, index=df_c.index)) == 1)
        exit_long = (df_c.get("exit_long", pd.Series(0, index=df_c.index)) == 1)
        exit_short = (df_c.get("exit_short", pd.Series(0, index=df_c.index)) == 1)

        base_sl = abs(float(getattr(strat_inst, "stoploss", -0.015)))
        roi_dict = getattr(strat_inst, "minimal_roi", {}) or {}
        base_tp = float(roi_dict.get("0", roi_dict.get(0, max(base_sl * 1.8, 0.025)))) if isinstance(roi_dict, dict) else max(base_sl * 1.8, 0.025)
        base_bars = int(getattr(strat_inst, "max_bars_held", getattr(strat_inst, "time_invalidation_bars", 16)) or 16)
        risk_pct = float(getattr(strat_inst, "risk_per_trade", getattr(strat_inst, "risk_per_trade_pct", 0.0045)) or 0.0045)
        use_trail = bool(getattr(strat_inst, "trailing_stop", False))
        base_trail_off = float(getattr(strat_inst, "trailing_stop_positive_offset", 0.010) or 0.010)

        med_price = float(df_c["close"].median()) if "close" in df_c.columns and len(df_c) > 0 else 100.0
        spread_pts, fee_pct, slip_pts = resolve_asset_friction(symbol, med_price)
        asset_fee_bps = float(fee_pct * 10000.0)
        asset_slip_bps = float(((spread_pts * 0.5 + slip_pts) / max(med_price, 1e-8)) * 10000.0)

        sl_factors = [0.92, 1.08]
        tp_factors = [0.92, 1.08]
        matrix: List[List[float]] = []

        for sl_f in sl_factors:
            row: List[float] = []
            for tp_f in tp_factors:
                rets, _ = simulate_trades_fast(
                    df_c,
                    enter_long=enter_long,
                    enter_short=enter_short,
                    exit_long=exit_long,
                    exit_short=exit_short,
                    stoploss_pct=max(0.001, base_sl * sl_f),
                    takeprofit_pct=max(0.002, base_tp * tp_f),
                    max_bars_held=max(4, int(round(base_bars * tp_f))),
                    fee_bps=asset_fee_bps,
                    slippage_bps=asset_slip_bps,
                    risk_per_trade_pct=risk_pct,
                    trailing_stop=use_trail,
                    trailing_offset_pct=max(0.001, base_trail_off * tp_f),
                )
                if len(rets) >= 5:
                    m_r = float(np.mean(rets))
                    s_r = float(np.std(rets, ddof=1)) or 1e-6
                    sr_p = float((m_r / s_r) * trade_annualization_factor())
                else:
                    sr_p = 0.0
                row.append(sr_p)
            matrix.append(row)
        return np.asarray(matrix, dtype=float)
    except Exception as e:
        logger.debug(f"[BacktestEngine] Parameter perturbation matrix warning: {e}")
        return None


def run_real_backtest(strategy_name: str = "", save_as_active: bool = False, timeframe_override: Optional[str] = None, days: Optional[int] = None) -> dict:
    """
    Executes real quantitative dual-directional (LONG & SHORT) backtest and DSR cynic audit.
    Zero hardcoded strategy logic: dynamically evaluates strategy definitions and rules
    loaded from strategies/*.py, data/strategies.json, and data/state.json as Single Source of Truth.
    Defaults to evaluating the full available historical dataset unless `days` is explicitly provided.
    """
    curr_sys_state = state_manager.get()
    if not strategy_name:
        strategy_name = strategy_registry.get_active_strategy_name()

    clean_name = strategy_name.replace(".py", "")
    logger.info(f"[BacktestEngine] Running dynamic quantitative backtest for strategy: {clean_name} (save_as_active={save_as_active})")

    meta = resolve_strategy_metadata(clean_name, timeframe_override=timeframe_override)
    symbol = meta["symbol"]
    timeframe = meta["timeframe"]
    thesis_props = meta["thesis_props"]
    strat_record = meta["strat_record"]

    cwd = _ROOT
    data_dir = os.path.join(_ROOT, "data")
    features_file = os.path.join(data_dir, "features.csv")
    returns_file = os.path.join(data_dir, "candidate_returns.json")
    feat_miner_script = os.path.join(_ROOT, "tools", "feature_miner.py")

    # 1. Resolve Candle Dataset and Sync via Dynamic Single Source of Truth
    from tools.core.data_tool import fetch_ohlcv
    from server import data_manager

    # Resolve canonical symbol and clean slug
    canon_sym = data_manager.resolve_market_symbol(symbol)
    slug = data_manager.canonical_market_slug(symbol)
    candles_file = data_manager.get_market_dataset_path(canon_sym, timeframe, check_legacy=True)
    is_gold = ("XAU" in canon_sym.upper()) or ("GOLD" in canon_sym.upper())
    is_sp500 = any(k in canon_sym.upper() for k in ["SP", "ES", "US500", "S&P"])

    logger.info(f"[BacktestEngine] Single Source of Truth fetch for {canon_sym} ({timeframe}) via tools/core/data_tool...")
    try:
        df_dynamic = fetch_ohlcv(symbol=canon_sym, timeframe=timeframe, count=5000, period="60d", use_cache=True)
        if df_dynamic is not None and not df_dynamic.empty:
            df_dynamic_reset = df_dynamic.reset_index()
            dt_col = df_dynamic_reset.columns[0]
            # Ensure standard timestamp and time columns in seconds
            df_dynamic_reset['timestamp'] = pd.to_datetime(df_dynamic_reset[dt_col], utc=True).apply(lambda x: int(x.timestamp()))
            df_dynamic_reset['time'] = df_dynamic_reset['timestamp']
            
            # Maintain disk cache consistency across canonical & legacy paths
            os.makedirs(os.path.dirname(candles_file), exist_ok=True)
            df_dynamic_reset.to_csv(candles_file, index=False)
            data_manager._save_canonical_and_legacy(canon_sym, timeframe, df_dynamic_reset, legacy_path=candles_file, source="data_tool_backtest")
    except Exception as e_dyn:
        logger.warning(f"[BacktestEngine] tools/core/data_tool fetch note: {e_dyn}, checking existing dataset on disk")

    if not os.path.exists(candles_file):
        raise FileNotFoundError(f"[BacktestEngine] Candle dataset file not found: {candles_file}")

    cmd_feat = [sys.executable, feat_miner_script, "--input", candles_file, "--output", features_file]

    # Always generate fresh features.csv
    logger.info(f"[BacktestEngine] Generating fresh feature set from {candles_file}...")
    try:
        subprocess.run(cmd_feat, cwd=_ROOT, check=True)
    except Exception as e_feat:
        logger.warning(f"[BacktestEngine] Feature miner warning: {e_feat}")

    # 2. Dynamic Strategy Loading & Indicator Computation
    strat_inst = load_strategy_instance(clean_name)
    
    if not os.path.exists(candles_file):
        raise FileNotFoundError(f"[BacktestEngine] Candle dataset file not found: {candles_file}")

    df_c = pd.read_csv(candles_file)
    df_c = df_c.dropna(subset=['open', 'high', 'low', 'close'])
    if 'timestamp' in df_c.columns:
        df_c['timestamp'] = df_c['timestamp'].ffill().bfill().fillna(0).astype(np.int64)
    df_c = df_c.reset_index(drop=True)
    n = len(df_c)
    if n < 50:
        raise ValueError(f"[BacktestEngine] Candle dataset contains insufficient rows: {n}")

    # Compute baseline candle geometry if not present
    df_c['total_range'] = (df_c['high'] - df_c['low']).replace(0, 1e-6)
    df_c['body_ratio'] = (df_c['close'] - df_c['open']).abs() / df_c['total_range']
    df_c['lower_wick'] = (np.minimum(df_c['close'], df_c['open']) - df_c['low']) / df_c['total_range']
    df_c['upper_wick'] = (df_c['high'] - np.maximum(df_c['close'], df_c['open'])) / df_c['total_range']
    
    vol_mean = df_c['volume'].rolling(20).mean()
    vol_std = df_c['volume'].rolling(20).std().replace(0, 1e-6)
    df_c['volume_zscore'] = (df_c['volume'] - vol_mean) / vol_std
    df_c['vol_z'] = df_c['volume_zscore']

    prev_close_c = df_c['close'].shift(1).fillna(df_c['open'])
    tr_c = np.maximum(df_c['high'] - df_c['low'], np.maximum((df_c['high'] - prev_close_c).abs(), (df_c['low'] - prev_close_c).abs()))
    df_c['atr_14'] = tr_c.rolling(14).mean().fillna(tr_c)

    # Extract strategy parameters dynamically from strategy instance
    if strat_inst:
        can_short = getattr(strat_inst, "can_short", True)
        stoploss_val = getattr(strat_inst, "stoploss", -0.02)
        stoploss_pct = abs(float(stoploss_val))
        minimal_roi = getattr(strat_inst, "minimal_roi", {})
        
        atr_multiplier = getattr(strat_inst, "atr_multiplier", None)
        atr_tp_mult = getattr(strat_inst, "atr_tp_mult", None)
        atr_sl_mult = getattr(strat_inst, "atr_sl_mult", None)
        min_wick_ratio = getattr(strat_inst, "min_wick_ratio", None)
        
        # Calculate dynamic holding windows from minimal_roi
        roi_keys = []
        if isinstance(minimal_roi, dict):
            for k in minimal_roi.keys():
                try:
                    roi_keys.append(int(k))
                except (ValueError, TypeError):
                    pass
        roi_keys.sort()
        
        # Minimum and maximum holding bars (anti-arbitrage or holding window)
        min_bars = getattr(strat_inst, "min_bars", getattr(strat_inst, "min_hold_bars", None))
        if min_bars is None:
            min_bars = 2 if "GOAT" in clean_name.upper() else 1
        strat_max_bars = getattr(strat_inst, "time_invalidation_bars", getattr(strat_inst, "max_bars", None))
        if strat_max_bars is not None and int(strat_max_bars) > 0:
            max_bars = int(strat_max_bars)
        elif roi_keys and max(roi_keys) > 10:
            max_bars = max(roi_keys)
        else:
            max_bars = 288  # 1 full daily session on 5m: allows full trend run protected by TP/SL/Trailing SL & session flatting

        # Trailing stop configuration
        use_trailing = getattr(strat_inst, "trailing_stop", False)
        trail_pos = float(getattr(strat_inst, "trailing_stop_positive", 0.0035))
        trail_offset = float(getattr(strat_inst, "trailing_stop_positive_offset", 0.0070))

        # Populate strategy indicators, entry, and exit trends (for legacy Freqtrade strategies)
        if hasattr(strat_inst, "populate_indicators"):
            try:
                df_c = strat_inst.populate_indicators(df_c, {})
                df_c = strat_inst.populate_entry_trend(df_c, {})
                df_c = strat_inst.populate_exit_trend(df_c, {})
            except Exception as e_strat_eval:
                logger.error(f"[BacktestEngine] Error executing strategy trend functions: {e_strat_eval}")
    else:
        # Fallback parameters from data/final_rules.json or defaults
        can_short = True
        stoploss_pct = 0.0025 if is_gold else 0.02
        minimal_roi = {"0": 0.003 if is_gold else 0.035, "12": 0.0}
        roi_keys = [0, 12]
        atr_tp_mult = None
        atr_sl_mult = None
        min_bars = 1
        max_bars = 15 if is_gold else 12
        use_trailing = False
        trail_pos = 0.0035
        trail_offset = 0.0070

        # Check session best_rule.json or data/final_rules.json
        from server.indicators import compute_all_standard_features
        from server.session_store import get_session_paths
        df_c = compute_all_standard_features(df_c, window=20)
        session_rule_path = get_session_paths(create_if_missing=False).get("best_rule", "")
        final_rules_path = os.path.join(data_dir, "final_rules.json")
        entry_rule = "ema_9 > ema_21 and ema_21 > ema_50 and adx_14 > 20"
        short_rule = "ema_9 < ema_21 and ema_21 < ema_50 and adx_14 > 20"
        for cand_rule_path in (session_rule_path, final_rules_path):
            if cand_rule_path and os.path.exists(cand_rule_path):
                try:
                    with open(cand_rule_path, "r") as rf:
                        f_rules = json.load(rf)
                        entry_rule = f_rules.get("entry_long", entry_rule)
                        short_rule = f_rules.get("entry_short", short_rule)
                        stoploss_pct = float(f_rules.get("stoploss_pct", f_rules.get("stop_loss_pct", stoploss_pct)))
                        break
                except Exception:
                    pass
        try:
            df_c['enter_long'] = df_c.eval(entry_rule).astype(int)
        except Exception:
            df_c['enter_long'] = 0
        try:
            df_c['enter_short'] = df_c.eval(short_rule).astype(int)
        except Exception:
            df_c['enter_short'] = 0

    # Ensure signals exist
    if 'enter_long' not in df_c.columns:
        df_c['enter_long'] = 0
    if 'enter_short' not in df_c.columns:
        df_c['enter_short'] = 0

    df_c['enter_long'] = df_c['enter_long'].fillna(0).astype(int)
    df_c['enter_short'] = df_c['enter_short'].fillna(0).astype(int)

    # 3. Dynamic Dual-Directional Sequential Simulation
    trade_markers = []
    trades_detail = []

    cutoff_time = (int(df_c['timestamp'].iloc[-1]) - int(days * 86400)) if (days and days > 0 and len(df_c) > 0 and 'timestamp' in df_c.columns) else 0

    if strat_inst and hasattr(strat_inst, "generate_signals"):
        from tools.core.backtest_engine import run_discrete_backtest
        df_idx = df_c.copy()
        df_idx['dt'] = pd.to_datetime(df_idx['timestamp'], unit='s', utc=True)
        df_idx = df_idx.set_index('dt')
        signals = strat_inst.generate_signals(df_idx)

        acct_size = float(getattr(strat_inst, "account_size", 100000.0))
        risk_pct = float(getattr(strat_inst, "risk_pct_1r", 0.0035))
        dollar_risk = acct_size * risk_pct
        max_daily_l = int(getattr(strat_inst, "max_daily_losses", 1))
        daily_cap_pct = getattr(strat_inst, "daily_profit_cap_pct", None)
        daily_cap = (acct_size * daily_cap_pct) if daily_cap_pct else getattr(strat_inst, "daily_profit_cap", None)
        max_hold_b = int(getattr(strat_inst, "max_hold_bars", 6))

        res_disc = run_discrete_backtest(
            df=df_idx,
            signals=signals,
            symbol="OANDA:XAUUSD" if is_gold else symbol,
            account_size=acct_size,
            dollar_risk_1r=dollar_risk,
            max_daily_losses=max_daily_l,
            daily_profit_cap=daily_cap,
            max_hold_bars=max_hold_b,
            close_eod=True
        )

        for idx, t in enumerate(res_disc["trades"]):
            entry_ts = int(t.entry_time.timestamp()) if hasattr(t.entry_time, 'timestamp') else int(t.entry_time)
            exit_ts = int(t.exit_time.timestamp()) if hasattr(t.exit_time, 'timestamp') else int(t.exit_time)
            if entry_ts < cutoff_time:
                continue

            side = "LONG" if t.direction == 1 else "SHORT"
            pnl_pct = round((t.pnl_dollars / acct_size) * 100.0, 4)
            spread_pts, fee_pct, slippage_pts = resolve_asset_friction(symbol, t.entry_price)
            friction_bps = round(((spread_pts * 2.0 / t.entry_price) + (fee_pct * 2.0) + (slippage_pts * 2.0 / t.entry_price)) * 10000.0, 1)

            exit_reason_map = {
                "TP": "TAKE_PROFIT",
                "SL": "STOP_LOSS",
                "TIME_STOP": "TIME_EXPIRATION",
                "EOD": "EOD"
            }
            exit_reason = exit_reason_map.get(t.exit_reason, t.exit_reason)

            price_fmt = f"${t.entry_price:.2f}"
            trade_markers.append({
                "time": entry_ts,
                "position": "belowBar" if side == "LONG" else "aboveBar",
                "color": "#26a69a" if side == "LONG" else "#ef5350",
                "shape": "arrowUp" if side == "LONG" else "arrowDown",
                "text": f"[BT] {side} {price_fmt}",
                "entry_price": round(float(t.entry_price), 2),
                "raw_signal_price": round(float(t.entry_price), 2),
                "stop_loss": round(float(t.stop_loss), 2),
                "take_profit": round(float(t.target), 2),
                "side": side
            })
            trade_markers.append({
                "time": exit_ts,
                "position": "aboveBar" if side == "LONG" else "belowBar",
                "color": "#26a69a" if t.pnl_dollars >= 0 else "#ef5350",
                "shape": "arrowDown" if side == "LONG" else "arrowUp",
                "text": f"[BT] EXIT {pnl_pct:+.2f}%"
            })

            trades_detail.append({
                "id": len(trades_detail) + 1,
                "side": side,
                "entry_time": entry_ts,
                "entry_price": round(float(t.entry_price), 2),
                "raw_signal_price": round(float(t.entry_price), 2),
                "stop_loss": round(float(t.stop_loss), 2),
                "take_profit": round(float(t.target), 2),
                "exit_time": exit_ts,
                "exit_price": round(float(t.exit_price), 2),
                "raw_exit_price": round(float(t.exit_price), 2),
                "exit_reason": exit_reason,
                "friction_bps": friction_bps,
                "pnl_pct": pnl_pct,
                "pnl_dollars": round(float(t.pnl_dollars), 2),
                "pnl_r": round(float(t.pnl_r), 3)
            })
    else:
        i = 100
        while i < n - 16:
            c = df_c.iloc[i]
            curr_close = float(c['close'])
            curr_low = float(c['low'])
            curr_high = float(c['high'])
            curr_open = float(c['open'])
            bar_time = int(c['timestamp']) if 'timestamp' in c else int(c.get('time', 0))

            is_long = bool(c['enter_long'] == 1)
            is_short = bool(c['enter_short'] == 1) if can_short else False

            # If both long and short trigger simultaneously, skip to prevent whipsaw
            if is_long and is_short:
                is_short = False

            if (is_long or is_short) and (bar_time >= cutoff_time):
                side = "LONG" if is_long else "SHORT"
                entry_time = bar_time

                # Weekend closure safeguard for traditional markets
                if (is_gold or is_sp500) and entry_time > 0:
                    dt_b = datetime.fromtimestamp(entry_time, tz=timezone.utc)
                    if (dt_b.weekday() == 5) or (dt_b.weekday() == 4 and dt_b.hour >= 21) or (dt_b.weekday() == 6 and dt_b.hour < 22):
                        i += 1
                        continue

                # Strict Realistic Execution (VectorBT / Freqtrade standard)
                # A signal on bar i is confirmed only when bar i closes.
                # The earliest physical fill is strictly the Close of bar i (or Open of bar i+1).
                # Intrabar fills on the signal candle are strictly prohibited to prevent lookahead bias.
                entry_price = round(curr_close, 2)
                spread_pts, fee_pct, slippage_pts = resolve_asset_friction(symbol, entry_price)
                entry_fill = round(entry_price + (spread_pts / 2.0) + slippage_pts if side == "LONG" else entry_price - (spread_pts / 2.0) - slippage_pts, 2)

                atr_val = float(c['atr_14']) if ('atr_14' in c and not np.isnan(c['atr_14'])) else entry_price * 0.005

                # Dynamic or Structural Stop Loss
                if 'structural_sl' in c and not np.isnan(c['structural_sl']):
                    stop_loss = round(float(c['structural_sl']), 2)
                elif atr_sl_mult is not None and atr_val > 0:
                    stop_loss = round(entry_price - atr_sl_mult * atr_val if side == "LONG" else entry_price + atr_sl_mult * atr_val, 2)
                else:
                    stop_loss = round(entry_price * (1.0 - stoploss_pct) if side == "LONG" else entry_price * (1.0 + stoploss_pct), 2)

                # Dynamic or Structural Take Profit
                if 'structural_tp' in c and not np.isnan(c['structural_tp']):
                    take_profit = round(float(c['structural_tp']), 2)
                elif atr_tp_mult is not None and atr_val > 0:
                    take_profit = round(entry_price + atr_tp_mult * atr_val if side == "LONG" else entry_price - atr_tp_mult * atr_val, 2)
                elif minimal_roi:
                    roi_0 = float(minimal_roi.get("0", minimal_roi.get(0, 0.035 if not is_gold else 0.005)))
                    take_profit = round(entry_price * (1.0 + roi_0) if side == "LONG" else entry_price * (1.0 - roi_0), 2)
                else:
                    take_profit = round(entry_price * (1.0 + stoploss_pct * 1.5) if side == "LONG" else entry_price * (1.0 - stoploss_pct * 1.5), 2)

                # Strict Quantitative Risk Sanity Check
                if side == "LONG" and (stop_loss >= entry_price or take_profit <= entry_price):
                    i += 1
                    continue
                elif side == "SHORT" and (stop_loss <= entry_price or take_profit >= entry_price):
                    i += 1
                    continue

                initial_sl = stop_loss
                initial_tp = take_profit

                # Sequential exit resolution
                exit_idx = i + 1
                exit_price = entry_price
                exit_reason = "TIME_EXPIRATION" if getattr(strat_inst, "time_invalidation_bars", None) else "BARS_HOLD"
                final_exit_idx = exit_idx

                while exit_idx < min(i + max_bars + 1, n):
                    bar_curr = df_c.iloc[exit_idx]
                    curr_l = float(bar_curr['low'])
                    curr_h = float(bar_curr['high'])
                    curr_c = float(bar_curr['close'])
                    bars_held = exit_idx - i

                    # Target Take Profit: Preserve ATR-based TP if configured, otherwise use time-decaying minimal_roi
                    if atr_tp_mult is not None and atr_val > 0:
                        target_tp = take_profit
                    elif minimal_roi:
                        target_tp = take_profit
                        for step_bar in sorted(roi_keys, reverse=True):
                            if bars_held >= step_bar:
                                step_roi = float(minimal_roi.get(str(step_bar), minimal_roi.get(step_bar, 0.0)))
                                if step_roi > 0:
                                    target_tp = round(entry_price * (1.0 + step_roi) if side == "LONG" else entry_price * (1.0 - step_roi), 2)
                                break
                    else:
                        target_tp = take_profit

                    # Pessimistic Intra-Bar Exit Resolution:
                    # 1. Always evaluate existing Stop-Loss FIRST (worst-case intra-bar path)
                    # 2. Then evaluate Take-Profit / Strategy Exit
                    # 3. Only ratchet Trailing Stop at the END of the bar if the trade survived the bar
                    if side == "LONG":
                        if curr_l <= stop_loss:
                            exit_price = stop_loss
                            exit_reason = "TRAIL_STOP" if stop_loss > entry_price else "STOP_LOSS"
                            final_exit_idx = exit_idx
                            break
                        elif curr_h >= target_tp and bars_held >= min_bars:
                            exit_price = target_tp
                            exit_reason = "TAKE_PROFIT"
                            final_exit_idx = exit_idx
                            break
                        elif bars_held >= min_bars and bar_curr.get('exit_long', 0) == 1:
                            exit_price = curr_c
                            exit_reason = "STRATEGY_EXIT"
                            final_exit_idx = exit_idx
                            break
                    else:  # SHORT
                        if curr_h >= stop_loss:
                            exit_price = stop_loss
                            exit_reason = "TRAIL_STOP" if stop_loss < entry_price else "STOP_LOSS"
                            final_exit_idx = exit_idx
                            break
                        elif curr_l <= target_tp and bars_held >= min_bars:
                            exit_price = target_tp
                            exit_reason = "TAKE_PROFIT"
                            final_exit_idx = exit_idx
                            break
                        elif bars_held >= min_bars and bar_curr.get('exit_short', 0) == 1:
                            exit_price = curr_c
                            exit_reason = "STRATEGY_EXIT"
                            final_exit_idx = exit_idx
                            break

                    # Ratchet Trailing Stop at bar close for the NEXT bar
                    if use_trailing and bars_held >= 1:
                        if side == "LONG":
                            max_gain = (curr_h - entry_price) / entry_price
                            if max_gain >= trail_offset:
                                new_sl = round(curr_h * (1.0 - trail_pos), 2)
                                stop_loss = max(stop_loss, new_sl)
                        else:
                            max_gain = (entry_price - curr_l) / entry_price
                            if max_gain >= trail_offset:
                                new_sl = round(curr_l * (1.0 + trail_pos), 2)
                                stop_loss = min(stop_loss, new_sl)

                    exit_price = curr_c
                    final_exit_idx = exit_idx
                    exit_idx += 1

                exit_bar = df_c.iloc[final_exit_idx]
                exit_time = int(exit_bar['timestamp']) if 'timestamp' in exit_bar else int(exit_bar.get('time', 0))

                # Physical fill accounting (spread + slippage + taker fees)
                if side == "LONG":
                    actual_exit_fill = round(exit_price - (spread_pts / 2.0) - slippage_pts, 2)
                    gross_pnl_pct = ((actual_exit_fill - entry_fill) / entry_fill) * 100.0
                else:
                    actual_exit_fill = round(exit_price + (spread_pts / 2.0) + slippage_pts, 2)
                    gross_pnl_pct = ((entry_fill - actual_exit_fill) / entry_fill) * 100.0

                total_fee_pct = (fee_pct * 2.0) * 100.0
                pnl_pct = round(gross_pnl_pct - total_fee_pct, 4)

                actual_tp = exit_price if exit_reason == "TAKE_PROFIT" else target_tp
                actual_sl = exit_price if exit_reason == "STOP_LOSS" else stop_loss

                price_fmt = f"${entry_fill:.2f}" if (is_gold or is_sp500) else f"${entry_fill:,.1f}"
                trade_markers.append({
                    "time": entry_time,
                    "position": "belowBar" if side == "LONG" else "aboveBar",
                    "color": "#26a69a" if side == "LONG" else "#ef5350",
                    "shape": "arrowUp" if side == "LONG" else "arrowDown",
                    "text": f"[BT] {side} {price_fmt}",
                    "entry_price": entry_fill,
                    "raw_signal_price": entry_price,
                    "stop_loss": initial_sl,
                    "take_profit": initial_tp,
                    "trailing_stop_exit": stop_loss if exit_reason == "TRAIL_STOP" else None,
                    "side": side
                })

                trade_markers.append({
                    "time": exit_time,
                    "position": "aboveBar" if side == "LONG" else "belowBar",
                    "color": "#26a69a" if pnl_pct >= 0 else "#ef5350",
                    "shape": "arrowDown" if side == "LONG" else "arrowUp",
                    "text": f"[BT] EXIT {pnl_pct:+.2f}%"
                })

                friction_bps = round(((spread_pts * 2.0 / entry_price) + (fee_pct * 2.0) + (slippage_pts * 2.0 / entry_price)) * 10000.0, 1)

                trades_detail.append({
                    "id": len(trades_detail) + 1,
                    "side": side,
                    "entry_time": entry_time,
                    "entry_price": entry_fill,
                    "raw_signal_price": entry_price,
                    "stop_loss": actual_sl,
                    "take_profit": actual_tp,
                    "exit_time": exit_time,
                    "exit_price": actual_exit_fill,
                    "raw_exit_price": exit_price,
                    "exit_reason": exit_reason,
                    "friction_bps": friction_bps,
                    "pnl_pct": pnl_pct
                })

                # Advance index past exit candle or apply cooldown to prevent overlapping trades/rapid churn
                i = max(final_exit_idx + 1, i + (25 if is_sp500 else 1))
            else:
                i += 1

    if len(trades_detail) == 0:
        raise RuntimeError(
            f"[BacktestEngine] Backtest produced zero trades for {clean_name} on {candles_file}. "
            "Verify that candle data exists and that strategy entry conditions can trigger."
        )

    # 4. Compute Single Source of Truth Returns & Statistics
    returns_arr = np.array([tr["pnl_pct"] / 100.0 for tr in trades_detail], dtype=float)

    # Save to candidate_returns.json for Cynic audit
    with open(returns_file, "w") as f:
        json.dump(returns_arr.tolist(), f)
        f.flush()
        os.fsync(f.fileno())

    trades = len(returns_arr)
    win_rate = float(np.mean(returns_arr > 0))
    gross_profit = float(np.sum(returns_arr[returns_arr > 0])) if np.any(returns_arr > 0) else 0.0
    gross_loss = float(np.abs(np.sum(returns_arr[returns_arr < 0]))) if np.any(returns_arr < 0) else 0.0
    profit_factor = round(min(gross_profit / gross_loss, 99.9), 2) if gross_loss > 1e-4 else (99.9 if gross_profit > 0 else 0.0)

    cum_ret = np.cumsum(returns_arr)
    peak = np.maximum.accumulate(cum_ret)
    dd = peak - cum_ret
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0.015

    mean_ret = float(np.mean(returns_arr))
    std_ret = float(np.std(returns_arr))
    # returns_arr is a TRADE-sampled series, so it annualises on the trade basis.
    sharpe = float((mean_ret / max(std_ret, 1e-6)) * trade_annualization_factor())
    expectancy_bps = float(mean_ret * 10000.0)

    # ── Genuine Cynic Audit ──────────────────────────────────────────────────
    # All gate math is delegated to server/cynic_gates.py (the single source of
    # truth). The complete matrix is assembled further below, once the regime
    # breakdown exists; these two scalars also feed the backtest summary.
    # N_trials must reflect how many hypotheses were actually searched. It was
    # previously derived from the trade count, which has no bearing on search
    # effort and made the DSR penalty arbitrary. Record this evaluation, then
    # read the auditable ledger.
    record_trial(
        kind="backtest",
        fingerprint=clean_name,
        metrics={"sharpe": round(sharpe, 2), "trades": trades},
        source="backtest_engine",
    )
    trials_penalized = n_trials_for_dsr()
    dsr_res = compute_dsr(returns_arr, trials_penalized)
    real_dsr = float(dsr_res.get("dsr", 0.0))
    mc_res = verify_monte_carlo(returns_arr)
    real_mdd_99 = float(mc_res.get("mdd_99", 0.0))

    # Derive accurate dataset time period
    valid_ts = df_c[df_c['timestamp'] > 1000000000]['timestamp'] if 'timestamp' in df_c.columns else pd.Series([])
    ds_end_ts = int(valid_ts.iloc[-1]) if len(valid_ts) > 0 else (int(trades_detail[-1]["exit_time"]) if trades_detail else int(time.time()))
    if days and days > 0 and len(valid_ts) > 0:
        raw_start = ds_end_ts - int(days * 86400)
        ds_start_ts = max(raw_start, int(valid_ts.iloc[0]))
        duration_days = round((ds_end_ts - ds_start_ts) / 86400, 1)
        candles_count = int((df_c['timestamp'] >= ds_start_ts).sum())
    else:
        ds_start_ts = int(valid_ts.iloc[0]) if len(valid_ts) > 0 else (int(trades_detail[0]["entry_time"]) if trades_detail else int(time.time()))
        duration_days = round((ds_end_ts - ds_start_ts) / 86400, 1)
        candles_count = len(df_c)
    dt_start = datetime.fromtimestamp(ds_start_ts, tz=timezone.utc)
    dt_end = datetime.fromtimestamp(ds_end_ts, tz=timezone.utc)
    start_date_str = dt_start.strftime("%Y-%m-%d %H:%M UTC")
    end_date_str = dt_end.strftime("%Y-%m-%d %H:%M UTC")
    period_label = f"{dt_start.strftime('%Y-%m-%d')} → {dt_end.strftime('%Y-%m-%d')} ({duration_days:.1f}d)"

    time_period_info = {
        "start_time": ds_start_ts,
        "end_time": ds_end_ts,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "duration_days": duration_days,
        "period_label": period_label,
        "candles_count": candles_count,
        "first_trade_time": trades_detail[0]["entry_time"] if trades_detail else ds_start_ts,
        "last_trade_time": trades_detail[-1]["exit_time"] if trades_detail else ds_end_ts,
    }

    backtest_summary = {
        "sharpe": round(sharpe, 2),
        "win_rate": round(win_rate, 3),
        "max_drawdown": round(max_dd, 4),
        "mdd_99": real_mdd_99,
        "dsr": real_dsr,
        "trades": trades,
        "profit_factor": profit_factor,
        "expectancy_bps": round(expectancy_bps, 2),
        "start_time": ds_start_ts,
        "end_time": ds_end_ts,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "duration_days": duration_days,
        "period_label": period_label,
        "candles_count": candles_count
    }

    # 5. Equity Curve, Return Distribution & Market Regime Breakdown
    df_c['sma50'] = df_c['close'].rolling(50).mean()
    regime_map = {}
    for _, r in df_c.iterrows():
        ts = int(r['timestamp']) if 'timestamp' in r else int(r.get('time', 0))
        c_val = float(r['close'])
        s_val = float(r['sma50']) if not np.isnan(r['sma50']) else c_val
        if c_val > s_val * 1.002:
            regime = "bull_market"
        elif c_val < s_val * 0.998:
            regime = "bear_market"
        else:
            regime = "ranging_market"
        regime_map[ts] = regime

    curr_equity = 100.0
    peak_equity = 100.0
    equity_curve = [{
        "time": trades_detail[0]["entry_time"],
        "equity_pct": 100.0,
        "drawdown_pct": 0.0
    }]

    regime_trades = {"bull_market": [], "bear_market": [], "ranging_market": []}
    for tr in trades_detail:
        curr_equity *= (1.0 + tr["pnl_pct"] / 100.0)
        peak_equity = max(peak_equity, curr_equity)
        dd_pct = round(((peak_equity - curr_equity) / peak_equity) * 100.0, 2)
        equity_curve.append({
            "time": tr["exit_time"],
            "equity_pct": round(curr_equity, 2),
            "drawdown_pct": dd_pct
        })
        reg = regime_map.get(tr["entry_time"], "ranging_market")
        tr["regime"] = reg
        regime_trades[reg].append(tr)

    regime_breakdown = {}
    for reg, tr_list in regime_trades.items():
        t_cnt = len(tr_list)
        if t_cnt > 0:
            arr_pnl = np.array([t["pnl_pct"] for t in tr_list])
            w_rate = float(np.mean(arr_pnl > 0))
            g_prof = float(np.sum(arr_pnl[arr_pnl > 0])) if np.any(arr_pnl > 0) else 0.0
            g_loss = float(np.abs(np.sum(arr_pnl[arr_pnl < 0]))) if np.any(arr_pnl < 0) else 0.0
            pf = round(min(g_prof / g_loss, 99.9), 2) if g_loss > 1e-4 else (99.9 if g_prof > 0 else 0.0)
            net_pnl = round(float(np.sum(arr_pnl)), 2)

            reg_eq = 100.0
            peak_reg_eq = 100.0
            max_reg_dd = 0.0
            reg_curve = [{"time": tr_list[0]["entry_time"], "equity_pct": 100.0, "drawdown_pct": 0.0, "trade_num": 0}]
            for idx_t, tr in enumerate(tr_list, start=1):
                reg_eq *= (1.0 + tr["pnl_pct"] / 100.0)
                peak_reg_eq = max(peak_reg_eq, reg_eq)
                dd_val = round(((peak_reg_eq - reg_eq) / peak_reg_eq) * 100.0, 2)
                max_reg_dd = max(max_reg_dd, dd_val)
                reg_curve.append({
                    "time": tr["exit_time"],
                    "equity_pct": round(reg_eq, 2),
                    "drawdown_pct": dd_val,
                    "pnl_pct": tr["pnl_pct"],
                    "trade_num": idx_t
                })

            regime_breakdown[reg] = {
                "trade_count": t_cnt,
                "win_rate": round(w_rate, 3),
                "profit_factor": pf,
                "net_pnl_pct": net_pnl,
                "peak_equity_pct": round(peak_reg_eq, 2),
                "max_drawdown_pct": round(max_reg_dd, 2),
                "equity_curve": reg_curve
            }
        else:
            regime_breakdown[reg] = {
                "trade_count": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "net_pnl_pct": 0.0,
                "peak_equity_pct": 100.0,
                "max_drawdown_pct": 0.0,
                "equity_curve": []
            }

    # Dynamic Return Distribution Histogram Bins
    all_pnls = [tr["pnl_pct"] for tr in trades_detail]
    std_pnl = float(np.std(all_pnls)) if len(all_pnls) > 1 else 1.0
    step = round(max(0.05, std_pnl * 0.75), 2)
    bins_def = [
        {"bin_label": f"<-{2*step:.2f}%", "min": -999.0, "max": -2*step, "win": False},
        {"bin_label": f"-{2*step:.2f}% to -{step:.2f}%", "min": -2*step, "max": -step, "win": False},
        {"bin_label": f"-{step:.2f}% to 0%", "min": -step, "max": 0.0, "win": False},
        {"bin_label": f"0% to +{step:.2f}%", "min": 0.0, "max": step, "win": True},
        {"bin_label": f"+{step:.2f}% to +{2*step:.2f}%", "min": step, "max": 2*step, "win": True},
        {"bin_label": f">+{2*step:.2f}%", "min": 2*step, "max": 999.0, "win": True}
    ]
    return_distribution = []
    for b in bins_def:
        cnt = sum(1 for p in all_pnls if b["min"] <= p < b["max"])
        return_distribution.append({
            "bin_label": b["bin_label"],
            "count": cnt,
            "win": b["win"]
        })

    # Build state dictionary
    # Compute Generic Account Growth Models across standard balance tiers ($5k, $10k, $25k, $50k, $100k)
    # Allows seamless visualization of Prop Firm / Leveraged Account returns vs Raw Spot Delta
    strat_risk_pct = getattr(strat_inst, 'risk_per_trade_pct', 0.0045) if strat_inst else 0.0045
    account_tiers = [5000, 10000, 25000, 50000, 100000]
    account_growth_models = {}
    
    # Growth multiplier relative to spot price move (calibrated for institutional lot sizing)
    if strat_inst and hasattr(strat_inst, "generate_signals"):
        account_mult = 1.0
    else:
        account_mult = round(float(strat_risk_pct / 0.0016), 4) if strat_risk_pct else 2.8191
    
    for tier in account_tiers:
        tier_bal = float(tier)
        peak_b = tier_bal
        tier_curve = [{"time": trades_detail[0]["entry_time"], "equity_pct": 100.0, "drawdown_pct": 0.0, "balance": tier_bal}]
        max_dd_tier = 0.0
        
        for tr in trades_detail:
            # Scaled account return percentage
            scaled_trade_pct = tr["pnl_pct"] * account_mult
            trade_dollar = tier_bal * (scaled_trade_pct / 100.0)
            tier_bal += trade_dollar
            peak_b = max(peak_b, tier_bal)
            dd_val = round(((peak_b - tier_bal) / peak_b) * 100.0, 2)
            max_dd_tier = max(max_dd_tier, dd_val)
            tier_curve.append({
                "time": tr["exit_time"],
                "equity_pct": round((tier_bal / float(tier)) * 100.0, 2),
                "drawdown_pct": dd_val,
                "balance": round(tier_bal, 2),
                "profit_dollars": round(tier_bal - float(tier), 2)
            })
            
        account_growth_models[str(tier)] = {
            "account_size": tier,
            "final_balance": round(tier_bal, 2),
            "net_growth_pct": round(((tier_bal - float(tier)) / float(tier)) * 100.0, 2),
            "net_profit_dollars": round(tier_bal - float(tier), 2),
            "max_drawdown_pct": round(max_dd_tier, 2),
            "equity_curve": tier_curve
        }

    # Standard benchmark account (defaults to $5,000 baseline)
    benchmark_model = account_growth_models.get("5000", {})
    account_summary = {
        "benchmark_tier": 5000,
        "net_growth_pct": benchmark_model.get("net_growth_pct", 5.82),
        "net_profit_dollars": benchmark_model.get("net_profit_dollars", 291.0),
        "max_drawdown_pct": benchmark_model.get("max_drawdown_pct", 1.15),
        "account_tiers": account_growth_models
    }

    state = {
        "active_strategy": clean_name if save_as_active else curr_sys_state.get("active_strategy", clean_name),
        "target_profile": thesis_props["target_profile"],
        "symbol": symbol,
        "timeframe": timeframe,
        "status": "ACTIVE_DEPLOYED" if save_as_active else curr_sys_state.get("status", "PREVIEW"),
        "backtest_summary": backtest_summary,
        "summary": backtest_summary,
        "account_summary": account_summary,
        "account_growth_models": account_growth_models,
        "time_period": time_period_info,
        "signals_count": len(trades_detail),
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trade_markers": trade_markers,
        "trades_detail": trades_detail,
        "equity_curve": equity_curve,
        "return_distribution": return_distribution,
        "regime_breakdown": regime_breakdown,
        "thesis_props": thesis_props
    }

    # ── Assemble the canonical Cynic gate matrix ────────────────────────────
    # Single source of truth: every gate (DSR, parameter stability, Monte
    # Carlo, OOS walk-forward, regime survival, friction/noise floor, noise
    # jitter, equity linearity) is computed by server/cynic_gates.py.
    #
    # Compute genuine perturbed parameter stability matrix around the strategy's
    # active parameters so Gate 2 is evaluated from real perturbed runs.
    perturbed_matrix = compute_strategy_parameter_stability_matrix(
        df_c=df_c,
        strat_inst=strat_inst,
        observed_sr=sharpe,
        symbol=symbol,
    )
    stop_dists_bps = np.array([
        abs(float(tr.get("entry_price", 1.0)) - float(tr.get("stop_loss", 1.0)))
        / max(float(tr.get("entry_price", 1.0)), 1e-8)
        * 10000.0
        for tr in trades_detail
    ], dtype=float)

    falsification_gates = evaluate_gates(
        returns_arr,
        n_trials=trials_penalized,
        strategy_name=clean_name,
        metric_matrix=perturbed_matrix,
        observed_sr=sharpe,
        regime_breakdown=regime_breakdown,
        returns_are_net=True,
    )
    state["falsification_gates"] = falsification_gates

    result = {
        "strategy": clean_name,
        "symbol": symbol,
        "timeframe": timeframe,
        "state": state,
        "candidate_returns": returns_arr.tolist(),
        "summary": backtest_summary,
        "time_period": time_period_info,
        "thesis_props": thesis_props,
        "trade_markers": trade_markers,
        "trades_detail": trades_detail,
        "equity_curve": equity_curve,
        "account_summary": account_summary,
        "account_growth_models": account_growth_models,
        "return_distribution": return_distribution,
        "regime_breakdown": regime_breakdown,
        "falsification_gates": falsification_gates
    }

    # 7. Update Single Source of Truth
    if save_as_active:
        state_manager.set_full(state)
        try:
            strategy_registry.update_status(clean_name, "ACTIVE_LIVE")
        except Exception as e_stat:
            logger.warning(f"[BacktestEngine] Could not update strategy status in registry: {e_stat}")

    try:
        strat_record = strategy_registry.record_backtest(clean_name, result, is_cron=False)
        if strat_record:
            result["drift_history"] = strat_record.get("cron_config", {}).get("drift_history", [])
            result["strategy_record"] = strat_record
    except Exception as e_reg:
        logger.warning(f"[BacktestEngine] Could not record backtest in strategy_registry: {e_reg}")

    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run Real Quantitative Backtest")
    parser.add_argument("--strategy", type=str, default="", help="Strategy name")
    parser.add_argument("--timeframe", type=str, default=None, help="Timeframe override")
    parser.add_argument("--days", type=int, default=None, help="Lookback days window")
    parser.add_argument("--save-active", action="store_true", help="Save as active strategy in state.json")
    args = parser.parse_args()

    res = run_real_backtest(
        strategy_name=args.strategy,
        save_as_active=args.save_active,
        timeframe_override=args.timeframe,
        days=args.days
    )
    s = res["summary"]
    print(f"\n=== BACKTEST COMPLETE: {res['strategy']} ===")
    print(f"Symbol: {res['symbol']} | Timeframe: {res['timeframe']}")
    print(f"Trades: {s['trades']} | Win Rate: {s['win_rate']*100:.1f}% | Profit Factor: {s['profit_factor']}")
    print(f"Sharpe: {s['sharpe']} | DSR: {s['dsr']} | Max DD: {s['max_drawdown']*100:.2f}%")
    print(f"Period: {s['period_label']} ({s['candles_count']} bars)")

