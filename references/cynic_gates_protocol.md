# 8 Institutional Cynic Falsification Gates & ML Trade Autopsy

The Cynic Audit evaluates all quantitative trading strategies against 8 adversarial gates defined in `core/cynic_gates.py`. A candidate strategy must survive both In-Sample and unseen Blind Out-of-Sample evaluation without curve fitting.

---

## 1. The 8 Gates Specification

| Gate | Name | Metric & Pass Condition | Failure Mode / Remediation |
| :--- | :--- | :--- | :--- |
| **Gate 1** | **Deflated Sharpe Ratio (DSR)** | $\text{DSR} \ge 0.95$ (penalized for trial multiplicity and non-normality) | High Sharpe achieved by lucky sequence or excessive iterations; reject overfitted candidates. |
| **Gate 2** | **Parameter Stability Surface** | No performance cliff ($> 30\%$ drop in Sharpe across neighboring $\pm 10\%$ parameter space) | Fragile parameters; use 2D MFE/MAE plateau centroid from `core/geometry_optimizer.py`. |
| **Gate 3** | **Monte Carlo Stress** | $\text{MDD}_{99} \le 3.0\%$, Tail Ratio $\le 2.5$ across 1,000 reshuffled return distributions | Severe sequence risk or fat-tail losses; calibrate `risk_pct_1r` and SL/TP asymmetry via `geometry_optimizer.py`. |
| **Gate 4** | **Combinatorial Purged CV (CPCV)** | Walk-Forward Out-of-Sample Sharpe retention $\ge 50\%$ | Regime overfitting; require 5-slice Sub-Era Invariance in `scan_edge.py` or apply `autopsy_strategy.py` filter. |
| **Gate 5** | **Regime Survival** | Profitable or neutral across Bull, Bear, and Ranging slices | Strategy bleeds in specific market phases; use unsigned regime gates (`abs_ker_25`, `vol_ratio_5_30`) or directional alignment (`align`). |
| **Gate 6** | **Microstructure Friction** | Survives realistic spread + commission; friction $\le 10\%$ of stop distance | Edge eaten up by transaction costs; lengthen holding period or increase stop distance (`sl_atr_mult`). |
| **Gate 7** | **Noise Jitter Resilience** | $\ge 80\%$ Sharpe retention under randomized price jitter / quote perturbation | Micro-price dependence; strategy relies on sub-pip execution luck rather than structural edge. |
| **Gate 8** | **Equity Linearity** | Equity curve $R^2 \ge 0.85$, positive slope, and $K\text{-Ratio} \ge 1.5$ | Lumpy or stair-step returns dependent on rare outliers; enforce consistent trade distribution. |

---

## 2. Canonical Audit & ML Trade Autopsy Workflow

1. **Execute the 8-Gate Audit:**
   ```bash
   python tools/run_backtest_audit.py --strategy <StrategyName.py> --days 60
   ```
2. **If Any Gate Fails — Execute ML Trade Autopsy (Zero Brute-Forcing):**
   ```bash
   python tools/autopsy_strategy.py --audit-json data/audit_report.json
   ```
   `autopsy_strategy.py` isolates the In-Sample trades (never leaking Blind Out-of-Sample data) and fits a shallow DecisionTree across the 39 stationary primitives in `core/feature_factory.py` to output the exact `--extra-filter-feature` or geometry correction needed.

---

## 3. Strict Verdict Enforcement (Anti-Hallucination Law)

1. **Zero Cherry-Picking:** An agent is **strictly forbidden** from presenting a strategy as "COMPLIANT", "READY", or "DEPLOYABLE" if the Cynic Audit overall verdict is `REJECTED`.
2. **Zero Parameter Brute-Forcing:** Never manually guess decimal changes to `sl_atr_mult`, `tp_atr_mult`, or indicator periods. Always rely on `tools/scan_edge.py` (`--from-scan-rank`) and `tools/autopsy_strategy.py`.
3. **Forbidden Escape Hatch:** Agents are strictly forbidden from abandoning a user's objective to audit or report an unrelated pre-existing strategy.
