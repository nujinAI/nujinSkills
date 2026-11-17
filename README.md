# ⚡ NujinSkill — Universal Quantitative Trading Engine as a Agent Skill

[![System: NujinAI](https://img.shields.io/badge/System-NujinAI-blue.svg)](SKILL.md)
[![Quant Protocol](https://img.shields.io/badge/Methodology-Pure%20Mathematical%20Basis-emerald.svg)](references/alpha_pipeline.md)
[![ML Discovery](https://img.shields.io/badge/ML%20Discovery-130--Coord%20Basis%20%2B%20Sub--Era%20Invariance-cyan.svg)](references/edge_discovery.md)
[![Audit: 8--Gate Cynic](https://img.shields.io/badge/Audit-8--Gate%20Cynic%20%7C%20R%C2%B2%20%E2%89%A5%200.85-amber.svg)](references/cynic_gates_protocol.md)
[![Chart Copilot](https://img.shields.io/badge/Visual-AI%20Chart%20Copilot-indigo.svg)](references/chart_copilot_protocol.md)
[![Bot Operations](https://img.shields.io/badge/Bot-Live%20Supervision-cyan.svg)](references/bot_operations.md)
[![Telemetry API](https://img.shields.io/badge/Telemetry-JSON%20API-sky.svg)](references/telemetry_api.md)

> **Empower autonomous AI agents to discover market anomalies, engineer battle-tested strategies, and deploy reliable trading bots—100% on CPU.**

> [!CAUTION]
> This project is in an early stage and is provided for **educational and research purposes only**. Nothing herein constitutes financial or investment advice. Participating in financial markets carries substantial risk of loss—never trade or risk more capital than you are willing to lose.

---

## 🎯 What is nujinSkills?

**nujinSkills** is an open-source, agent-agnostic **AI Quant Skill and Systematic Execution Framework**. It transforms an AI coding agent (in Antigravity, Claude Code, Cursor, or Windsurf) into an autonomous quantitative researcher and systematic trading engineer.

Instead of relying on an LLM to guess crowded retail indicators or brute-force backtest parameters, `nujinSkills` equips the agent with a **CPU-Native Machine Learning & Mathematical Discovery Microscope**:

1. **Mathematical Market Anomaly Discovery:** Analyzes raw market data across multiple timeframes to spot real statistical patterns without relying on lagging retail indicators.
2. **Multi-Era Consistency Check:** Validates that patterns hold across different market cycles and time periods rather than just working by chance in one specific slice.
3. **Robust Risk & Target Optimization:** Automatically scans stop-loss and take-profit levels to ensure strategies sit on stable, wide performance zones rather than fragile peak settings.
4. **Clean Strategy Generation:** Translates discovered market edges into compact, transparent code without bloated parameters or curve-fitting.
5. **Adversarial Stress Testing:** Subjecting every strategy to strict institutional stress tests (Monte Carlo simulations, fee stress, noise testing, and unseen out-of-sample data) to reject overfitted models before they ever see real capital.
6. **Live Paper Trading:** Deploys verified strategies in real-time market conditions via paper trading, allowing you to validate live execution, telemetry, and performance without risking any capital.

---

## 💎 Core Architectural Focus & Capabilities

### 1. User Mandate Envelope Translation (Zero Indicator Pre-Bias)
You never need to know which indicators or mathematical formulas to ask for. You simply state your high-level objective—and the AI translates your goal into mathematical envelope constraints while leaving anomaly discovery 100% to the unbiased mathematical engine:
- **Algo Scalping (1m–5m):** Short holding horizons, strict friction clearance multiples, tight drawdown ceiling.
- **Prop-Firm Day Trading (5m–15m):** Intraday execution, strict drawdown containment ($\text{MDD}_{99} \le 2.0\%$) tailored to prop-firm rules.
- **Swing Trading (1h–4h):** Multi-day holding horizons and structural volatility stops.
- **Investment / Position Plans (4h–1D):** Macro drift and dispersion-regime allocation.

### 2. The Deep Quantitative Discovery Microscope (Under the Hood)
Beneath the conversational interface, the engine executes institutional-grade quantitative mechanics on every research run:
1. **130-Coordinate Pure Mathematical Basis Grid:** Decomposes raw OHLCV into its 6 lossless physical vectors (normalized log-return velocity, span energy, intrabar displacement, boundary asymmetry, close coordinate, and relative log-volume impulse) and applies statistical operators (Moments 1–3, non-parametric IQR coordinates, cross-scale dispersion ratios, serial autocorrelation, variance ratios, path efficiency, and vector inner products) across the Fibonacci scale grid $W \in \{2, 3, 5, 8, 13, 21, 34, 55\}$.
2. **CPU ML Conditional Anomaly & 5-Slice Sub-Era Invariance Miner:** Uses tree-ensemble importance and shallow surrogate decision trees trained directly on discrete barrier outcomes to uncover non-linear 2D conditional anomalies. Enforces **5-Slice Chronological Sub-Era Invariance** ($\ge 75\text{--}80\%$ positive sub-eras) inside the In-Sample window to prevent 70/30 Out-of-Sample regime collapse.
3. **2D MFE/MAE Stability Plateau Optimizer:** Simulates candidate triggers under exact Pessimistic Intrabar Resolution and Opposite-Signal Reversals across the Stop-Loss / Take-Profit surface, applying neighborhood plateau smoothing and Monte Carlo bootstrap sizing ($1R$) so strategies sit on wide parameter plateaus.
4. **Formula-Driven Strategy Synthesis:** Compiles discovered mathematical anomalies directly into clean, $\le 3$-parameter strategy classes without human or LLM boilerplate bias.
5. **Adversarial 8-Gate Cynic Falsification & ML Trade Autopsy:** Actively stress-tests strategies across In-Sample and unseen Blind Out-of-Sample datasets. When any gate fails, an automated In-Sample shallow-tree trade autopsy diagnoses the exact mathematical regime state causing the failure—eliminating blind parameter brute-forcing.

### 3. The 5 Inviolable Quantitative Invariants
Regardless of user requirements or strategy style, the engine strictly enforces 5 mathematical laws:
1. **Zero Textbook Pre-Bias:** Entry and regime rules are mined from the 130 dimensionless basis coordinates—never guessed from retail indicator lore.
2. **5-Slice Sub-Era Invariance & 2/3 vs. 1/3 Blind OOS Isolation:** Discovery occurs exclusively on the first 66.7% In-Sample segment across 5 chronological sub-eras. The final 33.3% Blind Out-of-Sample segment remains untouched until final audit.
3. **Positive Net Expectancy ($\mathbb{E}[R] > 0$) on a Stability Plateau:**
   $$\mathbb{E}[R] = (W \times R_{\text{win}}) - ((1 - W) \times 1.0) - \text{Friction} > 0$$
4. **Authentic Instrument Modeling:** Models the genuine execution realities of the traded instrument (Forex Spot, CFD, Equities, Futures, or Crypto Spot/Perp) including tick sizes, spreads, swap, and synthetic volume limitations.
5. **Zero Hardcoded Capital & Zero Silent Fallbacks:** Position sizing scales dynamically with equity risk percentage (`risk_pct_1r`, calibrated via bootstrap Monte Carlo).

---

## 🔄 The 5-Phase Systematic Alpha Pipeline

```
[ Phase 1: User Mandate & Envelope Translation ]
  → Maps your goal (scalping, prop-firm day trading, swing, investing) to mathematical risk & horizon constraints.

[ Phase 2: Authentic Ingestion & Blind Out-of-Sample Isolation ]
  → Pulls authentic market history; chronologically locks the final 33.3% as unseen Blind OOS.

[ Phase 3: Pure Mathematical Basis & ML Plateau Scan ]
  → Evaluates 130 multi-scale coordinates -> Shallow Surrogate Trees -> 5-Era Invariance -> MFE/MAE Plateau.

[ Phase 4: Formula-Driven Strategy Synthesis ]
  → Compiles the verified anomaly into a <= 3-parameter strategy class with dynamic 1R sizing.

[ Phase 5: Adversarial 8-Gate Cynic Audit & ML Trade Autopsy ]
  → Evaluates In-Sample and Blind OOS against all 8 gates, iterating via ML Trade Autopsy until compliant.
```

---

## 🛡️ The 8 Institutional Cynic Stress Gates

Before any strategy is approved for deployment, it must survive the full adversarial falsification suite:

| Gate | Name | Pass Condition | Institutional Purpose |
| :--- | :--- | :--- | :--- |
| **Gate 1** | **Deflated Sharpe Ratio (DSR)** | $\text{DSR} \ge 0.95$ | Penalizes Sharpe for selection bias and trial multiplicity (López de Prado). |
| **Gate 2** | **Parameter Stability Surface** | $< 30\%$ drop across $\pm 10\%$ params | Rejects overfitted "needle-in-a-haystack" parameter cliffs. |
| **Gate 3** | **Monte Carlo Stress** | $\text{MDD}_{99} \le 3.0\%$, Tail Ratio $\le 2.5$ | Falsifies sequence risk and fat-tail ruin probability across 1,000 runs. |
| **Gate 4** | **Walk-Forward CPCV** | OOS Sharpe retention $\ge 50\%$ | Prevents regime overfitting across non-contiguous market blocks. |
| **Gate 5** | **Regime Survival** | Profitable/neutral across all market phases | Tests robustness in Bull, Bear, and Ranging market slices. |
| **Gate 6** | **Microstructure Friction** | Roundtrip cost $\le 10\%$ of stop distance | Ensures the edge is not eaten alive by real-world spread and slippage. |
| **Gate 7** | **Noise Jitter Resilience** | $\ge 80\%$ Sharpe retention under price jitter | Rejects strategies dependent on micro-tick sequence luck. |
| **Gate 8** | **Equity Linearity** | Curve $R^2 \ge 0.85$, $K\text{-Ratio} \ge 1.5$ | Demands consistent, steady growth over erratic outlier spikes. |

---

## 🚀 How to Use nujinSkills

You do not need to run any scripts or know any quantitative commands yourself. The AI agent knows the entire framework through [`SKILL.md`](SKILL.md) and executes every step autonomously from A to Z.

### 1. Start Here
Download the repository or use the following command in your terminal:
```bash
git clone https://github.com/nujinAI/nujinSkills.git
```

### 2. Open Your AI Agent in the Folder
Open the project folder in your AI coding environment (Antigravity, Claude Code, Cursor, or Windsurf).

### 3. Tell the AI What You Need
Simply describe your objective in plain language—the AI handles the research, mathematical anomaly discovery, strategy construction, 8-Gate stress testing, deployment, and live monitoring automatically:

- **Prop-Firm Day Trading:**
  > *"I need a day trading strategy on Gold (XAUUSD) for my \$10,000 prop-firm account with a strict 3% max drawdown limit."*
- **Algo Scalping:**
  > *"Build me a fast algorithmic scalping strategy for BTCUSDT that clears exchange fees and slippage."*
- **Swing Trading:**
  > *"I want a multi-day swing trading strategy on EURUSD or Nasdaq with low trade frequency and smooth equity growth."*
- **Investment Plan:**
  > *"Create a long-horizon systematic investment strategy with strict downside protection across bull and bear regimes."*

### 4. Optional: Run in the Background & on System Startup
> [!TIP]
> If you want to let the engine run continuously in the background—and even automatically start up whenever your device reboots—simply tell your AI agent:
> *"Set up nujinSkills to run in the background and start automatically on system reboot."*

---

## ⚠️ Data Limitations & Single Source of Truth

Out of the box, this engine runs **paper trading only** (no live order execution) and uses **`tradingview_websocket`** (`TradingViewWebSocket`) for **free, API-keyless** market data across Equities, FX, Futures, and Crypto. While this enables zero-config research and paper trading, users must be aware of the following limitations:

- **Shallow Intraday History:** Unauthenticated TradingView WebSocket feeds are capped on historical bar depth (e.g., ~30 days on `5m` timeframes), which limits long-horizon intraday strategy discovery and out-of-sample validation.
- **Paper Trading Only by Default:** `tradingview_websocket` is a market-data-only feed. Live order routing is not enabled out of the box—you must integrate your own broker/exchange API to execute real trades.
- **Broker Integration & Single Source of Truth:** Once a broker is integrated (e.g., Alpaca, OANDA, Interactive Brokers, or Binance/Bybit for Crypto), its feed can be used directly by the system for both backtesting and live execution to guarantee 1:1 parity.
- **Prop-Firm CFD Caveat:** Prop-firm CFD feeds are often synthetic or broker-specific and do not reflect true underlying market structure. When trading prop firms, **always discover and validate your mathematical edge on real exchange/institutional data (e.g., TradingView)**, and use the prop-firm broker strictly for **order execution**.

---

## 📜 License & Philosophy

`nujinSkills` is **free and open source**.

Wealth should be a right, not a privilege. In an AI era where traditional labor is disappearing and a K-shaped economy widens the divide, financial markets should not remain gated behind institutional walls.

This is a project for the people—built to make the markets accessible to everyone through a complete, standardized framework. Retail participants do not lose money because markets are unnavigable; they lose because they lack access to a disciplined, standardized process. `nujinSkills` exists to put that process in everyone's hands.
