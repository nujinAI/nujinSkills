# NujinSkills CLI Tools Reference Manual

This document details every tool available in `nujinSkills/tools/`.
Always invoke tools using the project virtualenv Python:
`nujinSkills/.venv/bin/python tools/<tool_name>.py [args]` (or `.venv/bin/python` if inside `nujinSkills/`).

> **Per-Session Workspace Isolation & Persistent Data Architecture:**
> - **Market Data & Runtime State:** Persistent historical OHLCV datasets live in `data/market/` (indexed by `data/market/catalog.json`) and `data/`. Live runtime state lives in `data/state.json`, `data/strategies.json`, and `data/signals.json`.
> - **Dedicated Per-Session Workspaces:** All research artifacts (features, empirical briefings, candidate returns, best rules, and DSR trial ledgers) are isolated per session inside `.nujin/sessions/<session_id>/` via `server/session_store.py`. Pass `--new-session` to start a clean session or `--id <session_id>` (`--session <session_id>`) across any tool so a new user request is never limited or biased by older sessions.

---

## 0. Preflight Verification

### `preflight.py`
Runs the full production-readiness gate: byte-compiles `server/`, `tools/`, and `tests/`, executes the hermetic `pytest` suite, and verifies that `tools/validation_cynic.py` and `tools/cynic_auditor.py` agree on the canonical 8-gate verdict.
- **Usage:**
  ```bash
  python -m tools.preflight [--json]
  ```

---

## 1. Feature Extraction & Strategy Modeling

### `feature_miner.py`
Extracts a comprehensive suite of TA-Lib indicators, causal multi-timeframe features (MTF 4x and 16x), continuous alpha forecasts, and user-specified custom formulas inside an isolated session.
- **Usage:**
  ```bash
  tools/feature_miner.py --input PATH [--output PATH] [--id SESSION_ID] [--indicators LIST] [--custom JSON]
  ```
- **Example:**
  ```bash
  tools/feature_miner.py --input data/candles_15m.csv --id my_session --indicators "ema_34,hma_55,rsi_7" --custom '{"spread": "(ema_9 - ema_21) / atr_14"}'
  ```

---

### `anomaly_scanner.py` (Optional Exploratory Tool)
Optional market dynamics profiler. Calculates Lo-MacKinlay Variance Ratios, Hurst exponent, session hourly volatility distributions, and feature Information Coefficients (IC) when doing open-ended exploratory data analysis. It is purely informational and never constrains strategy design.
- **Usage:**
  ```bash
  tools/anomaly_scanner.py [--data PATH] [--id SESSION_ID] [--new-session] [--output PATH] [--json]
  ```

---

### `feature_miner.py`
Composable Standard + Custom Indicator & Multi-Timeframe Feature Miner powered by `server/indicators.py`. Computes all standard indicators (`SMA`, `EMA`, `WMA`, `HMA`, `KAMA`, `Supertrend`, causal `Donchian`, `Bollinger`, `Keltner`, `TTM Squeeze`, `RSI`, `MACD`, `Stochastic`, `CCI`, `Williams %R`, `ROC`, `ADX`, `ATR`, `Z-Score`, `Hurst Proxy`, `Slope`, `AVWAP`, `OBV`, `CMF`), arbitrary parameterized indicators, custom user formulas, and causal Higher-Timeframe (`join_asof`) merges.
- **Usage:**
  ```bash
  tools/feature_miner.py --input PATH [--id SESSION_ID] [--new-session] [--output PATH] [--window INT] [--htf-data HTF_PATH] [--htf-prefix PREFIX] [--indicators LIST] [--custom JSON]
  ```
- **Arguments:**
  - `--input`: Path to input OHLCV CSV file (required).
  - `--id` / `--session`: Session ID to isolate features in `.nujin/sessions/<id>/features.csv`.
  - `--new-session`: Create a fresh isolated session for this run.
  - `--output`: Explicit output CSV path.
  - `--window`: Rolling window size for baseline metrics (default: `20`).
  - `--htf-data`: Optional Higher Timeframe CSV joined via backward `join_asof` (zero lookahead bias).
  - `--indicators`: Comma-separated dynamic parameterized indicators (e.g. `"ema_34,hma_55,rsi_5,donchian_upper_40"`).
  - `--custom`: JSON object of custom indicator formulas (e.g. `'{"trend_gap": "(ema_9 - ema_21) / atr_14"}'`).

---

## 2. Strategy Synthesis & Fast Vectorized Screening

### `vectorized_screener.py`
Fast Vectorized & Risk-Normalized Strategy Screener. Automatically resolves any dynamic standard indicator (`ema_34`, `hma_21`, `supertrend_dir`, `donchian_upper_20`, `zscore_20`, etc.) or custom formula via `server/indicators.py` and simulates trades with stop-loss, take-profit, trailing stop, and constant-risk position sizing (`risk_per_trade_pct`) for linear equity curves ($R^2 \ge 0.85$).
- **Usage:**
  ```bash
  tools/vectorized_screener.py [--data PATH] [--rules JSON_STR] [--strategy NAME] [--id SESSION_ID] [--fee-bps FLOAT] [--slippage-bps FLOAT] [--output PATH]
  ```
- **Example:**
  ```bash
  tools/vectorized_screener.py --data data/candles_15m.csv --id my_session --rules '{"entry_long": "ema_9 > ema_21 and adx_14 > 20", "entry_short": "ema_9 < ema_21 and adx_14 > 20", "stoploss_pct": 0.015, "takeprofit_pct": 0.035}'
  ```

---

### `strategy_emitter.py`
Synthesizes verified vectorized rules into standalone, production-ready Python strategy classes (`strategies/<Name>.py`).
- **Usage:**
  ```bash
  tools/strategy_emitter.py --thesis "<Thesis Description>" --rules .nujin/sessions/<session_id>/best_rule.json --out strategies/<Name>.py
  ```

---

## 3. Adversarial Cynic Audit (Falsification)

### `cynic_auditor.py` (and `validation_cynic.py`)
Canonical **8-Gate** Adversarial Falsification Auditor powered by [`server/cynic_gates.py`](../server/cynic_gates.py).
Evaluates:
1. `gate_1_dsr` ($\text{DSR} \ge 0.95$)
2. `gate_2_parameter_stability` (real perturbed plateau)
3. `gate_3_monte_carlo` ($\text{MDD}_{99} \le 3.0\%$, tail ratio $\le 2.5$)
4. `gate_4_walk_forward` ($SR_{OOS} > 1.0$, retention $\ge 30\%$)
5. `gate_5_regime_survival` ($\ge 50/100$ across Bull, Bear, Range)
6. `gate_6_friction` (net expectancy $> 0$ after 5 bps fee + 2 bps slippage; stops $\ge 10\text{ bps}$)
7. `gate_7_noise_jitter` ($\ge 80\%$ Sharpe retention)
8. `gate_8_equity_linearity` ($R^2 \ge 0.85$, positive slope, K-Ratio)

- **Usage:**
  ```bash
  tools/cynic_auditor.py [--id SESSION_ID] [--returns PATH] [--strategy NAME] [--spec PATH] [--trials INT] [--strict] [--json]
  ```
- **Examples:**
  ```bash
  tools/cynic_auditor.py --id my_session --trials 50 --strict
  tools/cynic_auditor.py --strategy MyStrategy --strict
  ```

---

### `portfolio_cynic.py`
Portfolio-level correlation and regime orthogonality auditor. Rejects strategies correlated ($\rho \ge 0.50$) with currently active strategies.
- **Usage:**
  ```bash
  tools/portfolio_cynic.py [--strategies NAMES] [--data PATH] [--threshold FLOAT] [--json]
  ```

---

## 4. Code Generation & Strategy Management

### `strategy_emitter.py`
Generates standalone Python strategy classes (`strategies/<StrategyName>.py`) wired to `server.indicators` so any standard or custom indicator, dynamic stop/target, and risk-normalized position sizing works out of the box.
- **Usage:**
  ```bash
  tools/strategy_emitter.py --thesis "THESIS_TEXT" --rules RULES_JSON_OR_PATH [--framework {nujin,freqtrade,jesse}] [--out PATH]
  ```

---

### `strategy_manager.py`
Central registry and lifecycle manager (`data/strategies.json`) for all strategies across `strategies/` and `plugins/`.
- **Actions:** `list`, `plugins`, `status`, `backtest`, `cron`, `rank`, `insights`, `register`, `summary`, `portfolio`, `correlation`, `drift`, `signals`, `sync`, `remove`, `add`.
- **Examples:**
  ```bash
  tools/strategy_manager.py list
  tools/strategy_manager.py rank
  tools/strategy_manager.py insights MyStrategy
  tools/strategy_manager.py status --strategy MyStrategy --status ACTIVE_LIVE
  ```

---

## 5. Live Bot Supervision & Telemetry

### `bot_control.py`
Non-disruptive supervisor CLI for the live trading bot (`status`, `deploy`, `stop`, `broker`).
- **Examples:**
  ```bash
  tools/bot_control.py status
  tools/bot_control.py deploy --strategy MyStrategy --mode paper
  ```

### `state_control.py`, `ui_dispatcher.py`, & `telegram_broadcast.py`
- Inspect live state & signals: `tools/state_control.py signal-stats`

---

## 6. AI Chart Copilot & Market Structure Analysis

### `chart_copilot.py`
Autonomous CLI & Agent Tool for collaborative market analysis and live chart markup. Computes fractal swings, confirmed BOS/MSS breaks, significant unmitigated Fair Value Gaps (50% equilibrium mitigation), resting Buyside (BSL) and Sellside (SSL) liquidity targets, and concrete trade setups.
- **Usage:**
  ```bash
  tools/chart_copilot.py [--symbol BTC/USDT] [--timeframe 15m] [--lookback 140] [--json]
  ```
- **Example:**
  ```bash
  python tools/chart_copilot.py --symbol BTC/USDT --timeframe 15m
  ```
- Dispatch Cockpit UI widgets: `tools/ui_dispatcher.py --event UPSERT_WIDGET --payload '{...}'`
- Broadcast Telegram alerts: `tools/telegram_broadcast.py broadcast --type alert --title "Alert" --message "Deployed"`
