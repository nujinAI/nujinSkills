# Strategy Craft: 4-Layer Institutional Architecture & Professional Indicator Discipline

First-principles guide for engineering creative, reliable, out-of-sample consistent strategies across any asset, timeframe, or user request—**without predefined indicator recipes or canned templates**.

---

## 1. Market Research First (Autonomous Thesis Selection)

Never force a fixed playbook or blindly default to a single scanner when the user leaves the approach open. Research the target market strictly on the **66.7% In-Sample slice** first:
- **Profile Microstructure:** Run `python tools/validate_hypothesis.py --profile --symbol <SYM> --tf <TF> --days <DAYS>` to inspect volatility (`ATR%`), friction-to-ATR feasibility (`min SL >= x*ATR`), return persistence (`Lag1 AC`, `VR(5)`, `Eff20`), regime mix, and peak UTC liquidity hours.
- **Optional Anomaly Radar:** Run `tools/scan_edge.py` whenever you want an exploratory ML scan across the ~103-coordinate dimensionless basis grid—treat it as one research instrument, not a mandatory straitjacket.
- **Select the Paradigm Empirically:** Let the asset's real dynamics and the user's constraints (horizon, drawdown, style) dictate whether momentum/breakout, mean-reversion/auction, liquidity/structure, volatility-expansion, or a hybrid thesis fits best.

---

## 2. The 4-Layer Institutional Architecture

High-consistency strategies separate *why*, *where*, *when*, and *where you're wrong* into four functional layers. Adapt how each layer is built to the paradigm rather than forcing one dogma:

| Layer | Core Question | Functional Role (Paradigm-Adaptive Examples, Not Fixed Menus) |
| :--- | :--- | :--- |
| **1. Context** *(Regime & Permission)* | *Should this playbook run right now, and in which direction?* | Filters **when NOT to trade**. Higher-timeframe bias (causal MTF), volatility state (compression vs. expansion), market efficiency/persistence vs. balance, session liquidity windows, or cross-asset regime. |
| **2. Location** *(Zone / Area of Value)* | *Where is asymmetric risk/reward physically located?* | Eliminates mid-range "no-man's-land" entries. Value/auction extremes (VWAP ± $\sigma$, statistical bands), structural liquidity pools (causal swings, session/range boundaries, imbalances), dynamic pullback value zones, or compression boxes. |
| **3. Confirmation** *(Trigger / Participation)* | *What proves real supply/demand shift is occurring right now?* | Prevents catching falling knives or buying blind touches. Liquidity sweep-and-reclaim, absorption / effort-vs-result (volume vs. range), causal micro-structure displacement, squeeze/volatility release, or momentum turn/divergence **at the zone**. |
| **4. Invalidation** *(Risk & Payoff Geometry)* | *What exact price falsifies the thesis, and where is logical payoff?* | Stop loss sits beyond the structural boundary of the zone/trigger (plus volatility buffer, clearing the $\le 10\%$ friction floor). Targets align to opposing structure, value equilibrium, empirical MFE plateau, or adaptive trails. |

Every layer must earn its place empirically—if adding a filter hurts Sub-Era consistency or starves sample size without improving expectancy/drawdown, strip it out.

---

## 3. Professional Indicator Discipline (Avoiding the Retail Trap)

Indicators (`core/indicators.py` — TA-Lib, `ta`, causal MTF, VWAP, or custom vectorized math) are **fully permitted** whenever they serve the thesis cleanly, subject to five institutional rules:

1. **No Standalone Lagging Oracles:** Never trigger trades solely on textbook crossings or static levels (`RSI < 30`, `EMA 9/21 cross`, `MACD cross`) detached from Context and Location.
2. **Orthogonal Sensor Roles Only:** Assign every feature to a distinct informational dimension—*(a) Regime/Trend, (b) Volatility/Compression, (c) Location/Fair Value, (d) Momentum/Exhaustion Confirmation, (e) Participation/Volume Flow*. **Never stack collinear duplicates** (e.g., RSI + Stoch + CCI + MACD all measuring the same price derivative; pairwise $|\rho|$ should stay well below `0.85`).
3. **Scale- & Volatility-Normalized (Stationary):** Express distances, slopes, and thresholds relative to ATR, rolling dispersion, z-scores, or percentile ranks—never raw price deltas or fixed pip offsets that break across volatility regimes.
4. **100% Causal (Zero Lookahead):** Use shifted completed HTF bars, causal swings (`detect_swing_points(..., causal=True)`), and strictly backward-looking windows. Verify every creative strategy with `validate_hypothesis.py` prefix-invariance before touching Blind OOS.
5. **Parsimony & Canonical Scales:** Keep tunable parameters minimal and thesis-justified. Use round/canonical scales and verify plateau robustness (Gate 2 $\pm 10\%$ stability) instead of hunting magic decimals (`RSI(13) < 28.4`).

---

## 4. Creative Iteration Loop (Blind OOS Stays Locked Until Pre-Flight Passes)

1. **Research (IS Only):** Profile asset/TF (`validate_hypothesis.py --profile`) + optional `scan_edge.py`.
2. **Architect & Code:** Write clean vectorized strategy in `zillionsAlpha/strategies/<Name>.py` (symlink to `strategies/`) using `core/` primitives or custom causal math.
3. **In-Sample Pre-Flight:** Run `tools/validate_hypothesis.py --strategy <Name>.py --days <DAYS>` to verify **Zero Lookahead**, **Sub-Era Invariance**, **Friction Floor**, and **4-Layer Diagnostics** (Context bleed, fast stop-outs = weak Confirmation, winner giveback = Location/Geometry mismatch). Refine structurally until `READY_FOR_CYNIC_AUDIT`.
4. **Blind OOS Falsification:** Run `tools/run_backtest_audit.py --strategy <Name>.py --days <DAYS>`. If any gate fails, diagnose strictly In-Sample via `tools/autopsy_strategy.py` and iterate autonomously until all 8 gates PASS.
