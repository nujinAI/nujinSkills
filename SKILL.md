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

3. **Primary Data Authority & The CFD Volume Reality:**
   - **Price & Execution Authority:** Authentic broker spot data (TradeLocker API or direct broker CFD feed) is the primary source of truth for historical execution candles, real spreads, and fill simulation. It provides full multi-month depth (minimum 90 days / 17,000+ bars on 5m).
   - **The CFD Volume Reality (Zero Real Volume on CFDs):** On OTC/CFD spot instruments (such as `XAUUSD`), broker-reported volume is **synthetic tick volume** (a simple counter of quote updates from the broker's liquidity feed) — it does **NOT** represent real interbank traded lots or institutional order book depth. Strategies built for CFD brokers must never rely on broker tick volume for core alpha (e.g. Volume Profile, VWAP, raw volume sweeps). Alpha must be derived from **pure price geometry, structural highs/lows, session boundaries, and volatility expansion**. TradingView (`core.data.fetch_ohlcv`) provides aggregated institutional volume, but is subject to ~6,000 bar limits on lower timeframes. Do NOT use `yfinance` or commodity futures tickers for strategy design or evaluation.

4. **Zero Silent Fallbacks:**
   Every tool, script, and strategy call requires an explicit, unambiguous symbol parameter (e.g. `OANDA:XAUUSD`, `BINANCE:BTCUSDT`). No hardcoded fallback symbols or silent fallback feeds are permitted.

5. **User-Defined Constraints:**
   Never assume arbitrary drawdown rules. If the user or prop firm specifies 5% max DD and 3% daily DD, test those exact numbers. If the user asks for a long-term swing strategy with no daily cutoff, test only the overall max drawdown.

---

## 2. The 5-Phase Institutional Alpha Pipeline (Domain-Constrained)

Follow this rigorous, non-curve-fitting autonomous loop for every user request:

```
[ PHASE 1: USER DOMAIN ANCHOR & DYNAMIC RISK BUDGET ]
  - Parse the user's trading objective, anchor domain, and style:
    (e.g., Price Action, Session Sweeps, VWAP Reversion, Key Levels, Trend Continuation).
  - Use: core.risk.parse_prompt_to_risk("<user prompt>")
  -> Derives: Account size, 1R dollar risk, daily circuit breakers, profit caps dynamically from active broker accounts or user limits.

[ PHASE 2: 90-DAY DATA INGESTION & BLIND OUT-OF-SAMPLE ISOLATION ]
  - Ingest at least 90 days of authentic broker spot candles (e.g., data/market/XAUUSD_5m.csv, ~17,600 bars).
  - Strictly partition the dataset into two chronological blocks:
    1. In-Sample (First 60 Days — 2/3 of data): Dedicated to thesis calibration and strategy assembly.
    2. Blind Out-of-Sample (Last 30 Days — 1/3 of data): Locked and hidden from the strategy creation step.

[ PHASE 3: DOMAIN-CONSTRAINED PREDICTIVE VERIFICATION ]
  - Respect the user's chosen anchor: extract features exclusively within that domain (e.g., VWAP standard deviation bands, session high/low bounds, rejection candle geometry).
  - Mathematically verify if the specific domain features possess forward predictive power (Information Coefficient / IC >= 0.02) and that expected move size >= 5x roundtrip broker friction on the 60-day In-Sample dataset before writing execution triggers.

[ PHASE 4: STRUCTURAL STRATEGY CONSTRUCTION ]
  - Implement entry_signal, stop_loss, and target with objective structural invalidation and asymmetric payoff (target >= 2.0R).
  - Invalidation must reflect the strategy's specific logic (e.g. key level breach, swing high/low break, channel exit, volatility bound, or pattern failure) — DO NOT bias or default to ATR-only stops. The geometry must naturally match the user's requested domain.
  - Sizing is pure percentage (risk_pct_1r) — ZERO hardcoded dollar amounts or static lots.

[ PHASE 5: ADVERSARIAL 8-GATE FALSIFICATION & PERSISTENT REFINEMENT ]
  - Evaluate the candidate across the 8 Canonical Cynic Falsification Gates (core/cynic_gates.py) against both In-Sample and the Unseen 30-Day Blind Out-of-Sample:
     1. Gate 1: Deflated Sharpe Ratio (DSR >= 0.95, penalized for trial multiplicity).
     2. Gate 2: Parameter Stability Surface (checks against performance cliff).
     3. Gate 3: Monte Carlo Sequence Stress (MDD99 <= 3.0%, tail ratio <= 2.5).
     4. Gate 4: Combinatorial Out-of-Sample Walk-Forward (CPCV OOS Sharpe retention >= 50%).
     5. Gate 5: Regime Survival (verified across Bull, Bear, and Ranging market slices).
     6. Gate 6: Microstructure Friction & Noise Floor (after authentic spread + commission).
     7. Gate 7: Noise Jitter Resilience (>= 80% Sharpe retention under price jitter).
     8. Gate 8: Equity Linearity Standard (R² >= 0.85, positive slope, K-ratio >= 1.5).

  * THE "PERSISTENT REFINEMENT" DIRECTIVE (DO NOT STOP):
    - If any gate fails, the AI MUST NOT STOP and MUST NOT abandon the user's requested domain.
    - FORBIDDEN: Brute-force parameter optimization or grid-searching decimal numbers to game the gates (guaranteed curve-fit).
    - REQUIRED: Diagnose the structural failure mode (e.g. "Strategy bleeds during high-volatility trend expansions" or "Stops are too tight relative to Asian session spread").
    - Refine the structural logic within the domain to account for the failure mode, re-test against the 60d/30d pipeline, and iterate until a genuine S-Tier (8/8 Gates Passed) candidate emerges.
```

---
## 3. Strategy Implementation Interface & Deployment Standard

### Strict Isolation Firewall (Context Protection)
When building or modifying trading strategies:
- **FORBIDDEN:** Do not inspect `server/`, `frontend/`, `tests/`, or API code.
- **FORBIDDEN:** Do not read or search `~/.nujin/archive/` or old strategy files.
- **FORBIDDEN:** Do not run recursive `find .` or broad repository greps.
All rules, signal definitions, and math contracts needed to create any strategy are 100% defined right here in this skill file.

### Fast-Path Deployment & Verification Workflow:
1. **Draft & Save:** Write the Python strategy class directly into `../zillionsAlpha/strategies/<StrategyName>.py` (or `../nujinPro/strategies/` for commercial).
2. **Symlink:** Create the symlink in `strategies/`:
   `ln -s ../../zillionsAlpha/strategies/<StrategyName>.py strategies/<StrategyName>.py`
3. **Audit SSOT:** Run the canonical backtest audit directly:
   `python3 tools/run_backtest_audit.py --strategy <StrategyName>.py --days 30`
   (Do NOT invent custom test scripts or ad-hoc backtest loops.)

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

    # MANDATORY CLASS METADATA: Explicit single source of truth for asset pair and timeframe
    symbol: str = "OANDA:XAUUSD"
    timeframe: str = "5m"

    def __init__(
        self,
        risk_pct_1r: float = 0.0035,        # Risk appetite: e.g. 0.0035 = 0.35% (or 0.01 = 1.0%)
        **kwargs: Any
    ):
        self.risk_pct_1r = risk_pct_1r
        # Dynamic strategy parameters as needed (e.g. lookback, threshold, swing level depth)
        # ZERO hardcoded capital amounts or static lot sizes.

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates mathematical indicators / geometry required by the strategy.
        Completely universal: free to compute any domain math (Price action swing points,
        moving averages, bands, session highs/lows, momentum, etc.).
        """
        data = df.copy()
        if not isinstance(data.index, pd.DatetimeIndex):
            data.index = pd.to_datetime(data.index, utc=True)
        elif data.index.tz is None:
            data.index = data.index.tz_localize("UTC")
        else:
            data.index = data.index.tz_convert("UTC")

        # Compute whatever indicators the user request / strategy domain requires:
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
- Deploy strategies into `strategies/<StrategyName>.py`.
- The backend watcher in `server/main.py` detects changes in real time, automatically evaluates initial backtests, and registers the strategy.

---

## 4. Pure Core Library Reference (`core/`)

All modules in `core/` are pure calculation primitives with zero trading bias and zero hardcoded capital:
- `core/data.py`: Dynamic candle fetcher (eliminates truncated CSVs) with True Range, ATR, and relative volume.
- `core/risk.py`: Dynamic risk-of-ruin sizing, 1R units, and circuit breaker math.
- `core/friction.py`: Dynamic spread, fee, and slippage verification.
- `core/simulation.py`: Discrete simulator with **Pessimistic Intrabar Resolution** (SL triggers first if both SL and TP are hit on the same bar).
- `core/cynic_gates.py`: The 8 Canonical Cynic Falsification Gates & Monte Carlo Stress.
- `core/portfolio.py`: Correlation matrix, regime orthogonality, and ensemble diversification.

---

## 5. Live Infrastructure & Operational References (`references/`)

For live bot execution, frontend chart visualization, and WebSocket telemetry, consult the operational reference guides on demand:
- [`references/bot_operations.md`](references/bot_operations.md): Non-disruptive live bot supervision, state inspection (`tools/state_control.py`), safe strategy hot-deployment (`tools/bot_control.py`), and the live trading interlock (`NUJIN_LIVE_TRADING=1`).
- [`references/chart_copilot_protocol.md`](references/chart_copilot_protocol.md): Protocol for dispatching AI chart visual primitives (lines, boxes, SMC zones) to the Vue TradingView canvas.
- [`references/telemetry_api.md`](references/telemetry_api.md): FastAPI REST endpoints and WebSocket message schemas for the frontend cockpit.
