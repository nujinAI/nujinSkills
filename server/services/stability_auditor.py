"""
server/services/stability_auditor.py - Universal Parameter Perturbation Matrix Evaluator.
Evaluates Gate 2 (Parameter Stability) by executing real perturbed parameter runs
around ANY strategy's active entry, exit, stop loss, and target multipliers.
"""
import copy
import inspect
import logging
from typing import Optional, List, Dict, Any
import numpy as np
import pandas as pd

from server.constants import trade_annualization_factor
from core.data import resolve_market_symbol
from core.simulation import run_discrete_simulation as run_discrete_backtest, resolve_strategy_close_eod
from core.execution_engine import StrategyContract

logger = logging.getLogger("StabilityAuditor")


def _clone_with_perturbed_params(strat_inst: Any, sl_mult: float, tp_mult: float) -> Any:
    """
    Universally clones ANY user strategy instance with perturbed SL/TP multipliers.
    Works whether the class accepts constructor kwargs or uses class/instance attributes.
    """
    try:
        sig = inspect.signature(strat_inst.__class__.__init__)
        params = sig.parameters
        has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        contract = StrategyContract.from_strategy(strat_inst)
        candidate_kwargs = {
            "risk_pct_1r": contract.risk_pct_1r,
            "sl_atr_mult": sl_mult,
            "tp_atr_mult": tp_mult,
        }
        if contract.max_hold_bars is not None:
            candidate_kwargs["max_hold_bars"] = contract.max_hold_bars
        if hasattr(strat_inst, "max_daily_losses"):
            candidate_kwargs["max_daily_losses"] = getattr(strat_inst, "max_daily_losses")
        if hasattr(strat_inst, "daily_profit_cap_pct"):
            candidate_kwargs["daily_profit_cap_pct"] = getattr(strat_inst, "daily_profit_cap_pct")

        if has_var_kw:
            inst = strat_inst.__class__(**candidate_kwargs)
        else:
            filtered = {k: v for k, v in candidate_kwargs.items() if k in params}
            if filtered:
                inst = strat_inst.__class__(**filtered)
            else:
                inst = copy.deepcopy(strat_inst)
        # Ensure attributes reflect perturbed values even if __init__ ignores them
        if hasattr(inst, "sl_atr_mult"):
            setattr(inst, "sl_atr_mult", sl_mult)
        if hasattr(inst, "tp_atr_mult"):
            setattr(inst, "tp_atr_mult", tp_mult)
        return inst
    except Exception:
        inst = copy.deepcopy(strat_inst)
        setattr(inst, "sl_atr_mult", sl_mult)
        setattr(inst, "tp_atr_mult", tp_mult)
        return inst


def compute_strategy_parameter_stability_matrix(
    df_c: pd.DataFrame,
    strat_inst: Any,
    observed_sr: float,
    symbol: str = "BTC/USDT",
    account_size: Optional[float] = None,
    close_eod: Optional[bool] = None,
    eod_close_hour_utc: int = 21,
    daily_carry_bps: float = 0.0,
    friction_override: Optional[Dict[str, float]] = None,
) -> Optional[np.ndarray]:
    """
    Computes a genuine 2x2 perturbed Sharpe matrix around the strategy's
    entry/exit signals and stop/target parameters so Gate 2
    (`gate_2_parameter_stability`) can be evaluated from real perturbed runs.
    """
    if strat_inst is None or len(df_c) < 60:
        return None

    try:
        from server.services.backtest_engine import resolve_default_account_size
        test_acct_size = resolve_default_account_size(account_size)
        canon_sym = resolve_market_symbol(symbol)
        eff_close_eod = resolve_strategy_close_eod(strat_inst, canon_sym) if close_eod is None else bool(close_eod)

        if hasattr(strat_inst, "generate_signals"):
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
                        strat_copy = _clone_with_perturbed_params(strat_inst, sl_base * sl_f, tp_base * tp_f)
                        sig = strat_copy.generate_signals(df_idx)
                        test_dollar_risk = test_acct_size * float(getattr(strat_copy, "risk_pct_1r", getattr(strat_copy, "risk_per_trade_pct", 0.0035)))
                        test_daily_cap = (test_acct_size * strat_copy.daily_profit_cap_pct) if getattr(strat_copy, "daily_profit_cap_pct", None) else getattr(strat_copy, "daily_profit_cap", None)
                        copy_contract = StrategyContract.from_strategy(strat_copy)
                        res = run_discrete_backtest(
                            df=df_idx,
                            signals=sig,
                            symbol=canon_sym,
                            account_size=test_acct_size,
                            dollar_risk_1r=test_dollar_risk,
                            max_daily_losses=copy_contract.max_daily_losses,
                            daily_profit_cap=test_daily_cap,
                            max_hold_bars=copy_contract.max_hold_bars,
                            close_eod=eff_close_eod,
                            eod_close_hour_utc=eod_close_hour_utc,
                            daily_carry_bps=daily_carry_bps,
                            friction_override=friction_override,
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

        # Fallback for strategies defining populate_entry_trend / populate_exit_trend
        df_idx = df_c.copy()
        if 'timestamp' in df_idx.columns:
            df_idx['dt'] = pd.to_datetime(df_idx['timestamp'], unit='s', utc=True)
            df_idx = df_idx.set_index('dt')

        base_sl = abs(float(getattr(strat_inst, "stoploss", -0.015)))
        roi_dict = getattr(strat_inst, "minimal_roi", {}) or {}
        base_tp = float(roi_dict.get("0", roi_dict.get(0, max(base_sl * 1.8, 0.025)))) if isinstance(roi_dict, dict) else max(base_sl * 1.8, 0.025)
        base_bars = int(getattr(strat_inst, "max_bars_held", getattr(strat_inst, "time_invalidation_bars", 16)) or 16)
        risk_pct = float(getattr(strat_inst, "risk_per_trade", getattr(strat_inst, "risk_per_trade_pct", 0.0035)) or 0.0035)

        sl_factors = [0.92, 1.08]
        tp_factors = [0.92, 1.08]
        matrix = []

        for sl_f in sl_factors:
            row = []
            for tp_f in tp_factors:
                try:
                    close_s = df_idx["close"]
                    sig_df = pd.DataFrame(index=df_idx.index)
                    sig_df["entry_signal"] = 0
                    if "enter_long" in df_idx.columns and (df_idx["enter_long"] == 1).any():
                        sig_df.loc[df_idx["enter_long"] == 1, "entry_signal"] = 1
                    if "enter_short" in df_idx.columns and (df_idx["enter_short"] == 1).any():
                        sig_df.loc[df_idx["enter_short"] == 1, "entry_signal"] = -1

                    cur_sl_pct = max(0.001, base_sl * sl_f)
                    cur_tp_pct = max(0.002, base_tp * tp_f)
                    sig_df["stop_loss"] = np.where(sig_df["entry_signal"] == 1, close_s * (1.0 - cur_sl_pct), close_s * (1.0 + cur_sl_pct))
                    sig_df["target"] = np.where(sig_df["entry_signal"] == 1, close_s * (1.0 + cur_tp_pct), close_s * (1.0 - cur_tp_pct))

                    res = run_discrete_backtest(
                        df=df_idx,
                        signals=sig_df,
                        symbol=canon_sym,
                        account_size=test_acct_size,
                        dollar_risk_1r=test_acct_size * risk_pct,
                        max_hold_bars=max(4, int(round(base_bars * tp_f))),
                        close_eod=eff_close_eod,
                        eod_close_hour_utc=eod_close_hour_utc,
                        daily_carry_bps=daily_carry_bps,
                        friction_override=friction_override,
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
    except Exception as e:
        logger.debug(f"[StabilityAuditor] Parameter perturbation matrix warning: {e}")
        return None
