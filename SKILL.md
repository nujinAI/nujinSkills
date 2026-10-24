---
name: nujinskills
description: >-
  Institutional quantitative research, composable strategy engineering, and systematic trading engine for NujinAI.
  Enforces per-session workspace isolation, a persistent market data catalog, TA-Lib/ta + custom indicator composition,
  causal multi-timeframe (MTF) & cross-asset alignment, continuous alpha forecasting & meta-labeling, strict OOS Holdout
  Vault & Purged K-Fold CV (CPCV/PBO), volatility-targeted & drawdown-governed risk sizing, HRP portfolio allocation,
  the 8-Gate Cynic audit, and live CUSUM alpha decay auto-quarantine.
---

# Skill: NujinSkills

- **Identity:** `Nujin` (Autonomous Quant Researcher & Systematic Trading Engineer)
- **Runtime:** `.venv/bin/python`

## 1. Core Operating Mandates

1. **Per-Session Isolation (`.nujin/sessions/<session_id>/`):**
   - Pass `--new-session` (or `--id <session_id>`) on every new user request via `server/session_store.py`.
   - Each session isolates its own `empirical_briefing.json`, `features.csv`, `best_rule.json`, `candidate_returns.json`, and `trial_ledger.jsonl` so prior sessions never bias or penalize a new request.
2. **Persistent Market Data Single Source of Truth (`data/market/` & `data/`):**
   - Market OHLCV data is indexed in `data/market/catalog.json` via `server/data_manager.py`.
   - Runtime cockpit/strategy state lives strictly in `data/state.json`, `data/strategies.json`, and `data/signals.json` via `server/state_manager.py`.
3. **Library-Backed Indicators (`TA-Lib` + `ta`), Causal MTF & Continuous Alpha/Meta-Labeling (`server/indicators.py` & `server/alpha_models.py`):**
   - **Industry Libraries (`TA-Lib` & `ta`):** All 201 C-accelerated `TA-Lib` functions (`talib.abstract`) and 86+ `ta` features resolve dynamically on-the-fly (`ema_<N>`, `zlema_<N>`, `hma_<N>`, `kama_<N>`, `t3_<N>`, `rsi_<N>`, `cmo_<N>`, `mfi_<N>`, `ultosc_7_14_28`, `tsi_25_13`, `vhf_<N>`, `er_<N>`, `adx_<N>`, `natr_<N>`, `rvol_<N>`, `cmf_<N>`, `efi_<N>`, `percentrank_<N>`, `linearreg_angle_<N>`, `ht_trendmode`, `cdlengulfing`, causal `donchian_upper_<N>`, `supertrend_dir`, `ttm_squeeze`, `zscore_<N>`, `avwap_<N>`).
   - **Causal Multi-Timeframe (MTF) & Cross-Asset Context:** Automatically exposes causal $4\times$ and $16\times$ higher-timeframe features (`htf4x_trend_dir`, `htf4x_rsi_14`, `htf4x_adx_14`, `htf16x_trend_dir`, `mtf_alignment_score`) and cross-asset beta/correlation (`cross_asset_beta_50`, `cross_asset_rs_zscore_20`).
   - **Continuous Alpha Forecast & Meta-Labeling:** Exposes causal IC-weighted forecast `alpha_forecast` $\in [-1, 1]$ (`alpha_forecast_z`), López de Prado meta-confidence `meta_label_prob` $\in [0, 1]$, and `kelly_conviction` $\in [0.50, 1.35]$.
   - **Custom Formulas & Code:** Pass `--custom '{"name": "<expr>"}'` or implement bespoke logic in `strategies/<Name>.py`.
4. **Holdout-Protected Model-Free IC & Interaction Discovery (`tools/anomaly_scanner.py`):**
   - Mines multi-horizon Variance Ratios / Hurst / ACF profiles, Spearman Rank IC (`scan_library_feature_ic`), and 2-factor quantile (`Q20`/`Q80`) interactions strictly on the **70% In-Sample Discovery Slice**, keeping the final **30% Holdout Vault** untouched for Gate 4 validation.
5. **Institutional Execution Realism, Drawdown Governor & 8-Gate Cynic Audit (`server/risk_governor.py` & `server/cynic_gates.py`):**
   - Enforces pessimistic intra-bar conflict resolution (Stop-Loss always takes precedence over Take-Profit), volatility-scaled dynamic slippage, holding-period funding drag, Volatility Targeting, Fractional Kelly conviction sizing, and a Multi-Tier Equity-Curve Drawdown Governor (`server/risk_governor.py`) for linear equity curves ($R^2 \ge 0.85$).
   - Approve only when all **8 canonical gates** report `PASS` ($\text{DSR} \ge 0.95$, Parameter Stability, $\text{MDD}_{99} \le 3.0\%$, OOS Walk-Forward + Purged K-Fold CPCV/PBO, Regime Survival $\ge 50$, Friction Floor, Noise Jitter $\ge 80\%$, Linearity $R^2 \ge 0.85$). `INCONCLUSIVE` never counts as passed.

## 2. 4-Stage Workflow & CLI Entrypoints

1. **Stage 1 — Session Init & Holdout-Protected Discovery / Feature Mining**
   - Open discovery: `python tools/data_miner.py --input data/candles_15m.csv --new-session` (or `python tools/anomaly_scanner.py --data data/candles_15m.csv --id <id>`)
   - Directed indicators: `python tools/feature_miner.py --input data/candles_15m.csv --id <id> --indicators "ema_34,hma_55,rsi_7" --custom '{"z": "(ema_9 - ema_21) / atr_14"}'`
2. **Stage 2 — Strategy Synthesis & Risk-Governed Screening**
   - Vectorized rule test: `python tools/vectorized_screener.py --id <id> --data data/candles_15m.csv --rules '<json>'`
   - Autonomous search: `python tools/autoresearch_miner.py init --id <id> --archetype auto && python tools/autoresearch_miner.py run --id <id> --cycles 5`
   - Grid search: `python tools/strategy_search_engine.py --features data/candles_15m.csv --target-sharpe 1.5 --id <id>`
3. **Stage 3 — Code Emission & 8-Gate Cynic Audit (with CPCV & Parameter Perturbation)**
   - Emit strategy: `python tools/strategy_emitter.py --thesis "<Thesis>" --rules .nujin/sessions/<id>/best_rule.json --out strategies/<Name>.py`
   - Full audit: `python tools/cynic_auditor.py --id <id> --strategy <Name> --strict`
4. **Stage 4 — HRP Portfolio Allocation, Deployment & Live CUSUM Drift Monitoring**
   - HRP & Orthogonality ($\rho < 0.50$): `python tools/portfolio_cynic.py --data data/candles_15m.csv --threshold 0.50`
   - Rank & deploy: `python tools/strategy_manager.py rank` / `python tools/bot_control.py deploy --strategy strategies/<Name>.py --mode paper`
   - Live CUSUM drift & auto-quarantine check: `python tools/drift_monitor.py --check-live`
   - Services: `python tools/server_control.py start --port 8000 --daemon` / `python tools/frontend_control.py start --port 3000 --daemon`

## 3. On-Demand References
Load only the reference file needed for your current step:
- [`references/quant_protocol.md`](references/quant_protocol.md) — 4-Stage Quant Methodology, MTF/Alpha Models, Holdout Vault & Risk Governor
- [`references/cynic_audit.md`](references/cynic_audit.md) — 8-Gate mathematical specification, CPCV/PBO & DSR formulas
- [`references/tools_reference.md`](references/tools_reference.md) — Full CLI flags & JSON output schemas
- [`references/microstructure_protocol.md`](references/microstructure_protocol.md) — Microstructure & order-flow mechanics
- [`references/bot_operations.md`](references/bot_operations.md) — Live bot supervision, CUSUM drift quarantine & hot-swap protocols
- [`references/telemetry_api.md`](references/telemetry_api.md) — Cockpit WebSocket/IPC & Telegram schemas
