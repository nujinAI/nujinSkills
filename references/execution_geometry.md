# Execution Geometry & Invalidation

This reference specifies the execution geometry rules, invalidation principles, and sizing mechanics enforced across the NujinSkills framework.

---

## 1. The Core Geometric Principles

1. **Market Direction is Non-Deterministic:**
   Order flow is partially hidden and passive liquidity is non-binding. Statistical edge stems from **asymmetric payoff geometry** and strictly defined invalidation, not high-certainty directional forecasts.

2. **Objective Structural Invalidation (Anchored to Location/Zone):**
   - Every setup must define an exact structural price level that unambiguously falsifies the premise (e.g., beyond the defended zone boundary, causal swing high/low breach, sweep extreme + ATR volatility buffer, session range break, or volatility envelope boundary).
   - Invalidation must reflect the underlying structural thesis—never rely on arbitrary static pip stops; pure ATR-multiple stops should only be used when volatility expansion/mean-excursion is itself the structural invalidation mechanism.

3. **Normalized 1R Dollar Risk:**
   - Risk is parameterized exclusively as a fractional percentage of current account equity:
     $$\text{Dollar Risk} = \text{Account Balance} \times \text{risk\_pct\_1r}$$
   - Position sizing scales dynamically with the distance to the invalidation level:
     $$\text{Units} = \frac{\text{Dollar Risk}}{|\text{Entry} - \text{Stop Loss}| \times \text{Contract Multiplier}}$$
   - Being wrong on any trade costs an invariant, strictly defined $1R$.

4. **Positive Net Expectancy & Payoff Symmetry:**
   - Targets and exits must be parameterized to deliver positive net expectancy after transaction costs:
     $$\mathbb{E}[R] = (W \times R_{\text{win}}) - ((1 - W) \times 1.0) - \text{Friction} > 0$$
   - *Paradigm Flexibility:* Trend-following systems typically seek asymmetric payouts ($2.0R$ to $4.0R+$) with lower win rates. Mean-reversion or statistical arbitrage systems may seek tighter payouts ($0.8R$ to $1.5R$) with higher win rates (>60%) or trailing/time-based invalidations. Both are fully supported provided they satisfy the statistical expectancy hurdle.

5. **Friction Floor Hurdle:**
   - Total round-trip costs (spread + slippage + broker commission) must satisfy:
     $$\text{Roundtrip Friction} \le 10\% \times |\text{Entry} - \text{Stop Loss}|$$
   - If stop distance is too tight relative to spread noise, the setup must be vetoed.

---

## 2. Authentic Execution Modeling

- **Venue-Specific Reality:**
  - Model the exact execution realities of the traded instrument (Forex Spot, CFD, Crypto Spot/Perp, Equities, Futures).
  - If trading Spot/CFD: model spread widening, swap/financing rates, and treat broker volume as synthetic tick frequency.
  - If trading Futures: model tick size, margin schedules, rollover windows, and order book depth where available.
  - If trading Crypto: model exchange taker/maker fee tiers and 8-hour funding rate drag.
- **Never substitute proxy instruments** (e.g. using COMEX `GC=F` to backtest spot `XAUUSD`) without explicit justification, as differing session hours, expiration rolls, and fee structures invalidate the micro-edge.
