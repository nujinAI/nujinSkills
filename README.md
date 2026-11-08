# ⚡ NujinAI / nujinSkills — Universal Quantitative Trading Engine & Agent Skill

[![System: NujinAI](https://img.shields.io/badge/System-NujinAI-blue.svg)](SKILL.md)
[![Quant Protocol](https://img.shields.io/badge/Methodology-Universal%20Quant-emerald.svg)](references/alpha_pipeline.md)
[![Edge Discovery](https://img.shields.io/badge/Discovery-Empirical%20Rank%20IC-cyan.svg)](references/edge_discovery.md)
[![Audit: 8--Gate Cynic](https://img.shields.io/badge/Audit-8--Gate%20Cynic%20%7C%20R%C2%B2%20%E2%89%A5%200.85-amber.svg)](references/cynic_gates_protocol.md)
[![Chart Copilot](https://img.shields.io/badge/Visual-AI%20Chart%20Copilot-indigo.svg)](references/chart_copilot_protocol.md)
[![Bot Operations](https://img.shields.io/badge/Bot-Live%20Supervision-cyan.svg)](references/bot_operations.md)
[![Telemetry API](https://img.shields.io/badge/Telemetry-JSON%20API-sky.svg)](references/telemetry_api.md)

> **Empower autonomous AI agents to discover authentic edges, build battle-tested strategies, and deploy reliable trading bots.**  
> Completely universal, paradigm-neutral, and free of hardcoded indicator dogmas. Evaluated through the strict lens of institutional mathematical invariants.

---

## 🎯 What is nujinSkills?

**nujinSkills** is an open-source, agent-agnostic **AI Quant Skill and Systematic Execution Framework**. It transforms an AI coding agent (in Antigravity, Claude Code, Cursor, or Windsurf) into an autonomous quantitative researcher and systematic trading engineer.

Instead of hardcoding indicator recipes or producing curve-fitted backtests, `nujinSkills` enforces a **universal, scientific discovery and validation pipeline**:
1. **Unbiased Edge & Anomaly Discovery:** Empirically measures whether *any* candidate hypothesis, feature, or structural market property has forward predictive power (Rank Information Coefficient) and comfortably clears broker friction.
2. **Dynamic 1R Execution Geometry:** Normalizes position sizing strictly to the structural invalidation distance ($Unit = \frac{\text{DollarRisk}}{|Entry - StopLoss|}$), making catastrophic sequence ruin mathematically impossible.
3. **Pessimistic Microstructure Simulation:** Simulates bar-by-bar execution with worst-case intrabar resolution (stops hit first if both TP and SL are touched in the same bar) and authentic venue friction (spread, commission, slippage, and funding rates).
4. **Adversarial 8-Gate Cynic Falsification:** Actively attempts to break candidate strategies across In-Sample and unseen Blind Out-of-Sample datasets before approving them for deployment.
5. **Production Hot-Deployment & Supervision:** Emits standardized Python strategy classes, hot-deploys them to live running bots, and supervises performance with real-time edge-decay circuit breakers.

---

## 💎 Core Architectural Focus & Capabilities

### 1. Universal & Paradigm-Agnostic
`nujinSkills` does not dictate *what* to trade or *which* indicators to use. The framework is equally powerful across:
- **Momentum & Trend Continuation** (Structural breakouts, volatility expansion, trend following).
- **Mean Reversion & Fair Value Envelopes** (VWAP deviations, Bollinger bands, channel boundaries).
- **Structural Liquidity & Session Dynamics** (Opening range breakouts, session high/low rejections).
- **Statistical Arbitrage & Cross-Asset Spreads** (Cointegration, ratio divergence).
- **Macro & Funding Arbitrage** (Yield differentials, perpetual funding rate carry).

Any trading horizon—from **LTF scalping (1m–5m)** and **intraday (15m–1h)** to **swing (4h–1D)** and **multi-day investing**—is natively supported.

### 2. The 4 Inviolable Quantitative Invariants
Regardless of user requirements or strategy style, the engine strictly enforces 4 mathematical laws:
1. **Positive Net Expectancy ($\mathbb{E}[R] > 0$):**
   $$\mathbb{E}[R] = (W \times R_{\text{win}}) - ((1 - W) \times 1.0) - \text{Friction} > 0$$
   Payout multiples and win rates are calibrated to the strategy thesis—never constrained by arbitrary R-ratio dogmas.
2. **Authentic Instrument Modeling:**
   Models the genuine execution realities of the traded instrument (Forex Spot, CFD, Equities, Futures, or Crypto Spot/Perp) including tick sizes, spreads, swap, and synthetic volume limitations.
3. **Strict 2/3 In-Sample vs. 1/3 Blind Out-of-Sample Isolation:**
   Hypothesis discovery and feature calibration occur exclusively on the In-Sample segment. The Out-of-Sample segment remains cryptographically untouched until final evaluation.
4. **Zero Hardcoded Capital & Zero Silent Fallbacks:**
   No static dollar bets or hardcoded prices. Position sizing scales dynamically with equity risk percentage (`risk_pct_1r`). Data failures raise explicit errors rather than injecting synthetic prices.

---

## 🔄 The 5-Phase Systematic Alpha Pipeline

```
[ Phase 1: User Goal Ingestion & Dynamic Risk Budget ]
  → Deduces horizon, risk tolerance, and account constraints without imposing arbitrary limits.

[ Phase 2: Authentic Ingestion & Blind Out-of-Sample Isolation ]
  → Pulls authentic market history; chronologically locks the final 33.3% as unseen Blind OOS.

[ Phase 3: Empirical Edge & Anomaly Discovery (`tools/scan_edge.py`) ]
  → Tests hypothesis series against forward returns (Rank IC >= 0.02, t-stat >= 2.0, move >= 3x friction).

[ Phase 4: Structural Strategy Construction ]
  → Formulates entry signal, structural invalidation (SL), thesis-aligned exit, and 1R dynamic sizing.

[ Phase 5: Adversarial 8-Gate Cynic Falsification & Deployment ]
  → Evaluates strategy across In-Sample and Blind OOS against the 8 institutional stress gates.
```

---

## 🛡️ The 8 Institutional Cynic Stress Gates

Before any strategy is approved for deployment, it must survive the full adversarial falsification suite (`core/cynic_gates.py`):

| Gate | Name | Pass Condition | Institutional Purpose |
| :--- | :--- | :--- | :--- |
| **Gate 1** | **Deflated Sharpe Ratio (DSR)** | $\text{DSR} \ge 0.95$ | Penalizes Sharpe for selection bias and trial multiplicity (López de Prado). |
| **Gate 2** | **Parameter Stability Surface** | $< 30\%$ drop across $\pm 10\%$ params | Rejects overfitted "needle-in-a-haystack" parameter cliffs. |
| **Gate 3** | **Monte Carlo Stress** | $\text{MDD}_{99} \le 3.0\%$ across 1,000 runs | Falsifies sequence risk and fat-tail ruin probability. |
| **Gate 4** | **Walk-Forward CPCV** | OOS Sharpe retention $\ge 50\%$ | Prevents regime overfitting across non-contiguous market blocks. |
| **Gate 5** | **Regime Survival** | Profitable/neutral across all market phases | Tests robustness in Bull, Bear, and Sideways/High-Vol conditions. |
| **Gate 6** | **Microstructure Friction** | Roundtrip cost $\le 10\%$ of stop distance | Ensures the edge is not eaten alive by real-world spread and slippage. |
| **Gate 7** | **Noise Jitter Resilience** | $\ge 80\%$ Sharpe retention under price jitter | Rejects strategies dependent on micro-tick sequence luck. |
| **Gate 8** | **Equity Linearity** | Curve $R^2 \ge 0.85$, $K\text{-Ratio} \ge 1.5$ | Demands consistent, steady growth over erratic outlier spikes. |

---

## 🚀 How to Use nujinSkills

### 1. Installation
Clone the repository and set up the shared Python environment:

```bash
git clone https://github.com/autonomousEnterprises/NujinAI.git
cd NujinAI/nujinSkills

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Universal CLI Tools

#### Empirical Edge & Anomaly Scanner
Test any market property or hypothesis series across forward bar horizons:
```bash
# Scan default features on Gold spot 15m
python tools/scan_edge.py --symbol OANDA:XAUUSD --tf 15m --days 60

# Scan features on BTCUSDT 1h
python tools/scan_edge.py --symbol BINANCE:BTCUSDT --tf 1h --days 30
```

#### Run 8-Gate Backtest Audit
Execute the complete institutional audit on any candidate strategy:
```bash
python tools/run_backtest_audit.py --strategy strategies/<StrategyName>.py --days 60
```

#### Dual-Screen Visual Cockpit & Server Control
```bash
# Start FastAPI Telemetry Engine (Port 8000)
python tools/server_control.py start --port 8000 --daemon

# Start Interactive TradingView Visual Canvas (Port 3000)
python tools/frontend_control.py start --port 3000 --daemon
```

---

## 🤖 Directing Your AI Agent

Because `nujinSkills` is designed for autonomous agent pairing, you can prompt your AI directly with goals at any level of abstraction:

### Example A: Greenfield Discovery (Autonomous Edge Hunter)
> *"I want a high-Sharpe intraday strategy for BTCUSDT on the 15m timeframe. I have no predefined indicators. Formulate candidate hypotheses, run the empirical edge scanner to verify forward Rank IC, construct a strategy with objective structural invalidation, run the 8-Gate Cynic audit, and show me the surviving system."*

### Example B: User-Guided Concept (Specific Hypothesis)
> *"Build an Asian session liquidity sweep strategy on XAUUSD (5m). Enter when price sweeps the Asian high or low during London open and prints structural rejection. Target the opposite session boundary, size with 0.5% 1R dollar risk, and stress-test it against Monte Carlo and noise jitter."*

### Example C: Prop-Firm Capital Preservation
> *"Create a conservative swing strategy on EURUSD targeting a smooth equity curve ($R^2 \ge 0.90$) with strict drawdown containment ($\text{MDD} \le 2.5\%$). Audit it against deflated Sharpe and regime survival."*

The AI will follow [`SKILL.md`](SKILL.md), execute the tools, inspect data mathematically, and build a verified, production-grade strategy.

---

## 📁 Repository Structure

```
nujinSkills/
├── SKILL.md                     # High-density agent skill meta-kernel (~80 lines)
├── README.md                    # Framework architecture, focus & quickstart
├── core/                        # Pure mathematical calculation primitives (Zero Trading Bias)
│   ├── discovery.py             # Universal Rank IC & Friction clearance engine
│   ├── cynic_gates.py           # The 8 Institutional Cynic Falsification Gates
│   ├── simulation.py            # Pessimistic intrabar discrete backtest simulator
│   ├── risk.py                  # Dynamic 1R risk normalization & drawdown governors
│   ├── friction.py              # Single source of truth for venue costs & hurdles
│   ├── data.py                  # Multi-venue candle fetcher & caching engine
│   ├── indicators.py            # Vectorized technical & statistical indicators
│   ├── market_structure.py      # Structural swing, liquidity & fair value detectors
│   ├── portfolio.py             # Cross-strategy correlation & ensemble management
│   └── regimes.py               # Market regime classifier (Bull, Bear, Range, High-Vol)
├── tools/                       # Reusable CLI utility executables
│   ├── scan_edge.py             # Empirical edge & anomaly scanner CLI
│   ├── run_backtest_audit.py    # 8-Gate Cynic audit runner (Single Source of Truth)
│   ├── strategy_manager.py      # Strategy lifecycle compiler & symlinker
│   ├── bot_control.py           # Live bot supervisor & runner
│   ├── server_control.py        # FastAPI telemetry daemon controller
│   └── chart_copilot.py         # TradingView visual canvas bridge
├── references/                  # Specialized deep-dive documentation modules
│   ├── edge_discovery.md        # Scientific hypothesis formulation & IC verification
│   ├── execution_geometry.md    # Invalidation math, 1R sizing & expectancy laws
│   ├── alpha_pipeline.md        # 5-Phase Institutional Discovery Pipeline
│   ├── cynic_gates_protocol.md  # 8-Gate specification & failure remediation
│   ├── strategy_interface.md    # Standard Python strategy contract & class skeleton
│   └── bot_operations.md        # Bot lifecycle, state control & Telegram commands
└── tests/                       # Complete automated unit & framework integrity test suite
```

---

## 📜 License & Philosophy

`nujinSkills` is engineered on the philosophy that **financial markets are non-deterministic, but mathematical and risk geometry are exact**. Edge is not finding a magic indicator; edge is finding a persistent statistical inefficiency, trading it with positive net expectancy, and managing risk with uncompromising rigor.
