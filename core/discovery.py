"""
core/discovery.py - Universal Pure Mathematical Anomaly & Sub-Era Invariant Discovery Engine.

Discovers authentic statistical inefficiencies across the 130-coordinate multi-scale basis grid
without hardcoded indicator dogmas, arbitrary pre-screen barriers, or heuristic assumptions.

Guarantees:
1. Pure empirical excursion distributions (MFE/MAE) dictate stop/target geometry.
2. 5-Slice Chronological Sub-Era Invariance ensures edges hold consistently across regimes.
3. Rigorous permutation testing falsifies noise.
4. Venue-accurate broker friction modeling ensures real-world survivability.
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
    horizons: List[int] = [3, 6, 12, 24],
    price_col: str = "close"
) -> pd.DataFrame:
    """Computes percentage forward returns across multiple future bar horizons."""
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
    Splits the series into `num_eras` contiguous chronological slices and verifies
    whether the predictive edge is consistent across time or a lucky regime cluster.
    """
    valid_mask = ~(
        signal_or_feature.isna()
        | forward_returns.isna()
        | np.isinf(signal_or_feature)
        | np.isinf(forward_returns)
    )
    x = signal_or_feature[valid_mask].values.astype(float)
    y = forward_returns[valid_mask].values.astype(float)
    n = len(x)

    if n < num_eras * 10:
        return {
            "num_eras": num_eras,
            "positive_eras": 0,
            "sub_era_consistency": 0.0,
            "era_scores": [],
            "passes_invariance": False,
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
            "passes_invariance": False,
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
        "passes_invariance": consistency >= 0.70 and len(era_scores) >= 3,
    }


def evaluate_feature_predictive_power(
    feature_series: pd.Series,
    forward_returns: pd.Series,
    num_quantiles: int = 5
) -> Dict[str, Any]:
    """Calculates Rank IC, Pearson correlation, t-stat, permutation p-value, and Sub-Era consistency."""
    valid_mask = ~(
        feature_series.isna()
        | forward_returns.isna()
        | np.isinf(feature_series)
        | np.isinf(forward_returns)
    )
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
            "sub_era_consistency": 0.0,
            "passes_sub_era_invariance": False,
        }

    cov = np.cov(x, y)[0, 1]
    std_x, std_y = np.std(x, ddof=1), np.std(y, ddof=1)
    pearson_ic = float(cov / (std_x * std_y)) if (std_x > 1e-12 and std_y > 1e-12) else 0.0

    rx = x.rank().values
    ry = y.rank().values
    cov_r = np.cov(rx, ry)[0, 1]
    std_rx, std_ry = np.std(rx, ddof=1), np.std(ry, ddof=1)
    rank_ic = float(cov_r / (std_rx * std_ry)) if (std_rx > 1e-12 and std_ry > 1e-12) else 0.0

    denom = np.sqrt(max(1e-12, (1.0 - rank_ic**2) / (n - 2)))
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
    is_sig = abs(t_stat) >= 1.95 and abs(rank_ic) >= 0.02 and noise_p_val <= 0.05

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
        "monotonic_spread": round(monotonic_spread, 6),
    }


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
    """Generates non-lookahead discrete entry signals (+1, -1, 0) for a 1D or 2D conditional rule."""
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
    min_friction_mult: float = 2.0
) -> Dict[str, Any]:
    """
    CPU-Native ML & Pure Mathematical Basis Anomaly Discovery Engine.
    Dynamically maps empirical excursion profiles without hardcoded indicators or pre-screen barriers.
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

    # Stage 1: Feature Importance & Predictive Ranking
    ml_importances = pd.Series(0.0, index=X_clean.columns)
    for h in horizons:
        y_col = fwd_df[f"fwd_ret_{h}"].replace([np.inf, -np.inf], np.nan)
        valid = ~y_col.isna()
        if valid.sum() > 60:
            et = ExtraTreesRegressor(
                n_estimators=25,
                max_depth=3,
                min_samples_leaf=max(15, int(valid.sum() // 35)),
                random_state=42,
                n_jobs=-1,
            )
            et.fit(X_clean.loc[valid], y_col.loc[valid])
            ml_importances += pd.Series(et.feature_importances_, index=X_clean.columns)

    for fname in directional_feats:
        best_h_metric = None
        best_score = -999.0
        for h in horizons:
            m = evaluate_feature_predictive_power(feat_df[fname], fwd_df[f"fwd_ret_{h}"])
            score = (
                (abs(m["rank_ic"]) * 100.0) * (0.5 + m["sub_era_consistency"])
                + float(ml_importances.get(fname, 0.0)) * 15.0
            )
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
                "rank_score": round(best_score, 3),
            })

    univariate_scores.sort(key=lambda d: d["rank_score"], reverse=True)
    top_primary_candidates = [d["feature"] for d in univariate_scores[:12]]

    # Stage 2: Mine 2D Conditional Interaction Rules via Decision Trees
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
                active_count = int((base_sig != 0).sum())
                if active_count < 12:
                    continue

                # Train depth-1 DecisionTree dynamically on forward returns to discover the best conditioning regime
                h_target = horizons[len(horizons) // 2]
                fwd_s = fwd_df[f"fwd_ret_{h_target}"]
                act_mask = (base_sig != 0) & (~fwd_s.isna())
                signed_rets = (base_sig[act_mask] * fwd_s[act_mask]).dropna()

                candidate_rules: List[Tuple[Optional[str], Optional[str], Optional[float]]] = [
                    (None, None, None)  # Always evaluate unconditional
                ]

                if len(signed_rets) >= 12:
                    X_reg = X_clean.loc[signed_rets.index, regime_feats]
                    y_reg = signed_rets.values
                    tree = DecisionTreeRegressor(
                        max_depth=1,
                        min_samples_leaf=max(5, len(y_reg) // 4),
                        random_state=42,
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

                for r_feat, r_op, r_thresh in candidate_rules:
                    if r_feat == p_feat:
                        continue
                    sig = _build_rule_signal_series(
                        feat_df, p_feat, dir_sign, q_low, q_high, r_feat, r_op, r_thresh
                    )
                    act = (sig != 0) & (~fwd_s.isna())
                    n_trig = int(act.sum())
                    if n_trig < 12:
                        continue

                    s_rets = (sig[act] * fwd_s[act]).values.astype(float)
                    mean_gross = float(np.mean(s_rets))
                    std_ret = float(np.std(s_rets, ddof=1)) if n_trig > 1 else 1.0
                    t_stat = (mean_gross / (std_ret + 1e-12)) * np.sqrt(n_trig)
                    if t_stat < 1.70:
                        continue

                    # Sub-Era Invariance check across 5 chronological slices
                    era_eval = compute_sub_era_stability(sig, fwd_s, num_eras=5, is_discrete_signal=True)
                    if not era_eval["passes_invariance"]:
                        continue

                    # Expected gross move at top decile excursion vs friction
                    fwd_vol = float(np.std(fwd_s.dropna()))
                    expected_excursion = max(mean_gross * 2.0, fwd_vol * 1.5)
                    hurdle_mult = (expected_excursion / rt_cost_pct) if rt_cost_pct > 0 else 999.0
                    if hurdle_mult < min_friction_mult:
                        continue

                    # Permutation Noise Test across 200 shuffles
                    rng = np.random.default_rng(seed=42)
                    fwd_vals = fwd_s[act].values.copy()
                    sig_vals = sig[act].values
                    perm_beats = 0
                    for _ in range(200):
                        rng.shuffle(fwd_vals)
                        if np.mean(sig_vals * fwd_vals) >= mean_gross:
                            perm_beats += 1
                    perm_p = perm_beats / 200.0
                    if perm_p > 0.05:
                        continue

                    rank_score = (
                        (t_stat * 5.0)
                        + (era_eval["sub_era_consistency"] * 30.0)
                        + (min(hurdle_mult, 10.0) * 1.5)
                        + (3.0 if r_feat is not None else 0.0)
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
                        "horizon": h_target,
                        "trigger_count": n_trig,
                        "t_stat": round(t_stat, 2),
                        "perm_p_val": round(perm_p, 3),
                        "gross_edge_bps": round(mean_gross * 10000.0, 2),
                        "friction_hurdle_multiple": round(hurdle_mult, 2),
                        "sub_era_consistency": era_eval["sub_era_consistency"],
                        "positive_eras": f"{era_eval['positive_eras']}/{era_eval['num_eras']}",
                        "discovery_score": round(rank_score, 2),
                        "_sig_series": sig,
                    })

    # Deduplicate candidates
    dedup: Dict[Tuple[str, int, Optional[str], Optional[str]], Dict[str, Any]] = {}
    for item in discovered_anomalies:
        key = (item["primary_feature"], item["direction_sign"], item["regime_feature"], item["regime_op"])
        if key not in dedup or item["discovery_score"] > dedup[key]["discovery_score"]:
            dedup[key] = item

    ranked = sorted(dedup.values(), key=lambda x: x["discovery_score"], reverse=True)

    # Stage 3: Dynamic 2D MFE/MAE Plateau Optimization on Survivors
    final_anomalies: List[Dict[str, Any]] = []
    for cand in ranked[: max(top_k * 3, 12)]:
        sig_s = cand.pop("_sig_series")
        geom = optimize_geometry_surface(
            df=df_is,
            signal_series=sig_s,
            symbol=symbol,
            max_holding_bars=250,
            target_mdd99_pct=target_mdd99_pct,
        )
        if geom["metrics"]["expectancy_r"] <= 0.02 or geom["metrics"]["num_trades"] < 10:
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
        "verified_conditional_anomalies": final_anomalies[:top_k],
    }
