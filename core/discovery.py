"""
core/discovery.py - Universal Parametric Statistical Edge & Anomaly Discovery Engine.

Quantifies the empirical predictive power and friction clearance of ANY candidate
feature, state machine, or hypothesis series across forward horizons without bias.
Zero hardcoded indicators, zero curve-fitting presets.
"""
from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import pandas as pd
from core.friction import get_roundtrip_friction


def compute_forward_returns(
    df: pd.DataFrame,
    horizons: List[int] = [1, 3, 5, 12, 24],
    price_col: str = "close"
) -> pd.DataFrame:
    """
    Computes percentage forward returns across multiple future bar horizons.
    Forward return at time t for horizon h: (Close[t + h] - Close[t]) / Close[t].
    """
    fwd = pd.DataFrame(index=df.index)
    prices = df[price_col].astype(float)
    for h in horizons:
        fwd[f"fwd_ret_{h}"] = (prices.shift(-h) - prices) / prices
    return fwd


def evaluate_feature_predictive_power(
    feature_series: pd.Series,
    forward_returns: pd.Series,
    num_quantiles: int = 5
) -> Dict[str, Any]:
    """
    Calculates Information Coefficient (Spearman Rank Correlation), Pearson Correlation,
    p-value proxy (t-stat), and quantile monotonic return distribution.
    """
    valid_mask = ~(feature_series.isna() | forward_returns.isna() | np.isinf(feature_series) | np.isinf(forward_returns))
    x = feature_series[valid_mask].astype(float)
    y = forward_returns[valid_mask].astype(float)
    n = len(x)

    if n < 30:
        return {
            "valid_samples": n,
            "rank_ic": 0.0,
            "pearson_ic": 0.0,
            "t_stat": 0.0,
            "is_statistically_significant": False,
            "quantile_returns_mean": {},
            "monotonic_spread": 0.0
        }

    # Pearson IC
    cov = np.cov(x, y)[0, 1]
    std_x, std_y = np.std(x, ddof=1), np.std(y, ddof=1)
    pearson_ic = float(cov / (std_x * std_y)) if (std_x > 1e-12 and std_y > 1e-12) else 0.0

    # Spearman Rank IC
    rx = x.rank().values
    ry = y.rank().values
    cov_r = np.cov(rx, ry)[0, 1]
    std_rx, std_ry = np.std(rx, ddof=1), np.std(ry, ddof=1)
    rank_ic = float(cov_r / (std_rx * std_ry)) if (std_rx > 1e-12 and std_ry > 1e-12) else 0.0

    # t-statistic for Rank IC
    denom = np.sqrt(max(1e-12, (1.0 - rank_ic ** 2) / (n - 2)))
    t_stat = float(rank_ic / denom) if denom > 1e-12 else 0.0

    # Permutation Test (White's Reality Check proxy for noise falsification)
    # Shuffles forward returns to test if rank_ic is achievable on pure noise
    num_permutations = 200
    noise_count = 0
    abs_rank_ic = abs(rank_ic)
    if n >= 50 and abs_rank_ic >= 0.01:
        rng = np.random.default_rng(seed=42)
        ry_shuffled = ry.copy()
        for _ in range(num_permutations):
            rng.shuffle(ry_shuffled)
            cov_perm = np.cov(rx, ry_shuffled)[0, 1]
            perm_ic = abs(cov_perm / (std_rx * std_ry)) if (std_rx > 1e-12 and std_ry > 1e-12) else 0.0
            if perm_ic >= abs_rank_ic:
                noise_count += 1
        noise_p_val = noise_count / num_permutations
    else:
        noise_p_val = 1.0

    is_sig = abs(t_stat) >= 2.0 and abs(rank_ic) >= 0.02 and noise_p_val <= 0.05

    # Quantile Monotonicity
    q_means = {}
    monotonic_spread = 0.0
    try:
        quantiles = pd.qcut(x, q=num_quantiles, labels=False, duplicates="drop")
        df_q = pd.DataFrame({"q": quantiles, "y": y})
        grouped = df_q.groupby("q")["y"].mean()
        for q_idx, m_val in grouped.items():
            q_means[int(q_idx)] = float(m_val)
        if len(grouped) >= 2:
            monotonic_spread = float(grouped.iloc[-1] - grouped.iloc[0])
    except Exception:
        pass

    return {
        "valid_samples": n,
        "rank_ic": round(rank_ic, 4),
        "pearson_ic": round(pearson_ic, 4),
        "t_stat": round(t_stat, 2),
        "noise_p_val": round(noise_p_val, 3),
        "is_statistically_significant": is_sig,
        "quantile_returns_mean": q_means,
        "monotonic_spread": round(monotonic_spread, 6)
    }


def audit_edge_friction_clearance(
    symbol: str,
    entry_price: float,
    gross_expected_return_pct: float,
    holding_bars: int = 12
) -> Dict[str, Any]:
    """
    Tests whether the gross expected move of a statistical edge exceeds the real-world
    broker roundtrip friction floor by an institutional safety margin (>= 3x to 5x).
    """
    rt_cost_dollar = get_roundtrip_friction(symbol, entry_price)
    rt_cost_pct = (rt_cost_dollar / entry_price) if entry_price > 0 else 0.0
    gross_abs = abs(gross_expected_return_pct)
    
    hurdle_ratio = (gross_abs / rt_cost_pct) if rt_cost_pct > 0 else 999.0
    passes_hurdle = hurdle_ratio >= 3.0  # Must clear roundtrip friction by at least 300%

    return {
        "symbol": symbol,
        "entry_price": entry_price,
        "roundtrip_cost_dollar": round(rt_cost_dollar, 4),
        "roundtrip_cost_pct": round(rt_cost_pct, 6),
        "gross_expected_return_pct": round(gross_abs, 6),
        "friction_hurdle_multiple": round(hurdle_ratio, 2),
        "clears_friction_hurdle": passes_hurdle
    }


def scan_candidate_series(
    df: pd.DataFrame,
    features: Dict[str, pd.Series],
    symbol: str,
    horizons: List[int] = [1, 3, 5, 12, 24]
) -> Dict[str, Any]:
    """
    Scans a dictionary of arbitrary candidate feature series against forward returns.
    Returns ranked summary of genuine statistical edges vs friction-eaten noise.
    """
    fwd_df = compute_forward_returns(df, horizons=horizons)
    mean_price = float(df["close"].mean()) if "close" in df.columns else 100.0

    results = {}
    for feat_name, feat_s in features.items():
        feat_results = {}
        for h in horizons:
            fwd_col = f"fwd_ret_{h}"
            metrics = evaluate_feature_predictive_power(feat_s, fwd_df[fwd_col])
            
            # Audit friction clearance on top decile/spread
            gross_move = abs(metrics["monotonic_spread"]) or abs(metrics["rank_ic"] * float(fwd_df[fwd_col].std()))
            friction_audit = audit_edge_friction_clearance(
                symbol=symbol,
                entry_price=mean_price,
                gross_expected_return_pct=gross_move,
                holding_bars=h
            )
            metrics["friction_audit"] = friction_audit
            metrics["has_tradable_edge"] = metrics["is_statistically_significant"] and friction_audit["clears_friction_hurdle"]
            feat_results[f"horizon_{h}"] = metrics

        results[feat_name] = feat_results

    return results
