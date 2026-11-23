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

Instead of forcing canned templates or falling into naive retail indicator traps, `nujinSkills` empowers the agent to **research any market empirically, engineer creative institutional strategies, and falsify them rigorously—100% on CPU**:

1. **Autonomous In-Sample Market Research:** Profiles volatility, friction feasibility, return persistence/reversion, regime mix, and diurnal liquidity (`tools/validate_hypothesis.py --profile`), plus optional multi-scale mathematical anomaly scanning (`tools/scan_edge.py`) so the agent selects the highest-fit paradigm on its own.
2. **4-Layer Institutional Strategy Craft:** Structures strategies around **Context → Location (Zone) → Confirmation → Structural Invalidation** with professional, orthogonal, volatility-normalized indicator discipline—zero predefined recipes or retail indicator traps.
3. **Automated Zero-Lookahead & Sub-Era Pre-Validation:** Proves causal prefix-invariance, 5-slice chronological Sub-Era Invariance, actual friction clearance, and 4-layer diagnostics strictly In-Sample before touching Blind Out-of-Sample data.
4. **Robust Risk & Target Geometry:** Anchors stops to objective structural invalidation and dynamic fractional equity risk (`risk_pct_1r`), validated on wide stability plateaus.
5. **Adversarial 8-Gate Cynic Stress Testing:** Subjects every strategy to strict institutional stress tests (DSR, parameter plateaus, Monte Carlo MDD99, CPCV walk-forward, regime survival, friction, jitter, linearity, and unseen Blind OOS) with layer-aware + ML Trade Autopsy.
6. **Live Paper Trading:** Deploys verified strategies in real-time market conditions via paper trading, allowing you to validate live execution, telemetry, and performance without risking any capital.

---

## 💎 Core Architectural Focus & Capabilities

### 1. Autonomous Market Research & Mandate Adaptation
You can specify an exact trading style, zone/structural thesis, or indicator domain—or leave the approach open. When unspecified, the agent profiles the market empirically on the In-Sample slice (`tools/validate_hypothesis.py --profile`, plus optional `tools/scan_edge.py`) and autonomously chooses the best paradigm:
- **Algo Scalping (1m–5m):** Short holding horizons, strict friction clearance, tight drawdown ceiling.
- **Prop-Firm Day Trading (5m–15m):** Intraday execution, strict drawdown containment ($\text{MDD}_{99} \le 2.0\%$) tailored to prop-firm rules.
- **Swing Trading (1h–4h):** Multi-day holding horizons and structural invalidation stops.
- **Investment / Position Plans (4h–1D):** Macro drift and dispersion-regime allocation.

### 2. Core Research & Falsification Engine (Under the Hood)
Beneath the conversational interface, the engine enforces institutional-grade rigor on every research run:
1. **In-Sample Market Profiler & Optional 103-Coordinate Mathematical Basis Scanner:** Profiles volatility, friction-to-ATR feasibility, persistence/mean-reversion signature, regime mix, and diurnal liquidity—with an optional multi-scale mathematical basis & CPU ML conditional anomaly scanner (`tools/scan_edge.py`).
2. **4-Layer Institutional Craft & Professional Indicator Discipline:** Empowers creative strategies built around **Context → Location (Zone) → Confirmation → Structural Invalidation** using `core.indicators` (201 TA-Lib indicators, causal MTF, cross-asset), `core.market_structure(..., causal=True)`, `core.feature_factory`, or custom causal math—without retail indicator traps or hardcoded templates.
3. **Automated Zero-Lookahead & Sub-Era Pre-Validation (`tools/validate_hypothesis.py`):** Proves causal prefix-invariance, 5-slice chronological Sub-Era Invariance, actual friction clearance, and 4-layer diagnostics strictly on the 66.7% In-Sample slice before touching Blind OOS.
4. **Adversarial 8-Gate Cynic Falsification & Layer-Aware Autopsy:** Stress-tests strategies across In-Sample and unseen Blind Out-of-Sample datasets. When any gate fails, In-Sample 4-layer + shallow-tree trade autopsy isolates the root cause—eliminating blind parameter brute-forcing.

### 3. The 5 Inviolable Quantitative Invariants
Regardless of user requirements or strategy style, the engine strictly enforces 5 mathematical laws:
1. **Professional Causal Engineering (Zero Retail Traps):** Indicators and zones must be strictly causal, volatility-normalized, orthogonal, and empirically validated—never standalone lagging triggers or magic-number curve-fits.
2. **Zero Lookahead, Sub-Era Invariance & 2/3 vs. 1/3 Blind OOS Isolation:** Research and pre-validation occur exclusively on the first 66.7% In-Sample segment. The final 33.3% Blind Out-of-Sample segment remains untouched until final audit.
3. **Positive Net Expectancy ($\mathbb{E}[R] > 0$) on a Stability Plateau:**
   $$\mathbb{E}[R] = (W \times R_{\text{win}}) - ((1 - W) \times 1.0) - \text{Friction} > 0$$
4. **Authentic Instrument Modeling:** Models the genuine execution realities of the traded instrument (Forex Spot, CFD, Equities, Futures, or Crypto Spot/Perp) including tick sizes, spreads, swap, and synthetic volume limitations.
5. **Zero Hardcoded Capital & Zero Silent Fallbacks:** Position sizing scales dynamically with equity risk percentage (`risk_pct_1r`) and objective structural invalidation.

---

## 🔄 The 5-Phase Systematic Alpha Pipeline

```
[ Phase 1: Mandate & In-Sample Market Research ]
  -> Profiles asset microstructure (`validate_hypothesis.py --profile` + optional `scan_edge.py`) to select paradigm.

[ Phase 2: Authentic Ingestion & Blind Out-of-Sample Isolation ]
  -> Pulls authentic market history; chronologically locks the final 33.3% as unseen Blind OOS.

[ Phase 3: Creative 4-Layer Strategy Synthesis ]
  -> Engineers Context -> Location (Zone) -> Confirmation -> Structural Invalidation with causal math/indicators.

[ Phase 4: In-Sample Hypothesis Pre-Validation (`tools/validate_hypothesis.py`) ]
  -> Verifies Zero Lookahead (prefix-invariance), Sub-Era Invariance, Friction Floor, and 4-Layer diagnostics.

[ Phase 5: Adversarial 8-Gate Cynic Audit & Layer-Aware Autopsy ]
  -> Evaluates In-Sample and Blind OOS against all 8 gates, iterating autonomously until compliant.
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

### 1. Install the Skill (Standardized)

**Universal Agent Install (`skills.sh` — Antigravity, Claude Code, Cursor, Codex, OpenCode, Hermes):**
```bash
npx skills add nujinAI/nujinSkills
```

**OpenClaw / ClawHub:**
```bash
clawhub install nujinskills
```

> **First-Run Setup:** On your first prompt, your AI agent will automatically create `.venv` and install `requirements.txt` (or ask once for permission to run it). No manual Python setup is required.

<details>
<summary>Alternative: Manual Clone (Secondary)</summary>

```bash
git clone https://github.com/nujinAI/nujinSkills.git
```
Then open the cloned folder in your AI coding environment (Antigravity, Claude Code, Cursor, or Windsurf).

</details>

### 2. Tell the AI What You Need
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

## 🤝 Contributing & Contributors

Contributions of all kinds—quantitative research tools, causal indicators, bug fixes, tests, and documentation—are welcome! Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a pull request.

Every contributor whose pull request is merged is attributed here:

<!-- Contributors are listed alphabetically by GitHub handle -->
| Contributor | Contributions |
| :--- | :--- |
| *Be the first to contribute!* | *See [`CONTRIBUTING.md`](CONTRIBUTING.md) to get started.* |

---

## 📜 License & Philosophy

`nujinSkills` is **free and open source**.

Wealth should be a right, not a privilege. In an AI era where traditional labor is disappearing and a K-shaped economy widens the divide, financial markets should not remain gated behind institutional walls.

This is a project for the people—built to make the markets accessible to everyone through a complete, standardized framework. Retail participants do not lose money because markets are unnavigable; they lose because they lack access to a disciplined, standardized process. `nujinSkills` exists to put that process in everyone's hands.
