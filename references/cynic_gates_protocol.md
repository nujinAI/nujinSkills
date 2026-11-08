# 8 Institutional Cynic Falsification Gates

The Cynic Audit evaluates all quantitative trading strategies against 8 adversarial gates defined in `core/cynic_gates.py`. A candidate strategy must survive both In-Sample and unseen Blind Out-of-Sample evaluation without curve fitting.

---

## The 8 Gates Specification

| Gate | Name | Metric & Pass Condition | Failure Mode / Remediation |
| :--- | :--- | :--- | :--- |
| **Gate 1** | **Deflated Sharpe Ratio (DSR)** | $\text{DSR} \ge 0.95$ (penalized for trial multiplicity and non-normality) | High Sharpe achieved by lucky sequence or excessive iterations; reject overfitted candidates. |
| **Gate 2** | **Parameter Stability Surface** | No performance cliff ($> 30\%$ drop in Sharpe across neighboring $\pm 10\%$ parameter space) | Fragile parameters; smooth the parameter response or widen structural tolerance bands. |
| **Gate 3** | **Monte Carlo Stress** | $\text{MDD}_{99} \le 3.0\%$, Tail Ratio $\le 2.5$ across 1,000 reshuffled return distributions | Severe sequence risk or fat-tail losses; lower risk per trade or tighten stop loss structure. |
| **Gate 4** | **Combinatorial Purged CV (CPCV)** | Walk-Forward Out-of-Sample Sharpe retention $\ge 50\%$ | Regime overfitting; incorporate regime filter or generalize entry triggers. |
| **Gate 5** | **Regime Survival** | Profitable or neutral across Bull, Bear, and Ranging slices | Strategy bleeds in specific market phases; add market regime gating (`core.regimes`). |
| **Gate 6** | **Microstructure Friction** | Survives realistic spread + commission; friction $\le 10\%$ of stop distance | Edge eaten up by transaction costs; lengthen holding period or increase stop distance. |
| **Gate 7** | **Noise Jitter Resilience** | $\ge 80\%$ Sharpe retention under randomized price jitter / quote perturbation | Micro-price dependence; strategy relies on sub-pip execution luck rather than structural edge. |
| **Gate 8** | **Equity Linearity** | Equity curve $R^2 \ge 0.85$, positive slope, and $K\text{-Ratio} \ge 1.5$ | Lumpy or stair-step returns dependent on rare outliers; enforce consistent trade distribution. |

---

## Canonical Audit Execution

Execute the full 8-gate audit using the unified tool:

```bash
python tools/run_backtest_audit.py --strategy <StrategyName.py> --days 90
```

Gate evaluations evaluate strictly to `PASS`, `FAIL`, or `INCONCLUSIVE`.
