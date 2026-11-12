# Pure Mathematical Basis Discovery & Hypothesis Formulation

This document guides the AI in discovering, verifying, and synthesizing empirical statistical anomalies across any market, horizon, and user mandate with zero indicator or keyword bias.

---

## 1. The Core Scientific Law of Edge

An edge exists if and only if a measurable, stationary mathematical coordinate $S_t$ has a **non-random, sub-era invariant predictive relationship** with future barrier outcomes $R_{t+h}$ that **comfortably exceeds transaction friction**:

$$\text{Net Edge} = |\mathbb{E}[R_{t+h} \mid S_t]| - \text{Roundtrip Friction} > 0$$

---

## 2. The Lossless 6-Vector $\times$ Multi-Scale Basis Grid (`core/feature_factory.py`)

To eliminate human indicator bias and LLM keyword fixation, `core/feature_factory.py` decomposes every OHLCV bar into its **6 fundamental dimensionless physical vectors**:
- **`V1` (Normalized Return Velocity):** $r_t = \ln(C_t / C_{t-1}) / \sigma_{21}$
- **`V2` (Normalized Span Energy):** $w_t = \text{TR}_t / \text{mean}_{14}(\text{TR})$
- **`V3` (Intrabar Displacement Vector):** $b_t = (C_t - O_t) / (H_t - L_t) \in [-1, 1]$
- **`V4` (Boundary Asymmetry Vector):** $a_t = ((\min(O,C) - L) - (H - \max(O,C))) / \text{TR}_t \in [-1, 1]$
- **`V5` (Close Coordinate):** $c_t = (2C_t - H_t - L_t) / (H_t - L_t) \in [-1, 1]$
- **`V6` (Volume Activity):** $v_t = \text{zscore}_{21}(\ln(1 + V_t))$

Across the geometric scale grid $W \in \{2, 3, 5, 8, 13, 21, 34, 55\}$, the engine applies pure mathematical operators (rolling moments 1–3, non-parametric IQR coordinates, cross-scale dispersion ratios, serial autocorrelation, variance ratios, path efficiency, and vector inner products) to generate **~124 pure mathematical coordinates** (`v1_drift_w{W}`, `coord_iqr_w{W}`, `path_eff_w{W}`, `disp_ratio_{Wf}_{Ws}`, `autocorr_lag1_w{W}`, `coupling_v3_v6_w{W}`, etc.).

---

## 3. Translating User Mandates into Mathematical Envelopes (`tools/scan_edge.py`)

When the user requests a trading style or account objective, translate it strictly into CLI envelope flags:

| User Request | Recommended Timeframe | `--style` Flag | `--max-mdd` Target |
| :--- | :--- | :--- | :--- |
| **Algo Scalping** | `1m` or `5m` | `--style scalp` | `0.018` (1.8%) |
| **Prop-Firm Day Trading** | `5m` or `15m` | `--style day` | `0.020` (2.0%) |
| **Swing Trading** | `1h` or `4h` | `--style swing` | `0.022` (2.2%) |
| **Investment / Position Plan** | `4h` or `1d` | `--style invest` | `0.024` (2.4%) |

```bash
python tools/scan_edge.py --symbol <TICKER> --tf <TIMEFRAME> --days 60 --style <scalp|day|swing|invest>
```

### The 5 Institutional Discovery Hurdles:
1. **ExtraTrees + Shallow Surrogate Tree Conditional Mining:**
   - Identifies top directional basis coordinates and trains depth-1 surrogate decision trees on discrete barrier outcomes to isolate the single strongest conditioning state coordinate (`<`, `>`, `align`, or `strict_align`).
2. **5-Slice Chronological Sub-Era Invariance:**
   - Splits the 66.7% In-Sample dataset into 5 chronological sub-eras; requires $\ge 75\text{--}80\%$ positive sub-eras.
3. **Canonical Regime Survival Pre-Check:**
   - Evaluates candidate trades across `bull_market`, `bear_market`, and `ranging_market` slices (`core/regimes.py`) inside the In-Sample window.
4. **Permutation Noise Test & $t$-stat Hurdle:**
   - Requires $|t\text{-stat}| \ge 1.85\text{--}2.0$ and 200-shuffle permutation $p \le 0.05$.
5. **2D MFE/MAE Stability Plateau Optimization (`core/geometry_optimizer.py`):**
   - Simulates exact Pessimistic Intrabar Resolution + Opposite-Signal Reversals across the `(sl_atr_mult, tp_atr_mult)` grid and applies a $3\times 3$ neighborhood smoothing filter.
