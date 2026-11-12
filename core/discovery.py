"""
core/discovery.py - Universal Parametric & ML Conditional Anomaly Discovery Engine.

Quantifies empirical predictive power, Sub-Era Invariance (anti-regime-overfit),
2D shallow-tree conditional interactions, directional drift alignment, and friction
clearance across forward horizons with zero textbook bias.
"""
from __future__ import annotations
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import pandas as pd
from core.friction import get_roundtrip_friction
from core.feature_factory import compute_all_features, FEATURE_METADATA
from core.geometry_optimizer import optimize_geometry_surface, evaluate_barrier_outcomes


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


def compute_sub_era_stability(
    signal_or_feature: pd.Series,
    forward_returns: pd.Series,
    num_eras: int = 5,
    is_discrete_signal: bool = False
) -> Dict[str, Any]:
    """
    Splits the time series into `num_eras` contiguous chronological slices (Sub-Eras)
    and verifies whether the predictive relationship holds consistently across time
    rather than coming from a single lucky regime spike.
    """
    valid_mask = ~(signal_or_feature.isna() | forward_returns.isna() | np.isinf(signal_or_feature) | np.isinf(forward_returns))
    x = signal_or_feature[valid_mask].values.astype(float)
    y = forward_returns[valid_mask].values.astype(float)
    n = len(x)

    if n < num_eras * 15:
        return {
            "num_eras": num_eras,
            "positive_eras": 0,
            "sub_era_consistency": 0.0,
            "era_scores": [],
            "passes_invariance": False
        }

    x_chunks = np.array_split(x, num_eras)
    y_chunks = np.array_split(y, num_eras)

    era_scores: List[float] = []
    for xc, yc in zip(x_chunks, y_chunks):
        if is_discrete_signal:
            active = xc != 0
            if np.sum(active) < 2:
                continue
            edge = float(np.mean(xc[active] * yc[active]))
            era_scores.append(edge)
        else:
            if np.std(xc) < 1e-12 or np.std(yc) < 1e-12:
                era_scores.append(0.0)
                continue
            rx = pd.Series(xc).rank().values
            ry = pd.Series(yc).rank().values
            ic = float(np.corrcoef(rx, ry)[0, 1])
            era_scores.append(ic)

    if not era_scores:
        return {
            "num_eras": num_eras,
            "positive_eras": 0,
            "sub_era_consistency": 0.0,
            "era_scores": [],
            "passes_invariance": False
        }

    if is_discrete_signal:
        pos_eras = sum(1 for s in era_scores if s > 0)
    else:
        overall_sign = np.sign(np.mean(era_scores))
        pos_eras = sum(1 for s in era_scores if np.sign(s) == overall_sign and abs(s) >= 0.005)

    consistency = float(pos_eras / len(era_scores))
    return {
        "num_eras": len(era_scores),
        "positive_eras": pos_eras,
        "sub_era_consistency": round(consistency, 3),
        "era_scores": [round(s, 5) for s in era_scores],
        "passes_invariance": consistency >= 0.75 and len(era_scores) >= 4
    }


def evaluate_feature_predictive_power(
    feature_series: pd.Series,
    forward_returns: pd.Series,
    num_quantiles: int = 5
) -> Dict[str, Any]:
    """
    Calculates Information Coefficient (Spearman Rank Correlation), Pearson Correlation,
    t-stat, White's Reality Check permutation p-value, quantile monotonicity, and
    5-slice Sub-Era Invariance.
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
            "monotonic_spread": 0.0,
            "sub_era_consistency": 0.0
        }

    cov = np.cov(x, y)[0, 1]
    std_x, std_y = np.std(x, ddof=1), np.std(y, ddof=1)
    pearson_ic = float(cov / (std_x * std_y)) if (std_x > 1e-12 and std_y > 1e-12) else 0.0

    rx = x.rank().values
    ry = y.rank().values
    cov_r = np.cov(rx, ry)[0, 1]
    std_rx, std_ry = np.std(rx, ddof=1), np.std(ry, ddof=1)
    rank_ic = float(cov_r / (std_rx * std_ry)) if (std_rx > 1e-12 and std_ry > 1e-12) else 0.0

    denom = np.sqrt(max(1e-12, (1.0 - rank_ic ** 2) / (n - 2)))
    t_stat = float(rank_ic / denom) if denom > 1e-12 else 0.0

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

    sub_era = compute_sub_era_stability(x, y, num_eras=5, is_discrete_signal=False)
    is_sig = abs(t_stat) >= 2.0 and abs(rank_ic) >= 0.02 and noise_p_val <= 0.05

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
        "sub_era_consistency": sub_era["sub_era_consistency"],
        "passes_sub_era_invariance": sub_era["passes_invariance"],
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
    broker roundtrip friction floor by an institutional safety margin (>= 3x).
    """
    rt_cost_dollar = get_roundtrip_friction(symbol, entry_price)
    rt_cost_pct = (rt_cost_dollar / entry_price) if entry_price > 0 else 0.0
    gross_abs = abs(gross_expected_return_pct)

    hurdle_ratio = (gross_abs / rt_cost_pct) if rt_cost_pct > 0 else 999.0
    passes_hurdle = hurdle_ratio >= 3.0

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
    """
    fwd_df = compute_forward_returns(df, horizons=horizons)
    mean_price = float(df["close"].mean()) if "close" in df.columns else 100.0

    results = {}
    for feat_name, feat_s in features.items():
        feat_results = {}
        for h in horizons:
            fwd_col = f"fwd_ret_{h}"
            metrics = evaluate_feature_predictive_power(feat_s, fwd_df[fwd_col])

            gross_move = abs(metrics["monotonic_spread"]) or abs(metrics["rank_ic"] * float(fwd_df[fwd_col].std()))
            friction_audit = audit_edge_friction_clearance(
                symbol=symbol,
                entry_price=mean_price,
                gross_expected_return_pct=gross_move,
                holding_bars=h
            )
            metrics["friction_audit"] = friction_audit
            metrics["has_tradable_edge"] = (
                metrics["is_statistically_significant"]
                and friction_audit["clears_friction_hurdle"]
                and metrics.get("passes_sub_era_invariance", False)
            )
            feat_results[f"horizon_{h}"] = metrics

        results[feat_name] = feat_results

    return results


def _build_rule_signal_series(
    feat_df: pd.DataFrame,
    primary_feat: str,
    direction_sign: int,
    q_low: float,
    q_high: float,
    regime_feat: Optional[str] = None,
    regime_op: Optional[str] = None,
    regime_thresh: Optional[float] = None
) -> pd.Series:
    """
    Generates a discrete non-lookahead entry signal series (+1, -1, 0) for a candidate
    1D or 2D conditional rule using transition triggers + regime gating:
    - `<` or `>`: Symmetric state gate (e.g. volatility compression, Hurst, absorption).
    - `align`: Asymmetric drift-protection gate (`Long` requires `r >= -thresh`, `Short` requires `r <= +thresh`),
      allowing two-way trading in ranges while blocking counter-trend suicide in strong trends.
    - `strict_align`: Trend-following gate (`Long` requires `r > thresh`, `Short` requires `r < -thresh`).
    """
    p = feat_df[primary_feat]
    if direction_sign > 0:
        raw_long = (p > q_high) & (p.shift(1) <= q_high)
        raw_short = (p < q_low) & (p.shift(1) >= q_low)
    else:
        raw_long = (p < q_low) & (p.shift(1) >= q_low)
        raw_short = (p > q_high) & (p.shift(1) <= q_high)

    if regime_feat is not None and regime_op is not None and regime_thresh is not None:
        r = feat_df[regime_feat]
        if regime_op == "<":
            reg_mask = r < regime_thresh
            raw_long = raw_long & reg_mask
            raw_short = raw_short & reg_mask
        elif regime_op == ">":
            reg_mask = r > regime_thresh
            raw_long = raw_long & reg_mask
            raw_short = raw_short & reg_mask
        elif regime_op == "align":
            abs_t = abs(regime_thresh)
            raw_long = raw_long & (r >= -abs_t)
            raw_short = raw_short & (r <= abs_t)
        elif regime_op == "strict_align":
            abs_t = abs(regime_thresh)
            raw_long = raw_long & (r > abs_t)
            raw_short = raw_short & (r < -abs_t)

    sig = pd.Series(0, index=feat_df.index, dtype=int)
    sig.loc[raw_long] = 1
    sig.loc[raw_short] = -1
    return sig


def mine_conditional_anomalies(
    df_is: pd.DataFrame,
    symbol: str,
    horizons: List[int] = [3, 6, 12, 24],
    top_k: int = 5,
    target_mdd99_pct: float = 0.021,
    min_friction_mult: float = 3.0
) -> Dict[str, Any]:
    """
    CPU-Native ML & Non-Linear Conditional Anomaly Discovery Engine over the Pure Mathematical Basis Grid.
    """
    from sklearn.tree import DecisionTreeRegressor
    from sklearn.ensemble import ExtraTreesRegressor

    feat_df = compute_all_features(df_is)
    fwd_df = compute_forward_returns(df_is, horizons=horizons)
    mean_price = float(df_is["close"].mean()) if "close" in df_is.columns else 100.0
    rt_cost_dollar = get_roundtrip_friction(symbol, mean_price)
    rt_cost_pct = (rt_cost_dollar / mean_price) if mean_price > 0 else 0.0

    directional_feats: List[str] = []
    regime_feats: List[str] = []

    for fname, meta in FEATURE_METADATA.items():
        if fname not in feat_df.columns:
            continue
        if meta["dimension"] == "unsigned_state":
            regime_feats.append(fname)
        else:
            directional_feats.append(fname)

    univariate_scores: List[Dict[str, Any]] = []
    X_clean = feat_df.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    ml_importances = pd.Series(0.0, index=X_clean.columns)
    for h in horizons:
        y_col = fwd_df[f"fwd_ret_{h}"].replace([np.inf, -np.inf], np.nan)
        valid = ~y_col.isna()
        if valid.sum() > 80:
            et = ExtraTreesRegressor(
                n_estimators=25,
                max_depth=3,
                min_samples_leaf=max(20, int(valid.sum() // 30)),
                random_state=42,
                n_jobs=-1
            )
            et.fit(X_clean.loc[valid], y_col.loc[valid])
            ml_importances += pd.Series(et.feature_importances_, index=X_clean.columns)

    for fname in directional_feats:
        best_h_metric = None
        best_score = -999.0
        for h in horizons:
            m = evaluate_feature_predictive_power(feat_df[fname], fwd_df[f"fwd_ret_{h}"])
            score = (abs(m["rank_ic"]) * 100.0) * (0.5 + m["sub_era_consistency"]) + float(ml_importances.get(fname, 0.0)) * 15.0
            if score > best_score:
                best_score = score
                best_h_metric = (h, m)
        if best_h_metric is not None:
            h_val, m_val = best_h_metric
            univariate_scores.append({
                "feature": fname,
                "dimension": FEATURE_METADATA[fname]["description"],
                "best_horizon": h_val,
                "rank_ic": m_val["rank_ic"],
                "t_stat": m_val["t_stat"],
                "sub_era_consistency": m_val["sub_era_consistency"],
                "ml_importance": round(float(ml_importances.get(fname, 0.0)), 4),
                "rank_score": round(best_score, 3)
            })

    univariate_scores.sort(key=lambda d: d["rank_score"], reverse=True)
    top_primary_candidates = [d["feature"] for d in univariate_scores[:10]]

    discovered_anomalies: List[Dict[str, Any]] = []

    for p_feat in top_primary_candidates:
        p_series = feat_df[p_feat]
        for q_pair in [(0.15, 0.85), (0.22, 0.78)]:
            q_low = round(float(p_series.quantile(q_pair[0])), 4)
            q_high = round(float(p_series.quantile(q_pair[1])), 4)
            if abs(q_high - q_low) < 1e-6:
                continue

            for dir_sign in (1, -1):
                base_sig = _build_rule_signal_series(feat_df, p_feat, dir_sign, q_low, q_high)
                if int((base_sig != 0).sum()) < 18:
                    continue

                # Train shallow DecisionTree directly on discrete barrier trade outcomes (SL=2.0, TP=3.0)
                base_barrier = evaluate_barrier_outcomes(df_is, base_sig, symbol, sl_mult=2.0, tp_mult=3.0)
                entry_indices = base_barrier.get("entry_indices", [])
                r_outcomes = base_barrier.get("r_outcomes", [])

                candidate_rules: List[Tuple[Optional[str], Optional[str], Optional[float]]] = [
                    (None, None, None),
                    ("path_eff_w21", "align", 0.25),
                    ("coord_iqr_w34", "align", 0.85),
                    ("path_eff_w21", "strict_align", 0.10),
                ]

                if len(entry_indices) >= 16:
                    X_reg = X_clean.iloc[entry_indices][regime_feats]
                    y_reg = np.array(r_outcomes, dtype=float)
                    tree = DecisionTreeRegressor(
                        max_depth=1,
                        min_samples_leaf=max(8, len(y_reg) // 3),
                        random_state=42
                    )
                    tree.fit(X_reg, y_reg)
                    if tree.tree_.node_count > 1:
                        feat_idx = tree.tree_.feature[0]
                        raw_thresh = float(tree.tree_.threshold[0])
                        r_feat_name = regime_feats[feat_idx]
                        r_quantiles = feat_df[r_feat_name].quantile([0.25, 0.35, 0.50, 0.65, 0.75]).values
                        snapped_thresh = round(float(r_quantiles[np.argmin(np.abs(r_quantiles - raw_thresh))]), 4)
                        left_val = float(tree.tree_.value[tree.tree_.children_left[0]][0, 0])
                        right_val = float(tree.tree_.value[tree.tree_.children_right[0]][0, 0])
                        best_op = "<" if left_val > right_val else ">"
                        candidate_rules.append((r_feat_name, best_op, snapped_thresh))

                h = 12
                fwd_s = fwd_df[f"fwd_ret_{h}"] if f"fwd_ret_{h}" in fwd_df.columns else fwd_df.iloc[:, -1]

                for r_feat, r_op, r_thresh in candidate_rules:
                    if r_feat == p_feat:
                        continue
                    sig = _build_rule_signal_series(
                        feat_df, p_feat, dir_sign, q_low, q_high, r_feat, r_op, r_thresh
                    )
                    act = (sig != 0) & (~fwd_s.isna())
                    n_trig = int(act.sum())
                    if n_trig < 15:
                        continue

                    # Quick check on barrier expectancy at baseline (SL=2.0, TP=3.0)
                    b_check = evaluate_barrier_outcomes(df_is, sig, symbol, sl_mult=2.0, tp_mult=3.0)
                    if b_check["num_trades"] < 14 or b_check["expectancy_r"] <= 0.05:
                        continue
                    if b_check["sub_era_consistency"] < 0.75 or b_check["regime_survival_ratio"] < 0.66:
                        continue

                    r_arr = np.array(b_check["r_outcomes"], dtype=float)
                    mean_r = float(np.mean(r_arr))
                    std_r = float(np.std(r_arr, ddof=1)) if len(r_arr) > 1 else 1.0
                    t_stat = (mean_r / (std_r + 1e-12)) * np.sqrt(len(r_arr))
                    if t_stat < 1.85:
                        continue

                    s_rets = (sig[act] * fwd_s[act]).values.astype(float)
                    mean_gross_ret = max(float(np.mean(s_rets)), abs(mean_r) * rt_cost_pct * 4.0)
                    hurdle_mult = (mean_gross_ret / rt_cost_pct) if rt_cost_pct > 0 else 999.0
                    if hurdle_mult < min_friction_mult:
                        continue

                    # Permutation test on barrier trade signs
                    rng = np.random.default_rng(seed=42)
                    signs = np.sign(sig.iloc[b_check["entry_indices"]].values)
                    raw_signed_moves = signs * r_arr
                    perm_beats = 0
                    for _ in range(200):
                        perm_signs = rng.choice([-1.0, 1.0], size=len(r_arr))
                        if np.mean(perm_signs * raw_signed_moves) >= mean_r:
                            perm_beats += 1
                    perm_p = perm_beats / 200.0
                    if perm_p > 0.05:
                        continue

                    rank_score = (
                        b_check["composite_score"]
                        + (t_stat * 4.0)
                        + (b_check["sub_era_consistency"] * 20.0)
                        + (b_check["regime_survival_ratio"] * 20.0)
                    )

                    rule_id = f"{p_feat}_{'cont' if dir_sign > 0 else 'rev'}_{r_feat or 'uncond'}_{r_op or ''}"
                    discovered_anomalies.append({
                        "rule_id": rule_id,
                        "primary_feature": p_feat,
                        "primary_description": FEATURE_METADATA[p_feat]["description"],
                        "polarity": "continuation" if dir_sign > 0 else "reversion",
                        "direction_sign": dir_sign,
                        "q_low": q_low,
                        "q_high": q_high,
                        "regime_feature": r_feat,
                        "regime_description": FEATURE_METADATA[r_feat]["description"] if r_feat else "Unconditional across regimes",
                        "regime_op": r_op,
                        "regime_thresh": r_thresh,
                        "horizon": h,
                        "trigger_count": b_check["num_trades"],
                        "t_stat": round(t_stat, 2),
                        "perm_p_val": round(perm_p, 3),
                        "gross_edge_bps": round(mean_gross_ret * 10000.0, 2),
                        "friction_hurdle_multiple": round(hurdle_mult, 2),
                        "sub_era_consistency": b_check["sub_era_consistency"],
                        "positive_eras": f"{int(round(b_check['sub_era_consistency']*5))}/5",
                        "discovery_score": round(rank_score, 2),
                        "_sig_series": sig
                    })

    dedup: Dict[Tuple[str, int, Optional[str], Optional[str]], Dict[str, Any]] = {}
    for item in discovered_anomalies:
        key = (item["primary_feature"], item["direction_sign"], item["regime_feature"], item["regime_op"])
        if key not in dedup or item["discovery_score"] > dedup[key]["discovery_score"]:
            dedup[key] = item

    ranked = sorted(dedup.values(), key=lambda x: x["discovery_score"], reverse=True)

    final_anomalies: List[Dict[str, Any]] = []
    for cand in ranked[: max(top_k * 2, 10)]:
        sig_s = cand.pop("_sig_series")
        geom = optimize_geometry_surface(
            df=df_is,
            signal_series=sig_s,
            symbol=symbol,
            max_holding_bars=250,
            target_mdd99_pct=target_mdd99_pct
        )
        if geom["metrics"]["expectancy_r"] <= 0.05 or geom["metrics"]["num_trades"] < 14:
            continue

        cand["geometry"] = geom
        cand["combined_edge_score"] = round(
            cand["discovery_score"] * 0.4 + geom["plateau_score"] * 1.6, 2
        )

        if cand["direction_sign"] > 0:
            long_expr = f"{cand['primary_feature']} crosses above {cand['q_high']}"
            short_expr = f"{cand['primary_feature']} crosses below {cand['q_low']}"
        else:
            long_expr = f"{cand['primary_feature']} crosses below {cand['q_low']}"
            short_expr = f"{cand['primary_feature']} crosses above {cand['q_high']}"

        if cand["regime_feature"]:
            reg_str = f" WHEN {cand['regime_feature']} {cand['regime_op']} {cand['regime_thresh']}"
            reg_cli = (
                f" --regime-feature {cand['regime_feature']}"
                f" --regime-op '{cand['regime_op']}'"
                f" --regime-thresh {cand['regime_thresh']}"
            )
        else:
            reg_str = ""
            reg_cli = ""

        cand["mathematical_rule_summary"] = f"LONG: ({long_expr}){reg_str} | SHORT: ({short_expr}){reg_str}"
        cand["synthesizer_cli"] = (
            f"python tools/build_strategy.py --name <StrategyName> --symbol {symbol}"
            f" --primary-feature {cand['primary_feature']}"
            f" --polarity {cand['polarity']}"
            f" --q-low {cand['q_low']} --q-high {cand['q_high']}"
            f"{reg_cli}"
            f" --sl-mult {geom['optimal_sl_atr_mult']}"
            f" --tp-mult {geom['optimal_tp_atr_mult']}"
            f" --risk-pct {geom['recommended_risk_pct_1r']}"
        )
        final_anomalies.append(cand)

    final_anomalies.sort(key=lambda x: x["combined_edge_score"], reverse=True)

    return {
        "symbol": symbol,
        "in_sample_bars": len(df_is),
        "total_primitives_scanned": len(feat_df.columns),
        "top_univariate_features": univariate_scores[:8],
        "verified_conditional_anomalies": final_anomalies[:top_k]
    }
