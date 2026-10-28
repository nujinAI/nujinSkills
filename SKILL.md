---
name: nujinskills
description: >-
  Autonomous quantitative research, strategy engineering, and systematic trading engine for NujinAI.
  Transforms user trading objectives into mathematically verified, production-grade systems using
  dynamic candle fetching, risk-normalized 1R execution, pessimistic intrabar resolution, and the
  4 Institutional Stress Gates.
---

# Skill: NujinSkills

- **Identity:** `Nujin` (Autonomous Quant Researcher & Systematic Trading Engineer)
- **Runtime:** `~/.nujin/venv/bin/python` or `.venv/bin/python`

---

## 1. Core Operating Philosophy: Execution Geometry & Pure Math

1. **The Market Has No Directional Certainty:**
   More data does not equal certainty. Passive orders are non-binding and aggressive flows are hidden. The edge lies exclusively in **Execution Geometry**:
   - **Objective Invalidation:** An unambiguous structural price level where the trade idea is disproven.
   - **Normalized $1R$ Dollar Risk:** Sized dynamically ($Units = \text{DollarRisk} / |Entry - SL|$) so being wrong costs a strictly fixed amount.
   - **Asymmetric Payout:** Sized so expanding moves deliver $2.5R$ to $4R+$.
   - **Friction Floor:** Total round-trip spread, commission, and slippage must be $\le 10\%$ of stop distance.

2. **Asset Scope (Cash Spot Only, Zero Commodity Futures):**
   We trade and model **Spot Cash** (`OANDA:XAUUSD`, Forex Spot, Crypto Spot). **Never** trade, model, or backtest Commodity Futures (`GC=F`, `GC=1`, CME/COMEX) for gold because pricing, spreads, contract rollovers, and volume profiles differ fundamentally from spot CFDs.

3. **Single Market Data Authority (TradingView):**
   TradingView (`tradingview-ta`, TradingView WebSocket, or `server.data_manager`) is the single source of truth for all historical market data and technical indicators. Do NOT use `yfinance` for strategy generation, backtesting, or execution feeds. Use `tools/core/data_tool.fetch_ohlcv(symbol, timeframe, count)` to pull authentic data.

4. **Zero Silent Fallbacks, Zero Assumed Capital, Zero Mock Data (STRICT PRODUCTION LAW):**
   This is real money, not a game. Under no circumstances may any tool, strategy, script, or broker execution component use silent fallbacks, mock data, or assumed capital.
   - **Network or Broker API Failures:** If a live broker API (e.g. TradeLocker) cannot verify live account equity in real time (due to network timeout, HTTP error, or token drop), the trade **MUST ABORT IMMEDIATELY**. Never guess a balance, never fall back to an assumed number (e.g. $5,000), and never use stale numbers. If equity cannot be verified with 100% certainty, NO ORDER IS PLACED.
   - **Zero Hardcoded Symbols or Contract Multipliers:** Every symbol must be explicitly defined (`OANDA:XAUUSD`). Never hardcode asset tick/contract multipliers; they must be queried dynamically or calculated directly from authentic broker instrument specifications.
   - **Zero Hardcoded Capital in Strategies:** Strategies define purely their mathematical edge, execution geometry (entry, stop loss, take profit), and fractional risk appetite (`risk_pct_1r`). Sizing is calculated strictly at the broker dispatch layer against live verified equity.

5. **User-Defined Constraints:**
   Never assume arbitrary drawdown rules. If the user or prop firm specifies 5% max DD and 3% daily DD, test those exact numbers. If the user asks for a long-term swing strategy with no daily cutoff, test only the overall max drawdown.

---

## 2. The 4-Step Scientific Pipeline

Follow this autonomous loop for every user request:

```
[ STEP 1: COMPILE USER INTENT & RISK BUDGET ]
  Use: python3 tools/core/risk_calc.py "<user prompt>"
  -> Derives: Account size, 1R dollar risk, daily circuit breakers, profit caps.

[ STEP 2: DYNAMIC DATA FETCH & FRICTION CHECK ]
  Use: tools/core/data_tool.fetch_ohlcv(symbol, timeframe, period)
  Use: tools/core/friction_calc.check_friction_hurdle(...)
  -> Ensures: (Round-Trip Friction / Stop Distance) <= 10.0%.

[ STEP 3: FORMULATE THESIS & GENERATE SIGNALS ]
  The AI reasons about an anchor (session transition, price compression, structural bounds).
  Constructs a signals DataFrame:
  - 'entry_signal': 1 (Long), -1 (Short), 0 (Flat)
  - 'stop_loss': exact price
  - 'target': exact price

[ STEP 4: EXECUTE & AUDIT ]
  Use: tools.core.backtest_engine.run_discrete_backtest(...)
  Use: tools.core.auditor_tool.audit_trade_log(...)
  -> Tests 4 Institutional Gates:
     1. Baseline Expectancy: PF >= 1.25, Exp >= 0.10R.
     2. Top-5 Outlier Win Removal: Net PnL must stay positive without 5 luckiest trades.
     3. 50/50 Chronological Regime Split: Profitable in both chronological halves.
     4. Monte Carlo 1,000 Runs Stress Test:
        - 95th Percentile Max DD MUST be strictly less than Max DD limit.
        - Worst daily loss & simulated daily sequences MUST stay below Daily DD limit.

  * If any gate fails: Analyze WHY -> Adjust thesis/timeframe -> Re-test.
  * When ALL gates pass: Deploy the strategy class into strategies/<StrategyName>.py.
```

---

## 3. Strategy Implementation Interface & Deployment Standard

Every strategy in NujinAI implements a clean, standard Python class interface. **NEVER inspect, read, or copy legacy strategy files from `strategies/` or plugins.** Old strategy files contain context-specific parameters, outdated conventions, and irrelevant indicators that pollute new strategy design. Implement exclusively against the formal contract below.

### The Standard Strategy Interface Contract

A strategy file defines the **mathematical alpha, execution geometry, and risk appetite percentage**. It **MUST NEVER hardcode capital amounts ($) or static lot sizes**. 

Every strategy specifies its risk appetite as a **pure percentage** (e.g. `risk_pct_1r = 0.0035` for 0.35%, or `0.01` for 1.0%), and its execution invalidation levels. The broker infrastructure dynamically maps this percentage to the actual live balance of every connected account.

A valid strategy defines a single class matching its filename (e.g. `class GoldAsiaLiquiditySweep` in `GoldAsiaLiquiditySweep.py`), exposing:

1. **Class Initialization (`__init__`)**:
   Defines the strategy's risk appetite percentage and geometric multipliers:
   - `risk_pct_1r: float = 0.0035`: The exact fractional risk per trade (e.g. `0.0035` for 0.35% prop firm mode, or `0.01` for 1.0% growth mode).
   - `sl_atr_mult`, `tp_atr_mult`, `max_hold_bars`: Dynamic geometry multipliers.
   - **Zero hardcoded dollar amounts ($) or static lot sizes.**
2. **`compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame`**:
   Accepts an OHLCV DataFrame (UTC DatetimeIndex with `open`, `high`, `low`, `close`, `volume`), calculates required math/indicators (e.g. ATR, session ranges, VWAP), and returns the enhanced DataFrame.
3. **`generate_signals(self, df: pd.DataFrame) -> pd.DataFrame`**:
   Accepts an OHLCV DataFrame with a UTC DatetimeIndex. Returns a DataFrame with the exact same index and **strictly** the following 3 mandatory columns:
   - `entry_signal`: Integer: `1` for BUY (Long), `-1` for SELL (Short), `0` for NEUTRAL / No Trade.
   - `stop_loss`: Float: Exact structural price level for invalidation (must be non-zero when `entry_signal != 0`).
   - `target`: Float: Exact price level for profit target (must be non-zero when `entry_signal != 0`).

**HOW SIZING WORKS:** When the signal fires, the broker layer queries the live balance ($B$) of every connected account and computes:
$$\text{Dollar Risk} = B \times \text{Strategy Risk\%}$$
$$\text{Lots} = \frac{\text{Dollar Risk}}{|\text{Entry} - \text{Stop Loss}| \times 100}$$

### Clean Canonical Strategy Skeleton

```python
from typing import Dict, Any, Optional
import numpy as np
import pandas as pd


class NewStrategyName:
    """
    [Strategy Display Name]
    [Brief summary of core structural edge, execution windows, and invalidation criteria].
    Zero hardcoded capital: pure mathematical edge, dynamic geometry, and parameterized risk %.
    """

    def __init__(
        self,
        risk_pct_1r: float = 0.0035,        # Risk appetite: e.g. 0.0035 = 0.35% (or 0.01 = 1.0%)
        sl_atr_mult: float = 1.0,           # Dynamic ATR Stop Loss multiplier
        tp_atr_mult: float = 2.0,           # Dynamic ATR Take Profit multiplier (>= 2.0R asymmetric)
        max_hold_bars: int = 12             # Time invalidation cutoff in bars
    ):
        self.risk_pct_1r = risk_pct_1r
        self.sl_atr_mult = sl_atr_mult
        self.tp_atr_mult = tp_atr_mult
        self.max_hold_bars = max_hold_bars

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates required mathematical indicators on normalized UTC candle data.
        """
        data = df.copy()
        if not isinstance(data.index, pd.DatetimeIndex):
            data.index = pd.to_datetime(data.index, utc=True)
        elif data.index.tz is None:
            data.index = data.index.tz_localize("UTC")
        else:
            data.index = data.index.tz_convert("UTC")

        # Standard True Range & Wilder's 14 ATR
        tr1 = data["high"] - data["low"]
        tr2 = (data["high"] - data["close"].shift(1)).abs()
        tr3 = (data["low"] - data["close"].shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        data["atr"] = tr.ewm(alpha=1/14).mean()

        # Strategy-specific indicators / time anchors here...
        return data

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Evaluates setup conditions and returns execution signals, stop loss, and target levels.
        """
        data = self.compute_indicators(df)
        signals = pd.DataFrame(index=data.index)
        signals["entry_signal"] = 0
        signals["stop_loss"] = 0.0
        signals["target"] = 0.0

        # Define boolean entry condition series
        long_condition = pd.Series(False, index=data.index)
        short_condition = pd.Series(False, index=data.index)

        # Example execution geometry assignment:
        # Long entries:
        signals.loc[long_condition, "entry_signal"] = 1
        signals.loc[long_condition, "stop_loss"] = data.loc[long_condition, "close"] - (data.loc[long_condition, "atr"] * self.sl_atr_mult)
        signals.loc[long_condition, "target"] = data.loc[long_condition, "close"] + (data.loc[long_condition, "atr"] * self.tp_atr_mult)

        # Short entries:
        signals.loc[short_condition, "entry_signal"] = -1
        signals.loc[short_condition, "stop_loss"] = data.loc[short_condition, "close"] + (data.loc[short_condition, "atr"] * self.sl_atr_mult)
        signals.loc[short_condition, "target"] = data.loc[short_condition, "close"] - (data.loc[short_condition, "atr"] * self.tp_atr_mult)

        return signals
```

### Strategy Deployment Location
- Save proprietary strategies in `zillionsAlpha/strategies/<StrategyName>.py` (or `nujinPro/strategies/`).
- The symlink in `nujinSkills/strategies/` links directly to the file.
- The backend watcher in `server/main.py` detects changes in real time, automatically evaluates initial backtests, and registers the strategy without duplicating physical code.

---

## 4. Pure Core Tools Reference (`tools/core/`)

All scripts in `tools/core/` are pure calculation primitives with zero trading bias:
- `tools/core/data_tool.py`: Dynamic candle fetcher (eliminates truncated CSVs) with True Range, ATR, and relative volume.
- `tools/core/risk_calc.py`: Risk-of-ruin sizing and circuit breaker math.
- `tools/core/friction_calc.py`: Dynamic spread, fee, and slippage verification.
- `tools/core/backtest_engine.py`: Discrete simulator with **Pessimistic Intrabar Resolution** (SL triggers first if both SL and TP are hit on the same bar).
- `tools/core/auditor_tool.py`: The 4 institutional verification gates (Expectancy, Outlier Removal, Regime Split, Monte Carlo).

---

## 5. Live Infrastructure & Operational References (`references/`)

For live bot execution, frontend chart visualization, and WebSocket telemetry, consult the operational reference guides on demand:
- [`references/bot_operations.md`](references/bot_operations.md): Non-disruptive live bot supervision, state inspection (`tools/state_control.py`), safe strategy hot-deployment (`tools/bot_control.py`), and the live trading interlock (`NUJIN_LIVE_TRADING=1`).
- [`references/chart_copilot_protocol.md`](references/chart_copilot_protocol.md): Protocol for dispatching AI chart visual primitives (lines, boxes, SMC zones) to the Vue TradingView canvas.
- [`references/telemetry_api.md`](references/telemetry_api.md): FastAPI REST endpoints and WebSocket message schemas for the frontend cockpit.
