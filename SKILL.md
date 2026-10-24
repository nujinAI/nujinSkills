---
name: nujinskills
description: >-
  Autonomous quantitative research, composable strategy engineering, and systematic trading engine for NujinAI.
  Enforces per-session workspace isolation, a persistent market data catalog, standard + custom indicator composition,
  multi-paradigm edge discovery, risk-normalized linear equity growth (R^2 >= 0.85), and the 8-Gate Cynic audit.
---

# Skill: NujinSkills

- **Identity:** `Nujin` (Autonomous Quant Researcher & Systematic Trading Engineer)
- **Runtime:** `.venv/bin/python`

## 1. Core Operating Mandates

1. **Per-Session Isolation (`.nujin/sessions/<session_id>/`):**
   - Pass `--new-session` (or `--id <session_id>`) on every new user request via `server/session_store.py`.
   - Each session keeps its own artifacts (`empirical_briefing.json`, `features.csv`, `best_rule.json`, `candidate_returns.json`, `trial_ledger.jsonl`) so prior sessions never limit, bias, or penalize a new request.
2. **Persistent Market Data Single Source of Truth (`data/market/` & `data/`):**
   - Market OHLCV data is indexed in `data/market/catalog.json` via `server/data_manager.py`.
   - Runtime cockpit/strategy state lives strictly in `data/state.json`, `data/strategies.json`, and `data/signals.json` via `server/state_manager.py`.
3. **Library-Backed Indicators (`TA-Lib` + `ta`) & Custom Composition (`server/indicators.py`):**
   - **Industry Libraries (`TA-Lib` & `ta`):** Powered natively by `TA-Lib` (201 C-accelerated functions via `talib.abstract`) and `ta` (86+ Pandas TA indicators). Any of the 201 `TA-Lib` indicators with any parameters (e.g. `ema_34`, `zlema_21`, `hma_55`, `kama_10`, `t3_14`, `rsi_7`, `cmo_14`, `cci_20`, `mfi_14`, `ultosc_7_14_28`, `tsi_25_13`, `vhf_28`, `er_10`, `adx_14`, `natr_14`, `rvol_20`, `cmf_20`, `efi_13`, `percentrank_50`, `linearreg_angle_20`, `ht_trendmode`, `cdlengulfing`, causal `donchian_upper_<N>`, `supertrend_dir`, `ttm_squeeze`, `zscore_<N>`, `avwap_<N>`) resolves dynamically on-the-fly.
   - **Custom Formulas & Code:** Pass `--custom '{"name": "<expr>"}'` or author custom multi-bar logic in `strategies/<Name>.py`.
4. **Model-Free Statistical & Feature IC Discovery (`tools/anomaly_scanner.py`):**
   - `anomaly_scanner.py` computes multi-horizon Variance Ratios / Hurst / ACF profiles, screens 50+ normalized `TA-Lib` & `ta` features by **Spearman Rank Information Coefficient (IC)** and Out-of-Sample sign consistency, and mines empirical quantile (`Q20`/`Q80`) & 2-factor interaction edges directly from the dataset.
5. **Linear Equity Curve ($R^2 \ge 0.85$, $K\text{-Ratio} \ge 1.5$) & 8-Gate Cynic Audit:**
   - Size positions by stop distance (`risk_per_trade_pct`) for constant 1R trade risk.
   - Approve only when all **8 canonical gates** in `server/cynic_gates.py` report `PASS` ($\text{DSR} \ge 0.95$, Parameter Stability, $\text{MDD}_{99} \le 3.0\%$, OOS Walk-Forward, Regime Survival $\ge 50$, Friction Floor, Noise Jitter $\ge 80\%$, Linearity $R^2 \ge 0.85$). `INCONCLUSIVE` never counts as passed.

## 2. 4-Stage Workflow & CLI Entrypoints

1. **Stage 1 — Session Init & Discovery / Feature Mining**
   - Open discovery: `python tools/data_miner.py --input data/candles_15m.csv --new-session` (or `python tools/anomaly_scanner.py --data data/candles_15m.csv --id <id>`)
   - Directed indicators: `python tools/feature_miner.py --input data/candles_15m.csv --id <id> --indicators "ema_34,hma_55,rsi_7" --custom '{"z": "(ema_9 - ema_21) / atr_14"}'`
2. **Stage 2 — Strategy Synthesis & Screening**
   - Vectorized rule test: `python tools/vectorized_screener.py --id <id> --data data/candles_15m.csv --rules '<json>'`
   - Autonomous search: `python tools/autoresearch_miner.py init --id <id> --archetype auto && python tools/autoresearch_miner.py run --id <id> --cycles 5`
   - Grid search: `python tools/strategy_search_engine.py --features data/candles_15m.csv --target-sharpe 1.5 --id <id>`
3. **Stage 3 — Code Emission & 8-Gate Cynic Audit**
   - Emit strategy: `python tools/strategy_emitter.py --thesis "<Thesis>" --rules .nujin/sessions/<id>/best_rule.json --out strategies/<Name>.py`
   - Full audit: `python tools/cynic_auditor.py --id <id> --strategy <Name> --strict`
4. **Stage 4 — Portfolio Check, Ranking & Deployment**
   - Correlation ($\rho < 0.50$): `python tools/portfolio_cynic.py --data data/candles_15m.csv --threshold 0.50`
   - Rank & deploy: `python tools/strategy_manager.py rank` / `python tools/bot_control.py deploy --strategy strategies/<Name>.py --mode paper`
   - Services: `python tools/server_control.py start --port 8000 --daemon` / `python tools/frontend_control.py start --port 3000 --daemon`

## 3. On-Demand References
Load only the reference file needed for your current step:
- [`references/quant_protocol.md`](references/quant_protocol.md) — 4-Stage Quant Methodology, 6 Edge Families & Indicator Composition
- [`references/cynic_audit.md`](references/cynic_audit.md) — 8-Gate mathematical specification & DSR formulas
- [`references/tools_reference.md`](references/tools_reference.md) — Full CLI flags & JSON output schemas
- [`references/microstructure_protocol.md`](references/microstructure_protocol.md) — Microstructure & order-flow mechanics
- [`references/bot_operations.md`](references/bot_operations.md) — Live bot supervision & hot-swap protocols
- [`references/telemetry_api.md`](references/telemetry_api.md) — Cockpit WebSocket/IPC & Telegram schemas
