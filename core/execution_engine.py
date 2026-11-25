"""
core/execution_engine.py - Unified Single Source of Truth Execution Engine.

Both Historical Backtesting and Live Paper/Broker Execution run through this
exact same state machine and StrategyContract. Broker adapters (Backtest,
Paper, TradeLocker) only execute orders at the edge and never alter strategy
or engine rules.

Core Principles:
  1. Single Source of Truth: One StrategyContract, one signal extractor, one
     exit/risk state machine shared by Backtest and Live.
  2. What belongs to strategies belongs to strategies: Zero silent/hardcoded
     engine fallbacks (e.g. no phantom max_hold_bars or max_daily_losses caps
     unless the strategy explicitly declares them).
  3. Pessimistic Intrabar Resolution: On same-bar SL + TP collision, SL wins.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from core.friction import get_roundtrip_friction, compute_carry_cost


@dataclass(frozen=True)
class StrategyContract:
    """
    Canonical execution contract extracted strictly from a strategy instance.
    Never injects hidden backtest-only or live-only rules.
    """
    max_hold_bars: Optional[int] = None
    max_daily_losses: Optional[int] = None
    daily_profit_cap_pct: Optional[float] = None
    daily_profit_cap: Optional[float] = None
    close_eod: bool = False
    eod_close_hour_utc: int = 21
    can_short: bool = True
    trailing_stop: bool = False
    trailing_stop_positive: float = 0.0002
    trailing_stop_positive_offset: float = 0.0003
    risk_pct_1r: float = 0.0035
    daily_carry_bps: float = 0.0
    friction_override: Optional[Dict[str, float]] = None

    @classmethod
    def from_strategy(cls, strat_inst: Any = None) -> "StrategyContract":
        if strat_inst is None:
            return cls()

        # 1. max_hold_bars (strictly strategy-declared; None = SL/TP only)
        max_hold_bars: Optional[int] = None
        for attr in ("time_invalidation_bars", "max_bars", "max_hold_bars"):
            val = getattr(strat_inst, attr, None)
            if val is not None:
                try:
                    ival = int(val)
                    if ival > 0:
                        max_hold_bars = ival
                        break
                except (TypeError, ValueError):
                    pass

        # 2. max_daily_losses (strictly strategy-declared; None = no count cap)
        max_daily_losses: Optional[int] = None
        raw_mdl = getattr(strat_inst, "max_daily_losses", None)
        if raw_mdl is not None:
            try:
                ival = int(raw_mdl)
                if ival > 0:
                    max_daily_losses = ival
            except (TypeError, ValueError):
                pass

        # 3. daily profit cap
        daily_profit_cap_pct = getattr(strat_inst, "daily_profit_cap_pct", None)
        daily_profit_cap = getattr(strat_inst, "daily_profit_cap", None)

        # 4. EOD close (False unless strategy explicitly opts in)
        close_eod = False
        if hasattr(strat_inst, "close_eod") and getattr(strat_inst, "close_eod") is not None:
            close_eod = bool(getattr(strat_inst, "close_eod"))
        eod_close_hour_utc = int(getattr(strat_inst, "eod_close_hour_utc", 21))

        # 5. Direction & trailing stop (False unless strategy explicitly opts in)
        can_short = bool(getattr(strat_inst, "can_short", True))
        trailing_stop = bool(getattr(strat_inst, "trailing_stop", False))
        trailing_stop_positive = float(getattr(strat_inst, "trailing_stop_positive", 0.0002))
        trailing_stop_positive_offset = float(getattr(strat_inst, "trailing_stop_positive_offset", 0.0003))

        # 6. Risk & friction
        risk_pct_1r = float(
            getattr(strat_inst, "risk_pct_1r", getattr(strat_inst, "risk_per_trade_pct", 0.0035))
        )
        daily_carry_bps = float(getattr(strat_inst, "daily_carry_bps", 0.0) or 0.0)
        friction_override = getattr(strat_inst, "friction_override", None)

        return cls(
            max_hold_bars=max_hold_bars,
            max_daily_losses=max_daily_losses,
            daily_profit_cap_pct=float(daily_profit_cap_pct) if daily_profit_cap_pct is not None else None,
            daily_profit_cap=float(daily_profit_cap) if daily_profit_cap is not None else None,
            close_eod=close_eod,
            eod_close_hour_utc=eod_close_hour_utc,
            can_short=can_short,
            trailing_stop=trailing_stop,
            trailing_stop_positive=trailing_stop_positive,
            trailing_stop_positive_offset=trailing_stop_positive_offset,
            risk_pct_1r=risk_pct_1r,
            daily_carry_bps=daily_carry_bps,
            friction_override=friction_override,
        )

    def resolve_daily_profit_cap_dollars(self, account_size: float) -> Optional[float]:
        if self.daily_profit_cap_pct is not None and self.daily_profit_cap_pct > 0:
            return account_size * self.daily_profit_cap_pct
        if self.daily_profit_cap is not None and self.daily_profit_cap > 0:
            return self.daily_profit_cap
        return None


@dataclass
class ExitDecision:
    exit_price: float
    exit_reason: str  # "SL", "TP", "TIME_STOP", "EOD"


@dataclass
class SignalIntent:
    direction: int          # 1 (LONG) or -1 (SHORT)
    stop_loss: float
    target: float
    order_type: str         # "MARKET" or "LIMIT"
    limit_price: Optional[float] = None
    limit_expiry_bars: Optional[int] = None


def evaluate_bar_exit(
    direction: int,
    stop_loss: float,
    target: float,
    bars_held: int,
    bar_high: float,
    bar_low: float,
    bar_close: float,
    bar_time: Any,
    max_hold_bars: Optional[int] = None,
    close_eod: bool = False,
    eod_close_hour_utc: int = 21,
) -> Optional[ExitDecision]:
    """
    Canonical bar-level exit evaluation shared by Backtest and Live.
    Pessimistic resolution: if both SL and TP are touched on the same bar, SL wins.
    """
    sl_hit = (bar_low <= stop_loss) if direction == 1 else (bar_high >= stop_loss)
    tp_hit = (bar_high >= target) if direction == 1 else (bar_low <= target)

    if sl_hit and tp_hit:
        return ExitDecision(exit_price=stop_loss, exit_reason="SL")
    if sl_hit:
        return ExitDecision(exit_price=stop_loss, exit_reason="SL")
    if tp_hit:
        return ExitDecision(exit_price=target, exit_reason="TP")
    if max_hold_bars is not None and bars_held >= max_hold_bars:
        return ExitDecision(exit_price=bar_close, exit_reason="TIME_STOP")
    if close_eod and hasattr(bar_time, "hour") and bar_time.hour >= eod_close_hour_utc:
        return ExitDecision(exit_price=bar_close, exit_reason="EOD")
    return None


def can_open_new_trade(
    daily_losses: int,
    daily_pnl: float,
    max_daily_losses: Optional[int] = None,
    daily_profit_cap: Optional[float] = None,
) -> Tuple[bool, str]:
    """
    Canonical daily circuit-breaker check shared by Backtest and Live.
    Only blocks when the strategy/caller explicitly sets a limit.
    """
    if max_daily_losses is not None and daily_losses >= max_daily_losses:
        return False, f"max_daily_losses ({daily_losses}/{max_daily_losses})"
    if daily_profit_cap is not None and daily_pnl >= daily_profit_cap:
        return False, f"daily_profit_cap ({daily_pnl:.2f}/{daily_profit_cap:.2f})"
    return True, ""


def extract_latest_signal(
    strat_inst: Any,
    df: pd.DataFrame,
    price_prec: int = 2,
) -> Tuple[Optional[SignalIntent], Optional[pd.DataFrame], Optional[Any]]:
    """
    Canonical signal extractor for strategies implementing `generate_signals(df)`.
    Normalizes the UTC DatetimeIndex identically in Backtest and Live, evaluates
    `strat_inst.generate_signals(df_idx)`, and returns `(SignalIntent, sig_df, last_sig)`.
    """
    if strat_inst is None or not hasattr(strat_inst, "generate_signals"):
        return None, None, None

    df_idx = df.copy()
    if not isinstance(df_idx.index, pd.DatetimeIndex):
        if "time" in df_idx.columns:
            df_idx["dt"] = pd.to_datetime(df_idx["time"], unit="s", utc=True)
            df_idx = df_idx.set_index("dt")
        elif "timestamp" in df_idx.columns:
            df_idx["dt"] = pd.to_datetime(df_idx["timestamp"], unit="s", utc=True)
            df_idx = df_idx.set_index("dt")
        else:
            df_idx["dt"] = pd.to_datetime(df_idx.index, utc=True)
            df_idx = df_idx.set_index("dt")

    sig_df = strat_inst.generate_signals(df_idx)
    if sig_df is None or sig_df.empty:
        return None, sig_df, None

    last_sig = sig_df.iloc[-1]
    sig_val = int(last_sig.get("entry_signal", 0))
    contract = StrategyContract.from_strategy(strat_inst)

    if sig_val == 1:
        direction = 1
    elif sig_val == -1 and contract.can_short:
        direction = -1
    else:
        return None, sig_df, last_sig

    sl = round(float(last_sig.get("stop_loss", 0.0)), price_prec)
    tp = round(float(last_sig.get("target", 0.0)), price_prec)

    raw_limit_p = last_sig.get("limit_price", 0.0)
    limit_p = (
        round(float(raw_limit_p), price_prec)
        if (raw_limit_p is not None and not np.isnan(raw_limit_p) and float(raw_limit_p) > 0)
        else None
    )
    sig_order_t = str(last_sig.get("order_type", "")).upper()
    is_limit_order = (sig_order_t == "LIMIT") or (limit_p is not None and limit_p > 0)

    raw_lim_exp = last_sig.get("limit_expiry_bars", None) if hasattr(last_sig, "get") else None
    limit_expiry_bars: Optional[int] = None
    if raw_lim_exp is not None and not np.isnan(raw_lim_exp) and int(raw_lim_exp) > 0:
        limit_expiry_bars = int(raw_lim_exp)
    else:
        strat_lim_exp = getattr(strat_inst, "limit_expiry_bars", None)
        if strat_lim_exp is not None and int(strat_lim_exp) > 0:
            limit_expiry_bars = int(strat_lim_exp)

    intent = SignalIntent(
        direction=direction,
        stop_loss=sl,
        target=tp,
        order_type="LIMIT" if is_limit_order else "MARKET",
        limit_price=limit_p if is_limit_order else None,
        limit_expiry_bars=limit_expiry_bars if is_limit_order else None,
    )
    return intent, sig_df, last_sig
