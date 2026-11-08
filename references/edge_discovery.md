# Universal Edge Discovery & Hypothesis Formulation

This document guides the AI in discovering, formulating, and verifying empirical statistical edges across any market, horizon, and asset class without bias or hardcoded indicator dogmas.

---

## 1. The Core Scientific Law of Edge

An edge exists if and only if a measurable market state $S_t$ has a **non-random, forward predictive relationship** with future price changes $R_{t+h}$ that **comfortably exceeds transaction friction**:

$$\text{Net Edge} = |\mathbb{E}[R_{t+h} \mid S_t]| - \text{Roundtrip Friction} > 0$$

If this condition is not met, no amount of risk management, fancy order types, or indicator stacking will produce a profitable strategy.

---

## 2. Hypothesis Formulation (Paradigm Neutral)

The AI must treat all trading ideas—whether suggested by the user or discovered autonomously—as testable mathematical hypotheses:

| Paradigm Family | Example Hypothesis Formulation | Mathematical Form |
| :--- | :--- | :--- |
| **Momentum / Trend** | Directional persistence over lookback $L$ continues over horizon $H$. | $\text{ROC}_L(t) = \frac{P_t - P_{t-L}}{P_{t-L}}$ |
| **Mean Reversion** | Price deviations from a baseline expand elasticity and snap back. | $Z(t) = \frac{P_t - \mu_{L}(t)}{\sigma_L(t)}$ |
| **Structural Breakout** | Compression in range or volatility precedes directional impulse. | $\text{Ratio}(t) = \frac{\text{Range}_t}{\text{ATR}_L(t)}$ |
| **Liquidity / Session** | Extreme price action outside session bounds is rejected when liquidity returns. | $\text{Dist}(t) = P_t - \text{SessionExtreme}$ |
| **Cross-Asset / Spread** | Cointegrated asset deviations revert to fair ratio. | $\Delta(t) = P_{A,t} - \beta P_{B,t}$ |

---

## 3. The 3-Step Verification Protocol

Before constructing entry and exit rules, run the candidate hypothesis through `tools/scan_edge.py`:

```bash
python tools/scan_edge.py --symbol <TICKER> --tf <TIMEFRAME> --days 60
```

### The Three Hurdle Gates:
1. **Directional Information Coefficient (Rank IC):**
   - $|\text{Rank IC}| \ge 0.02$ between candidate feature and forward return $R_{t+h}$.
2. **Statistical Significance ($t$-stat):**
   - $|t\text{-stat}| \ge 2.0$ ($p < 0.05$), ensuring the correlation is not an artifact of small sample noise.
3. **Friction Clearance Multiple:**
   - The gross expected move must satisfy:
     $$\text{Gross Expected Move} \ge 3.0 \times \text{Roundtrip Friction Cost}$$
   - If a feature has a statistically significant Rank IC on 1m bars, but the expected move is only 0.5 bps while the spread is 1.5 bps, **it is rejected as friction-dead**.

---

## 4. Converting Verified Edges into Strategies

When a feature passes the 3 hurdles at horizon $H^*$:
1. **Entry Trigger:** Set triggers where feature reaches statistically significant quantile extremes (e.g. top decile or structural breach).
2. **Horizon Alignment:** Calibrate holding duration and take-profit expectations to horizon $H^*$.
3. **Structural Invalidation:** Place the stop loss at the exact price level that disproves the premise (e.g. failure of the breakout bar, swing low breach). Never use an arbitrary pip stop.
