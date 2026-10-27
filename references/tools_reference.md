# Tools Reference — Nujin Core Calculation Primitives

This document specifies the core calculation tools located in `tools/core/`. All tools are pure mathematical primitives with zero strategy bias.

---

## 1. `tools/core/data_tool.py` — Dynamic Candle Fetcher

Eliminates the legacy truncated static CSV bottleneck. Dynamically fetches fresh, continuous OHLCV data for ANY requested asset, timeframe, and period on the fly, with automated local caching.

### Python API:
```python
from tools.core.data_tool import fetch_ohlcv

# Dynamically fetches 1 year of 1-hour Gold futures candles
df = fetch_ohlcv(symbol="GC=F", timeframe="1h", period="1y")

# Columns returned:
# ['open', 'high', 'low', 'close', 'volume', 'tr', 'atr', 'norm_range', 'rel_volume', 'hour', 'day_of_week']
```

---

## 2. `tools/core/risk_calc.py` — Pure Mathematical Risk & Sizing Calculator

Translates natural language prompts or explicit parameters into mathematically sound, non-ruinous position sizing parameters.

### Python API:
```python
from tools.core.risk_calc import calculate_risk_budget, parse_prompt_to_risk

# From user prompt:
risk = parse_prompt_to_risk("Prop firm day trading strategy with 3% daily DD, 5% max DD, $100k account")

# Returns:
# {
#   'account_size': 100000.0,
#   'max_drawdown_pct': 0.05,
#   'daily_drawdown_pct': 0.03,
#   'risk_pct_1r': 0.00357,       # ~0.357% per trade
#   'dollar_risk_1r': 357.14,      # $357 per 1R stop
#   'max_daily_losses': 2,        # Circuit breaker: halt after 2 losses
#   'daily_profit_cap': 1200.0,   # Consistency rule cap
#   'holding_mode': 'day_trading'
# }
```

---

## 3. `tools/core/friction_calc.py` — Dynamic Cost & Hurdle Calculator

Enforces the institutional friction hurdle:
$$\frac{\text{Round-Trip Friction}}{\text{Stop-Loss Distance }} \le 10.0\%$$

### Python API:
```python
from tools.core.friction_calc import check_friction_hurdle

result = check_friction_hurdle(
    symbol="GC=F",
    stop_distance=6.0,
    current_price=2750.0,
    atr=12.5
)
# Returns: {'passed': True, 'roundtrip_friction': 0.35, 'friction_pct_of_stop': 5.83, 'status': 'APPROVED'}
```

---

## 4. `tools/core/backtest_engine.py` — Discrete Execution Simulator

Simulates bar-by-bar discrete trade execution with **Pessimistic Intrabar Resolution** (if both SL and TP are touched on the same bar, SL triggers first).

### Python API:
```python
from tools.core.backtest_engine import run_discrete_backtest

results = run_discrete_backtest(
    df=df,
    signals=signals_df,           # Columns: ['entry_signal', 'stop_loss', 'target']
    symbol="GC=F",
    account_size=100000.0,
    dollar_risk_1r=350.0,
    max_daily_losses=2,
    daily_profit_cap=1200.0,
    max_hold_bars=24,
    close_eod=True
)
# Returns: {'total_trades', 'win_rate', 'profit_factor', 'net_pnl_dollars', 'net_pnl_r', 'trades': [...]}
```

---

## 5. `tools/core/auditor_tool.py` — The 4 Institutional Verification Gates

Evaluates a completed trade log against the 4 non-negotiable gates:

### Python API:
```python
from tools.core.auditor_tool import audit_trade_log

report = audit_trade_log(
    trades=results['trades'],
    account_size=100000.0,
    max_drawdown_limit_pct=0.05,
    daily_drawdown_limit_pct=0.03
)
# Returns: {'overall_approved': True/False, 'gate_1_expectancy', 'gate_2_top5_outlier_removal', 'gate_3_regime_split_50_50', 'gate_4_monte_carlo'}
```
