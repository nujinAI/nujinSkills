"""
tools/friction_calc.py - Pure Friction & Execution Hurdle Calculator

Calculates realistic execution friction (broker commission, spread, and slippage)
and enforces the 10% Friction Hurdle:
Friction / Stop Distance <= 10.0%

Zero strategy bias. Pure cost mechanics.
"""

from typing import Dict, Any


def get_roundtrip_friction(symbol: str, current_price: float, atr: float) -> float:
    """
    Returns realistic round-trip friction in price points (dollars/points).
    Uses typical market spreads + commissions + slippage.
    """
    sym = symbol.upper()

    # Asset class baselines
    if "BTC" in sym:
        # Crypto: ~0.05% taker fee round-trip + 2 bps spread + 2 bps slippage = ~0.09% of price
        return current_price * 0.0009
    elif "ETH" in sym:
        return current_price * 0.0010
    elif "GC" in sym:  # Gold Futures
        # ~$0.20 spread + $4 round-trip contract fee (~$0.04/oz) + $0.10 slippage = ~$0.35/oz
        return 0.35
    elif "CL" in sym:  # Crude Oil
        return 0.04
    elif "SPY" in sym:
        # $0.01 spread + $0.005 commission + $0.01 slippage = $0.025
        return 0.03
    elif "QQQ" in sym:
        return 0.03
    elif "EURUSD" in sym or "GBPUSD" in sym:
        # ~1 pip spread + ~0.5 pip commission/slippage = 0.00015
        return 0.00015
    else:
        # Generic liquid default: 5 bps of price or 5% of ATR
        return max(current_price * 0.0005, atr * 0.05)


def check_friction_hurdle(symbol: str, stop_distance: float, current_price: float, atr: float) -> Dict[str, Any]:
    """
    Enforces that total round-trip friction does not eat more than 10% of the stop-loss risk.
    """
    friction = get_roundtrip_friction(symbol, current_price, atr)
    if stop_distance <= 0:
        return {"passed": False, "reason": "Invalid stop distance (<=0)"}

    friction_pct_of_stop = (friction / stop_distance) * 100.0
    passed = friction_pct_of_stop <= 10.0

    return {
        "passed": passed,
        "roundtrip_friction": round(friction, 4),
        "stop_distance": round(stop_distance, 4),
        "friction_pct_of_stop": round(friction_pct_of_stop, 2),
        "max_allowed_pct": 10.0,
        "status": "APPROVED" if passed else "REJECTED (Friction Eats Edge)"
    }


if __name__ == "__main__":
    import sys
    res = check_friction_hurdle(symbol="GC=F", stop_distance=5.0, current_price=2700.0, atr=8.0)
    print("Friction Hurdle Check:")
    for k, v in res.items():
        print(f"  {k}: {v}")
