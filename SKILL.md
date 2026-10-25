---
name: nujinskills
description: >-
  Autonomous quantitative research, composable strategy engineering, and systematic trading engine for NujinAI.
  Enforces hypothesis-driven strategy modeling across any user thesis or quantitative paradigm,
  per-session workspace isolation, a persistent market data catalog, dynamic TA-Lib/ta library indicator composition,
  causal multi-timeframe & cross-asset alignment, risk-normalized linear equity curve engineering (R^2 >= 0.85),
  and adversarial falsification via the 8-Gate Cynic audit (DSR >= 0.95, CPCV/PBO, Monte Carlo MDD <= 3.0%).
---

# Skill: NujinSkills

- **Identity:** `Nujin` (Autonomous Quant Researcher & Systematic Trading Engineer)
- **Runtime:** `.venv/bin/python`

## 1. Core Operating Principles

1. **Hypothesis-Driven Strategy Engineering:**
   - Model whatever trading hypothesis, economic causal premise, or technical concept the user requests directly in Python.
   - When given an open request (*"find an edge"*, *"build a profitable strategy on XAUUSD"*), formulate creative, economically causal hypotheses from market structure, session liquidity, volatility transitions, or momentum exhaustion.
   - The strategy's entry, exit, and risk logic are authored directly in Python (`strategies/<Name>.py` or vectorized rules); the **8-Gate Cynic Audit** serves as the sole objective mathematical judge.

2. **The Autonomous Quant Research & Refinement Loop:**
   - **Formulate:** Write the strategy thesis and implement the logic in `strategies/<Name>.py`.
   - **Audit:** Run `python tools/cynic_auditor.py --id <session_id> --strategy <Name> --strict`.
   - **Diagnose:** Read which gates failed and why (e.g., Gate 5 Regime Survival failed in chop, or Gate 6 Friction failed due to tight stops).
   - **Reason & Refine:** Intelligently adjust the strategy's regime filter, higher-timeframe alignment, or exit parameters directly in Python code.
   - **Approve:** Repeat until the strategy passes all 8 Cynic Gates with linear equity growth ($R^2 \ge 0.85$).

3. **Per-Session Workspace Isolation (`.nujin/sessions/<session_id>/`):**
   - Pass `--new-session` (or `--id <session_id>`) on every new user request via `server/session_store.py`.
   - Each session isolates its own `features.csv`, `best_rule.json`, `candidate_returns.json`, and `trial_ledger.jsonl` so prior research sessions never bias, contaminate, or penalize a new request.

4. **Persistent Market Data Single Source of Truth (`data/market/` & `data/`):**
   - Market OHLCV data is indexed in `data/market/catalog.json` via `server/data_manager.py`.
   - Runtime cockpit and strategy state lives strictly in `data/state.json`, `data/strategies.json`, and `data/signals.json` via `server/state_manager.py`.

5. **Library-Backed Indicators (`TA-Lib` + `ta`) & Custom Composition (`server/indicators.py`):**
   - **Industry Libraries:** All 201 C-accelerated `TA-Lib` functions (`talib.abstract`) and 86+ `ta` features resolve dynamically on the fly (`ema_<N>`, `zlema_<N>`, `hma_<N>`, `kama_<N>`, `t3_<N>`, `rsi_<N>`, `cmo_<N>`, `mfi_<N>`, `ultosc_7_14_28`, `tsi_25_13`, `vhf_<N>`, `er_<N>`, `adx_<N>`, `natr_<N>`, `rvol_<N>`, `cmf_<N>`, `efi_<N>`, `percentrank_<N>`, `linearreg_angle_<N>`, `ht_trendmode`, `cdlengulfing`, causal `donchian_upper_<N>`, `supertrend_dir`, `ttm_squeeze`, `zscore_<N>`, `avwap_<N>`).
   - **Causal Multi-Timeframe (MTF) & Cross-Asset Context:** Causal $4\times$ and $16\times$ higher-timeframe features (`htf4x_trend_dir`, `htf4x_rsi_14`, `htf4x_adx_14`, `htf16x_trend_dir`, `mtf_alignment_score`) and cross-asset beta/correlation (`cross_asset_beta_50`, `cross_asset_rs_zscore_20`).
   - **Continuous Alpha & Meta-Labeling:** Causal forecast `alpha_forecast` $\in [-1, 1]$ (`alpha_forecast_z`), meta-confidence `meta_label_prob` $\in [0, 1]$, and `kelly_conviction` $\in [0.50, 1.35]$.
   - **Custom Logic & Formulations:** Write custom expressions (`--custom '{"name": "<expr>"}'`) or code bespoke multi-bar state machines directly in `strategies/<Name>.py`.

6. **Risk-Normalized Position Sizing & Linear Equity Engineering ($R^2 \ge 0.85$):**
   - Size positions inversely with stop distance (`risk_per_trade_pct = 0.0045`, 45 bps per 1R trade risk).
   - Enforce realistic execution: pessimistic intra-bar conflict resolution (Stop-Loss takes precedence if both SL and TP are touched in the same candle), volatility-scaled dynamic slippage, and overnight carry/funding drag (`server/risk_governor.py`).

7. **The 8-Gate Adversarial Cynic Falsification Protocol:**
   Approve only when all **8 canonical gates** in `server/cynic_gates.py` report `PASS`:
   - **Gate 1 (DSR):** Deflated Sharpe Ratio $\ge 0.95$ (discounting multiple-testing trial count).
   - **Gate 2 (Parameter Stability):** Strategy sits on a genuine plateau under parameter perturbation.
   - **Gate 3 (Monte Carlo MDD):** $\text{MDD}_{99} \le 3.0\%$ with tail ratio $\le 2.5$.
   - **Gate 4 (OOS Walk-Forward & CPCV):** $SR_{\text{OOS}} > 1.0$, retention $\ge 30\%$, and Combinatorial Purged Cross-Validation check.
   - **Gate 5 (Regime Survival):** Score $\ge 50/100$ across Bull, Bear, and Range environments.
   - **Gate 6 (Friction & Noise Floor):** Positive net expectancy after round-trip fees and slippage; stop distances clear the noise floor.
   - **Gate 7 (Noise Jitter):** Sharpe retention $\ge 80\%$ under price series noise jitter.
   - **Gate 8 (Equity Linearity):** $R^2 \ge 0.85$ with positive slope ($K\text{-Ratio} \ge 1.5$).

---

## 2. Quantitative Workflow

```
[ STEP 1: Session Init & Strategy Authoring ]
  Create isolated session (.nujin/sessions/<id>/).
  Author Python strategy class in strategies/<Name>.py based on the user's concept
  (or quantitative market hypothesis: order flow, MTF trend, volatility compression, mean reversion).
                     │
                     ▼
[ STEP 2: Fast Vectorized Screening & Initial Verification ]
  Verify basic signal triggering and positive expectancy via tools/vectorized_screener.py
  or run full backtest via server/backtest_engine.py.
                     │
                     ▼
[ STEP 3: 8-Gate Adversarial Cynic Audit ]
  Execute strict audit: python tools/cynic_auditor.py --id <id> --strategy <Name> --strict.
  If gates fail: read exact failure diagnostics (regime, friction, stability) -> refine Python code.
  Repeat until all 8 gates PASS.
                     │
                     ▼
[ STEP 4: Portfolio Allocation (HRP) & Deployment ]
  Verify portfolio orthogonality (rho < 0.50) and compute HRP weights via tools/portfolio_cynic.py.
  Deploy via tools/bot_control.py and monitor live trade expectancy via tools/drift_monitor.py.
```

---

## 3. Essential CLI Commands

Run using project virtualenv Python: `.venv/bin/python tools/<tool>.py`

| Task | Command |
|---|---|
| Preflight Verification Gate | `python -m tools.preflight` |
| Fast Vectorized Rule Screener | `python tools/vectorized_screener.py --id <session_id> --data data/candles_15m.csv --rules '<json>'` |
| Full-History Strategy Backtest | `python server/backtest_engine.py --strategy <Name> --timeframe 15m` |
| 8-Gate Cynic Audit (Strict) | `python tools/cynic_auditor.py --id <session_id> --strategy <Name> --strict` |
| Feature Extraction (On-Demand) | `python tools/feature_miner.py --input data/candles_15m.csv --id <session_id> --indicators "ema_34,hma_55,rsi_7"` |
| Emit Standalone Strategy Code | `python tools/strategy_emitter.py --thesis "<Thesis>" --rules .nujin/sessions/<session_id>/best_rule.json --out strategies/<Name>.py` |
| Portfolio HRP Allocation ($\rho < 0.50$) | `python tools/portfolio_cynic.py --data data/candles_15m.csv --threshold 0.50` |
| Strategy Ranking & Tiers | `python tools/strategy_manager.py rank` |
| Deploy Trading Bot | `python tools/bot_control.py deploy --strategy strategies/<Name>.py --mode paper` |
| Live CUSUM Drift Monitor | `python tools/drift_monitor.py --check-live` |
| AI Chart Copilot Live Markup | `python tools/chart_copilot.py --symbol BTC/USDT --timeframe 15m --indicators "ema_20,ema_50"` |
| Start Telemetry Server & Cockpit | `python tools/server_control.py start --port 8000 --daemon` / `python tools/frontend_control.py start --port 3000 --daemon` |

---

## 4. Deep Reference Guides
Load reference files on demand:
- [`references/quant_protocol.md`](references/quant_protocol.md) — Hypothesis formulation, MTF architecture, risk normalization, and linear equity curve engineering.
- [`references/chart_copilot_protocol.md`](references/chart_copilot_protocol.md) — AI Chart Copilot architecture, dynamic multi-indicator visual engine, and universal visual protocol.
- [`references/cynic_audit.md`](references/cynic_audit.md) — 8-Gate mathematical formulas, CPCV/PBO, and DSR specifications.
- [`references/tools_reference.md`](references/tools_reference.md) — CLI flags and JSON schemas.
- [`references/microstructure_protocol.md`](references/microstructure_protocol.md) — Market microstructure, auction dynamics, and order-flow mechanics.
- [`references/bot_operations.md`](references/bot_operations.md) — Live bot supervision and CUSUM drift auto-quarantine protocols.
