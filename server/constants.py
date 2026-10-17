"""
server/constants.py — SINGLE SOURCE OF TRUTH for shared quantitative thresholds.

Every module that needs a threshold, a cost assumption or an annualisation
factor must import it from here. Do NOT reintroduce numeric literals for these
values in other files.

History: these numbers used to be copy-pasted across ~8 modules, which is how
`3.0%` and `4.5%` drawdown limits, and `sqrt(252)` vs `sqrt(252*24*4)`
annualisation, ended up coexisting for the *same* metric.
"""

from __future__ import annotations

import math

# ─────────────────────────────────────────────────────────────────────────────
# Annualisation
# ─────────────────────────────────────────────────────────────────────────────
# Two distinct bases exist and must never be confused:
#   * BAR returns   — sampled once per candle. Annualise by sqrt(bars per year),
#                     which depends on the timeframe.
#   * TRADE returns — sampled once per closed trade. Annualise by sqrt(252) as
#                     the house convention for "one observation per trading day".
# Applying a bar factor to trade returns (or vice versa) inflates or deflates
# Sharpe by ~9.8x for 15m data, and silently changes which strategies pass.

BARS_PER_YEAR: dict[str, int] = {
    "1m": 252 * 24 * 60,
    "3m": 252 * 24 * 20,
    "5m": 252 * 24 * 12,
    "15m": 252 * 24 * 4,
    "30m": 252 * 24 * 2,
    "1h": 252 * 24,
    "2h": 252 * 12,
    "4h": 252 * 6,
    "6h": 252 * 4,
    "12h": 252 * 2,
    "1d": 252,
}

DEFAULT_TIMEFRAME = "15m"

# Annualisation convention for per-trade return series.
TRADE_PERIODS_PER_YEAR = 252


def bars_per_year(timeframe: str) -> int:
    """Bars per year for a timeframe string such as '15m' or '1h'."""
    if timeframe in BARS_PER_YEAR:
        return BARS_PER_YEAR[timeframe]
    raise ValueError(
        f"Unknown timeframe {timeframe!r}; known: {sorted(BARS_PER_YEAR)}"
    )


def annualization_factor(timeframe: str) -> float:
    """sqrt(periods per year) for BAR-sampled returns at `timeframe`."""
    return math.sqrt(bars_per_year(timeframe))


def trade_annualization_factor() -> float:
    """sqrt(periods per year) for TRADE-sampled returns."""
    return math.sqrt(TRADE_PERIODS_PER_YEAR)


# ─────────────────────────────────────────────────────────────────────────────
# Falsification gate thresholds (consumed by server/cynic_gates.py)
# ─────────────────────────────────────────────────────────────────────────────
PERIODS_PER_YEAR = TRADE_PERIODS_PER_YEAR

MIN_TRADES = 30  # minimum trades before a strategy is considered evaluable at all
MIN_TRADES_DSR = MIN_TRADES  # DSR needs the same sample floor
DSR_THRESHOLD = 0.95

FEE_BPS = 5.0
SLIPPAGE_BPS = 2.0
MIN_NOISE_FLOOR = 0.0010  # 10 bps: stops tighter than this trade inside noise

NOISE_JITTER_SIGMA = 0.001
MIN_NOISE_RETENTION = 0.80

MC_SIMULATIONS = 1000
MAX_MDD_99 = 0.030
MAX_TAIL_RATIO = 2.5

MIN_R2 = 0.85
MIN_K_RATIO = 1.5

OOS_SPLIT = 0.70
MIN_OOS_TRADES = 30
MIN_OOS_SR = 1.0
MIN_OOS_RETENTION_PCT = 30.0

MIN_REGIME_TRADES = 30
MIN_REGIME_SLICE_MEAN = -0.015

# ─────────────────────────────────────────────────────────────────────────────
# Strategy acceptance / ranking thresholds
# ─────────────────────────────────────────────────────────────────────────────
MIN_SHARPE = 1.80
MIN_PROFIT_FACTOR = 1.30
MIN_TRADES_SIGNIFICANT = 60
MIN_WIN_RATE = 0.50
MIN_EXPECTANCY_BPS = 14.0
MAX_DRAWDOWN = 0.030

# Tiering floors (institutional classification).
S_TIER_COMPOSITE = 80.0
S_TIER_SHARPE = 2.5
S_TIER_DSR = 0.95
S_TIER_PROFIT_FACTOR = 1.5
S_TIER_TRADES = 25

A_TIER_COMPOSITE = 65.0
A_TIER_SHARPE = 1.8
A_TIER_DSR = 0.90
A_TIER_DRAWDOWN = 0.04
A_TIER_PROFIT_FACTOR = 1.3
A_TIER_TRADES = 20
