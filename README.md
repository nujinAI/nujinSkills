# ⚡ NujinAI / nujinSkills — Autonomous Quant Trading Agent Skill

[![System: NujinAI](https://img.shields.io/badge/System-NujinAI-blue.svg)](SKILL.md)
[![Quant Protocol](https://img.shields.io/badge/Methodology-Universal%20Quant-emerald.svg)](references/quant_protocol.md)
[![Audit: 6--Gate Cynic](https://img.shields.io/badge/Audit-6--Gate%20Cynic%20%7C%20R%C2%B2%20%E2%89%A5%200.85-amber.svg)](references/cynic_audit.md)
[![Market Invariants](https://img.shields.io/badge/Invariants-Auction%20%26%20Wyckoff-teal.svg)](references/microstructure_protocol.md)
[![Tools Reference](https://img.shields.io/badge/Tools-CLI%20Reference-purple.svg)](references/tools_reference.md)
[![Bot Operations](https://img.shields.io/badge/Bot-Live%20Supervision-cyan.svg)](references/bot_operations.md)
[![Telemetry API](https://img.shields.io/badge/Telemetry-JSON%20API-sky.svg)](references/telemetry_api.md)

> **Unlock quantitative trading with full autonomy.** You bring the creative hypothesis and define your targets; your AI agent handles the mathematical modeling, multi-timeframe feature extraction, adversarial statistical falsification (8-Gate Cynic Audit), 24/7 live signaling, and safe bot hot-deployment.

---

## 🎯 What is NujinAI?

**NujinAI (nujinSkills)** is an autonomous quantitative research engine and systematic trading bot packaged as an open-source, agent-agnostic **AI Skill**.

Instead of getting bogged down in boilerplate code, manual data joining, or curve-fitted indicator traps:
1. **Universal Hypothesis Modeling:** Formulate strategies for any concept or market (Price Action, Market Structure, Order Flow, Statistical Arbitrage, Volatility Breakouts, Macro/Funding Spreads, or Machine Learning classifiers).
2. **Institutional Multi-Timeframe (MTF) Confluence:** Seamlessly link Higher-Timeframe (HTF) market regime and context, Mid-Timeframe (MTF) structural zones, and Lower-Timeframe (LTF) precision execution triggers with **strict zero lookahead bias**.
3. **8-Gate Adversarial Falsification:** Stress-test candidates against the Deflated Sharpe Ratio ($\text{DSR} \ge 0.95$), a genuine parameter-stability plateau, 1,000-run Monte Carlo trade order permutations ($\text{MDD}_{99} \le 3.0\%$), out-of-sample walk-forward, multi-regime survival, real friction plus the microstructure noise floor, synthetic noise jitter ($\ge 80\%$ Sharpe retention), and the Equity Linearity Standard ($R^2 \ge 0.85$). All gate mathematics lives in one place — `server/cynic_gates.py` — so the auditor and the deployment path cannot disagree, and a gate that cannot be evaluated reports `INCONCLUSIVE` rather than passing.
4. **Unified Single-Folder Data Isolation (`.nujin/`):** All research features, briefings, returns, and states live strictly inside `.nujin/`, namespaced via `--id <experiment_name>` so new strategies never contaminate or overwrite prior research.
5. **Live Bot Hot-Deployment:** Emits production Python strategies and hot-deploys them into the live running trading engine without dropping active WebSocket connections or restarting server processes.

---

## 💎 Core Strengths & Institutional Edge

1. **Zero Overfitting & No Curve-Fitting Illusions**
   * **Physical Microstructure Noise Floor:** Stop losses, trailing stops, and targets are mathematically required to clear broker spread and tick noise ($\ge \max(3\times \text{Spread}, 1.5\times \text{ATR})$), eliminating sub-pip backtest fantasies.
   * **Adversarial Falsification:** Actively attempts to break every strategy candidate before deployment using Deflated Sharpe Ratio (discounting for multiple search trials and non-normal returns), price noise perturbation, and parameter plateau stability.

2. **Smooth, Linear Capital Growth ($R^2 \ge 0.85$, $K$-Ratio $\ge 1.5$)**
   * Rejects erratic, high-variance strategies driven by lucky outlier windfalls.
   * Specifically optimizes for a steady, straight-line upward equity curve with strict tail-risk drawdown containment ($\text{MDD}_{99} \le 3.0\%$)—tailored for consistency and passing prop firm evaluations.

3. **Universal Market Invariants (Auction Market Theory & Wyckoff Mechanics)**
   * Anchors alpha to physical price formation laws: Value Area acceptance ($H < 0.45$) vs. price discovery ($H > 0.55$), Wyckoff volatility compression (`vol_compression < 0.70`), and passive limit absorption of trapped inventory (`absorption_bullish`/`bearish`).

4. **Active Alpha Protection & Volatility Risk Management**
   * **Invalidation-Based Position Sizing:** Automatically scales position size inversely with structural invalidation distance to enforce strict dollar-risk uniformity.
   * **Alpha Half-Life (Time Invalidation):** Automatically scratches stale trades after $N$ bars (`TIME_EXPIRATION`), cutting dead-money drag and chop risk.
   * **Live CUSUM Drift Circuit Breaker:** Continuously monitors live forward returns; automatically halts new entries and dispatches Telegram alerts if performance degrades beyond $2.5\sigma$.

5. **Institutional Multi-Timeframe (MTF) Confluence**
   * Solves single-timeframe myopia through a rigorous 3-tier hierarchy: **HTF** (Macro Regime & Bias) $\rightarrow$ **MTF** (Structural Zone / Setup) $\rightarrow$ **LTF** (Execution Trigger & Precise Invalidation).

6. **Unified Closed-Loop AI Quantitative Compiler**
   * The AI directly authors native Python strategies inheriting `IStrategy`, verifies all 6 Cynic Gates in closed-loop iteration, and hot-deploys them to the live running engine and dual-screen telemetry dashboard.

---

## ⚡ Quick Start

### 1. Installation & Environment Setup
Clone the repository and initialize the Python virtual environment:

```bash
git clone https://github.com/autonomousEnterprises/nujinSkills.git
cd nujinSkills

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Start the System Engines
```bash
# 1. Start FastAPI Telemetry & Execution Server (Port 8000)
python tools/server_control.py start --port 8000 --daemon

# 2. Start Dual-Screen Visual Cockpit (Port 3000)
python tools/frontend_control.py start --port 3000 --daemon
```

### 3. Prompt Your AI Agent
Open this workspace in your agentic coding environment (**Google Antigravity**, **Claude Code**, **Cursor**, **Windsurf**, or **Hermes**) and issue a request:

> *"Research a gold (XAU/USD) 1m scalping strategy targeting max 3% drawdown and Sharpe >= 1.8 with 5m MTF trend confluence. Mine the features, run the 8-Gate Cynic audit, and deploy it to paper mode."*

The agent reads [`SKILL.md`](SKILL.md), invokes the specialized CLI tools, and executes the entire institutional pipeline.

---

## 🔄 The 4-Stage Quant Methodology

```
[ STAGE 1: Empirical Anomaly & Statistical Discovery ]
  Calculate Variance Ratios, Hurst Exponent, and Alpha Half-Life Decay without indicator bias.
                    │
                    ▼
[ STAGE 2: Multi-Timeframe Feature Mining & Iterative Search ]
  Join HTF context -> Extract scale-invariant features -> Vectorized screen -> Mutate rules.
                    │
                    ▼
[ STAGE 3: 8-Gate Adversarial Cynic Audit (Falsification) ]
  DSR (>= 0.95) + Param Stability + MC MDD99 (<= 3.0%) + OOS Walk-Forward + Regime Survival
  + Friction/Noise Floor + Noise Jitter (>= 80%) + Linearity (R² >= 0.85). All in server/cynic_gates.py.
                    │
                    ▼
[ STAGE 4: Native Strategy Synthesis, Closed-Loop Audit & Live Hot-Deployment ]
  Directly code native Python class, enforce all 8 Cynic Gates, verify correlation (< 0.50), & hot-deploy.
```

---

## 📁 Unified `.nujin/` Data Architecture

All agent-generated data is strictly consolidated inside `.nujin/`, keeping root directories completely clean:

```
nujin/
├── data/                               <- RAW MARKET FEEDS ONLY (Untouched historical CSVs)
│   ├── candles_15m.csv
│   └── xauusd_candles_1m.csv
│
├── .nujin/                             <- ALL GENERATED RESEARCH DATA & STATE ONLY
│   ├── features.csv                    (Latest mined features)
│   ├── empirical_briefing.json         (Latest empirical anomaly briefing)
│   ├── candidate_returns.json          (Latest backtest return series)
│   ├── best_rule.json                  (Latest promoted rule specification)
│   │
│   └── experiments/                    <- ISOLATED EXPERIMENT SCOPES (--id <name>)
│       ├── btc_momentum_15m/           (Completely isolated research files)
│       │   ├── features.csv
│       │   ├── briefing.json
│       │   ├── state.json
│       │   ├── rules.json
│       │   ├── best_rules.json
│       │   ├── candidate_returns.json
│       │   └── results.jsonl
│       │
│       └── xauusd_scalp_1m/            (Zero collision with other strategies)
│
└── strategies/                         <- STANDALONE PYTHON STRATEGY CODE ONLY
    ├── XauLiquidityWallsDisplacementScalper.py
    └── MyNewAlphaStrategy.py
```

---

## 🛠️ Complete CLI Tool Matrix

Invoke all tools using the project virtualenv (`.venv/bin/python3 tools/<tool>.py`):

### 0. Preflight (Run This First)
* **Full production-readiness gate (compile + hermetic suite + audit CLI agreement):**
  ```bash
  python tools/preflight.py
  ```

### 1. Empirical Discovery & Feature Extraction
* **Market Anomaly & Statistical Profiling:**
  ```bash
  python tools/anomaly_scanner.py --data data/candles_15m.csv --id my_alpha
  ```
* **Multi-Feature Extraction with Multi-Timeframe (MTF) Confluence:**
  ```bash
  python tools/feature_miner.py --input data/xauusd_candles_1m.csv --id my_alpha --htf-data data/xauusd_candles_5m.csv --window 20
  ```

### 2. Search & Iterative Optimization Loop
* **Autonomous Research Engine (Full loop or single steps):**
  ```bash
  python tools/autoresearch_miner.py init --id my_alpha --target "XAUUSD Scalper"
  python tools/autoresearch_miner.py run --id my_alpha --cycles 5
  python tools/autoresearch_miner.py status
  ```
* **Fast Vectorized Screener (Condition Filter with Friction):**
  ```bash
  python tools/vectorized_screener.py --id my_alpha --rules '{"entry_long": "ret_zscore < -2.0", "exit": "bars >= 6"}'
  ```

### 3. Adversarial Cynic Audit (Falsification)
* **8-Gate Adversarial Cynic Auditor (DSR + Param Stability + MC MDD + OOS + Regimes + Friction/Noise Floor + Noise Jitter + Linearity):**
  ```bash
  python tools/cynic_auditor.py --id my_alpha --trials 50 --strict
  ```
* **Portfolio Correlation & Regime Orthogonality:**
  ```bash
  python tools/portfolio_cynic.py --data data/candles_15m.csv --threshold 0.50
  ```

### 4. Native Strategy Synthesis & Closed-Loop Cynic Verification
* **Native Production Python Class Generation & Self-Correction:**
  ```bash
  # Directly authored by the AI Agent with full state machines and risk guards, verified via:
  python tools/cynic_auditor.py --strategy MyCustomStrategy --strict
  ```
* **Strategy Registry & Dynamic Plugins Inspection:**
  ```bash
  python tools/strategy_manager.py list
  python tools/strategy_manager.py plugins
  python tools/strategy_manager.py rank
  ```

### 5. Live Bot Supervision & Telemetry (Non-Disruptive)
* **Query Live Bot Status & Hot-Deploy Strategy:**
  ```bash
  python tools/bot_control.py status
  python tools/bot_control.py deploy --strategy MyCustomStrategy --mode paper
  ```
* **Inspect Live Performance & Signals:**
  ```bash
  python tools/state_control.py signal-stats
  python tools/state_control.py signals
  ```
* **Cockpit UI & Telegram Dispatches:**
  ```bash
  python tools/ui_dispatcher.py --event UPSERT_WIDGET --payload '{"widget_id": "alpha_card", "payload": {}}'
  python tools/telegram_broadcast.py broadcast --type update -m "New alpha strategy hot-deployed to paper mode."
  ```

---

## 🖥️ The Dual-Screen Cockpit

Access the interactive trading cockpit at **`http://localhost:3000`**:

| Screen / Deck | Hotkey | Purpose & Telemetry |
|---|---|---|
| **Chart Canvas** | **`F1`** | High-performance candlestick chart overlaid with visual primitives (multi-scale EMAs, Bollinger Bands, Fair Value Gaps, liquidity sweeps, and execution markers). |
| **Signal Deck** | **`F2`** | Live execution telemetry: win rate, profit factor, annualized Sharpe, active open position card with real-time unrealized PnL, and manual override controls. |
| **Backtest Deck** | **`F3`** | Backtest audit: equity trajectory curves, return distribution, regime breakdown (Bull, Bear, Range), and the 8-Gate Cynic matrix ($R^2 \ge 0.85$). |
| **Strategy Manager** | **`F4`** | Strategy leaderboard, global Live vs. Paper toggle, equity trajectory curves, correlation matrices, and direct action navigation. |
| **Cycle Screens** | **`Ctrl + Space`** | Seamlessly toggle focus between open decks. |

---

## 🧩 Dynamic Plugin Architecture

Nujin supports external modular extensions via the `plugins/` directory. Any installed plugin containing a `plugin.json` or `strategies/` directory is automatically discovered by `server/plugin_loader.py` and `tools/strategy_manager.py plugins` without modifying the core codebase.

---

## 📚 Deep Reference Manuals

For in-depth mathematical derivations and operational specifications:
- [`SKILL.md`](SKILL.md) — Master Autonomous Quant Engine Protocol & Instructions
- [`references/quant_protocol.md`](references/quant_protocol.md) — Universal quant research methodology, MTF architecture, volatility sizing & risk-reward math
- [`references/cynic_audit.md`](references/cynic_audit.md) — 8-Gate Adversarial Falsification formulas (DSR, parameter stability, Monte Carlo MDD, OOS walk-forward, regime survival, friction/noise floor, noise jitter, linearity)

**Testing:** run `python -m pytest` inside `nujinSkills/` (config in `pytest.ini`; dependencies in `requirements-dev.txt`). Shared thresholds and the annualisation policy live in `server/constants.py` — import them rather than restating literals.

**Preflight — "is this checkout safe to run?"** One command runs the whole gate and exits non-zero on the first problem:
```bash
python -m tools.preflight          # add --json for a machine-readable result
```
It byte-compiles `server/`, `tools/` and `tests/`, runs the full suite, and then checks that `tools/validation_cynic.py` and `tools/cynic_auditor.py` still reach the *same* verdict on the same deterministic return series (they are two entry points onto one body of gate mathematics, so a disagreement means the contract broke). This repository deliberately has no CI pipeline, so run it before deploying a change — it is the only gate there is.

The suite is hermetic by contract. `tests/conftest.py` redirects every persisted store into a throwaway directory and blocks outbound sockets *and* name resolution, so a test run never touches live broker accounts, live signal history or live market prices — and never places an order through a connected broker. A test that needs a real feed must opt in explicitly with `NUJIN_ALLOW_NETWORK_TESTS=1`, and `NUJIN_TRACE_NETWORK=1` prints the call site of any blocked attempt. Tests covering the proprietary `nujinPro` extension skip when that plugin (or a given strategy within it) is not installed.

Five invariants are enforced mechanically rather than by convention: every module in `server/` and `tools/` must import with the network blocked (`tests/test_import_safety.py`); live fetches must be reached through the `server.data_manager` module so one seam intercepts them, never via a module-level `from server.data_manager import fetch_x`; no function may read a global the module never defines (`test_framework_consistency.py` resolves scopes with `symtable`); **discovering** broker adapters must not **authenticate** against one — `list_available_brokers()` is read-only by default *and* every call site has to name `connect=` explicitly, so no status surface can inherit a login from a silent default; `get_broker(..., connect=False)` is the read-only form of resolution, an unconnected adapter is never cached (a cached instance whose `connect()` never ran looks healthy to the executor about to place an order), and the reported `connected`/`balance` describe the session that actually exists instead of presenting a configured account as a live one; and the on-disk secret format must not depend on optional packages, so `SecretCipher` always writes the standard-library `sl:` payload (legacy `fn:` Fernet blobs are still read where `cryptography` is installed). None of these are theoretical — they caught an exception handler logging another method's variable, a Telegram listener whose daily-report state was silently never persisted, and a broker listing call that logged in to a live account.
- [`references/microstructure_protocol.md`](references/microstructure_protocol.md) — Market microstructure, trapped inventory, passive absorption, and auction failure dynamics
- [`references/tools_reference.md`](references/tools_reference.md) — Complete CLI manual with all tool flags, parameters, and invocation examples
- [`references/bot_operations.md`](references/bot_operations.md) — Non-disruptive live bot supervision, state inspection, and hot-deployment guide
- [`references/telemetry_api.md`](references/telemetry_api.md) — Cockpit UI WebSocket/IPC payload specifications and Telegram alert schemas

---

## 📄 License

MIT License — Autonomous Enterprises. Built for systematic quantitative researchers and autonomous trading agents.
