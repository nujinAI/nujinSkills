"""
core/hypothesis_validator.py - Strictly In-Sample Market Profiling & Hypothesis Falsification.

Enables unrestricted, creative strategy engineering (indicators, structural zones,
price/volume microstructure, MTF/cross-asset context, or pure math) while enforcing
empirical rigor BEFORE touching the locked Blind Out-of-Sample window:

1. Market Microstructure Profiling (66.7% In-Sample only):
   Volatility, friction-to-ATR feasibility, autocorrelation / variance-ratio persistence,
   canonical regime mix, and diurnal activity peaks.
2. Automated Causality / Zero-Lookahead Proof (Prefix-Invariance Test):
   Verifies generate_signals(df[:t]) matches generate_signals(df) at bar t-1.
3. In-Sample Structural Simulation & 4-Layer Diagnostic Telemetry:
   - Pessimistic Intrabar Resolution using the strategy's actual stop_loss & target
   - 5-Slice Chronological Sub-Era Invariance & 200-Shuffle Permutation Noise Test
   - Actual Friction Floor compliance (roundtrip cost <= 10% of stop distance)
   - Context (Bull/Bear/Range), Location/Geometry (MAE/MFE & winner giveback),
     and Confirmation (1-2 bar immediate stop-out rate) diagnostics
   - Optional Anti-Collinearity check when a strategy exposes diagnostic features
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from core.friction import get_roundtrip_friction


def _ensure_utc_index(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if not isinstance(d.index, pd.DatetimeIndex):
        if "timestamp" in d.columns:
            ts = pd.to_numeric(d["timestamp"], errors="coerce")
            unit = "ms" if ts.dropna().median() > 1e11 else "s"
            d.index = pd.to_datetime(ts, unit=unit, utc=True)
        elif "time" in d.columns:
            ts = pd.to_numeric(d["time"], errors="coerce")
            unit = "ms" if ts.dropna().median() > 1e11 else "s"
            d.index = pd.to_datetime(ts, unit=unit, utc=True)
        else:
            d.index = pd.to_datetime(d.index, utc=True)
    elif d.index.tz is None:
        d.index = d.index.tz_localize("UTC")
    else:
        d.index = d.index.tz_convert("UTC")
    return d


def _compute_atr14(df: pd.DataFrame) -> pd.Series:
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    c = df["close"].astype(float)
    pc = c.shift(1).bfill()
    tr = np.maximum(h - l, np.maximum((h - pc).abs(), (l - pc).abs()))
    return tr.rolling(14, min_periods=3).mean().bfill()


def _canonical_regime_labels(df: pd.DataFrame, window: int = 50, band_pct: float = 0.002) -> np.ndarray:
    """Matches core/regimes.py (+1 bull, -1 bear, 0 ranging)."""
    c = df["close"].astype(float)
    sma = c.rolling(window, min_periods=10).mean().bfill()
    labels = np.zeros(len(c), dtype=int)
    labels[c > sma * (1.0 + band_pct)] = 1
    labels[c < sma * (1.0 - band_pct)] = -1
    return labels


def profile_market_microstructure(
    df_is: pd.DataFrame,
    symbol: str,
    timeframe: str = "15m",
) -> Dict[str, Any]:
    """
    Produces a compact empirical market research profile strictly from the
    In-Sample slice so the AI can choose the best approach/style/timeframe autonomously.
    """
    d = _ensure_utc_index(df_is)
    n = len(d)
    if n < 30:
        return {"error": f"Insufficient In-Sample bars ({n}) for profiling."}

    close = d["close"].astype(float)
    high = d["high"].astype(float)
    low = d["low"].astype(float)
    atr14 = _compute_atr14(d)
    eps = 1e-12

    mean_price = float(close.mean())
    mean_atr = float(atr14.mean())
    atr_pct = (mean_atr / max(mean_price, eps)) * 100.0
    rt_cost = get_roundtrip_friction(symbol, mean_price)
    friction_pct_of_atr = (rt_cost / max(mean_atr, eps)) * 100.0

    log_ret = np.log((close + eps) / (close.shift(1).bfill() + eps)).dropna()
    lag1_ac = float(log_ret.autocorr(lag=1)) if len(log_ret) > 10 else 0.0
    if np.isnan(lag1_ac):
        lag1_ac = 0.0

    ret_5 = np.log((close + eps) / (close.shift(5).bfill() + eps)).dropna()
    var_1 = float(log_ret.var(ddof=1)) if len(log_ret) > 10 else eps
    var_5 = float(ret_5.var(ddof=1)) if len(ret_5) > 10 else var_1 * 5.0
    var_ratio_5 = float(var_5 / max(5.0 * var_1, eps))

    path_20 = close.diff().abs().rolling(20, min_periods=10).sum()
    eff_20 = ((close - close.shift(20)).abs() / (path_20 + eps)).dropna()
    median_eff_20 = float(eff_20.median()) if len(eff_20) > 0 else 0.0

    bar_range = (high - low).clip(lower=0.0)
    vol_cv = float(bar_range.std() / max(bar_range.mean(), eps))

    # Neutral empirical characterization (never prescribes a strategy)
    if var_ratio_5 >= 1.08 or (lag1_ac >= 0.03 and median_eff_20 >= 0.28):
        behavior = "persistent_trending_bias"
    elif var_ratio_5 <= 0.92 or lag1_ac <= -0.03:
        behavior = "mean_reverting_chop_bias"
    else:
        behavior = "mixed_regime_balanced"

    reg = _canonical_regime_labels(d)
    bull_pct = round(float(np.mean(reg == 1)) * 100.0, 1)
    bear_pct = round(float(np.mean(reg == -1)) * 100.0, 1)
    range_pct = round(float(np.mean(reg == 0)) * 100.0, 1)

    # Diurnal volatility profile (UTC hours)
    top_utc_hours: List[int] = []
    quiet_utc_hours: List[int] = []
    try:
        hours = d.index.hour
        if len(set(hours)) >= 6:
            hr_range = bar_range.groupby(hours).median().sort_values(ascending=False)
            top_utc_hours = [int(h) for h in hr_range.index[:4]]
            quiet_utc_hours = [int(h) for h in hr_range.index[-4:]]
    except Exception:
        pass

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "in_sample_bars": n,
        "date_start": str(d.index[0]),
        "date_end": str(d.index[-1]),
        "mean_price": round(mean_price, 4),
        "mean_atr14": round(mean_atr, 5),
        "atr_pct_of_price": round(atr_pct, 4),
        "roundtrip_friction": round(rt_cost, 5),
        "friction_pct_of_1atr": round(friction_pct_of_atr, 2),
        "min_sl_atr_for_10pct_floor": round(max(0.25, friction_pct_of_atr / 10.0), 2),
        "lag1_autocorr": round(lag1_ac, 4),
        "variance_ratio_5": round(var_ratio_5, 3),
        "median_abs_efficiency_20": round(median_eff_20, 3),
        "range_volatility_cv": round(vol_cv, 3),
        "behavioral_signature": behavior,
        "regime_mix_pct": {"bull": bull_pct, "bear": bear_pct, "ranging": range_pct},
        "peak_utc_hours": top_utc_hours,
        "quiet_utc_hours": quiet_utc_hours,
    }


def check_causality_prefix_invariance(
    strategy_obj: Any,
    df_is: pd.DataFrame,
    n_probes: int = 8,
    rtol: float = 1e-4,
    atol: float = 1e-6,
) -> Dict[str, Any]:
    """
    Automated Lookahead / Causality Detector.
    Verifies that generate_signals(df_is[:t+1]) produces identical signal, stop_loss,
    and target at bar t as generate_signals(df_is).
    """
    n = len(df_is)
    if n < 120:
        return {
            "passed": False,
            "probes_tested": 0,
            "mismatches": 0,
            "detail": f"Dataset too short ({n} bars) for prefix-invariance causality test.",
        }

    full_sig = strategy_obj.generate_signals(df_is)
    for col in ("entry_signal", "stop_loss", "target"):
        if col not in full_sig.columns:
            return {
                "passed": False,
                "probes_tested": 0,
                "mismatches": 1,
                "detail": f"Missing required signal column: '{col}'",
            }

    min_probe = max(100, int(n * 0.45))
    max_probe = n - 2
    if min_probe >= max_probe:
        min_probe = max(60, n // 2)

    # Prioritize active signal bars + evenly spaced neutral bars
    sig_vals = full_sig["entry_signal"].fillna(0).values
    active_idx = [i for i in range(min_probe, max_probe + 1) if sig_vals[i] != 0]
    probe_indices: List[int] = []
    if active_idx:
        step = max(1, len(active_idx) // max(1, n_probes // 2))
        probe_indices.extend(active_idx[::step][: max(1, n_probes // 2)])

    spaced = np.linspace(min_probe, max_probe, num=n_probes, dtype=int).tolist()
    for idx in spaced:
        if len(probe_indices) >= n_probes:
            break
        if idx not in probe_indices:
            probe_indices.append(int(idx))
    probe_indices = sorted(set(probe_indices))[:n_probes]

    mismatches = 0
    first_mismatch: Optional[Dict[str, Any]] = None

    for idx in probe_indices:
        sub_df = df_is.iloc[: idx + 1].copy()
        sub_sig = strategy_obj.generate_signals(sub_df)

        f_s = int(full_sig["entry_signal"].iloc[idx]) if not pd.isna(full_sig["entry_signal"].iloc[idx]) else 0
        p_s = int(sub_sig["entry_signal"].iloc[-1]) if not pd.isna(sub_sig["entry_signal"].iloc[-1]) else 0

        f_sl = float(full_sig["stop_loss"].iloc[idx]) if not pd.isna(full_sig["stop_loss"].iloc[idx]) else 0.0
        p_sl = float(sub_sig["stop_loss"].iloc[-1]) if not pd.isna(sub_sig["stop_loss"].iloc[-1]) else 0.0

        f_tp = float(full_sig["target"].iloc[idx]) if not pd.isna(full_sig["target"].iloc[idx]) else 0.0
        p_tp = float(sub_sig["target"].iloc[-1]) if not pd.isna(sub_sig["target"].iloc[-1]) else 0.0

        sig_diff = f_s != p_s
        sl_diff = (f_s != 0 or p_s != 0) and not np.isclose(f_sl, p_sl, rtol=rtol, atol=atol)
        tp_diff = (f_s != 0 or p_s != 0) and not np.isclose(f_tp, p_tp, rtol=rtol, atol=atol)

        if sig_diff or sl_diff or tp_diff:
            mismatches += 1
            if first_mismatch is None:
                first_mismatch = {
                    "bar_index": idx,
                    "full": {"signal": f_s, "sl": round(f_sl, 5), "tp": round(f_tp, 5)},
                    "prefix": {"signal": p_s, "sl": round(p_sl, 5), "tp": round(p_tp, 5)},
                }

    passed = mismatches == 0
    detail = (
        f"Prefix-invariant across {len(probe_indices)} probes (zero lookahead detected)."
        if passed
        else f"LOOKAHEAD DETECTED: {mismatches}/{len(probe_indices)} probes changed when future bars were removed."
    )
    return {
        "passed": passed,
        "probes_tested": len(probe_indices),
        "mismatches": mismatches,
        "first_mismatch": first_mismatch,
        "detail": detail,
    }


def check_feature_collinearity(
    feat_df: Optional[pd.DataFrame],
    threshold: float = 0.85,
) -> Dict[str, Any]:
    """
    Optional Anti-Collinearity Check (Retail Indicator Stack Detector).
    Checks pairwise |corr| when a strategy exposes diagnostic features.
    """
    if feat_df is None or not isinstance(feat_df, pd.DataFrame) or feat_df.shape[1] < 2:
        return {"checked": False, "collinear_pairs": [], "max_abs_corr": 0.0}

    num_df = feat_df.select_dtypes(include=[np.number]).replace([np.inf, -np.inf], np.nan).dropna()
    if len(num_df) < 30 or num_df.shape[1] < 2:
        return {"checked": False, "collinear_pairs": [], "max_abs_corr": 0.0}

    # Keep only non-constant columns
    valid_cols = [c for c in num_df.columns if num_df[c].std() > 1e-12]
    if len(valid_cols) < 2:
        return {"checked": False, "collinear_pairs": [], "max_abs_corr": 0.0}

    corr = num_df[valid_cols].corr().abs()
    pairs: List[Dict[str, Any]] = []
    max_corr = 0.0
    for i in range(len(valid_cols)):
        for j in range(i + 1, len(valid_cols)):
            val = float(corr.iloc[i, j])
            if np.isnan(val):
                continue
            if val > max_corr:
                max_corr = val
            if val >= threshold:
                pairs.append({"f1": valid_cols[i], "f2": valid_cols[j], "abs_corr": round(val, 3)})

    pairs.sort(key=lambda x: x["abs_corr"], reverse=True)
    return {
        "checked": True,
        "max_abs_corr": round(max_corr, 3),
        "collinear_pairs": pairs[:5],
        "passed": len(pairs) == 0,
    }


def simulate_in_sample_diagnostics(
    df_is: pd.DataFrame,
    signals: pd.DataFrame,
    symbol: str,
    max_holding_bars: int = 250,
) -> Dict[str, Any]:
    """
    Simulates a strategy's actual structural stop_loss & target on the In-Sample
    dataset using Pessimistic Intrabar Resolution + Opposite-Signal Reversal,
    producing Sub-Era Invariance, Permutation p-value, Friction Floor, and
    4-Layer Diagnostic Telemetry (Context / Location / Confirmation / Geometry).
    """
    d = _ensure_utc_index(df_is)
    close = d["close"].astype(float).values
    high = d["high"].astype(float).values
    low = d["low"].astype(float).values
    regimes = _canonical_regime_labels(d)
    n = len(close)

    sig_arr = signals["entry_signal"].fillna(0).astype(int).values
    sl_arr = signals["stop_loss"].fillna(0.0).astype(float).values
    tp_arr = signals["target"].fillna(0.0).astype(float).values

    trades: List[Dict[str, Any]] = []
    invalid_geometry_count = 0
    total_raw_signals = int(np.sum(sig_arr != 0))

    i = 1
    while i < n - 2:
        sig = int(sig_arr[i])
        if sig == 0:
            i += 1
            continue

        entry_p = float(close[i])
        sl_p = float(sl_arr[i])
        tp_p = float(tp_arr[i])

        # Validate structural geometry
        if sig > 0:
            valid_geom = (sl_p > 0.0) and (sl_p < entry_p) and (tp_p > entry_p)
            stop_dist = entry_p - sl_p
            target_dist = tp_p - entry_p
        else:
            valid_geom = (sl_p > entry_p) and (tp_p > 0.0) and (tp_p < entry_p)
            stop_dist = sl_p - entry_p
            target_dist = entry_p - tp_p

        if not valid_geom or stop_dist <= 1e-12:
            invalid_geometry_count += 1
            i += 1
            continue

        rt_cost = get_roundtrip_friction(symbol, entry_p)
        fric_pct_sl = (rt_cost / stop_dist) * 100.0
        fric_r = rt_cost / stop_dist

        exit_bar = min(i + max_holding_bars, n - 1)
        mfe_r = 0.0
        mae_r = 0.0
        outcome_r = 0.0
        exit_reason = "TIME"
        reversed_on_exit = False

        for j in range(i + 1, exit_bar + 1):
            if sig > 0:
                bar_fav = max(0.0, (high[j] - entry_p) / stop_dist)
                bar_adv = max(0.0, (entry_p - low[j]) / stop_dist)
                hit_sl = low[j] <= sl_p
                hit_tp = high[j] >= tp_p
            else:
                bar_fav = max(0.0, (entry_p - low[j]) / stop_dist)
                bar_adv = max(0.0, (high[j] - entry_p) / stop_dist)
                hit_sl = high[j] >= sl_p
                hit_tp = low[j] <= tp_p

            if bar_fav > mfe_r:
                mfe_r = bar_fav
            if bar_adv > mae_r:
                mae_r = bar_adv

            # Pessimistic intrabar resolution: SL wins if both hit on same bar
            if hit_sl:
                outcome_r = -1.0 - fric_r
                exit_bar = j
                exit_reason = "SL"
                break
            if hit_tp:
                outcome_r = (target_dist / stop_dist) - fric_r
                exit_bar = j
                exit_reason = "TP"
                break
            if sig_arr[j] == -sig:
                pnl_pts = (close[j] - entry_p) if sig > 0 else (entry_p - close[j])
                outcome_r = (pnl_pts / stop_dist) - fric_r
                exit_bar = j
                exit_reason = "REV"
                reversed_on_exit = True
                break
        else:
            pnl_pts = (close[exit_bar] - entry_p) if sig > 0 else (entry_p - close[exit_bar])
            outcome_r = (pnl_pts / stop_dist) - fric_r

        trades.append({
            "entry_idx": i,
            "exit_idx": exit_bar,
            "hold_bars": exit_bar - i,
            "direction": sig,
            "regime": int(regimes[i]),
            "r_net": float(outcome_r),
            "rr_planned": float(target_dist / stop_dist),
            "fric_pct_sl": float(fric_pct_sl),
            "mfe_r": float(mfe_r),
            "mae_r": float(mae_r),
            "exit_reason": exit_reason,
        })

        i = exit_bar if reversed_on_exit else (exit_bar + 1)

    num_trades = len(trades)
    if num_trades < 5:
        return {
            "num_trades": num_trades,
            "total_raw_signals": total_raw_signals,
            "invalid_geometry_signals": invalid_geometry_count,
            "sufficient_sample": False,
            "expectancy_r": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "t_stat": 0.0,
            "perm_p_val": 1.0,
            "sub_era_consistency": 0.0,
            "positive_eras": "0/5",
            "median_friction_pct_sl": 100.0,
            "pct_failing_friction_floor": 100.0,
            "layer_diagnostics": {},
        }

    r_arr = np.array([t["r_net"] for t in trades], dtype=float)
    wins = r_arr > 0
    win_rate = float(np.mean(wins))
    exp_r = float(np.mean(r_arr))
    std_r = float(np.std(r_arr, ddof=1)) if num_trades > 1 else 1.0
    t_stat = float((exp_r / max(std_r, 1e-12)) * np.sqrt(num_trades))
    gross_win = float(np.sum(r_arr[r_arr > 0]))
    gross_loss = float(np.abs(np.sum(r_arr[r_arr < 0])))
    pf = round(min(gross_win / max(gross_loss, 1e-9), 99.9), 2) if gross_loss > 1e-9 else (99.9 if gross_win > 0 else 0.0)

    # 5-Slice Chronological Sub-Era Invariance (partitioned across the IS time axis)
    era_edges = np.linspace(0, n, 6, dtype=int)
    era_exps: List[float] = []
    for e_i in range(5):
        lo_b, hi_b = int(era_edges[e_i]), int(era_edges[e_i + 1])
        era_rs = [t["r_net"] for t in trades if lo_b <= t["entry_idx"] < hi_b]
        if len(era_rs) >= 2:
            era_exps.append(float(np.mean(era_rs)))
    pos_eras = sum(1 for v in era_exps if v > 0)
    sub_era_consistency = (pos_eras / len(era_exps)) if era_exps else 0.0

    # 200-Shuffle Timing Permutation Test on forward returns at median holding horizon
    med_hold = max(2, min(48, int(np.median([t["hold_bars"] for t in trades]))))
    entry_indices = np.array([t["entry_idx"] for t in trades], dtype=int)
    entry_dirs = np.array([t["direction"] for t in trades], dtype=float)
    valid_perm = entry_indices + med_hold < n
    perm_p = 1.0
    if int(np.sum(valid_perm)) >= 8:
        e_idx = entry_indices[valid_perm]
        e_dir = entry_dirs[valid_perm]
        fwd_rets = (close[e_idx + med_hold] - close[e_idx]) / np.maximum(close[e_idx], 1e-12)
        obs_edge = float(np.mean(e_dir * fwd_rets))
        rng = np.random.default_rng(42)
        # Compare against 200 random entry-time placements across IS bars
        max_start = n - med_hold - 1
        beats = 0
        all_fwd = (close[med_hold:] - close[:-med_hold]) / np.maximum(close[:-med_hold], 1e-12)
        for _ in range(200):
            rand_pos = rng.integers(0, max(1, max_start), size=len(e_dir))
            if float(np.mean(e_dir * all_fwd[rand_pos])) >= obs_edge:
                beats += 1
        perm_p = beats / 200.0

    # Friction Floor
    frics = np.array([t["fric_pct_sl"] for t in trades], dtype=float)
    med_fric = float(np.median(frics))
    pct_fail_fric = float(np.mean(frics > 10.0)) * 100.0

    # 4-Layer Diagnostic Telemetry
    # 1. Context Health: Bull / Bear / Ranging IS breakdown
    reg_names = {1: "bull", -1: "bear", 0: "ranging"}
    context_breakdown: Dict[str, Dict[str, Any]] = {}
    bleeding_regimes: List[str] = []
    for reg_code, rname in reg_names.items():
        r_sub = [t["r_net"] for t in trades if t["regime"] == reg_code]
        if r_sub:
            sub_exp = float(np.mean(r_sub))
            sub_wr = float(np.mean(np.array(r_sub) > 0))
            context_breakdown[rname] = {
                "trades": len(r_sub),
                "win_rate": round(sub_wr, 3),
                "exp_r": round(sub_exp, 3),
            }
            if len(r_sub) >= 4 and sub_exp < -0.10:
                bleeding_regimes.append(rname)
        else:
            context_breakdown[rname] = {"trades": 0, "win_rate": 0.0, "exp_r": 0.0}

    # 2. Confirmation Health: Immediate 1-2 bar stop-out rate
    fast_stopouts = [t for t in trades if t["exit_reason"] == "SL" and t["hold_bars"] <= 2]
    fast_stopout_rate = float(len(fast_stopouts) / num_trades)

    # 3. Location & Geometry Health: MAE/MFE & winner giveback
    med_mfe = float(np.median([t["mfe_r"] for t in trades]))
    med_mae = float(np.median([t["mae_r"] for t in trades]))
    losers = [t for t in trades if t["r_net"] < 0]
    giveback_losers = [t for t in losers if t["mfe_r"] >= 0.8]
    winner_giveback_rate = float(len(giveback_losers) / len(losers)) if losers else 0.0

    return {
        "num_trades": num_trades,
        "total_raw_signals": total_raw_signals,
        "invalid_geometry_signals": invalid_geometry_count,
        "sufficient_sample": num_trades >= 12,
        "expectancy_r": round(exp_r, 4),
        "win_rate": round(win_rate, 3),
        "profit_factor": pf,
        "avg_planned_rr": round(float(np.mean([t["rr_planned"] for t in trades])), 2),
        "t_stat": round(t_stat, 2),
        "perm_p_val": round(perm_p, 3),
        "sub_era_consistency": round(sub_era_consistency, 3),
        "positive_eras": f"{pos_eras}/{len(era_exps)}",
        "era_expectancies_r": [round(v, 3) for v in era_exps],
        "median_friction_pct_sl": round(med_fric, 2),
        "pct_failing_friction_floor": round(pct_fail_fric, 1),
        "median_hold_bars": med_hold,
        "layer_diagnostics": {
            "context_regimes": context_breakdown,
            "bleeding_regimes": bleeding_regimes,
            "confirmation_fast_stopout_rate": round(fast_stopout_rate, 3),
            "location_median_mfe_r": round(med_mfe, 2),
            "location_median_mae_r": round(med_mae, 2),
            "geometry_winner_giveback_rate": round(winner_giveback_rate, 3),
        },
    }


def validate_strategy_in_sample(
    strategy_obj: Any,
    df_is: pd.DataFrame,
    symbol: str,
) -> Dict[str, Any]:
    """
    Full In-Sample Hypothesis Pre-Validation Gate (Blind OOS strictly untouched).
    """
    causality = check_causality_prefix_invariance(strategy_obj, df_is)
    signals = strategy_obj.generate_signals(df_is)
    sim = simulate_in_sample_diagnostics(df_is, signals, symbol=symbol)

    # Optional anti-collinearity inspection if strategy exposes diagnostic features
    diag_feats: Optional[pd.DataFrame] = None
    if hasattr(strategy_obj, "get_diagnostic_features") and callable(strategy_obj.get_diagnostic_features):
        try:
            diag_feats = strategy_obj.get_diagnostic_features(df_is)
        except Exception:
            diag_feats = None
    elif hasattr(strategy_obj, "last_feature_matrix") and isinstance(strategy_obj.last_feature_matrix, pd.DataFrame):
        diag_feats = strategy_obj.last_feature_matrix
    collinearity = check_feature_collinearity(diag_feats)

    issues: List[str] = []
    if not causality["passed"]:
        issues.append(f"CAUSALITY FAIL: {causality['detail']}")
    if not sim.get("sufficient_sample", False):
        issues.append(f"LOW SAMPLE: Only {sim['num_trades']} In-Sample trades (need >= 12).")
    if sim.get("invalid_geometry_signals", 0) > 0:
        issues.append(f"INVALID GEOMETRY: {sim['invalid_geometry_signals']} signals had missing/inverted SL or TP.")
    if sim.get("expectancy_r", 0.0) <= 0.02:
        issues.append(f"WEAK EXPECTANCY: In-Sample net expectancy {sim['expectancy_r']:+.3f}R (<= +0.02R).")
    if sim.get("sub_era_consistency", 0.0) < 0.60:
        issues.append(f"SUB-ERA FRAGILITY: Only {sim['positive_eras']} positive chronological sub-eras.")
    if sim.get("median_friction_pct_sl", 100.0) > 10.0:
        issues.append(f"FRICTION FLOOR FAIL: Median friction is {sim['median_friction_pct_sl']:.1f}% of SL (> 10%).")
    if collinearity.get("checked") and not collinearity.get("passed", True):
        top_p = collinearity["collinear_pairs"][0]
        issues.append(f"COLLINEAR INDICATORS: {top_p['f1']} vs {top_p['f2']} |corr|={top_p['abs_corr']} (>= 0.85).")

    ld = sim.get("layer_diagnostics", {})
    hints: List[str] = []
    if ld.get("bleeding_regimes"):
        hints.append(f"Context layer: bleeding in {', '.join(ld['bleeding_regimes'])} regime(s).")
    if ld.get("confirmation_fast_stopout_rate", 0.0) >= 0.35:
        hints.append(f"Confirmation layer: {ld['confirmation_fast_stopout_rate']*100:.0f}% trades stop out within <=2 bars (premature entries).")
    if ld.get("geometry_winner_giveback_rate", 0.0) >= 0.35:
        hints.append(f"Geometry/Exit layer: {ld['geometry_winner_giveback_rate']*100:.0f}% of losers first reached >=0.8R MFE (consider tighter target/trail).")

    verdict = "READY_FOR_CYNIC_AUDIT" if len(issues) == 0 else "NEEDS_REFINEMENT"
    return {
        "verdict": verdict,
        "symbol": symbol,
        "in_sample_bars": len(df_is),
        "causality": causality,
        "in_sample_metrics": sim,
        "collinearity": collinearity,
        "issues": issues,
        "layer_hints": hints,
    }
