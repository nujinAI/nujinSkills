# Universal Edge Discovery & Hypothesis Formulation

This document guides the AI in discovering, formulating, and verifying empirical statistical edges across any market, horizon, and asset class without bias or hardcoded indicator dogmas.

---

## 1. The Core Scientific Law of Edge

An edge exists if and only if a measurable market state $S_t$ has a **non-random, forward predictive relationship** with future price changes $R_{t+h}$ that **comfortably exceeds transaction friction**:

$$\text{Net Edge} = |\mathbb{E}[R_{t+h} \mid S_t]| - \text{Roundtrip Friction} > 0$$

If this condition is not met, no amount of risk management, fancy order types, or indicator stacking will produce a profitable strategy.

---

## 2. The Structural Inefficiency Contract (Mandatory Before Strategy Assembly)

To prevent the AI from overfitting noise or assuming random indicator thresholds, every trading hypothesis must declare a causal counterparty:

```markdown
### Structural Hypothesis Contract
1. Target Counterparty: [Forced Actor (liquidation, index rebalance) / Inventory-Constrained MM / Predictable Herd]
2. Inelastic Catalyst:  [Clock Handover / Liquidity Zone Breach / Volatility Expansion / Rebalance Window]
3. 3-Part Causal Chain: When [Market State], [Target Counterparty] executes [Constrained Action], causing [Measurable Inefficiency] net of friction.
4. Pre-Mortem:          [The exact empirical condition under which this mechanism is completely falsified]
```

---

## 3. The 4-Step Verification Hurdle (Empirical Scan)

Before writing any execution rules or strategy classes, test the candidate feature through `tools/scan_edge.py`:

```bash
python tools/scan_edge.py --symbol <TICKER> --tf <TIMEFRAME> --days 60
```

### The 4 Institutional Hurdle Gates:
1. **Directional Information Coefficient (Rank IC):**
   - $|\text{Rank IC}| \ge 0.02$ between candidate feature and forward return $R_{t+h}$.
2. **Statistical Significance ($t$-stat):**
   - $|t\text{-stat}| \ge 2.0$ ($p < 0.05$), ensuring the correlation is not small-sample noise.
3. **Permutation Noise Test (White's Reality Check):**
   - Noise probability $p_{\text{perm}} \le 0.05$ across 200 return shuffles. Kills overfitted patterns.
4. **Friction Clearance Multiple:**
   - $\text{Gross Expected Move} \ge 3.0 \times \text{Roundtrip Friction Cost}$.
   - If expected move is less than 3x the spread + slippage floor, **the edge is rejected as friction-dead**.

---

## 4. Converting Verified Edges into Strategies

When a feature passes the 3 hurdles at horizon $H^*$:
1. **Entry Trigger:** Set triggers where feature reaches statistically significant quantile extremes (e.g. top decile or structural breach).
2. **Horizon Alignment:** Calibrate holding duration and take-profit expectations to horizon $H^*$.
3. **Structural Invalidation:** Place the stop loss at the exact price level that disproves the premise (e.g. failure of the breakout bar, swing low breach). Never use an arbitrary pip stop.
