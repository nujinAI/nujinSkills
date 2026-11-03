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
