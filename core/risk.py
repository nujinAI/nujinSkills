from __future__ import annotations
"""
core/risk.py - Dynamic Risk Budgeting & 1R Position Sizing arithmetic.
Used by: AI prompt compiler, Backtester, Live Order Router, and Cockpit Risk views.
"""
from typing import Dict, Any, Optional

def parse_prompt_to_risk(prompt: str, active_balance: Optional[float] = None) -> Dict[str, Any]:
    """
    Parses user requirements into dynamic risk parameters.
    Baseline account size defaults to active broker account or $5,000 prop baseline (never hardcoded $100k).
    """
    account_size = float(active_balance) if active_balance and active_balance > 0 else 5000.0
    p = (prompt or "").lower()

    if "conservative" in p or "prop" in p or "gft" in p or "pass" in p:
        risk_pct = 0.0035  # 0.35%
        max_daily_dd = 0.03  # 3.0%
        max_total_dd = 0.05  # 5.0%
        max_daily_losses = 2
    elif "aggressive" in p or "high risk" in p:
        risk_pct = 0.0100  # 1.0%
        max_daily_dd = 0.05
        max_total_dd = 0.10
        max_daily_losses = 3
    else:
        risk_pct = 0.0050  # 0.50% standard default
        max_daily_dd = 0.04
        max_total_dd = 0.08
        max_daily_losses = 2

    dollar_risk_1r = round(account_size * risk_pct, 2)

    return {
        "account_size": account_size,
        "risk_pct_1r": risk_pct,
        "dollar_risk_1r": dollar_risk_1r,
        "max_daily_drawdown_pct": max_daily_dd,
        "max_total_drawdown_pct": max_total_dd,
        "max_daily_losses": max_daily_losses,
        "daily_profit_cap": round(dollar_risk_1r * 4.0, 2)
    }

def calculate_position_units(dollar_risk_1r: float, entry_price: float, stop_loss: float) -> float:
    """Calculates exact units sized so losing = exactly 1R."""
    stop_dist = abs(entry_price - stop_loss)
    if stop_dist <= 0:
        return 0.0
    return dollar_risk_1r / stop_dist


"""
server/risk_governor.py
─────────────────────────────────────────────────────────────────────────────
Institutional Risk Sizing, Volatility Targeting, Drawdown Governor &
Microstructure Execution Model for NujinAI.

Implements:
  1. Volatility-Targeted & Stop-Normalized Sizing (`risk_per_trade_pct` + `VolTarget`)
  2. Fractional Kelly / Signal-Conviction Multiplier (`conviction_mult`)
  3. Multi-Tier Equity-Curve Drawdown Governor (dynamic risk throttle during drawdowns)
  4. Volatility- & Spread-Scaled Dynamic Slippage (`compute_dynamic_slippage_bps`)
  5. Pessimistic Intra-Bar Exit Resolution (Stop-Loss always takes precedence over
     Take-Profit if both are breached inside the same bar's [low, high] range)
  6. Carry / Perpetual Funding Cost Accounting (`compute_funding_drag_frac`)
"""



from typing import Dict, List, Optional, Tuple
import numpy as np


def compute_dynamic_slippage_bps(
    base_slippage_bps: float,
    bar_range: float,
    median_range: float,
    volume_ratio: float = 1.0,
) -> float:
    """
    Scales slippage dynamically based on intra-bar volatility expansion and liquidity:
      Slippage_t = base_slippage_bps * clip(bar_range / median_range, 1.0, 3.5)
    """
    if median_range <= 1e-12 or bar_range <= 0:
        return float(base_slippage_bps)
    vol_expansion = float(np.clip(bar_range / median_range, 1.0, 3.5))
    # Slight liquidity discount when volume is healthy, penalty when thin
    liq_factor = 1.15 if volume_ratio < 0.5 else 1.0
    return float(base_slippage_bps * vol_expansion * liq_factor)


def compute_funding_drag_frac(
    bars_held: int,
    bar_seconds: int = 900,
    funding_bps_per_8h: float = 0.5,
) -> float:
    """
    Computes cumulative funding / overnight carry cost as a fraction of notional
    based on holding time (default 0.5 bps per 8-hour funding interval).
    """
    if bars_held <= 0 or funding_bps_per_8h <= 0:
        return 0.0
    hours_held = (bars_held * max(60, int(bar_seconds))) / 3600.0
    intervals = hours_held / 8.0
    return float((intervals * funding_bps_per_8h) / 10000.0)


def resolve_intrabar_exit(
    pos: int,
    entry_price: float,
    bar_open: float,
    bar_high: float,
    bar_low: float,
    bar_close: float,
    sl_pct: float,
    tp_pct: float,
    trail_peak: float,
    trailing_stop: bool = False,
) -> Tuple[bool, float, str, float]:
    """
    Pessimistic Intra-Bar Path Resolution:
      - Updates `trail_peak` cautiously.
      - Checks both Stop-Loss and Take-Profit against `[bar_low, bar_high]`.
      - CRITICAL INSTITUTIONAL RULE: If a single bar's `[bar_low, bar_high]` breaches
        BOTH the Stop-Loss and Take-Profit levels, it ALWAYS resolves as a
        STOP-LOSS hit first (worst-case intra-bar path assumption).
    Returns:
      `(exited, raw_pct_return, exit_reason, updated_trail_peak)`
    """
    if pos == 1:
        hit_sl = (bar_low - entry_price) / entry_price <= -sl_pct
        hit_tp = (bar_high - entry_price) / entry_price >= tp_pct
        # Check trailing stop against prior peak before updating peak with current bar high
        hit_trail = False
        if trailing_stop and (trail_peak - entry_price) / entry_price >= sl_pct * 0.8:
            if (bar_low - trail_peak) / trail_peak <= -sl_pct * 0.65:
                hit_trail = True

        # Pessimistic priority: SL > Trail > TP
        if hit_sl:
            # Account for gap-down below stop on open
            fill_ret = min(-sl_pct, (bar_open - entry_price) / entry_price) if bar_open < entry_price * (1.0 - sl_pct) else -sl_pct
            return True, float(fill_ret), "SL", trail_peak
        if hit_trail:
            trail_exit_price = trail_peak * (1.0 - sl_pct * 0.65)
            return True, float((trail_exit_price - entry_price) / entry_price), "TRAIL", trail_peak
        if hit_tp:
            return True, float(tp_pct), "TP", max(trail_peak, bar_high)

        return False, float((bar_close - entry_price) / entry_price), "HOLD", max(trail_peak, bar_high)

    elif pos == -1:
        hit_sl = (entry_price - bar_high) / entry_price <= -sl_pct
        hit_tp = (entry_price - bar_low) / entry_price >= tp_pct
        hit_trail = False
        if trailing_stop and (entry_price - trail_peak) / entry_price >= sl_pct * 0.8:
            if (trail_peak - bar_high) / trail_peak <= -sl_pct * 0.65:
                hit_trail = True

        # Pessimistic priority: SL > Trail > TP
        if hit_sl:
            fill_ret = min(-sl_pct, (entry_price - bar_open) / entry_price) if bar_open > entry_price * (1.0 + sl_pct) else -sl_pct
            return True, float(fill_ret), "SL", trail_peak
        if hit_trail:
            trail_exit_price = trail_peak * (1.0 + sl_pct * 0.65)
            return True, float((entry_price - trail_exit_price) / entry_price), "TRAIL", trail_peak
        if hit_tp:
            return True, float(tp_pct), "TP", min(trail_peak, bar_low)

        return False, float((entry_price - bar_close) / entry_price), "HOLD", min(trail_peak, bar_low)

    return False, 0.0, "FLAT", trail_peak


def drawdown_governor_multiplier(current_dd: float, max_dd_limit: float = 0.030) -> float:
    """
    Multi-Tier Equity-Curve Drawdown Governor:
      - DD < 33% of limit (< 1.0%): 1.00x risk (Full allocation)
      - DD in [33%, 60%] of limit (1.0% - 1.8%): 0.60x risk (Tier-1 throttle)
      - DD in [60%, 80%] of limit (1.8% - 2.4%): 0.35x risk (Tier-2 preservation)
      - DD > 80% of limit (> 2.4%): 0.20x risk (Minimum shadow sizing until recovery)
    """
    if max_dd_limit <= 0:
        return 1.0
    ratio = current_dd / max_dd_limit
    if ratio < 0.33:
        return 1.00
    if ratio < 0.60:
        return 0.60
    if ratio < 0.80:
        return 0.35
    return 0.20


def apply_equity_curve_governor(
    unscaled_r_returns: List[float],
    base_risk_pct: float = 0.0045,
    max_dd_limit: float = 0.030,
    conviction_multipliers: Optional[List[float]] = None,
    vol_ratios: Optional[List[float]] = None,
) -> List[float]:
    """
    Applies dynamic Volatility Targeting, Signal Conviction (Fractional Kelly),
    and the Multi-Tier Equity-Curve Drawdown Governor across a sequence of trade R-multiples.
    """
    governed: List[float] = []
    cum_equity = 0.0
    peak_equity = 0.0

    for idx, r_mult in enumerate(unscaled_r_returns):
        current_dd = max(0.0, peak_equity - cum_equity)
        dd_mult = drawdown_governor_multiplier(current_dd, max_dd_limit=max_dd_limit)

        conv_mult = 1.0
        if conviction_multipliers and idx < len(conviction_multipliers):
            conv_mult = float(np.clip(conviction_multipliers[idx], 0.50, 1.35))

        vol_mult = 1.0
        if vol_ratios and idx < len(vol_ratios):
            vr = float(vol_ratios[idx])
            if vr > 0:
                vol_mult = float(np.clip(1.0 / vr, 0.50, 1.30))

        effective_risk = base_risk_pct * dd_mult * conv_mult * vol_mult
        trade_ret = float(r_mult * effective_risk)
        governed.append(trade_ret)

        cum_equity += trade_ret
        if cum_equity > peak_equity:
            peak_equity = cum_equity

    return governed
