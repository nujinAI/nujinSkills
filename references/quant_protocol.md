# Institutional Quant Protocol — Intent-Aware Alpha Discovery & Composable Strategy Engineering

This document establishes the end-to-end standard for quantitative research, intent routing, composable indicator engineering, linear equity curve optimization, and adversarial falsification in NujinAI.

---

## 🏛️ 1. Core Quantitative Principles

A strategy is accepted for production only if it demonstrates **positive mathematical expectancy**, **economic causality**, **linear equity progression ($R^2 \ge 0.85$)**, and **statistical resilience** across all 8 canonical Cynic gates.

### 1.1 Dedicated Per-Session Isolation (`.nujin/sessions/<session_id>/`)
Every user request or research initiative operates inside its own dedicated session workspace (`.nujin/sessions/<session_id>/`, managed by `server/session_store.py`):
- **Zero Cross-Session Contamination:** A new user request is never limited, biased, or overwritten by features, rules, or return series generated during an older request.
- **Session-Scoped DSR Trial Accounting:** Each session maintains its own `trial_ledger.jsonl` via `server/trial_ledger.py`. Searching 100 hypotheses in Session A never inflates the $N_{\text{trials}}$ multiple-testing penalty for a brand-new strategy in Session B.

### 1.2 Intent-Aware Routing: User-Directed Hypothesis vs. Open Discovery
Before running any scanner or miner, classify the user's request into one of two operating modes:
- **Mode A — User-Directed Hypothesis (Standard or Custom Indicators):**
  When the user specifies an indicator, concept, or formula (e.g., *"Build a Supertrend + RSI strategy"*, *"Test a 9/21/50 EMA pullback"*, or *"Create a custom Keltner/Bollinger squeeze oscillator"*), directly construct those indicators via `server/indicators.py` (`--indicators` or `--custom`), screen the exact hypothesis, and refine its regime filter and risk/exit structure to maximize equity linearity.
- **Mode B — Open-Ended Multi-Paradigm Alpha Discovery:**
  When the user asks Nujin to *find an edge* on an asset/timeframe without prescribing indicators, execute `tools/anomaly_scanner.py` to screen the `TA-Lib` / `ta` feature universe via Spearman Rank IC and mine empirical quantile & 2-factor interaction rules net of friction.

### 1.3 The 6 Orthogonal Edge Families
Every open discovery scan evaluates six independent structural mechanisms:
1. **`TREND_CONTINUATION` (`trend_following`):** Multi-scale moving average alignment (`EMA`, `HMA`, `KAMA`), `Supertrend` direction, `ADX` trend strength, and rolling linear regression slope (`slope_20`).
2. **`MOMENTUM_BREAKOUT` (`momentum_breakout` / `volatility_squeeze`):** Causal `Donchian` channel breakouts (`shift(1)`), `TTM Squeeze` / Bollinger-inside-Keltner volatility compression release (`vol_compression`), and Rate-of-Change (`ROC`) surges.
3. **`STRUCTURAL_PULLBACK` (`mtf_pullback`):** Counter-trend value retracements (`close <= ema_21`, `RSI` dip) within a dominant Higher-Timeframe trend (`ema_50 > ema_200`).
4. **`MEAN_REVERSION` (`zscore_reversion` / `vwap_reversion`):** Statistical overextension beyond $2\sigma$ (`zscore_20`, `avwap_zscore`, `bb_pct_b`) in low-Hurst ($H < 0.45$) regimes.
5. **`SESSION_TIME_EDGE` (`session_breakout`):** Institutional liquidity injection at London Open (`killzone_london`), NY Open (`killzone_ny`), or Asian range breakouts.
6. **`MICROSTRUCTURE_FLOW` (`smc_liquidity`):** Order-flow effort vs. result (`volume_zscore`, `cmf_20`, `obv`), Fair Value Gaps (`fvg_bullish`/`bearish`), and trapped inventory sweeps.

### 1.4 Composable Standard + Custom Indicator Architecture (`server/indicators.py`)
Strategies are composed from three modular building blocks:
$$\text{Strategy} = \underbrace{\text{Regime Filter}}_{\text{Hurst / ADX / HTF Trend / Vol}} + \underbrace{\text{Setup \& Trigger}}_{\text{Standard or Custom Indicators}} + \underbrace{\text{Dynamic Exit \& Risk Sizing}}_{\text{R-Multiple / Trail / Half-Life}}$$

- **Standard Parameterized Indicators:** Any column token such as `sma_50`, `ema_34`, `wma_20`, `hma_21`, `kama_10`, `rsi_7`, `roc_14`, `cci_20`, `willr_14`, `stoch_k_14`, `adx_14`, `atr_14`, `donchian_upper_55`, `supertrend_dir`, `ttm_squeeze`, `zscore_50`, `slope_20`, or `cmf_20` is dynamically resolved on the fly by `ensure_dynamic_indicators()`.
- **Custom Mathematical Formulas:** Arbitrary expressions over any combination of columns (`--custom '{"custom_osc": "(ema_9 - ema_21) / atr_14"}'`) are evaluated vectorially without boilerplate.

### 1.5 Mathematical Expectancy, Microstructure Noise Floor & Friction Realism
Every strategy must produce positive mathematical expectancy after full round-trip friction:
$$E = (P_{\text{win}} \times \overline{\text{Win Size}}) - (P_{\text{loss}} \times \overline{\text{Loss Size}}) - \text{Friction} > 0$$

1. **Minimum Stop / Trailing Distance:**
   $$\text{Stop Distance} \ge \max\left(3.0 \times \text{Typical Spread}, \; 1.5 \times \text{ATR}(14), \; 10\text{ bps}\right)$$
2. **Full Round-Trip Friction Accounting:**
   - Default crypto/index/FX screening deducts 5 bps fee + 2 bps slippage per side; asset-aware backtests apply realistic bid-ask spread, slippage, and taker fees (`resolve_asset_friction` in `server/backtest_engine.py`).

### 1.6 Risk-Normalized Position Sizing & Linear Equity Curve Engineering ($R^2 \ge 0.85$)
A strategy cannot achieve a linear equity curve ($R^2 \ge 0.85$, $K\text{-Ratio} \ge 1.5$) if its per-trade account risk fluctuates wildly with market volatility.
1. **Constant-Risk Normalization (`risk_per_trade_pct`):**
   $$\text{Position Size} = \frac{\text{Account Equity} \times \text{Risk Fraction (e.g. } 0.45\%\text{)}}{\max(|\text{Entry Price} - \text{Stop Loss}|, \; \text{Noise Floor})}$$
   Every trade risks the exact same percentage of equity ($1R = 0.45\%$). A $1R$ stop-loss always impacts equity by $-0.45\%$, and a $2.5R$ target always adds $+1.125\%$ (less friction), eliminating volatility-spike equity distortions.
2. **Linearity Goodness-of-Fit ($R^2 \ge 0.85$, Target $\ge 0.90$):**
   $$R^2 = 1 - \frac{\sum (\text{Equity}_t - \widehat{\text{Equity}}_t)^2}{\sum (\text{Equity}_t - \overline{\text{Equity}})^2} \ge 0.85$$
3. **K-Ratio Consistency ($\ge 1.5$):**
   $$\text{K-Ratio} = \frac{\text{Slope}}{\text{SE}(\text{Slope})} \times \frac{\sqrt{N}}{T} \ge 1.5$$

### 1.7 Continuous Quality Control & CUSUM Alpha Degradation Monitoring
Post-deployment, Page's Cumulative Sum (CUSUM) test monitors live trade returns against expected backtest expectancy:
$$S_t = \max\left(0, \; S_{t-1} + (\mu_{\text{expected}} - R_t - k)\right), \quad k = 0.5\sigma$$
When $S_t \ge 2.5\sigma$, the engine raises `CRITICAL_ALERT: ALPHA_DEGRADED` and halts new entries.

---

## 🔭 2. Institutional Multi-Timeframe (MTF) Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. HIGHER TIMEFRAME (HTF) — Context, Macro Regime & Dominant Bias     │
│    • Horizons: Daily, 4-Hour, or 1-Hour (joined via causal join_asof)  │
│    • Purpose: Establish market regime (Bull, Bear, Range), Hurst H,    │
│      and macro directional bias.                                       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Condition: Trade only in alignment
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 2. MID TIMEFRAME (MTF) — Structural Setup & Value Interaction Zone     │
│    • Horizons: 15-Minute or 5-Minute                                   │
│    • Purpose: Identify volatility squeeze, channel breakout, trend     │
│      pullback, or statistical envelope extreme.                        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Condition: Setup confirmed
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 3. LOWER TIMEFRAME (LTF) — Execution Trigger & Risk-Normalized Sizing  │
│    • Horizons: 15-Minute, 5-Minute, or 1-Minute                        │
│    • Purpose: Confirm trigger on bar close, anchor structural stop     │
│      above noise floor, and size position for constant 1R risk.        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 🔬 3. Stage-by-Stage Alpha Discovery Pipeline

### Stage 1: Session Initialization, Intent Routing & Market Characterization
1. Create or specify a dedicated session (`--new-session` or `--id <session_id>`).
2. Run `tools/anomaly_scanner.py --data <path> --id <session_id>` to compute:
   - Lo-MacKinlay Variance Ratios ($VR$) and multi-horizon Hurst Exponent ($H$).
   - Conditional forward returns (net of friction) and alpha half-life across all **6 Orthogonal Edge Families**.
   - Session hourly volatility and directional drift matrix.
3. Extract features via `tools/feature_miner.py --input <path> --id <session_id>` (including any `--indicators` or `--custom` formulas requested by the user).

### Stage 2: Composable Strategy Synthesis & Iterative Optimization Loop
1. **Synthesize Candidate Rules:**
   - Combine a Regime Filter + Setup/Trigger + Exit/Stop/Target structure.
2. **Vectorized Screening & Evolution:**
   - Screen rules rapidly with `tools/vectorized_screener.py --id <session_id>` or iterate via `tools/autoresearch_miner.py run --id <session_id> --archetype auto`.
   - Every evaluated hypothesis is recorded in the session's `.nujin/sessions/<session_id>/trial_ledger.jsonl`.

### Stage 3: Full-History Backtest & 8-Gate Adversarial Cynic Audit
Every candidate must pass all **8 canonical gates** in `server/cynic_gates.py` (see [`references/cynic_audit.md`](cynic_audit.md)):
1. **Deflated Sharpe Ratio (DSR):** $\text{DSR} \ge 0.95$, penalized by session $N_{\text{trials}}$ and return skew/kurtosis ($\ge 30$ trades).
2. **Parameter Stability Surface:** Perturbed parameter grid ($2\times 2$ or $3\times 3$) must form a stable plateau ($\min(M) > 0.40\,\widehat{SR}$ and $\text{mean}(M) > 0.70\,\widehat{SR}$). Automatically computed by `server/backtest_engine.py` and `tools/autoresearch_miner.py`.
3. **Monte Carlo MDD:** 1,000 trade-order permutations must yield $\text{MDD}_{99} \le 3.0\%$ with tail ratio $\le 2.5$.
4. **Out-of-Sample Walk-Forward:** 70/30 chronological split; $SR_{OOS} > 1.0$ and retention $\ge 30\%$.
5. **Market Regime Survival:** Score $\ge 50/100$ across Bull / Bear / Range (or $\ge 2$ of 3 temporal slices positive).
6. **Execution Friction & Noise Floor:** Net expectancy $> 0$ after 5 bps fee + 2 bps slippage; stops must clear the 10 bps microstructure floor.
7. **Noise Perturbation Jitter:** Sharpe retention $\ge 80\%$ under seeded synthetic noise.
8. **Equity Curve Linearity Standard:** $R^2 \ge 0.85$ with positive slope (target $R^2 \ge 0.90$, $K\text{-Ratio} \ge 1.5$).

A gate that cannot be evaluated returns `INCONCLUSIVE` and **never counts as passed**. The candidate is `APPROVED` only when all 8 gates report `PASS`.

### Stage 4: Strategy Emission, Portfolio Orthogonality & Live Hot-Deployment
1. Emit or author the production strategy in `strategies/<StrategyName>.py` (`tools/strategy_emitter.py`).
2. Run closed-loop verification: `tools/cynic_auditor.py --strategy <StrategyName> --strict`.
3. Verify portfolio orthogonality ($\rho < 0.50$) against existing active strategies via `tools/portfolio_cynic.py`.
4. Register and hot-deploy via `tools/strategy_manager.py` and `tools/bot_control.py`.
