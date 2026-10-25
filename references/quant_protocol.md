# Institutional Quant Protocol — Hypothesis-Driven Strategy Engineering & Adversarial Falsification

This document establishes the end-to-end standard for quantitative research, hypothesis formulation, composable indicator engineering, risk-normalized linear equity curve optimization, and adversarial falsification in NujinAI.

---

## 🏛️ 1. Core Quantitative Principles

A strategy is accepted for production only if it demonstrates **positive mathematical expectancy**, **economic causality**, **linear equity progression ($R^2 \ge 0.85$)**, and **statistical resilience** across all 8 canonical Cynic gates.

### 1.1 Dedicated Per-Session Isolation (`.nujin/sessions/<session_id>/`)
Every user request or research initiative operates inside its own dedicated session workspace (`.nujin/sessions/<session_id>/`, managed by `server/session_store.py`):
- **Zero Cross-Session Contamination:** A new user request is never limited, biased, or overwritten by features, rules, or return series generated during an older request.
- **Session-Scoped DSR Trial Accounting:** Each session maintains its own `trial_ledger.jsonl` via `server/trial_ledger.py`. Searching hypotheses in Session A never inflates the $N_{\text{trials}}$ multiple-testing penalty for a brand-new strategy in Session B.

### 1.2 Hypothesis-Driven Alpha Formulation (Unconstrained Strategy Modeling)
Trading strategies originate from **sound market structure hypotheses**, not brute-force data dredging. The AI agent has complete flexibility to model any trading methodology:
- **Smart Money Concepts (SMC) & Institutional Price Action:** Fair Value Gaps (FVG), Order Blocks, Liquidity Sweeps, and Premium/Discount market pricing.
- **Order Flow & Volume Dynamics:** Cumulative Volume Delta (CVD) divergence, Volume Profile / Value Area shifts, and Volume-Price analysis.
- **Multi-Timeframe Trend Continuation:** HTF directional alignment combined with lower-timeframe pullbacks to key dynamic moving averages or value boundaries.
- **Volatility Transitions & Squeezes:** Bollinger inside Keltner compression followed by directional volatility release.
- **Statistical Mean Reversion & Spreads:** Standardized deviations ($Z \ge 2\sigma$) from equilibrium baselines (VWAP, rolling regression lines).
- **Session & Temporal Breakouts:** London / New York open range expansions and session liquidity timing.

The agent designs the strategy to faithfully execute the hypothesis; the **8-Gate Cynic Audit** acts as the objective arbiter of profitability and robustness.

### 1.3 Composable Indicator Architecture (`server/indicators.py`)
Strategies are composed from modular building blocks:
$$\text{Strategy} = \underbrace{\text{Regime Filter}}_{\text{HTF Trend / Volatility / Session}} + \underbrace{\text{Setup \& Trigger}}_{\text{SMC, Price Action, Indicators, Order Flow}} + \underbrace{\text{Dynamic Exit \& Risk Sizing}}_{\text{R-Multiple / VolTarget / Trailing Stop}}$$

- **Standard Parameterized Indicators:** Any column token such as `sma_50`, `ema_34`, `wma_20`, `hma_21`, `kama_10`, `rsi_7`, `roc_14`, `cci_20`, `willr_14`, `stoch_k_14`, `adx_14`, `atr_14`, `donchian_upper_55`, `supertrend_dir`, `ttm_squeeze`, `zscore_50`, `slope_20`, or `cmf_20` is dynamically resolved on the fly by `ensure_dynamic_indicators()`.
- **Custom Mathematical Formulas:** Arbitrary expressions over any combination of columns (`--custom '{"custom_osc": "(ema_9 - ema_21) / atr_14"}'`) are evaluated vectorially without boilerplate.

### 1.4 Mathematical Expectancy, Microstructure Noise Floor & Friction Realism
Every strategy must produce positive mathematical expectancy after full round-trip friction:
$$E = (P_{\text{win}} \times \overline{\text{Win Size}}) - (P_{\text{loss}} \times \overline{\text{Loss Size}}) - \text{Friction} > 0$$

1. **Minimum Stop / Trailing Distance:**
   $$\text{Stop Distance} \ge \max\left(3.0 \times \text{Typical Spread}, \; 1.5 \times \text{ATR}(14), \; 10\text{ bps}\right)$$
2. **Full Round-Trip Friction Accounting:**
   - Default crypto/index/FX screening deducts 5 bps fee + 2 bps slippage per side; asset-aware backtests apply realistic bid-ask spread, slippage, and taker fees (`resolve_asset_friction` in `server/backtest_engine.py`).
3. **Pessimistic Intra-Bar Execution (`server/risk_governor.py`):**
   - If both the Stop-Loss and Take-Profit price boundaries are penetrated during the same bar, the simulator assumes the Stop-Loss was triggered first (worst-case path).

### 1.5 Risk-Normalized Position Sizing & Linear Equity Curve Engineering ($R^2 \ge 0.85$)
A strategy cannot achieve a linear equity curve ($R^2 \ge 0.85$, $K\text{-Ratio} \ge 1.5$) if its per-trade account risk fluctuates wildly with market volatility.
1. **Constant-Risk Normalization (`risk_per_trade_pct`):**
   $$\text{Position Size} = \frac{\text{Account Equity} \times \text{Risk Fraction (e.g. } 0.45\%\text{)}}{\max(|\text{Entry Price} - \text{Stop Loss}|, \; \text{Noise Floor})}$$
   Every trade risks the exact same percentage of equity ($1R = 0.45\%$). A $1R$ stop-loss impacts equity by $-0.45\%$, and a $2.5R$ target adds $+1.125\%$ (less friction), eliminating volatility-spike equity distortions.
2. **Linearity Goodness-of-Fit ($R^2 \ge 0.85$, Target $\ge 0.90$):**
   $$R^2 = 1 - \frac{\sum (\text{Equity}_t - \widehat{\text{Equity}}_t)^2}{\sum (\text{Equity}_t - \overline{\text{Equity}})^2} \ge 0.85$$
3. **K-Ratio Consistency ($\ge 1.5$):**
   $$\text{K-Ratio} = \frac{\text{Slope}}{\text{SE}(\text{Slope})} \times \frac{\sqrt{N}}{T} \ge 1.5$$

### 1.6 Continuous Quality Control & CUSUM Alpha Degradation Monitoring
Post-deployment, Page's Cumulative Sum (CUSUM) test monitors live trade returns against expected backtest expectancy (`server/drift_monitor.py`):
$$S_t = \max\left(0, \; S_{t-1} + (\mu_{\text{expected}} - R_t - k)\right), \quad k = 0.5\sigma$$
When $S_t \ge 4.0\sigma$ or live equity breaches the 5th percentile of the backtest Monte Carlo distribution, the engine automatically quarantines the strategy to paper mode.

---

## 🔭 2. Institutional Multi-Timeframe (MTF) Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. HIGHER TIMEFRAME (HTF) — Context, Macro Regime & Dominant Bias     │
│    • Horizons: 4-Hour (16x) or 1-Hour (4x)                             │
│    • Metrics: HTF Trend (htf16x_trend_dir), HTF RSI, HTF ADX           │
│    • Causal shift(1) guarantees zero lookahead leakage into base bars. │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 2. BASE EXECUTION TIMEFRAME — Structure, Setups & Precise Triggers    │
│    • Horizons: 15-Minute or 5-Minute                                   │
│    • Setups: Order Blocks, FVGs, Breakouts, Pullbacks, Volume Delta     │
│    • Validation: Causal alignment score (mtf_alignment_score >= 0.25)  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 🛡️ 3. The 8 Canonical Cynic Gates

Every strategy must pass all 8 gates in `server/cynic_gates.py` before approval:

| Gate | Canonical Key | Metric / Condition | Threshold |
|---|---|---|---|
| **1** | `gate_1_dsr` | Deflated Sharpe Ratio | $\text{DSR} \ge 0.95$ (accounting for $N_{\text{trials}}$) |
| **2** | `gate_2_parameter_stability` | Perturbation Grid Plateau | Min cell $> 40\%$ ref, mean cell $> 70\%$ ref |
| **3** | `gate_3_monte_carlo` | Permutation Max Drawdown | $\text{MDD}_{99} \le 3.0\%$, Tail Ratio $\le 2.5$ |
| **4** | `gate_4_oos_walkforward` | Out-of-Sample Retention & CPCV | $SR_{\text{OOS}} > 1.0$, Retention $\ge 30\%$, PBO check |
| **5** | `gate_5_regime_survival` | Regime Score (Bull/Bear/Range) | Score $\ge 50/100$, positive expectation across slices |
| **6** | `gate_6_friction` | Net Expectancy & Stop Clearance | Expectancy $> 0$, stops clear spread + slippage floor |
| **7** | `gate_7_noise_jitter` | Noise Resistance (1 bps jitter) | Sharpe retention $\ge 80\%$ |
| **8** | `gate_8_equity_linearity` | Equity Curve Smoothness ($R^2$) | $R^2 \ge 0.85$, $K\text{-Ratio} \ge 1.5$ with positive slope |
