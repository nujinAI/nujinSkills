# Agent Architecture & Operating Directives: NujinSkills

This document establishes the **immutable architectural law** of `nujinSkills`. Any AI agent operating within this codebase must strictly adhere to the unified architecture defined below.

---

## 1. The Core Architecture Law

```
                  ┌────────────────────────────────────────────────────────┐
                  │              THE ONE SHARED LIBRARY (core/)            │
                  │   cynic_gates.py     data.py         friction.py       │
                  │   indicators.py      market_structure.py               │
                  │   risk.py            simulation.py   portfolio.py      │
                  │   regimes.py         analytics.py                      │
                  └───────────────────────────┬────────────────────────────┘
                                              │
        ┌─────────────────────────────────────┼─────────────────────────────────────┐
        ▼                                     ▼                                     ▼
┌──────────────┐                    ┌──────────────────┐                    ┌──────────────┐
│ 1. AI AGENT  │                    │    2. SERVER     │                    │ 3. FRONTEND  │
│ (8 CLI Tools)│                    │ (API & Services) │                    │ (UI Cockpit) │
└──────────────┘                    └──────────────────┘                    └──────────────┘
```

### The Invariant Principle: Single Source of Truth (SSOT)
There is **only ONE shared mathematical and operational engine**: the `core/` package.
* **No Logic Duplication:** Any AI agent, server daemon, or CLI tool that requires data fetching, technical indicators, market structure detection, risk calculations, simulation, regime classification, or audit gates **MUST** import directly from `core.*`.
* **No Ad-Hoc Math in Tools or Scripts:** Never write one-off indicator formulas, isolated backtest loops, or custom risk models in scripts or server files. If a new calculation or indicator is needed, implement it directly in `core/`, write unit tests in `tests/`, and import it from `core/`.

---

## 2. The One Shared Library (`core/`)

Every quantitative capability is centralized in `core/`:

| Module | Canonical Responsibility |
|---|---|
| **`core.cynic_gates`** | Institutional 8-Gate Cynic Audit engine (DSR $\ge 0.95$, Parameter Stability Plateau, Monte Carlo $\text{MDD}_{99} \le 3\%$, OOS Walk-Forward, Regime Survival, Friction Floor, Noise Jitter, Equity Linearity $R^2 \ge 0.85$). |
| **`core.data`** | Single Market Data Authority (TradingView historical candles, cash spot normalization for `OANDA:XAUUSD`, session slicing). Zero silent fallbacks. |
| **`core.friction`** | Real-world execution friction hurdle: round-trip spread + commissions + slippage must be $\le 10\%$ of stop distance. |
| **`core.indicators`** | High-performance, vectorized technical indicators (ATR, EMA, SMA, RSI, VWAP, Volume Profile, Bollinger Bands, MACD). |
| **`core.market_structure`** | Algorithmic market structure: Swing High/Low detection, Fair Value Gaps (FVG), Order Blocks, Session Liquidity Pools, Value Area (VAH/VAL/POC). |
| **`core.risk`** | Normalized $1R$ dollar risk sizing ($Units = \text{DollarRisk} / |Entry - SL|$), dynamic prop firm / account constraints, daily circuit breakers. |
| **`core.simulation`** | Pessimistic intrabar order execution simulator, bracket order resolution (SL/TP priority), realistic fill models. |
| **`core.portfolio`** | Multi-strategy portfolio allocation, correlation filtering, aggregate risk management, exposure balancing. |
| **`core.regimes`** | Empirical market regime classification (Trending Bull/Bear, Balanced Range, Volatility Spike, Compression). |
| **`core.analytics`** | Statistical performance analysis (Sharpe, Sortino, Calmar, K-Ratio, trade expectancy, return distributions). |

---

## 3. The Three System Consumers

### Consumer 1: The AI Agent (8 Canonical CLI Tools)
AI agents do not improvise commands or hand-roll backtest scripts. They execute their quantitative and operational tasks through the **8 Canonical CLI Tools** in `tools/`:

| CLI Tool | Purpose | Primary CLI Workflow |
|---|---|---|
| **`tools.preflight`** | System & Architecture Verifier | `python -m tools.preflight` |
| **`tools.strategy_manager`** | Strategy Discovery, Ranking & Tiers | `python tools/strategy_manager.py rank` |
| **`tools.run_backtest_audit`** | Backtesting & 8-Gate Cynic Audit | `python tools/run_backtest_audit.py --strategy <path>` |
| **`tools.state_control`** | Telemetry State Inspection & Sync | `python tools/state_control.py get` |
| **`tools.bot_control`** | Live / Dry-Run Trading Bot Control | `python tools/bot_control.py deploy --strategy <path> --mode dry-run` |
| **`tools.chart_copilot`** | Multi-Timeframe Chart Visualizer | `python tools/chart_copilot.py --symbol OANDA:XAUUSD` |
| **`tools.server_control`** | Telemetry Server Lifecycle Daemon | `python tools/server_control.py start --port 8000 --daemon` |
| **`tools.frontend_control`**| Cockpit UI Lifecycle Daemon | `python tools/frontend_control.py start --port 3000 --daemon` |

### Consumer 2: The Server (`server/`)
* Asynchronous service running FastAPI / WebSockets.
* Powers real-time telemetry streaming, live bot runners (`server/bot_runner.py`), TradeLocker broker connectivity, and execution state sync.
* Consumes `core/` modules directly for signal evaluation, risk checks, and trade tracking.

### Consumer 3: The Frontend Cockpit (`frontend/`)
* High-performance Vue 3 + Tailwind CSS + DaisyUI trading cockpit.
* Consumes real-time state emitted from `server/` on port 8000 (and `data/state.json`).
* Renders interactive TradingView lightweight charts, active trade markers, 8-gate audit cards, and equity curves.

---

## 4. Mandatory Directives for Any AI Agent

1. **Verify Architectural Integrity First:**
   * Before committing changes or declaring a task complete, always execute:
     ```bash
     .venv/bin/python -m tools.preflight
     ```
   * It enforces byte-compilation across `core/`, `tools/`, `server/`, runs the test suite, and verifies canonical SSOT agreement.
2. **Never Reinvent the Wheel:**
   * If a task requires calculating an indicator, parsing risk, fetching data, running a backtest, or auditing a strategy, use `core/` and the `tools/` suite.
3. **Respect Spot Cash Execution Geometry:**
   * Model and trade **Cash Spot** (`OANDA:XAUUSD`, Forex Spot, Crypto Spot). **Never** substitute commodity futures (`GC=F`) for gold.
4. **Deep Methodology Reference:**
   * For quantitative protocols, stage workflows, and gate math, consult **[`SKILL.md`](SKILL.md)**.
