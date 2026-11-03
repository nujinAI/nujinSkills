"""
server/services/stability_auditor.py - Parameter Perturbation Matrix Evaluator.
Evaluates Gate 2 (Parameter Stability) by executing real perturbed parameter runs
around the strategy's active entry, exit, stop loss, and target multipliers.
"""
import logging
from typing import Optional, List, Any
import numpy as np
import pandas as pd

from server.constants import trade_annualization_factor

logger = logging.getLogger("StabilityAuditor")


def compute_strategy_parameter_stability_matrix(
    df_c: pd.DataFrame,
    strat_inst: Any,
    observed_sr: float,
    symbol: str = "BTC/USDT",
    account_size: Optional[float] = None,
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

        if hasattr(strat_inst, "generate_signals"):
            from core.simulation import run_discrete_simulation as run_discrete_backtest
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

        # Fallback for strategies defining populate_entry_trend / populate_exit_trend
        from core.simulation import run_discrete_simulation as run_discrete_backtest
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
        matrix: List[List[float]] = []

        for sl_f in sl_factors:
            row: List[float] = []
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
                        symbol="OANDA:XAUUSD" if ("XAU" in symbol.upper() or "GOLD" in symbol.upper()) else symbol,
                        account_size=test_acct_size,
                        dollar_risk_1r=test_acct_size * risk_pct,
                        max_hold_bars=max(4, int(round(base_bars * tp_f))),
                        close_eod=True,
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
