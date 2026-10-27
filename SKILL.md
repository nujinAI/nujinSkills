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

2. **No Static CSV Limitations:**
   Never restrict research to truncated static CSVs. Use `tools/core/data_tool.py` to dynamically fetch fresh, continuous OHLCV data for ANY requested asset (`GC=F`, `BTC-USD`, `SPY`, `EURUSD=X`, etc.) across any timeframe (`1m`, `5m`, `15m`, `1h`, `1d`) and period (`60d`, `1y`, `2y`).

3. **User-Defined Constraints:**
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

## 3. Strategy Deployment Standard (`strategies/<StrategyName>.py`)

In Nujin, every strategy is authored directly as a standard Python strategy file in the `strategies/` directory:
`strategies/<StrategyName>.py` (e.g. `strategies/GoldIntradayTrendExhaustion.py`).

The backend watcher in `server/main.py` monitors `strategies/*.py`. When the strategy file is written:
1. The backend automatically detects the new strategy.
2. It registers it into `data/strategies.json`.
3. It broadcasts `STRATEGY_DISCOVERED` to the WebSocket and frontend cockpit in real time.

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
