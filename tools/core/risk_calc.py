"""
tools/risk_calc.py - Pure Mathematical Risk & Sizing Calculator

Translates high-level user constraints (e.g. account capital, max drawdown, daily drawdown)
into mathematically sound, non-ruinous position sizing parameters.
Zero strategy bias. Pure risk arithmetic.
"""

import re
import math
from typing import Dict, Any, Optional


def calculate_risk_budget(
    account_size: float = 100_000.0,
    max_drawdown_pct: float = 0.05,
    daily_drawdown_pct: float = 0.03,
    consistency_rule_pct: Optional[float] = 0.15,
    profit_target_pct: Optional[float] = 0.08,
    holding_mode: str = "day_trading"
) -> Dict[str, Any]:
    """
    Calculates 1R risk per trade, daily circuit breaker, and consistency profit caps.
    
    Standard Industry Sizing Rule:
    1R is sized between Max Drawdown / 12 and Max Drawdown / 15.
    This guarantees that a trader can withstand a statistical cluster of 8-10 consecutive
    losses without breaching the hard max drawdown limit.
    """
    # 1R Risk Sizing: ~1/12 to 1/15 of Max Drawdown
    risk_pct_1r = max_drawdown_pct / 14.0
    # Clamped between safe operational limits (0.15% to 1.0%)
    risk_pct_1r = max(0.0015, min(0.010, risk_pct_1r))
    dollar_risk_1r = account_size * risk_pct_1r

    # Daily Circuit Breaker: Max losses allowed in a single session
    # For day trading / prop firms, default is 2 losses (or daily DD / (1R * 2.5))
    if holding_mode == "day_trading":
        max_daily_losses = 2
    else:
        max_daily_losses = max(2, int(daily_drawdown_pct / (risk_pct_1r * 2.0)))

    # Consistency Rule: Max profit allowed in a single day
    daily_profit_cap = None
    if consistency_rule_pct and profit_target_pct:
        target_dollars = account_size * profit_target_pct
        daily_profit_cap = target_dollars * consistency_rule_pct

    return {
        "account_size": account_size,
        "max_drawdown_pct": max_drawdown_pct,
        "daily_drawdown_pct": daily_drawdown_pct,
        "risk_pct_1r": round(risk_pct_1r, 5),
        "dollar_risk_1r": round(dollar_risk_1r, 2),
        "max_daily_losses": max_daily_losses,
        "daily_profit_cap": round(daily_profit_cap, 2) if daily_profit_cap else None,
        "holding_mode": holding_mode
    }


def parse_prompt_to_risk(prompt: str) -> Dict[str, Any]:
    """
    Parses common natural language inputs (e.g. 5% max dd, 3% daily dd, 100k account)
    and returns calculated risk parameters.
    """
    p = prompt.lower()

    # Account size
    acc = 100_000.0
    m_acc = re.search(r'\$?(\d{1,3}(?:,\d{3})+|\d+)\s*(k|thousand|million|m)?\s*(?:usd|dollar)?\s*(account|capital|balance)?', p)
    if m_acc and m_acc.group(1):
        raw_val = float(m_acc.group(1).replace(',', ''))
        unit = m_acc.group(2)
        if unit and ('k' in unit or 'thousand' in unit):
            raw_val *= 1_000
        elif unit and ('m' in unit or 'million' in unit):
            raw_val *= 1_000_000
        if raw_val > 100:  # avoid matching percentages like 5% or 3%
            acc = raw_val

    # Max Drawdown
    max_dd = 0.05
    m_mdd = re.search(r'(?:max(?:imum)?\s*(?:trailing\s*)?(?:drawdown|dd)\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*%|(\d+(?:\.\d+)?)\s*%\s*max(?:imum)?\s*(?:trailing\s*)?(?:drawdown|dd))', p)
    if m_mdd:
        max_dd = float(m_mdd.group(1) or m_mdd.group(2)) / 100.0

    # Daily Drawdown
    daily_dd = max_dd * 0.6
    m_ddd = re.search(r'(?:daily\s*(?:drawdown|dd)\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*%|(\d+(?:\.\d+)?)\s*%\s*daily\s*(?:drawdown|dd))', p)
    if m_ddd:
        daily_dd = float(m_ddd.group(1) or m_ddd.group(2)) / 100.0

    # Consistency Rule
    consistency = None
    m_cr = re.search(r'consistency\s*(?:rule)?\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*%', p)
    if m_cr:
        consistency = float(m_cr.group(1)) / 100.0

    holding_mode = "day_trading" if ("day" in p or "overnight" in p or "prop" in p) else "swing"

    return calculate_risk_budget(
        account_size=acc,
        max_drawdown_pct=max_dd,
        daily_drawdown_pct=daily_dd,
        consistency_rule_pct=consistency,
        holding_mode=holding_mode
    )


if __name__ == "__main__":
    import sys
    test_prompt = sys.argv[1] if len(sys.argv) > 1 else "Prop firm day trading strategy with 3% daily DD, 5% max DD, 15% consistency rule"
    res = parse_prompt_to_risk(test_prompt)
    print("Parsed Risk Budget:")
    for k, v in res.items():
        print(f"  {k}: {v}")
