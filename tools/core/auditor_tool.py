"""
tools/auditor_tool.py - Pure Institutional Verification Gauntlet

Applies the 4 classic quantitative verification gates to any trade log:
1. Friction & Intrabar Audit (Positive Expectancy & PF >= 1.25)
2. Top-5 Outlier Removal Test (Net PnL must remain positive without 5 luckiest trades)
3. 50/50 Chronological Regime Split (Must maintain positive expectancy in both halves)
4. Monte Carlo Sequence Stress Test (1,000 Runs):
   - Daily Drawdown Gate: Verifies no single day breaches the Daily Drawdown limit.
   - Max Drawdown Gate: Verifies 95th percentile Max DD stays strictly below the Max Drawdown limit.
"""

from typing import List, Dict, Any, Optional
import numpy as np


def audit_trade_log(
    trades: List[Any],
    account_size: float = 100_000.0,
    max_drawdown_limit_pct: float = 0.05,
    daily_drawdown_limit_pct: float = 0.03,
    min_trade_count: int = 30
) -> Dict[str, Any]:
    """
    Evaluates a list of completed trades against the 4 institutional gates.
    """
    if len(trades) < min_trade_count:
        return {
            "overall_approved": False,
            "failure_reason": f"Insufficient sample size: {len(trades)} trades (minimum {min_trade_count})",
            "gates": {}
        }

    dollar_pnls = np.array([t.pnl_dollars for t in trades])
    r_multiples = np.array([t.pnl_r for t in trades])

    # -------------------------------------------------------------
    # GATE 1: Baseline Expectancy & Profit Factor
    # -------------------------------------------------------------
    wins = dollar_pnls[dollar_pnls > 0]
    losses = dollar_pnls[dollar_pnls < 0]
    pf = (wins.sum() / abs(losses.sum())) if len(losses) > 0 and abs(losses.sum()) > 0 else 99.0
    exp_r = float(np.mean(r_multiples))
    g1_pass = (pf >= 1.25) and (exp_r >= 0.10)

    # -------------------------------------------------------------
    # GATE 2: Top-5 Outlier Win Removal Test
    # -------------------------------------------------------------
    sorted_pnls = np.sort(dollar_pnls)
    censored_pnls = sorted_pnls[:-5]  # remove top 5
    censored_wins = censored_pnls[censored_pnls > 0]
    censored_losses = censored_pnls[censored_pnls < 0]
    censored_pf = (censored_wins.sum() / abs(censored_losses.sum())) if len(censored_losses) > 0 else 0.0
    censored_net_pnl = float(censored_pnls.sum())
    g2_pass = (censored_net_pnl > 0) and (censored_pf >= 1.0)

    # -------------------------------------------------------------
    # GATE 3: 50/50 Chronological Regime Split
    # -------------------------------------------------------------
    half = len(dollar_pnls) // 2
    h1_pnls = dollar_pnls[:half]
    h2_pnls = dollar_pnls[half:]
    h1_pf = (h1_pnls[h1_pnls > 0].sum() / abs(h1_pnls[h1_pnls < 0].sum())) if (h1_pnls < 0).any() else 99.0
    h2_pf = (h2_pnls[h2_pnls > 0].sum() / abs(h2_pnls[h2_pnls < 0].sum())) if (h2_pnls < 0).any() else 99.0
    g3_pass = (h1_pnls.sum() > 0) and (h2_pnls.sum() > 0) and (h1_pf >= 1.1) and (h2_pf >= 1.1)

    # -------------------------------------------------------------
    # GATE 4: Monte Carlo Sequence Stress Test (1,000 Runs)
    # -------------------------------------------------------------
    # 1. Overall Cumulative Drawdown Stress:
    n_sims = 1000
    cum_breach_count = 0
    max_dds = []

    for _ in range(n_sims):
        sim_pnls = np.random.choice(dollar_pnls, size=len(dollar_pnls), replace=True)
        equity = np.cumsum(sim_pnls) + account_size
        peak = np.maximum.accumulate(equity)
        dd = (peak - equity) / peak
        sim_max_dd = float(np.max(dd))
        max_dds.append(sim_max_dd)
        if sim_max_dd > max_drawdown_limit_pct:
            cum_breach_count += 1

    p_cum_breach = cum_breach_count / n_sims
    p95_max_dd = float(np.percentile(max_dds, 95))
    p99_max_dd = float(np.percentile(max_dds, 99))

    # Strict Cumulative DD Rule:
    # 1) Breach probability must be <= 1.0%
    # 2) 95th Percentile Max DD MUST be strictly less than the max drawdown limit!
    g4_cum_pass = (p_cum_breach <= 0.01) and (p95_max_dd < max_drawdown_limit_pct)

    # 2. Daily Drawdown Stress (Preserving session groupings):
    # Group trades by exit_date to measure real daily PnLs
    daily_pnls_dict = {}
    for t in trades:
        d = t.exit_time.date() if hasattr(t.exit_time, 'date') else str(t.exit_time)[:10]
        daily_pnls_dict[d] = daily_pnls_dict.get(d, 0.0) + t.pnl_dollars

    historical_daily_pnls = np.array(list(daily_pnls_dict.values()))
    worst_daily_loss = float(abs(np.min(historical_daily_pnls))) if len(historical_daily_pnls) > 0 else 0.0
    worst_daily_loss_pct = worst_daily_loss / account_size

    # Simulate daily sequences (1,000 runs)
    daily_breach_count = 0
    for _ in range(n_sims):
        sim_days = np.random.choice(historical_daily_pnls, size=len(historical_daily_pnls), replace=True)
        worst_sim_day = abs(np.min(sim_days))
        if (worst_sim_day / account_size) > daily_drawdown_limit_pct:
            daily_breach_count += 1

    p_daily_breach = daily_breach_count / n_sims
    g4_daily_pass = (p_daily_breach <= 0.005) and (worst_daily_loss_pct <= daily_drawdown_limit_pct)

    g4_pass = g4_cum_pass and g4_daily_pass

    # -------------------------------------------------------------
    # OVERALL VERDICT
    # -------------------------------------------------------------
    overall_pass = g1_pass and g2_pass and g3_pass and g4_pass

    return {
        "overall_approved": overall_pass,
        "total_trades": len(trades),
        "expectancy_r": round(exp_r, 3),
        "profit_factor": round(float(pf), 2),
        "gate_1_expectancy": {
            "passed": g1_pass,
            "profit_factor": round(float(pf), 2),
            "expectancy_r": round(exp_r, 3)
        },
        "gate_2_top5_outlier_removal": {
            "passed": g2_pass,
            "censored_net_pnl": round(censored_net_pnl, 2),
            "censored_profit_factor": round(float(censored_pf), 2)
        },
        "gate_3_regime_split_50_50": {
            "passed": g3_pass,
            "h1_pnl": round(float(h1_pnls.sum()), 2),
            "h1_pf": round(float(h1_pf), 2),
            "h2_pnl": round(float(h2_pnls.sum()), 2),
            "h2_pf": round(float(h2_pf), 2)
        },
        "gate_4_monte_carlo": {
            "passed": g4_pass,
            "cum_drawdown_passed": g4_cum_pass,
            "daily_drawdown_passed": g4_daily_pass,
            "p_cum_breach": round(p_cum_breach, 4),
            "p95_max_drawdown_pct": round(p95_max_dd * 100, 2),
            "p99_max_drawdown_pct": round(p99_max_dd * 100, 2),
            "max_allowed_drawdown_pct": round(max_drawdown_limit_pct * 100, 2),
            "worst_historical_daily_loss_pct": round(worst_daily_loss_pct * 100, 2),
            "daily_drawdown_limit_pct": round(daily_drawdown_limit_pct * 100, 2),
            "p_daily_breach": round(p_daily_breach, 4)
        }
    }
