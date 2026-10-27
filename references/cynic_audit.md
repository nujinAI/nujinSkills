# Institutional Audit & Verification Specification (The 4 Gates)

The **Audit Gauntlet** is NujinAI's adversarial falsification suite. Its purpose is to verify that a strategy's edge is robust, repeatable, and survives pessimistic execution and sequence-of-returns risk.

---

## The 4 Canonical Verification Gates

Every strategy generated must survive all 4 institutional gates before deployment:

### 1. Gate 1: Baseline Expectancy & Friction Hurdle
- **Requirement:** Profit Factor $\ge 1.25$, Net Expectancy $\ge +0.10R$, and Minimum 30 completed trades.
- **Microstructure Realism:**
  - Round-trip spread, exchange commissions, and tick slippage are deducted from every trade.
  - **Pessimistic Intrabar Resolution:** If a bar touches both Stop-Loss and Target, Stop-Loss is **always assumed to trigger first**.
  - Total friction must be $\le 10\%$ of stop distance.

### 2. Gate 2: Top-5 Outlier Win Removal Test
- **Requirement:** Recalculate net cumulative PnL after censoring the 5 largest winning trades.
- **Pass Threshold:** Censored Net PnL $> 0$ and Censored Profit Factor $\ge 1.0$.
- **Purpose:** Proves the edge is distributed across everyday trades and does not rely on a handful of black-swan lucky windfalls.

### 3. Gate 3: 50/50 Chronological Regime Split
- **Requirement:** Slices the full trade history into two chronological halves (H1 and H2) without parameter refitting.
- **Pass Threshold:** Net PnL $> 0$ and Profit Factor $\ge 1.10$ in **both** halves independently.
- **Purpose:** Verifies that the strategy is not regime-dependent (e.g. only working in a single bull year and blowing up in a bear or range year).

### 4. Gate 4: Monte Carlo Sequence Stress Test (1,000 Runs)
- **Requirement:** 1,000 randomized trade sequence reshuffles to stress-test sequence-of-returns risk.
- **Cumulative Drawdown Rule:**
  - Probability of breaching the Max Drawdown limit must be $\le 1.0\%$.
  - **The 95th Percentile Max Drawdown MUST be strictly less than the user/strategy Max Drawdown limit.**
- **Daily Drawdown Rule:**
  - Preserves real session exit groupings.
  - Probability of breaching the Daily Drawdown limit must be $\le 0.5\%$.
  - Worst historical single-day loss must not breach the Daily Drawdown limit.

---

## Verdict Standard

- **`REJECTED`:** If any of the 4 gates fail.
- **`APPROVED`:** Only when all 4 gates pass.
