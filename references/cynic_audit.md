# Cynic Audit & Adversarial Verification Specification

The **Cynic Audit** is NujinAI's adversarial falsification suite. Its purpose is to *reject* candidates
that only look profitable because of data-mining bias, survivorship bias, unrealised execution costs,
or fragile parameter tuning.

> **Single source of truth.** All gate mathematics is implemented **once**, in
> [`server/cynic_gates.py`](../server/cynic_gates.py). The backtester
> ([`server/backtest_engine.py`](../server/backtest_engine.py)), the agent CLI
> ([`tools/cynic_auditor.py`](../tools/cynic_auditor.py)), the shim
> ([`tools/validation_cynic.py`](../tools/validation_cynic.py)) and the report renderer
> ([`tools/run_backtest_audit.py`](../tools/run_backtest_audit.py)) all call it.
> **Do not implement any gate anywhere else.** Historically three divergent copies existed
> (annualising Sharpe by $\sqrt{252}$ vs $\sqrt{252\cdot24\cdot4}$ — a $\approx9.8\times$ difference —
> and MDD ceilings of 3% vs 10%), which made the same strategy receive different verdicts in
> different tools.

> **Thresholds** are likewise defined once, in [`server/constants.py`](../server/constants.py).
> Import them — never restate `0.95`, `0.030`, `0.85` or `1.80` as literals, which is how the
> `3.0%` vs `4.5%` drawdown split arose across the codebase.

> **Two annualisation bases exist and must not be mixed.** *Bar-sampled* returns (feature/screener
> paths) are annualised by $\sqrt{\text{bars per year}}$ for the series' timeframe via
> `annualization_factor(timeframe)`. *Trade-sampled* returns (the gate suite) use
> `trade_annualization_factor()` = $\sqrt{252}$. Applying a bar factor to trade returns inflates
> Sharpe by $\approx9.8\times$ at 15m and silently changes which strategies pass.

---

## 🏛️ The 8 Canonical Gates

Every gate returns a `status` of **`PASS`**, **`FAIL`**, or **`INCONCLUSIVE`**.

| # | Gate | Key | Passes when |
|---|------|-----|-------------|
| 1 | Deflated Sharpe Ratio | `gate_1_dsr` | $\text{DSR} \ge 0.95$ over $\ge 30$ trades |
| 2 | Parameter Stability | `gate_2_parameter_stability` | Real perturbed grid forms a plateau |
| 3 | Monte Carlo MDD | `gate_3_monte_carlo` | $\text{MDD}_{99} \le 3.0\%$ and tail ratio $\le 2.5$ |
| 4 | OOS Walk-Forward | `gate_4_oos_walkforward` | OOS Sharpe $> 1.0$ and retention $\ge 30\%$ |
| 5 | Regime Survival | `gate_5_regime_survival` | Score $\ge 50/100$ (or $\ge 2$ of 3 slices positive) |
| 6 | Friction & Noise Floor | `gate_6_friction` | Net expectancy $> 0$; stops clear the noise floor |
| 7 | Noise Jitter | `gate_7_noise_jitter` | Sharpe retention $\ge 80\%$ |
| 8 | Equity Linearity | `gate_8_equity_linearity` | $R^2 \ge 0.85$ and positive slope |

### Verdict rule

- **`REJECTED`** if *any* gate reports `FAIL`.
- **`INCONCLUSIVE`** if no gate fails but at least one cannot be evaluated.
- **`APPROVED`** only when **all 8** gates report `PASS`.

> **INCONCLUSIVE never counts as a pass.** A gate whose required inputs are missing must not claim
> success — a check that cannot fail is worse than no check, because it manufactures false confidence.
> Only `PASS` increments `gates_passed`.

`gates_summary` in the persisted matrix carries `gates_passed`, `gates_failed`,
`gates_inconclusive`, `gates_total` and `verdict`.

---

## 📐 Mathematical Formulations

### Gate 1 — Deflated Sharpe Ratio (DSR)

Following Bailey & López de Prado (2014), DSR is the probability that the estimated Sharpe ratio
$\widehat{SR}$ exceeds zero after discounting for selection bias across $N$ trials and for
non-normal return distributions:

$$\text{DSR} = \Phi\left( \frac{(\widehat{SR} - SR^*) \sqrt{T - 1}}{\sqrt{1 - \gamma_3 \widehat{SR} + \frac{\gamma_4 - 1}{4} \widehat{SR}^2}} \right)$$

- $\gamma_3$ — skewness of the return distribution, $\gamma_4$ — Pearson kurtosis ($=3$ if normal).
- $SR^*$ — expected maximum Sharpe under the null of zero true edge across $N$ trials:
  $$SR^* = \sqrt{2 \ln N}\left(1 - \frac{\gamma_E}{2 \ln N}\right) + \frac{\gamma_E}{\sqrt{2 \ln N}}$$
  with $\gamma_E \approx 0.5772156649$ (Euler–Mascheroni).

**Implementation notes.**
- Returns are **per-trade fractional returns**; $\widehat{SR}$ is annualised as
  $\frac{\bar r}{\sigma_r}\sqrt{252}$ (daily convention; `PERIODS_PER_YEAR = 252`).
- Minimum sample: **30 trades**. Fewer returns `FAIL` outright.
- **Threshold:** $\text{DSR} \ge 0.95$.

---

### Gate 2 — Parameter Stability Surface

Strategies must sit on a broad plateau, not a fragile spike.

1. Re-run the strategy across a grid that perturbs its critical parameters (typically $\pm 10\%$ to
   $\pm 30\%$) and record the metric matrix $M_{i,j}$.
2. Classify: `STABLE_PLATEAU` when $\min(M) > 0.40\,\widehat{SR}$ **and** $\text{mean}(M) > 0.70\,\widehat{SR}$;
   otherwise `ISOLATED_CLIFF`.

**Implementation notes.** The matrix must come from **real perturbed re-runs**. When no such results
are supplied the gate returns **`INCONCLUSIVE`** (`NOT_EVALUATED`) rather than fabricating a plateau.
A previous implementation synthesised $M$ from $\widehat{SR}$ itself, which made the gate
mathematically incapable of failing.

---

### Gate 3 — Monte Carlo Permutation (MDD tail risk)

A single historical path is one realisation. Trade **order** is permuted $K = 1000$ times
(seeded, deterministic) and each simulated equity curve's max drawdown is recorded:

$$\text{MDD}_k = \max_{t}\left(\max_{s \le t} W_s - W_t\right), \qquad
\text{MDD}_{99} = \text{Percentile}_{99}\left(\{\text{MDD}_1, \dots, \text{MDD}_K\}\right),
\qquad
\text{Tail Ratio} = \frac{\text{MDD}_{99}}{\text{MDD}_{\text{original}}}$$

**Passing standard:** $\text{MDD}_{99} \le 3.0\%$ **and** Tail Ratio $\le 2.5$.

---

### Gate 4 — Out-of-Sample Walk-Forward

Returns are split chronologically $70\%$ in-sample / $30\%$ out-of-sample. The OOS leg must stand on
its own rather than inheriting the search's curve-fit:

$$\text{Retention} = \frac{SR_{OOS}}{SR_{IS}} \times 100\%$$

**Passing standard:** $\ge 30$ trades, $SR_{OOS} > 1.0$ **and** Retention $\ge 30\%$.

---

### Gate 5 — Regime Survival

Expectancy must survive more than one market state. Two input modes are supported:

- **Bucket mode** (preferred): the backtester's per-regime breakdown is scored
  $0.35\,w_{\text{bull}} + 0.35\,w_{\text{bear}} + 0.30\,w_{\text{range}}$ on win rate, scaled to 100.
- **Slice mode:** the return series is cut into three equal temporal slices; at least **2 of 3** must
  have positive mean and none may fall below $-1.5\%$.

**Passing standard:** score $\ge 50/100$. Fewer than 30 samples returns `INCONCLUSIVE`.

---

### Gate 6 — Execution Friction & Microstructure Noise Floor

1. **Net friction hurdle.** A round-trip cost of **5 bps taker fee + 2 bps slippage** (7 bps) is
   charged against the mean trade return; net expectancy must stay positive ($E > 0$).
   When returns already come from a real backtest — whose fills embed spread, slippage and fees —
   friction is **not charged again** (`returns_are_net=True`), otherwise the gate double-counts cost
   and spuriously rejects healthy strategies.
2. **Noise floor.** Any active trailing stop tighter than **10 bps** (`0.0010`) fails with
   `FAIL_NOISE_FLOOR`: it sits inside bid-ask bounce and will be liquidated by spread widening before
   a trend can develop.

> The theoretical target remains $\text{Stop Distance} \ge \max(3\times\text{Spread},\ 1.5\times\text{ATR})$.
> The implemented check is the conservative 10 bps floor applied to `trailing_stop_positive`.

---

### Gate 7 — Noise Perturbation Jitter

Return series are perturbed with seeded Gaussian noise ($\sigma = 0.001 \times \sigma_r$, i.e. a
return-space proxy for microstructure jitter) and the Sharpe ratio recomputed:

$$\text{Noise Resilience} = \frac{SR_{\text{perturbed}}}{SR_{\text{original}}}$$

**Passing standard:** Noise Resilience $\ge 0.80$ (retain at least 80% of original Sharpe).
Fewer than 10 samples returns `INCONCLUSIVE`.

---

### Gate 8 — Equity Curve Linearity Standard

Cumulative net equity is regressed against sequential trade index $t = 1 \dots N$:

$$R^2 \ge 0.85 \quad(\text{target } \ge 0.90), \qquad \text{K-Ratio} \ge 1.5$$

**Passing standard:** positive slope **and** $R^2 \ge 0.85$. High total profit achieved through a few
isolated windfalls ($R^2 < 0.70$) is rejected: it cannot be relied on to compound.

---

## 🔗 Portfolio-Level Check (not one of the 8 gates)

### Portfolio Correlation & Regime Orthogonality

$$\rho_{i,j} = \frac{\text{Cov}(R_i, R_j)}{\sigma_i \sigma_j} < 0.50$$

Implemented in [`tools/portfolio_cynic.py`](../tools/portfolio_cynic.py). A strategy correlated
$\rho \ge 0.50$ with an already-active strategy is rejected or assigned reduced capital, since running
both doubles leverage during drawdowns without diversification benefit.

---

## 📉 Post-Deployment Degradation Monitoring (CUSUM)

Once live, regimes drift and alpha decays. Page's CUSUM test provides statistical process control and
is implemented in `compute_cusum_degradation` (also `server/cynic_gates.py`). Its return contract
(`status` of `DEGRADED` / `HEALTHY`, plus `max_cusum`, `threshold`, `mean_return`, `std_return`) is
consumed verbatim by [`server/strategy_executor.py`](../server/strategy_executor.py), which raises
`ALPHA_DEGRADED` alerts and can transition the runner toward safe mode.
