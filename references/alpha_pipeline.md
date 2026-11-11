# 5-Phase Institutional Alpha Pipeline

This document defines the 5-phase systematic pipeline for conceptualizing, validating, building, and stress-testing quantitative strategies. 
It is entirely **paradigm-agnostic** (applicable to Trend Continuation, Mean Reversion, Statistical Arbitrage, Volatility Breakout, Liquidity Sweeps, or Macro Momentum).

---

```
[ Phase 1: User Domain Anchor & Dynamic Risk Budget ]
  → Derives account limits, 1R risk %, and daily circuit breakers dynamically.

[ Phase 2: Authentic Ingestion & Blind Out-of-Sample Isolation ]
  → Partitions authentic spot/futures/crypto candles into 2/3 In-Sample (thesis calibration) 
    and 1/3 Blind Out-of-Sample (locked & untouched). 
    Default: 60d/30d when broker/cached data permits; dynamically adapts to 
    maximum authentic window (e.g., 20d/10d or 2,000/1,000 bars) on zero-broker initial setups.

[ Phase 3: Domain-Constrained Predictive Verification ]
  → Verifies forward predictive power (Information Coefficient / IC ≥ 0.02) 
    and move size ≥ 5x broker friction.

[ Phase 4: Structural Strategy Construction ]
  → Implements entry_signal, stop_loss, and exit/target with objective structural invalidation
    and positive net expectancy after friction.

[ Phase 5: Adversarial 8-Gate Cynic Falsification & Persistent Refinement ]
  → Evaluates strategy across In-Sample and unseen Blind Out-of-Sample.
```

---

## Phase 1: Domain Anchor & Dynamic Risk Budget
- Parse the user's trading objective, anchor domain, and style (e.g., Price Action, Session Sweeps, VWAP Reversion, Key Levels, Trend Continuation, Stat-Arb).
- Use `core.risk.parse_prompt_to_risk("<user prompt>")` to derive account size, 1R dollar risk, daily circuit breakers, and profit caps dynamically from active broker accounts or user limits.
- Never impose arbitrary drawdown limits—respect the explicit user/prop-firm constraints.

## Phase 2: Authentic Ingestion & Blind Out-of-Sample Isolation
- Ingest authentic candles matching the traded venue and asset class:
  1. **Tier 1 (Cached / Broker Feed):** Canonical store (`data/market/<SLUG>_<TF>.csv`) or connected broker API. Target: 90 days (~17,600 bars on 5m).
  2. **Tier 2 (Initial Setup / Zero-Broker / TradingView Limits):** When no broker is configured, pull the maximum authentic history available from the public/WebSocket feed (e.g. 3,000–5,000 bars or available lookback).
- **The Inviolable 2/3 vs 1/3 Partition Principle:** Regardless of dataset size, never calibrate logic across the entire set. Strictly partition chronologically:
  1. **In-Sample (First 66.7% / ~2/3 of data, e.g. 60 days):** Dedicated to thesis calibration, feature discovery, and strategy assembly.
  2. **Blind Out-of-Sample (Last 33.3% / ~1/3 of data, e.g. 30 days):** Locked and completely hidden from strategy logic calibration until final Cynic evaluation.
- When running in an initial zero-broker setup, log the exact sample size and statistical degrees of freedom so the user knows the empirical depth of the test.

## Phase 3: Domain-Constrained Predictive Verification
- Respect the requested domain anchor: extract features exclusively within that domain (e.g., VWAP standard deviation bands, session high/low bounds, rejection candle geometry, momentum divergence).
- Statistically test forward predictive capability:
  - Information Coefficient (IC) $\ge 0.02$.
  - Expected move size $\ge 5 \times$ roundtrip broker friction on the In-Sample dataset before writing execution triggers.

## Phase 4: Structural Strategy Construction
- Implement `entry_signal`, `stop_loss`, and `target` (or dynamic trailing/time exit) with objective structural invalidation:
  - **Structural Invalidation (SL):** Invalidation must reflect the strategy's specific thesis (e.g. key level breach, swing high/low break, channel exit, volatility bound, pattern failure). An arbitrary fixed pip stop is forbidden unless derived from structural volatility (e.g., ATR multiples).
  - **Payoff & Expectancy:** Sized to achieve positive mathematical expectancy:
    $$\mathbb{E}[R] = (W \times R_{\text{win}}) - ((1 - W) \times 1.0) - \text{Friction} > 0$$
    *(Examples: Trend following typically targets $\ge 2.0R$ with modest win rate; mean-reversion or order-flow scalping may target $0.8R$ to $1.5R$ with high win rate or time/indicator-based exits).*
  - **Sizing:** Must be parameterized as a pure percentage (`risk_pct_1r`)—zero hardcoded dollar amounts or static lot sizes.

## Phase 5: Adversarial 8-Gate Falsification & Persistent Refinement
- Evaluate the candidate against the 8 Canonical Cynic Falsification Gates (see [`references/cynic_gates_protocol.md`](cynic_gates_protocol.md)) across both In-Sample and Unseen Blind Out-of-Sample data.
- **Persistent Refinement Protocol:**
  - If any gate fails, do not abandon the domain or stop.
  - **Forbidden:** Brute-force parameter optimization or decimal grid search (guaranteed curve-fitting).
  - **Required:** Diagnose the structural failure mode (e.g., bleeding in high-volatility expansions, stops too tight relative to spread floor, regime mismatch). Refine the structural logic and iterate until an S-Tier candidate emerges.
