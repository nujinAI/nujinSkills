"""
cynic_gates.py — SINGLE SOURCE OF TRUTH for Cynic falsification gate math.

Every consumer MUST call these functions:
  - server/backtest_engine.py   (persists the gate matrix that ranking reads)
  - tools/cynic_auditor.py      (agent-facing auditor)
  - tools/validation_cynic.py   (thin shim, re-exports these names)
  - tools/run_backtest_audit.py (displays the matrix)

Do NOT add a second implementation of DSR, Monte Carlo, regime survival,
noise jitter, friction, or equity linearity anywhere else in this repository.
Historically three divergent copies existed (sqrt(252) vs sqrt(252*24*4)
annualisation, 3% vs 10% MDD thresholds, and two fabricated always-pass gates),
which made the same strategy produce different verdicts in different tools.

Gate contract
-------------
Each gate returns a dict that always contains:
    status : "PASS" | "FAIL" | "INCONCLUSIVE"
"INCONCLUSIVE" is used when the inputs required to actually test the gate are
missing. It deliberately does NOT claim PASS — a gate that cannot fail must
never report success. Only "PASS" counts toward the passed-gate tally.
"""

from __future__ import annotations

import numpy as np
from scipy import stats

# ─────────────────────────────────────────────────────────────────────────────
# Canonical constants — the ONLY place these thresholds are defined.
# ─────────────────────────────────────────────────────────────────────────────

# All thresholds live in server/constants.py (single source of truth). They are
# re-exported here so every existing importer of server.cynic_gates keeps
# working unchanged. Do not redefine them locally.
from server.constants import (  # noqa: F401  (re-exported for compatibility)
    DSR_THRESHOLD,
    FEE_BPS,
    MAX_MDD_99,
    MAX_TAIL_RATIO,
    MC_SIMULATIONS,
    MIN_K_RATIO,
    MIN_NOISE_FLOOR,
    MIN_NOISE_RETENTION,
    MIN_OOS_RETENTION_PCT,
    MIN_OOS_SR,
    MIN_OOS_TRADES,
    MIN_R2,
    MIN_REGIME_SLICE_MEAN,
    MIN_REGIME_TRADES,
    MIN_TRADES_DSR,
    NOISE_JITTER_SIGMA,
    OOS_SPLIT,
    PERIODS_PER_YEAR,
    SLIPPAGE_BPS,
    trade_annualization_factor,
)

# Ordered canonical gate registry: (key, human label).
CANONICAL_GATES = (
    ("gate_1_dsr", "Deflated Sharpe Ratio"),
    ("gate_2_parameter_stability", "Parameter Stability"),
    ("gate_3_monte_carlo", "Monte Carlo MDD"),
    ("gate_4_oos_walkforward", "OOS Walk-Forward"),
    ("gate_5_regime_survival", "Regime Survival"),
    ("gate_6_friction", "Friction & Noise Floor"),
    ("gate_7_noise_jitter", "Noise Jitter"),
    ("gate_8_equity_linearity", "Equity Linearity"),
)

GATE_KEYS = tuple(k for k, _ in CANONICAL_GATES)

PASS, FAIL, INCONCLUSIVE = "PASS", "FAIL", "INCONCLUSIVE"


def _clean(returns) -> np.ndarray:
    arr = np.asarray(returns, dtype=float).ravel()
    return arr[~np.isnan(arr)]


# ─────────────────────────────────────────────────────────────────────────────
# Gate 1 — Deflated Sharpe Ratio (Bailey & Lopez de Prado)
# ─────────────────────────────────────────────────────────────────────────────

def compute_dsr(returns, n_trials: int = 40,
                periods_per_year: int = PERIODS_PER_YEAR) -> dict:
    clean_r = _clean(returns)
    if len(clean_r) < MIN_TRADES_DSR:
        return {"dsr": 0.0, "observed_sr": 0.0, "status": FAIL,
                "threshold": DSR_THRESHOLD,
                "reason": f"Insufficient return samples (< {MIN_TRADES_DSR})"}

    mean_r = float(np.mean(clean_r))
    std_r = float(np.std(clean_r, ddof=1))
    if std_r == 0:
        return {"dsr": 0.0, "observed_sr": 0.0, "status": FAIL,
                "threshold": DSR_THRESHOLD, "reason": "Zero return variance"}

    sr = (mean_r / std_r) * float(np.sqrt(periods_per_year))
    t_obs = len(clean_r)
    sk = float(stats.skew(clean_r))
    kt = float(stats.kurtosis(clean_r, fisher=False))  # Pearson kurtosis (normal = 3)

    # Expected maximum Sharpe under pure chance across N trials.
    euler_gamma = 0.5772156649
    n = max(int(n_trials), 2)
    ln_n = np.log(n)
    z = float(np.sqrt(2.0 * ln_n))
    sr_0 = z * (1.0 - euler_gamma / (2.0 * ln_n)) + (euler_gamma / z)

    denom = np.sqrt(
        (1.0 - sk * sr + ((kt - 1.0) / 4.0) * (sr ** 2)) / max(1, t_obs - 1)
    )
    dsr = float(stats.norm.cdf((sr - sr_0) / denom)) if denom > 0 else 0.0
    passed = dsr >= DSR_THRESHOLD

    return {
        "dsr": round(dsr, 4),
        "observed_sr": round(sr, 4),
        "benchmark_sr_0": round(sr_0, 4),
        "trials_penalized": int(n_trials),
        "threshold": DSR_THRESHOLD,
        "annualization_periods": int(periods_per_year),
        "status": PASS if passed else FAIL,
        "reason": (f"DSR {dsr:.4f} >= {DSR_THRESHOLD}" if passed
                   else f"DSR {dsr:.4f} < {DSR_THRESHOLD}"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Gate 2 — Parameter stability (only real perturbed results may PASS)
# ─────────────────────────────────────────────────────────────────────────────

def verify_parameter_stability(metric_matrix=None, observed_sr: float | None = None,
                               min_cell_factor: float = 0.40,
                               mean_cell_factor: float = 0.70) -> dict:
    """
    Evaluate a parameter plateau from genuinely perturbed results.

    `metric_matrix` must be a 2-D list of metric values that were actually
    measured by re-running the strategy with perturbed parameters. If it is
    absent, there is nothing to falsify and the gate returns INCONCLUSIVE —
    it never fabricates a plateau (the previous implementation synthesised the
    matrix from `observed_sr` and so could never fail).
    """
    if metric_matrix is None:
        return {
            "status": INCONCLUSIVE,
            "plateau_status": "NOT_EVALUATED",
            "reason": ("No perturbed parameter re-runs supplied; stability is "
                       "unverified. Provide metric_matrix from real grid re-runs."),
        }

    flat = [float(v) for row in metric_matrix for v in row]
    if not flat:
        return {"status": INCONCLUSIVE, "plateau_status": "NOT_EVALUATED",
                "reason": "Empty parameter grid"}

    ref = abs(float(observed_sr)) if observed_sr else abs(float(np.mean(flat)))
    if ref <= 0:
        return {"status": INCONCLUSIVE, "plateau_status": "NOT_EVALUATED",
                "reason": "Non-positive reference metric"}

    min_cell = float(np.min(flat))
    avg_cell = float(np.mean(flat))
    stable = (min_cell > min_cell_factor * ref) and (avg_cell > mean_cell_factor * ref)

    return {
        "matrix": metric_matrix,
        "min_cell": round(min_cell, 4),
        "mean_cell": round(avg_cell, 4),
        "observed_sr": round(ref, 4),
        "plateau_status": "STABLE_PLATEAU" if stable else "ISOLATED_CLIFF",
        "status": PASS if stable else FAIL,
        "reason": ("Plateau verified across perturbed parameters" if stable
                   else "Performance collapses under parameter perturbation"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Gate 3 — Monte Carlo trade-order permutation (MDD tail risk)
# ─────────────────────────────────────────────────────────────────────────────

def verify_monte_carlo(returns, num_simulations: int = MC_SIMULATIONS,
                       max_mdd_99: float = MAX_MDD_99,
                       max_tail_ratio: float = MAX_TAIL_RATIO) -> dict:
    clean_r = _clean(returns)
    if len(clean_r) < 10:
        return {"mdd_99": 0.0, "status": FAIL,
                "reason": "Insufficient return samples (< 10)"}

    cum_returns = np.cumsum(clean_r)
    orig_mdd = float(np.max(np.maximum.accumulate(cum_returns) - cum_returns))

    rng = np.random.default_rng(42)
    sim_mdds = []
    for _ in range(int(num_simulations)):
        permuted = rng.permutation(clean_r)
        cum_p = np.cumsum(permuted)
        sim_mdds.append(float(np.max(np.maximum.accumulate(cum_p) - cum_p)))

    mdd_99 = float(np.percentile(sim_mdds, 99))
    ratio = mdd_99 / (orig_mdd + 1e-6)
    passed = (ratio <= max_tail_ratio) and (mdd_99 <= max_mdd_99)

    return {
        "original_mdd": round(orig_mdd, 4),
        "mdd_99": round(mdd_99, 4),
        "tail_ratio": round(ratio, 2),
        "max_allowed": max_mdd_99,
        "status": PASS if passed else FAIL,
        "reason": (f"MDD99 <= {max_mdd_99:.1%} & tail ratio <= {max_tail_ratio}"
                   if passed else
                   (f"MDD99 {mdd_99:.2%} > {max_mdd_99:.1%}" if mdd_99 > max_mdd_99
                    else f"Tail ratio {ratio:.2f} > {max_tail_ratio}")),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Gate 4 — Out-of-sample walk-forward + Purged K-Fold CV (CPCV) & Rolling WFO
# ─────────────────────────────────────────────────────────────────────────────

def compute_cpcv_and_rolling_wfo(
    returns,
    n_folds: int = 6,
    purge_len: int = 1,
    periods_per_year: int = PERIODS_PER_YEAR,
) -> dict:
    """
    López de Prado Combinatorial Purged Cross-Validation (CPCV) & Rolling WFO:
      - Splits `returns` into `n_folds` contiguous blocks, purging `purge_len`
        boundary trades between train and test blocks to eliminate serial overlap.
      - Evaluates every 2-fold out-of-sample test combination C(n_folds, 2) to
        measure `cpcv_median_oos_sharpe` and `pbo_estimate` (Probability of
        Backtest Overfitting = fraction of purged OOS combinations with SR <= 0).
      - Evaluates rolling walk-forward sub-windows to measure temporal consistency.
    """
    from itertools import combinations

    clean_r = _clean(returns)
    n = len(clean_r)
    if n < 24:
        return {
            "cpcv_median_oos_sharpe": 0.0,
            "pbo_estimate": 1.0,
            "rolling_wfo_positive_windows_pct": 0.0,
        }

    k = min(max(4, int(n_folds)), n // 6)
    folds = np.array_split(np.arange(n), k)
    oos_sharpes = []

    for test_i, test_j in combinations(range(k), 2):
        test_idx = np.concatenate([folds[test_i], folds[test_j]])
        # Purge boundary elements adjacent to training folds
        if purge_len > 0 and len(test_idx) > 2 * purge_len + 4:
            test_idx = test_idx[purge_len:-purge_len]
        sub_r = clean_r[test_idx]
        if len(sub_r) < 4:
            continue
        std_sub = float(np.std(sub_r))
        sr_sub = float((np.mean(sub_r) / max(std_sub, 1e-6)) * np.sqrt(periods_per_year))
        oos_sharpes.append(sr_sub)

    if oos_sharpes:
        median_cpcv_sr = float(np.median(oos_sharpes))
        pbo = float(np.mean([1.0 if s <= 0.0 else 0.0 for s in oos_sharpes]))
    else:
        median_cpcv_sr = 0.0
        pbo = 1.0

    # Rolling Walk-Forward OOS sub-windows (4 non-overlapping OOS slices in the second half)
    wfo_slices = np.array_split(clean_r[n // 3 :], 4)
    pos_windows = sum(1 for sl in wfo_slices if len(sl) > 0 and float(np.mean(sl)) > 0.0)
    wfo_pos_pct = round((pos_windows / max(1, len(wfo_slices))) * 100.0, 1)

    return {
        "cpcv_median_oos_sharpe": round(median_cpcv_sr, 2),
        "pbo_estimate": round(pbo, 3),
        "rolling_wfo_positive_windows_pct": wfo_pos_pct,
    }


def verify_oos_walkforward(returns, split: float = OOS_SPLIT,
                           periods_per_year: int = PERIODS_PER_YEAR) -> dict:
    clean_r = _clean(returns)
    if len(clean_r) < max(MIN_OOS_TRADES, MIN_TRADES_DSR):
        return {"status": FAIL,
                "reason": (f"Insufficient return samples for OOS walk-forward "
                           f"(< {max(MIN_OOS_TRADES, MIN_TRADES_DSR)})"),
                "sharpe_is": 0.0, "sharpe_oos": 0.0, "retention_pct": 0.0}

    split_idx = int(len(clean_r) * split)
    is_ret, oos_ret = clean_r[:split_idx], clean_r[split_idx:]
    is_std, oos_std = np.std(is_ret), np.std(oos_ret)
    sr_is = float((np.mean(is_ret) / max(is_std, 1e-6)) * np.sqrt(periods_per_year))
    sr_oos = float((np.mean(oos_ret) / max(oos_std, 1e-6)) * np.sqrt(periods_per_year))
    retention = round((sr_oos / max(sr_is, 1e-6)) * 100.0, 1) if sr_is > 0 else 0.0
    cpcv_info = compute_cpcv_and_rolling_wfo(clean_r, periods_per_year=periods_per_year)
    passed = (sr_oos > MIN_OOS_SR) and (retention >= MIN_OOS_RETENTION_PCT)

    return {
        "sharpe_is": round(sr_is, 2),
        "sharpe_oos": round(sr_oos, 2),
        "retention_pct": retention,
        **cpcv_info,
        "status": PASS if passed else FAIL,
        "reason": (f"IS Sharpe {sr_is:.2f} -> OOS Sharpe {sr_oos:.2f} "
                   f"(Retention: {retention}%, CPCV SR: {cpcv_info['cpcv_median_oos_sharpe']:.2f}, PBO: {cpcv_info['pbo_estimate']:.2f})"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Gate 5 — Regime survival
# ─────────────────────────────────────────────────────────────────────────────

def verify_regime_survival(returns, regime_breakdown: dict | None = None) -> dict:
    """
    Either consume pre-computed per-regime bucket performance
    (`regime_breakdown` from the backtester) or split the return series into
    three temporal slices. One implementation, two input modes.
    """
    if regime_breakdown:
        wins = [
            float(regime_breakdown.get(k, {}).get("win_rate", 0.0))
            for k in ("bull_market", "bear_market", "ranging_market")
        ]
        weights = (0.35, 0.35, 0.30)
        score = round(min(100.0, max(0.0, sum(w * r for w, r in zip(weights, wins)) * 100.0)), 1)
        status = PASS if score >= 50.0 else FAIL
        return {
            "score": score,
            "bull_win": wins[0], "bear_win": wins[1], "ranging_win": wins[2],
            "status": status,
            "reason": f"Regime survival score {score}/100",
        }

    clean_r = _clean(returns)
    if len(clean_r) < MIN_REGIME_TRADES:
        return {"status": INCONCLUSIVE,
                "reason": f"Sample size too small for 3-way slice (< {MIN_REGIME_TRADES})"}

    n = len(clean_r)
    s1, s2, s3 = clean_r[:n // 3], clean_r[n // 3:2 * n // 3], clean_r[2 * n // 3:]
    means = [float(np.mean(s)) for s in (s1, s2, s3)]
    positive = sum(1 for m in means if m > 0)
    passed = positive >= 2 and min(means) > MIN_REGIME_SLICE_MEAN

    return {
        "slice_1_mean": round(means[0], 6),
        "slice_2_mean": round(means[1], 6),
        "slice_3_mean": round(means[2], 6),
        "positive_slices": f"{positive}/3",
        "status": PASS if passed else FAIL,
        "reason": f"{positive}/3 regime slices positive",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Gate 6 — Friction & microstructure noise floor
# ─────────────────────────────────────────────────────────────────────────────

def verify_friction(returns, fee_bps: float = FEE_BPS,
                    slippage_bps: float = SLIPPAGE_BPS) -> dict:
    clean_r = _clean(returns)
    if len(clean_r) == 0:
        return {"status": FAIL, "reason": "No trades"}

    friction_per_trade = (fee_bps + slippage_bps) / 10000.0
    net_mean = float(np.mean(clean_r) - friction_per_trade)
    return {
        "friction_bps": fee_bps + slippage_bps,
        "net_mean_return": round(net_mean, 6),
        "status": PASS if net_mean > 0 else FAIL,
        "reason": (f"Net expectancy {net_mean:+.6f} after {fee_bps + slippage_bps} bps"
                   if net_mean > 0 else "Negative expectancy after friction"),
    }


def verify_noise_floor(strategy_name: str | None) -> dict:
    """Stops/trailing stops must not sit inside the bid-ask noise band."""
    if not strategy_name:
        return {"status": INCONCLUSIVE, "note": "No strategy specified; bypassed"}
    try:
        from server.backtest_engine import load_strategy_instance
        strat = load_strategy_instance(strategy_name)
        if not strat:
            return {"status": INCONCLUSIVE, "note": "Strategy instance not loadable"}

        trail_pos = getattr(strat, "trailing_stop_positive", 0.0)
        trail_pos = float(getattr(trail_pos, "value", trail_pos) or 0.0)
        use_trail = getattr(strat, "trailing_stop", False)

        if use_trail and 0 < trail_pos < MIN_NOISE_FLOOR:
            return {"status": FAIL, "trail_pos": trail_pos,
                    "reason": (f"Trailing stop {trail_pos:.4f} is narrower than the "
                               f"{MIN_NOISE_FLOOR:.4f} microstructure noise floor")}
        return {"status": PASS, "trail_pos": trail_pos}
    except Exception as e:  # pragma: no cover - defensive
        return {"status": INCONCLUSIVE, "note": f"Error inspecting strategy: {e}"}


# ─────────────────────────────────────────────────────────────────────────────
# Gate 7 — Noise perturbation jitter
# ─────────────────────────────────────────────────────────────────────────────

def verify_noise_jitter(returns, noise_sigma: float = NOISE_JITTER_SIGMA,
                        min_retention: float = MIN_NOISE_RETENTION) -> dict:
    clean_r = _clean(returns)
    if len(clean_r) < 10:
        return {"status": INCONCLUSIVE, "retention_pct": None,
                "reason": "Insufficient return samples (< 10)"}

    orig_std = float(np.std(clean_r))
    if orig_std == 0:
        return {"status": FAIL, "reason": "Zero variance"}

    orig_sr = float(np.mean(clean_r)) / orig_std
    rng = np.random.default_rng(42)
    noise = rng.normal(0, noise_sigma * orig_std, size=len(clean_r))
    perturbed = clean_r + noise
    pert_sr = float(np.mean(perturbed)) / (float(np.std(perturbed)) + 1e-8)
    retention = float(pert_sr / (orig_sr + 1e-8)) if orig_sr > 0 else 0.0
    passed = retention >= min_retention

    return {
        "original_sr": round(orig_sr, 4),
        "perturbed_sr": round(pert_sr, 4),
        "retention_pct": round(retention * 100.0, 1),
        "min_retention_pct": min_retention * 100.0,
        "status": PASS if passed else FAIL,
        "reason": f"Sharpe retention {retention * 100.0:.1f}% (min {min_retention * 100.0:.0f}%)",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Gate 8 — Equity curve linearity
# ─────────────────────────────────────────────────────────────────────────────

def compute_equity_linearity(returns, min_r2: float = MIN_R2,
                             min_k_ratio: float = MIN_K_RATIO) -> dict:
    clean_r = _clean(returns)
    if len(clean_r) < 15:
        return {"r_squared": 0.0, "k_ratio": 0.0, "status": FAIL,
                "reason": "Insufficient samples (< 15)"}

    cum_eq = np.cumsum(clean_r)
    n = len(cum_eq)
    x = np.arange(n, dtype=float)
    x_mean, y_mean = float(np.mean(x)), float(np.mean(cum_eq))
    ss_xy = float(np.sum((x - x_mean) * (cum_eq - y_mean)))
    ss_xx = float(np.sum((x - x_mean) ** 2))
    ss_yy = float(np.sum((cum_eq - y_mean) ** 2))
    slope = ss_xy / ss_xx if ss_xx > 0 else 0.0
    r_val = ss_xy / np.sqrt(ss_xx * ss_yy) if (ss_xx * ss_yy) > 0 else 0.0
    r_squared = float(r_val ** 2) if not np.isnan(r_val) else 0.0
    residuals = cum_eq - (y_mean + slope * (x - x_mean))
    std_err = (np.sqrt(np.sum(residuals ** 2) / max(1, n - 2)) / np.sqrt(ss_xx)
               if ss_xx > 0 else 1.0)
    k_ratio = (float(slope / max(std_err, 1e-6)) * (np.sqrt(n) / n)
               if (std_err > 0 and n > 0) else 0.0)
    passed = (slope > 0) and (r_squared >= min_r2)

    return {
        "r_squared": round(r_squared, 4),
        "k_ratio": round(k_ratio, 2),
        "slope": round(float(slope), 6),
        "min_r_squared": min_r2,
        "min_k_ratio": min_k_ratio,
        "status": PASS if passed else FAIL,
        "reason": (f"R² {r_squared:.4f} >= {min_r2}" if passed
                   else f"R² {r_squared:.4f} < {min_r2} or non-positive slope"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Live alpha-degradation monitoring (Page's CUSUM)
# ─────────────────────────────────────────────────────────────────────────────

def compute_cusum_degradation(returns, threshold_sigma: float = 2.5) -> dict:
    """
    Page's Cumulative Sum (CUSUM) test for live/forward alpha degradation.

    NOTE: the return contract here (status "DEGRADED"/"HEALTHY", keys
    max_cusum/threshold/mean_return/std_return) is consumed verbatim by
    server/strategy_executor.py, which checks `status != "DEGRADED"`.
    The stabilisation term deliberately does not subtract the expected mean,
    matching the behaviour this monitor has always had in production.
    (references/quant_protocol.md 1.8 describes a mean-shifted variant; that is
    a separate, deliberate change and must not be made silently here.)
    """
    arr = np.asarray(returns, dtype=float).ravel()
    if len(arr) < 5:
        return {"status": "HEALTHY", "cusum_statistic": 0.0,
                "reason": "Insufficient samples (< 5)"}

    mean_r = float(np.mean(arr))
    std_r = float(np.std(arr, ddof=1)) if len(arr) > 1 else 1.0
    if std_r == 0:
        std_r = 1e-6

    k = 0.5 * std_r
    s_t, max_s = 0.0, 0.0
    for r in arr:
        s_t = max(0.0, s_t - float(r) - k)
        if s_t > max_s:
            max_s = s_t

    h_threshold = threshold_sigma * std_r
    degraded = max_s >= h_threshold

    return {
        "status": "DEGRADED" if degraded else "HEALTHY",
        "max_cusum": round(max_s, 6),
        "threshold": round(h_threshold, 6),
        "mean_return": round(mean_r, 6),
        "std_return": round(std_r, 6),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Matrix assembly — the single canonical gate payload
# ─────────────────────────────────────────────────────────────────────────────

def summarize_gates(gates: dict) -> dict:
    """Count PASS/FAIL/INCONCLUSIVE across the canonical registry."""
    passed = failed = inconclusive = 0
    for key in GATE_KEYS:
        status = (gates.get(key) or {}).get("status")
        if status == PASS:
            passed += 1
        elif status == FAIL:
            failed += 1
        else:
            inconclusive += 1

    total = len(GATE_KEYS)
    if failed > 0:
        verdict = "REJECTED"
    elif inconclusive > 0:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "APPROVED"

    return {
        "gates_passed": passed,
        "gates_failed": failed,
        "gates_inconclusive": inconclusive,
        "gates_total": total,
        "gate_keys": list(GATE_KEYS),
        "verdict": verdict,
    }


def evaluate_gates(returns, n_trials: int = 40, strategy_name: str | None = None,
                   regime_breakdown: dict | None = None,
                   metric_matrix=None, observed_sr: float | None = None,
                   returns_are_net: bool = False,
                   max_mdd_99: float = MAX_MDD_99) -> dict:
    """
    Compute the complete canonical Cynic matrix from one return series.

    `returns_are_net` must be True when the series was produced by a real
    backtest, because those fills already carry spread, slippage and taker
    fees. Charging friction again would double-count it and spuriously fail
    the friction gate (the historical cynic_auditor guarded this explicitly).

    Returns a dict containing every key in CANONICAL_GATES, plus
    `gates_summary` (counts + verdict). This is the ONLY function that should
    assemble a gate matrix.
    """
    fee_bps = 0.0 if returns_are_net else FEE_BPS
    slippage_bps = 0.0 if returns_are_net else SLIPPAGE_BPS

    gates = {
        "gate_1_dsr": compute_dsr(returns, n_trials=n_trials),
        "gate_2_parameter_stability": verify_parameter_stability(
            metric_matrix=metric_matrix, observed_sr=observed_sr),
        "gate_3_monte_carlo": verify_monte_carlo(returns, max_mdd_99=max_mdd_99),
        "gate_4_oos_walkforward": verify_oos_walkforward(returns),
        "gate_5_regime_survival": verify_regime_survival(
            returns, regime_breakdown=regime_breakdown),
        "gate_6_friction": verify_friction(returns, fee_bps=fee_bps,
                                           slippage_bps=slippage_bps),
        "gate_7_noise_jitter": verify_noise_jitter(returns),
        "gate_8_equity_linearity": compute_equity_linearity(returns),
    }
    gates["gate_6_friction"]["returns_were_net_of_friction"] = bool(returns_are_net)

    # The noise-floor check needs the strategy definition, not just returns.
    # Only meaningful when we have actual returns to charge friction against.
    if strategy_name:
        floor = verify_noise_floor(strategy_name)
        gates["gate_6_friction"]["noise_floor"] = floor
        if floor.get("status") == FAIL:
            gates["gate_6_friction"]["status"] = FAIL
            gates["gate_6_friction"]["reason"] = floor.get("reason", "Violated noise floor")

    gates["gates_summary"] = summarize_gates(gates)
    gates["overall_status"] = gates["gates_summary"]["verdict"]
    return gates


def format_matrix(gates: dict) -> str:
    """Render the gate matrix as human-readable text (shared by all CLIs)."""
    lines = ["", "=" * 70, "🛡️  CANONICAL CYNIC-FALSIFICATION MATRIX", "=" * 70]
    for i, (key, label) in enumerate(CANONICAL_GATES, start=1):
        g = gates.get(key) or {}
        status = g.get("status", "MISSING")
        detail = g.get("reason", "")
        lines.append(f"  [{i}] {label:<26} {status:<13} {detail}")
    summary = gates.get("gates_summary") or summarize_gates(gates)
    lines.append("-" * 70)
    lines.append(
        f"  Passed {summary['gates_passed']}/{summary['gates_total']} | "
        f"Failed {summary['gates_failed']} | Inconclusive {summary['gates_inconclusive']}"
    )
    lines.append(f"  VERDICT: {summary['verdict']}")
    lines.append("=" * 70 + "\n")
    return "\n".join(lines)


# Canonical Aliases for System-wide Consistency
evaluate_cynic_gates = evaluate_gates
render_gate_matrix = format_matrix
