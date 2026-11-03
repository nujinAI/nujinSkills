"""
server/drift_monitor.py
─────────────────────────────────────────────────────────────────────────────
Live-vs-Backtest Alpha Decay & Statistical Process Control (SPC) Monitor (Pillar 7).

Implements:
  1. Downward Tabular CUSUM / Page-Hinkley Sequential Change-Point Test:
     Detects when live trade expectancy drifts below the audited backtest mean.
  2. Bootstrap Monte Carlo 5th-Percentile Trajectory Envelope Check:
     Verifies whether the realized live cumulative equity path has fallen below
     the 5th percentile of backtest bootstrap paths of the same trade length.
  3. Two-Sample Kolmogorov-Smirnov (KS) Distribution Shift Test.
  4. Automatic Strategy Quarantine (`audit_and_quarantine_live_strategies`):
     Demotes a decaying live strategy to `paper` shadow mode when CUSUM or the
     Monte Carlo 5th-percentile envelope is breached.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence
import numpy as np
from scipy import stats


def evaluate_live_vs_backtest_drift(
    live_returns: Sequence[float],
    backtest_returns: Optional[Sequence[float]] = None,
    expected_mean: Optional[float] = None,
    expected_std: Optional[float] = None,
    cusum_slack_k: float = 0.50,
    cusum_threshold_h: float = 4.00,
    num_mc_paths: int = 500,
) -> Dict[str, Any]:
    """
    Evaluates whether a sequence of realized `live_returns` is statistically consistent
    with the audited `backtest_returns` distribution.
    """
    live_arr = np.asarray(live_returns, dtype=float).ravel()
    live_arr = live_arr[~np.isnan(live_arr)]
    n_live = len(live_arr)

    if n_live < 5:
        return {
            "status": "HEALTHY",
            "action": "CONTINUE_LIVE",
            "n_live_trades": n_live,
            "cusum_score": 0.0,
            "cusum_threshold": cusum_threshold_h,
            "live_cum_return": float(np.sum(live_arr)) if n_live > 0 else 0.0,
            "mc_5th_percentile_bound": None,
            "ks_p_value": 1.0,
            "reason": f"Insufficient live trades ({n_live} < 5) to trigger SPC alarm.",
        }

    bt_arr = None
    if backtest_returns is not None:
        raw_bt = np.asarray(backtest_returns, dtype=float).ravel()
        raw_bt = raw_bt[~np.isnan(raw_bt)]
        if len(raw_bt) >= 10:
            bt_arr = raw_bt

    mu_ref = float(expected_mean) if expected_mean is not None else (float(np.mean(bt_arr)) if bt_arr is not None else 0.0010)
    sd_ref = float(expected_std) if expected_std is not None else (float(np.std(bt_arr, ddof=1)) if bt_arr is not None else 0.0045)
    sd_ref = max(sd_ref, 1e-6)

    # 1. Downward Tabular CUSUM Test
    z_scores = (live_arr - mu_ref) / sd_ref
    c_minus = 0.0
    peak_c_minus = 0.0
    for z in z_scores:
        c_minus = max(0.0, c_minus - float(z) - cusum_slack_k)
        if c_minus > peak_c_minus:
            peak_c_minus = c_minus

    # 2. Monte Carlo 5th-Percentile Envelope at horizon n_live
    rng = np.random.default_rng(42)
    if bt_arr is not None:
        sim_paths = rng.choice(bt_arr, size=(num_mc_paths, n_live), replace=True)
    else:
        sim_paths = rng.normal(mu_ref, sd_ref, size=(num_mc_paths, n_live))
    sim_cum_totals = np.sum(sim_paths, axis=1)
    mc_p05 = float(np.percentile(sim_cum_totals, 5))
    mc_p15 = float(np.percentile(sim_cum_totals, 15))
    live_cum = float(np.sum(live_arr))

    # 3. Two-Sample KS Test (one-sided: is live stochastically smaller than backtest?)
    ks_pval = 1.0
    if bt_arr is not None and n_live >= 8:
        res_ks = stats.ks_2samp(live_arr, bt_arr, alternative="greater")
        ks_pval = float(res_ks.pvalue)

    cusum_breach = c_minus >= cusum_threshold_h
    envelope_breach = (live_cum < mc_p05) and (live_cum < 0.0 or c_minus >= cusum_threshold_h * 0.50)
    ks_breach = ks_pval < 0.01 and float(np.mean(live_arr)) < 0.0

    if cusum_breach or envelope_breach or ks_breach:
        status = "QUARANTINE"
        action = "AUTO_DEMOTE_TO_PAPER"
        reasons = []
        if cusum_breach:
            reasons.append(f"CUSUM {c_minus:.2f} >= {cusum_threshold_h:.2f}")
        if envelope_breach:
            reasons.append(f"Live CumRet {live_cum*100:+.2f}% < MC 5th-pct {mc_p05*100:+.2f}%")
        if ks_breach:
            reasons.append(f"KS p-val {ks_pval:.4f} < 0.01")
        reason_str = " | ".join(reasons)
    elif c_minus >= cusum_threshold_h * 0.65 or (live_cum < mc_p15 and c_minus >= 1.0):
        status = "WARNING"
        action = "THROTTLE_RISK_50PCT"
        reason_str = f"Early alpha decay warning (CUSUM={c_minus:.2f}, LiveCum={live_cum*100:+.2f}%)"
    else:
        status = "HEALTHY"
        action = "CONTINUE_LIVE"
        reason_str = f"Live performance within backtest Monte Carlo envelope (CUSUM={c_minus:.2f} < {cusum_threshold_h:.2f})"

    return {
        "status": status,
        "action": action,
        "n_live_trades": n_live,
        "cusum_score": round(float(c_minus), 3),
        "peak_cusum_score": round(float(peak_c_minus), 3),
        "cusum_threshold": cusum_threshold_h,
        "live_mean_return": round(float(np.mean(live_arr)), 6),
        "backtest_mean_return": round(mu_ref, 6),
        "live_cum_return": round(live_cum, 5),
        "mc_5th_percentile_bound": round(mc_p05, 5),
        "ks_p_value": round(ks_pval, 4),
        "reason": reason_str,
    }


def audit_and_quarantine_live_strategies(auto_quarantine: bool = True) -> List[Dict[str, Any]]:
    """
    Checks active strategies in `server/state_manager.py` against their audited backtest
    baseline and automatically demotes any strategy in `QUARANTINE` status from `live` -> `paper`.
    """
    from server import state_manager

    state = state_manager.load_state()
    strats = state_manager.load_strategies()
    trade_history = state.get("trade_history", [])
    reports: List[Dict[str, Any]] = []

    for s in strats:
        name = s.get("name", "Unknown")
        # Extract live trades for this strategy
        s_trades = [t for t in trade_history if t.get("strategy") == name or len(strats) == 1]
        live_rets = [float(t.get("pnl_pct", 0.0)) / 100.0 for t in s_trades if "pnl_pct" in t]

        bt_metrics = s.get("metrics", {})
        exp_bps = float(bt_metrics.get("expectancy_bps", 12.0))
        mu_bt = exp_bps / 10000.0
        sr_bt = max(float(bt_metrics.get("sharpe", 1.8)), 0.5)
        # Approximate per-trade std from trade annualization factor (~15.87)
        sd_bt = max(abs(mu_bt) * (15.8745 / sr_bt), 0.0020)

        drift = evaluate_live_vs_backtest_drift(
            live_returns=live_rets,
            expected_mean=mu_bt,
            expected_std=sd_bt,
        )
        drift["strategy"] = name

        if drift["status"] == "QUARANTINE" and auto_quarantine:
            if state.get("bot_mode") == "live" and state.get("active_strategy") == name:
                state_manager.update_state({"bot_mode": "paper", "drift_quarantine_reason": drift["reason"]})
                drift["quarantine_applied"] = True
            else:
                drift["quarantine_applied"] = False
        reports.append(drift)

    return reports
