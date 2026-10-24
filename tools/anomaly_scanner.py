#!/usr/bin/env python3
"""
Anomaly Scanner: Model-Free Statistical Profiler, Library-Wide Feature IC Engine & Interaction Miner
Part of NujinSkills Alpha Mining System

Instead of testing a fixed menu of pre-baked strategy ideas, this scanner performs
unbiased, data-driven empirical discovery directly on the asset's OHLCV + TA-Lib/ta feature matrix:

1. Model-Free Price & Serial Correlation Surface:
   - Multi-horizon Autocorrelation (ACF), Lo-MacKinlay Variance Ratios VR(q),
     multi-scale Hurst Exponent H(q), and volatility clustering.
2. Exhaustive Library Feature Information Coefficient (IC) Screen:
   - Evaluates 50+ normalized TA-Lib & `ta` features (plus any custom user columns)
     against forward returns across multiple horizons (1, 2, 3, 5, 8, 13, 21 bars).
   - Computes rank Information Coefficient (Spearman rho), t-statistic, p-value,
     and In-Sample (first 50%) vs. Out-of-Sample (second 50%) sign consistency.
3. Empirical Quantile & 2-Factor Interaction Mining (Zero Hardcoded Thresholds):
   - Dynamically extracts empirical quantiles (Q15/Q20/Q80/Q85) for the strongest features
     and mines 2-factor conditional interactions (Regime Filter x Directional Trigger).
   - Lets the empirical forward return distribution determine trade direction (continuation vs. reversion)
     and optimal holding horizon (alpha half-life), net of round-trip friction.
4. Writes the Structured Empirical Briefing into `.nujin/sessions/<session_id>/empirical_briefing.json`.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.constants import FEE_BPS, SLIPPAGE_BPS
from server.indicators import compute_all_standard_features
from server.session_store import create_session, get_session_paths

FRICTION_BPS = FEE_BPS + SLIPPAGE_BPS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("AnomalyScanner")

# Feature domain classification for grouping discovered statistical edges
FEATURE_DOMAIN_MAP: Dict[str, Tuple[str, str]] = {
    # Trend & Regression
    "dist_ema_21_atr": ("TREND_CONTINUATION", "trend_following"),
    "dist_ema_50_atr": ("TREND_CONTINUATION", "trend_following"),
    "ema_spread_9_21_atr": ("TREND_CONTINUATION", "trend_following"),
    "ema_spread_21_50_atr": ("TREND_CONTINUATION", "trend_following"),
    "hma_spread_21_55_atr": ("TREND_CONTINUATION", "trend_following"),
    "slope_20": ("TREND_CONTINUATION", "trend_following"),
    "slope_50": ("TREND_CONTINUATION", "trend_following"),
    "linreg_angle_20": ("TREND_CONTINUATION", "trend_following"),
    "di_spread_14": ("TREND_CONTINUATION", "trend_following"),
    "aroonosc_14": ("TREND_CONTINUATION", "trend_following"),
    "vortex_diff_14": ("TREND_CONTINUATION", "trend_following"),
    "supertrend_dir": ("TREND_CONTINUATION", "trend_following"),
    # Momentum & Breakout
    "donchian_pos_10": ("MOMENTUM_BREAKOUT", "momentum_breakout"),
    "donchian_pos_20": ("MOMENTUM_BREAKOUT", "momentum_breakout"),
    "donchian_pos_55": ("MOMENTUM_BREAKOUT", "momentum_breakout"),
    "roc_10": ("MOMENTUM_BREAKOUT", "momentum_breakout"),
    "roc_20": ("MOMENTUM_BREAKOUT", "momentum_breakout"),
    "ppo_12_26": ("MOMENTUM_BREAKOUT", "momentum_breakout"),
    "macd_hist": ("MOMENTUM_BREAKOUT", "momentum_breakout"),
    "tsi": ("MOMENTUM_BREAKOUT", "momentum_breakout"),
    "cmo_14": ("MOMENTUM_BREAKOUT", "momentum_breakout"),
    "ultosc": ("MOMENTUM_BREAKOUT", "momentum_breakout"),
    "vol_compression": ("MOMENTUM_BREAKOUT", "volatility_squeeze"),
    "rvi_14": ("MOMENTUM_BREAKOUT", "momentum_breakout"),
    # Statistical Mean Reversion & Oscillators
    "zscore_20": ("MEAN_REVERSION", "zscore_reversion"),
    "zscore_50": ("MEAN_REVERSION", "zscore_reversion"),
    "ret_zscore": ("MEAN_REVERSION", "zscore_reversion"),
    "avwap_zscore": ("MEAN_REVERSION", "vwap_reversion"),
    "bb_pct_b": ("MEAN_REVERSION", "zscore_reversion"),
    "rsi_7": ("MEAN_REVERSION", "zscore_reversion"),
    "rsi_14": ("MEAN_REVERSION", "zscore_reversion"),
    "cci_20": ("MEAN_REVERSION", "zscore_reversion"),
    "williams_r_14": ("MEAN_REVERSION", "zscore_reversion"),
    "stoch_k_14": ("MEAN_REVERSION", "zscore_reversion"),
    "percentrank_50": ("MEAN_REVERSION", "zscore_reversion"),
    # Structural Pullback & Cycle
    "ht_dcperiod": ("STRUCTURAL_PULLBACK", "mtf_pullback"),
    "er_10": ("STRUCTURAL_PULLBACK", "mtf_pullback"),
    "vhf_28": ("STRUCTURAL_PULLBACK", "mtf_pullback"),
    # Volume & Order Flow
    "cmf_20": ("MICROSTRUCTURE_FLOW", "momentum_breakout"),
    "mfi_14": ("MICROSTRUCTURE_FLOW", "momentum_breakout"),
    "efi_13": ("MICROSTRUCTURE_FLOW", "momentum_breakout"),
    "adosc": ("MICROSTRUCTURE_FLOW", "momentum_breakout"),
    "volume_zscore": ("MICROSTRUCTURE_FLOW", "momentum_breakout"),
    "relative_vol": ("MICROSTRUCTURE_FLOW", "momentum_breakout"),
    "bop": ("MICROSTRUCTURE_FLOW", "momentum_breakout"),
    "vpin_proxy": ("MICROSTRUCTURE_FLOW", "smc_liquidity"),
    "close_location": ("MICROSTRUCTURE_FLOW", "momentum_breakout"),
}


def load_candles(data_path: str) -> pd.DataFrame:
    """Loads OHLCV candle data and standardizes columns."""
    if not os.path.exists(data_path):
        for fallback in [
            "data/market/BTCUSDT_15m.csv",
            "data/candles_15m.csv",
            "data/btc_candles_5m.csv",
            "data/xauusd_candles_1m.csv",
        ]:
            if os.path.exists(fallback):
                data_path = fallback
                break
    if not os.path.exists(data_path):
        raise FileNotFoundError(f"No candle dataset found at {data_path}")

    df = pd.read_csv(data_path)
    df.columns = [c.lower() for c in df.columns]

    time_col = "timestamp" if "timestamp" in df.columns else ("time" if "time" in df.columns else None)
    if time_col:
        df["time"] = pd.to_numeric(df[time_col], errors="coerce").fillna(0).astype(int)
    else:
        df["time"] = np.arange(len(df)) * 900

    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").ffill().bfill().fillna(100.0)
        else:
            df[col] = 100.0

    for col in df.columns:
        if col not in ["time", "timestamp"]:
            try:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            except Exception:
                pass

    return df.sort_values(by="time").reset_index(drop=True)


def compute_variance_ratios_and_hurst(df: pd.DataFrame, lags: List[int] = [2, 4, 8, 16, 32]) -> Dict[str, Any]:
    """
    Model-free serial correlation profile:
      - Lo-MacKinlay Variance Ratio VR(q) = Var(r_q) / (q * Var(r_1))
      - Multi-scale Hurst Exponent H(q) = 0.5 * (1 + ln(VR(q)) / ln(q))
      - Return Autocorrelation ACF(k) and Volatility Clustering ACF(|r_t|)
    """
    close = df["close"].values
    ret1 = np.diff(np.log(np.clip(close, 1e-8, None)))
    var1 = np.var(ret1, ddof=1) if len(ret1) > 2 else 0.0

    if var1 < 1e-12:
        return {
            "hurst_exponent": 0.5,
            "regime": "RANDOM_WALK",
            "description": "Insufficient variance",
            "variance_ratios": {},
            "return_autocorrelation": {},
            "volatility_clustering_acf1": 0.0,
        }

    vr_results = {}
    acf_results = {}
    hurst_estimates = []

    for q in lags:
        if len(close) <= q + 4:
            continue
        ret_q = np.log(np.clip(close[q:], 1e-8, None) / np.clip(close[:-q], 1e-8, None))
        var_q = np.var(ret_q, ddof=1)
        vr = float(var_q / (q * var1))
        vr_results[f"lag_{q}"] = round(vr, 3)

        if len(ret1) > q + 2:
            acf_k = float(np.corrcoef(ret1[:-q], ret1[q:])[0, 1])
            acf_results[f"lag_{q}"] = round(0.0 if np.isnan(acf_k) else acf_k, 4)

        if vr > 0:
            h_q = 0.5 * (1.0 + np.log(vr) / np.log(q))
            hurst_estimates.append(np.clip(h_q, 0.1, 0.9))

    abs_ret = np.abs(ret1)
    vol_cluster = float(np.corrcoef(abs_ret[:-1], abs_ret[1:])[0, 1]) if len(abs_ret) > 4 else 0.0
    vol_cluster = round(0.0 if np.isnan(vol_cluster) else vol_cluster, 3)

    avg_hurst = round(float(np.mean(hurst_estimates)) if hurst_estimates else 0.50, 3)

    if avg_hurst > 0.55:
        regime = "PERSISTENT_TREND"
        regime_desc = (
            f"Positive serial dependence (Hurst={avg_hurst:.2f}, VolCluster={vol_cluster:.2f}). "
            "Directional continuation and breakout features carry structural tailwind."
        )
    elif avg_hurst < 0.45:
        regime = "MEAN_REVERTING"
        regime_desc = (
            f"Negative serial dependence (Hurst={avg_hurst:.2f}, VolCluster={vol_cluster:.2f}). "
            "Extreme quantile mean-reversion and value-envelope features carry structural tailwind."
        )
    else:
        regime = "MIXED_REGIME"
        regime_desc = (
            f"Scale-dependent regime dynamics (Hurst={avg_hurst:.2f}, VolCluster={vol_cluster:.2f}). "
            "Edge requires conditioning on regime filters (volatility compression, efficiency ratio, or trend strength)."
        )

    return {
        "hurst_exponent": avg_hurst,
        "regime": regime,
        "description": regime_desc,
        "variance_ratios": vr_results,
        "return_autocorrelation": acf_results,
        "volatility_clustering_acf1": vol_cluster,
    }


def compute_session_hourly_matrix(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Empirical return, volatility, and t-statistic by UTC hour (0-23)."""
    if "time" not in df.columns or len(df) < 100:
        return []

    d = df.copy()
    ts = d["time"].values
    if len(ts) > 0 and ts[0] > 1e11:
        ts = ts // 1000
    d["utc_hour"] = (ts % 86400) // 3600
    d["bar_return"] = (d["close"] - d["open"]) / d["open"].replace(0, 1e-8)
    d["bar_range"] = (d["high"] - d["low"]) / d["open"].replace(0, 1e-8)
    baseline_range = float(d["bar_range"].mean()) or 1e-8

    hourly_stats = []
    for h in range(24):
        h_subset = d[d["utc_hour"] == h]
        if len(h_subset) < 10:
            continue

        ret_series = h_subset["bar_return"].values
        mean_ret = float(np.mean(ret_series))
        avg_range = float(h_subset["bar_range"].mean())
        vol_multiplier = round(float(avg_range / baseline_range), 2)

        t_stat, p_val = stats.ttest_1samp(ret_series, 0.0)
        t_stat = float(t_stat) if not np.isnan(t_stat) else 0.0
        p_val = float(p_val) if not np.isnan(p_val) else 1.0

        session_tag = (
            "ASIAN_SESSION" if 0 <= h < 6
            else "LONDON_OPEN" if 7 <= h <= 9
            else "LONDON_MIDDAY" if 10 <= h <= 12
            else "NEW_YORK_OPEN_OVERLAP" if 13 <= h <= 16
            else "NEW_YORK_AFTERNOON" if 17 <= h <= 20
            else "OFF_HOURS"
        )

        hourly_stats.append({
            "utc_hour": h,
            "session": session_tag,
            "sample_count": len(h_subset),
            "volatility_multiplier": vol_multiplier,
            "mean_return_pct": round(mean_ret * 100, 3),
            "t_statistic": round(t_stat, 2),
            "p_value": round(p_val, 4),
            "statistically_significant_drift": bool(p_val < 0.05 and abs(t_stat) >= 2.0),
        })

    return hourly_stats


def extract_mathematical_primitives(df: pd.DataFrame) -> pd.DataFrame:
    """Computes full TA-Lib + `ta` standard feature bank."""
    return compute_all_standard_features(df.copy(), window=20)


def scan_library_feature_ic(
    df: pd.DataFrame,
    horizons: List[int] = [1, 3, 5, 8, 13, 21],
) -> List[Dict[str, Any]]:
    """
    Model-free Information Coefficient (IC) screen across all stationary TA-Lib/ta features
    and any custom user columns.
    For each feature, computes:
      - Spearman rank IC across horizons
      - Peak IC t-statistic and optimal horizon h*
      - Split-sample stability: Does sign(IC_first_half) == sign(IC_second_half)?
      - Empirical quantiles (q15, q20, q50, q80, q85) for rule synthesis
    """
    d = extract_mathematical_primitives(df)
    c = d["close"].astype(float)
    n = len(d)
    max_h = max(horizons)
    if n <= max_h + 30:
        return []

    fwd_rets = {hz: ((c.shift(-hz) - c) / c.replace(0, 1e-8)).values for hz in horizons}

    # Candidate stationary features: all mapped TA-Lib features + any custom user numeric columns
    exclude_raw_price = {
        "time", "timestamp", "open", "high", "low", "close", "volume", "utc_hour",
        "upper_band", "lower_band", "keltner_mid", "keltner_upper", "keltner_lower",
        "avwap_100", "value_area_high", "value_area_low", "supertrend", "supertrend_line",
        "obv", "total_range", "true_range", "cvd_proxy", "delta_proxy", "returns", "log_ret",
    }
    candidate_cols: List[str] = []
    for col in d.columns:
        if col in exclude_raw_price:
            continue
        if any(col.startswith(p) for p in ("ema_", "sma_", "hma_", "kama_", "zlema_", "t3_", "atr_", "donchian_upper_", "donchian_lower_", "donchian_mid_")) and not col.endswith("_atr"):
            continue
        if pd.api.types.is_numeric_dtype(d[col]):
            candidate_cols.append(col)

    valid_len = n - max_h
    mid_idx = valid_len // 2
    ic_profiles: List[Dict[str, Any]] = []

    for col in candidate_cols:
        vals = d[col].values[:valid_len].astype(float)
        if np.isnan(vals).all() or np.nanstd(vals) < 1e-9:
            continue
        unique_cnt = len(np.unique(vals[~np.isnan(vals)]))
        if unique_cnt < 5:
            continue

        best_ic = 0.0
        best_t = 0.0
        best_p = 1.0
        best_hz = horizons[0]
        oos_consistent = False
        ic_by_hz: Dict[str, float] = {}

        for hz in horizons:
            y = fwd_rets[hz][:valid_len]
            mask = ~(np.isnan(vals) | np.isnan(y))
            if np.sum(mask) < 30:
                continue
            x_clean, y_clean = vals[mask], y[mask]
            rho, pval = stats.spearmanr(x_clean, y_clean)
            if np.isnan(rho):
                continue
            m = len(x_clean)
            t_val = float(rho * np.sqrt((m - 2) / max(1e-8, 1.0 - rho**2)))
            ic_by_hz[f"h_{hz}"] = round(float(rho), 4)

            if abs(t_val) > abs(best_t):
                best_t = t_val
                best_ic = float(rho)
                best_p = float(pval)
                best_hz = hz
                # Check IS (first half) vs OOS (second half) sign consistency
                rho_is, _ = stats.spearmanr(x_clean[: m // 2], y_clean[: m // 2])
                rho_oos, _ = stats.spearmanr(x_clean[m // 2 :], y_clean[m // 2 :])
                oos_consistent = bool(
                    not np.isnan(rho_is)
                    and not np.isnan(rho_oos)
                    and (np.sign(rho_is) == np.sign(rho_oos))
                    and abs(rho_oos) >= 0.02
                )

        if abs(best_t) < 0.5:
            continue

        clean_s = pd.Series(vals).dropna()
        q15, q20, q50, q80, q85 = [
            round(float(clean_s.quantile(q)), 4) for q in (0.15, 0.20, 0.50, 0.80, 0.85)
        ]
        fam, arch = FEATURE_DOMAIN_MAP.get(col, ("CUSTOM_USER_FEATURE", "trend_following"))

        ic_profiles.append({
            "feature": col,
            "edge_family": fam,
            "archetype": arch,
            "peak_ic": round(best_ic, 4),
            "ic_t_stat": round(best_t, 2),
            "p_value": round(best_p, 4),
            "optimal_horizon_bars": best_hz,
            "oos_sign_consistent": oos_consistent,
            "quantiles": {"q15": q15, "q20": q20, "q50": q50, "q80": q80, "q85": q85},
            "ic_by_horizon": ic_by_hz,
        })

    ic_profiles.sort(key=lambda x: (1 if x["oos_sign_consistent"] else 0, abs(x["ic_t_stat"])), reverse=True)
    return ic_profiles


def _evaluate_condition_mask(
    mask: pd.Series,
    fwd_returns: Dict[int, pd.Series],
    horizons: List[int],
    n_bars: int,
    friction_frac: float,
) -> Optional[Dict[str, Any]]:
    indices = np.where(mask.fillna(False).values)[0]
    valid_indices = [idx for idx in indices if idx < n_bars - max(horizons)]
    sample_count = len(valid_indices)
    if sample_count < 12:
        return None

    horizon_data: Dict[str, Any] = {}
    peak_abs_t = 0.0
    optimal_hz = horizons[0]
    optimal_dir = "LONG"
    optimal_trade_ret = 0.0
    optimal_net_ret = -999.0

    for hz in horizons:
        rets = fwd_returns[hz].iloc[valid_indices].dropna().values
        if len(rets) < 10:
            continue
        mean_r = float(np.mean(rets))
        t_stat, p_val = stats.ttest_1samp(rets, 0.0)
        t_stat = float(t_stat) if not np.isnan(t_stat) else 0.0
        p_val = float(p_val) if not np.isnan(p_val) else 1.0

        long_wr = float(np.sum(rets > 0) / len(rets)) * 100.0
        short_wr = float(np.sum(rets < 0) / len(rets)) * 100.0

        trade_dir = "LONG" if mean_r >= 0 else "SHORT"
        trade_ret = abs(mean_r)
        net_ret = trade_ret - friction_frac

        horizon_data[f"h_{hz}"] = {
            "bars": hz,
            "asset_return_pct": round(mean_r * 100, 3),
            "trade_return_pct": round(trade_ret * 100, 3),
            "net_return_pct": round(net_ret * 100, 3),
            "t_statistic": round(t_stat, 2),
            "p_value": round(p_val, 4),
            "long_win_rate": round(long_wr, 1),
            "short_win_rate": round(short_wr, 1),
            "optimal_dir": trade_dir,
        }

        if abs(t_stat) > peak_abs_t:
            peak_abs_t = abs(t_stat)
            optimal_hz = hz
            optimal_dir = trade_dir
            optimal_trade_ret = trade_ret
            optimal_net_ret = net_ret

    if not horizon_data:
        return None

    best_info = horizon_data[f"h_{optimal_hz}"]
    return {
        "sample_count": sample_count,
        "favored_direction": optimal_dir,
        "alpha_half_life_bars": optimal_hz,
        "peak_t_statistic": round(best_info["t_statistic"], 2),
        "p_value": best_info["p_value"],
        "expected_return_pct": round(optimal_trade_ret * 100, 3),
        "net_expected_return_pct": round(optimal_net_ret * 100, 3),
        "win_rate_pct": round(
            best_info["long_win_rate"] if optimal_dir == "LONG" else best_info["short_win_rate"], 1
        ),
        "is_statistically_significant": bool(
            best_info["p_value"] < 0.05 and peak_abs_t >= 2.0 and optimal_net_ret > 0
        ),
        "horizons_profile": horizon_data,
    }


def scan_conditional_anomalies(
    df: pd.DataFrame,
    horizons: List[int] = [1, 2, 3, 5, 8, 13, 21],
    friction_bps: float = FRICTION_BPS,
) -> List[Dict[str, Any]]:
    """
    Model-Free Empirical Condition & Interaction Miner:
      1. Screens all TA-Lib / `ta` / user features via `scan_library_feature_ic`.
      2. Dynamically evaluates upper-tail (>= Q80) and lower-tail (<= Q20) quantile regimes
         for the top predictive features across every orthogonal domain — letting the data
         decide whether a tail is a continuation or mean-reversion signal!
      3. Automatically mines 2-factor interactions (Regime Context x Trigger Feature) from
         the empirical quantiles of the dataset.
    """
    d = extract_mathematical_primitives(df)
    c = d["close"].astype(float)
    n_bars = len(d)
    friction_frac = friction_bps / 10000.0
    fwd_returns = {hz: (c.shift(-hz) - c) / c.replace(0, 1e-8) for hz in horizons}

    ic_ranked = scan_library_feature_ic(d, horizons=[h for h in horizons if h >= 1])

    # Ensure broad representation across all domains + top IC winners
    selected_features: List[Dict[str, Any]] = []
    seen_features = set()
    # First pick top 3 features from each domain so no domain is ignored
    domains = set( info["edge_family"] for info in ic_ranked )
    for dom in domains:
        dom_feats = [f for f in ic_ranked if f["edge_family"] == dom][:3]
        for f in dom_feats:
            if f["feature"] not in seen_features:
                selected_features.append(f)
                seen_features.add(f["feature"])
    # Fill with overall top IC features up to 24 features
    for f in ic_ranked:
        if f["feature"] not in seen_features and len(selected_features) < 24:
            selected_features.append(f)
            seen_features.add(f["feature"])

    dynamic_specs: Dict[str, Dict[str, Any]] = {}

    # A. Single-feature empirical quantile tail discovery (data decides direction!)
    for f_info in selected_features:
        col = f_info["feature"]
        fam = f_info["edge_family"]
        arch = f_info["archetype"]
        q20 = f_info["quantiles"]["q20"]
        q80 = f_info["quantiles"]["q80"]
        if q80 <= q20:
            continue

        # Upper quantile tail
        dynamic_specs[f"EMPIRICAL_{col.upper()}_HIGH_Q80"] = {
            "family": fam,
            "archetype": arch,
            "mask": d[col] >= q80,
            "high_expr": f"{col} >= {q80}",
            "low_expr": f"{col} <= {q20}",
        }
        # Lower quantile tail
        dynamic_specs[f"EMPIRICAL_{col.upper()}_LOW_Q20"] = {
            "family": fam,
            "archetype": arch,
            "mask": d[col] <= q20,
            "high_expr": f"{col} <= {q20}",
            "low_expr": f"{col} >= {q80}",
        }

    # B. Data-mined 2-Factor Interactions (Regime Filter x Top IC Trigger Features)
    regime_filters: List[Tuple[str, pd.Series, str, str]] = []
    if "adx_14" in d.columns:
        adx_med = round(float(d["adx_14"].dropna().quantile(0.55)), 2)
        regime_filters.append(("ADX_TREND", d["adx_14"] >= adx_med, f"adx_14 >= {adx_med}", f"adx_14 >= {adx_med}"))
    if "vhf_28" in d.columns:
        vhf_q60 = round(float(d["vhf_28"].dropna().quantile(0.60)), 3)
        regime_filters.append(("VHF_PERSISTENT", d["vhf_28"] >= vhf_q60, f"vhf_28 >= {vhf_q60}", f"vhf_28 >= {vhf_q60}"))
    if "vol_compression" in d.columns:
        vc_q40 = round(float(d["vol_compression"].dropna().quantile(0.40)), 3)
        regime_filters.append(("VOL_COMPRESSED", d["vol_compression"] <= vc_q40, f"vol_compression <= {vc_q40}", f"vol_compression <= {vc_q40}"))
    if "relative_vol" in d.columns:
        rv_q65 = round(float(d["relative_vol"].dropna().quantile(0.65)), 2)
        regime_filters.append(("HIGH_RVOL", d["relative_vol"] >= rv_q65, f"relative_vol >= {rv_q65}", f"relative_vol >= {rv_q65}"))
    if "supertrend_dir" in d.columns:
        regime_filters.append(("SUPERTREND_ALIGNED", d["supertrend_dir"] == 1, "supertrend_dir == 1", "supertrend_dir == -1"))
    if "killzone_london" in d.columns and "killzone_ny" in d.columns:
        sess_mask = (d["killzone_london"] == 1) | (d["killzone_ny"] == 1)
        if int(sess_mask.sum()) >= 20:
            regime_filters.append(
                ("ACTIVE_KILLZONE", sess_mask, "(killzone_london == 1 or killzone_ny == 1)", "(killzone_london == 1 or killzone_ny == 1)")
            )

    for r_name, r_mask, r_expr_long, r_expr_short in regime_filters:
        for f_info in selected_features[:8]:
            col = f_info["feature"]
            if col in r_expr_long:
                continue
            q20 = f_info["quantiles"]["q20"]
            q80 = f_info["quantiles"]["q80"]
            if q80 <= q20:
                continue
            fam = "SESSION_TIME_EDGE" if r_name == "ACTIVE_KILLZONE" else f_info["edge_family"]
            arch = "session_breakout" if r_name == "ACTIVE_KILLZONE" else f_info["archetype"]
            dynamic_specs[f"INTERACTION_{r_name}_X_{col.upper()}_Q80"] = {
                "family": fam,
                "archetype": arch,
                "mask": r_mask & (d[col] >= q80),
                "high_expr": f"{r_expr_long} and {col} >= {q80}",
                "low_expr": f"{r_expr_short} and {col} <= {q20}",
            }
            dynamic_specs[f"INTERACTION_{r_name}_X_{col.upper()}_Q20"] = {
                "family": fam,
                "archetype": arch,
                "mask": r_mask & (d[col] <= q20),
                "high_expr": f"{r_expr_long} and {col} <= {q20}",
                "low_expr": f"{r_expr_short} and {col} >= {q80}",
            }

    results: List[Dict[str, Any]] = []
    for name, spec in dynamic_specs.items():
        eval_res = _evaluate_condition_mask(spec["mask"], fwd_returns, horizons, n_bars, friction_frac)
        if eval_res is None:
            continue

        fav_dir = eval_res["favored_direction"]
        # If the empirically favored direction when mask is True is LONG, then high_expr is entry_long;
        # if the empirically favored direction when mask is True is SHORT, then high_expr is entry_short!
        if fav_dir == "LONG":
            entry_long = spec["high_expr"]
            entry_short = spec["low_expr"]
        else:
            entry_long = spec["low_expr"]
            entry_short = spec["high_expr"]

        rationale = synthesize_structural_rationale(
            name, spec["family"], fav_dir, eval_res["alpha_half_life_bars"], eval_res["peak_t_statistic"]
        )

        results.append({
            "anomaly_id": name,
            "edge_family": spec["family"],
            "archetype": spec["archetype"],
            **eval_res,
            "suggested_entry_long": entry_long,
            "suggested_entry_short": entry_short,
            "economic_rationale": rationale,
        })

    results.sort(
        key=lambda x: (
            1 if x["net_expected_return_pct"] > 0 else 0,
            1 if x["is_statistically_significant"] else 0,
            abs(x["peak_t_statistic"]),
        ),
        reverse=True,
    )
    return results


def synthesize_structural_rationale(
    condition_name: str,
    family: str,
    direction: str,
    horizon: int,
    t_stat: float = 0.0,
) -> str:
    """Generates data-driven statistical explanation for the discovered empirical relationship."""
    return (
        f"Data-mined quantile/interaction anomaly `{condition_name}` ({family}) exhibits empirical "
        f"{direction} drift over a {horizon}-bar horizon (t={t_stat:+.2f}) net of friction."
    )


def summarize_edge_families(anomalies: List[Dict[str, Any]], hurst_info: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregates empirically discovered anomalies across domains and extracts the top data-driven rules."""
    family_scores: Dict[str, Dict[str, Any]] = {}
    for a in anomalies:
        fam = a.get("edge_family", "OTHER")
        entry = family_scores.setdefault(fam, {
            "family": fam,
            "archetype": a.get("archetype", "trend_following"),
            "best_anomaly": a["anomaly_id"],
            "peak_abs_t": 0.0,
            "best_net_return_pct": -999.0,
            "significant_signals": 0,
            "suggested_entry_long": a.get("suggested_entry_long", ""),
            "suggested_entry_short": a.get("suggested_entry_short", ""),
            "optimal_horizon_bars": a.get("alpha_half_life_bars", 8),
        })
        abs_t = abs(float(a.get("peak_t_statistic", 0.0)))
        net_r = float(a.get("net_expected_return_pct", 0.0))
        if a.get("is_statistically_significant"):
            entry["significant_signals"] += 1
        if (net_r > 0 and entry["best_net_return_pct"] <= 0) or (abs_t > entry["peak_abs_t"] and net_r >= entry["best_net_return_pct"]):
            entry["peak_abs_t"] = round(abs_t, 2)
            entry["best_net_return_pct"] = round(net_r, 3)
            entry["best_anomaly"] = a["anomaly_id"]
            entry["archetype"] = a.get("archetype", entry["archetype"])
            entry["suggested_entry_long"] = a.get("suggested_entry_long", "")
            entry["suggested_entry_short"] = a.get("suggested_entry_short", "")
            entry["optimal_horizon_bars"] = a.get("alpha_half_life_bars", 8)

    ranked_families = sorted(
        family_scores.values(),
        key=lambda x: (x["significant_signals"], x["best_net_return_pct"] > 0, x["peak_abs_t"]),
        reverse=True,
    )

    hurst_val = float(hurst_info.get("hurst_exponent", 0.5))
    default_arch = "trend_following" if hurst_val >= 0.52 else ("zscore_reversion" if hurst_val <= 0.46 else "volatility_squeeze")

    top_family = ranked_families[0] if ranked_families else {
        "family": "TREND_CONTINUATION",
        "archetype": default_arch,
        "best_anomaly": "NONE",
        "peak_abs_t": 0.0,
        "best_net_return_pct": 0.0,
    }

    return {
        "recommended_family": top_family["family"],
        "recommended_archetype": top_family["archetype"],
        "recommended_entry_long": top_family.get("suggested_entry_long", ""),
        "recommended_entry_short": top_family.get("suggested_entry_short", ""),
        "recommended_horizon_bars": top_family.get("optimal_horizon_bars", 8),
        "family_rankings": ranked_families,
    }


def generate_empirical_briefing(
    data_path: str,
    output_path: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes model-free market profiling, library-wide feature IC ranking, and
    2-factor quantile interaction discovery, writing `.nujin/sessions/<id>/empirical_briefing.json`.
    """
    df = load_candles(data_path)
    asset_name = os.path.basename(data_path).replace(".csv", "")

    if not output_path:
        paths = get_session_paths(session_id=session_id, symbol=asset_name, create_if_missing=True)
        output_path = paths["briefing"]
        resolved_sid = paths["session_id"]
    else:
        resolved_sid = session_id or ""

    hurst_data = compute_variance_ratios_and_hurst(df)
    session_data = compute_session_hourly_matrix(df)
    feature_ic_ranking = scan_library_feature_ic(df)
    anomalies = scan_conditional_anomalies(df)
    edge_summary = summarize_edge_families(anomalies, hurst_data)

    briefing = {
        "session_id": resolved_sid,
        "asset": asset_name,
        "dataset_path": data_path,
        "total_bars": len(df),
        "macro_regime_characteristics": hurst_data,
        "top_predictive_library_features": feature_ic_ranking[:25],
        "edge_family_synthesis": edge_summary,
        "recommended_archetype": edge_summary["recommended_archetype"],
        "session_hourly_matrix": session_data,
        "empirical_anomalies_detected": anomalies[:35],
        "statistically_significant_count": sum(1 for a in anomalies if a["is_statistically_significant"]),
        "generated_at": pd.Timestamp.now("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(briefing, f, indent=2)

    return briefing


def print_ascii_briefing(briefing: Dict[str, Any]) -> None:
    """Pretty prints the model-free IC & interaction discovery briefing."""
    asset = briefing.get("asset", "Unknown")
    bars = briefing.get("total_bars", 0)
    sid = briefing.get("session_id", "default")
    hurst_info = briefing.get("macro_regime_characteristics", {})
    edge_syn = briefing.get("edge_family_synthesis", {})
    top_ic = briefing.get("top_predictive_library_features", [])
    anomalies = briefing.get("empirical_anomalies_detected", [])

    print("\n" + "=" * 100)
    print(" 🔬 NUJINSKILLS OPEN STATISTICAL PROFILER & TA-LIB FEATURE IC DISCOVERY BRIEFING")
    print("=" * 100)
    print(f"  Session ID:            {sid}")
    print(f"  Asset Dataset:         {asset} ({bars} Total Historical Bars)")
    print(f"  Macro Regime:          {hurst_info.get('regime')} (Hurst H = {hurst_info.get('hurst_exponent')}, VolCluster = {hurst_info.get('volatility_clustering_acf1')})")
    print(f"  Top Data-Mined Rule:   LONG:  {edge_syn.get('recommended_entry_long')}")
    print(f"                         SHORT: {edge_syn.get('recommended_entry_short')}")
    print("-" * 100)

    print("\n[1] TOP PREDICTIVE TA-LIB / LIBRARY FEATURES (Spearman Rank IC vs Forward Returns):")
    ic_header = f"{'Feature (TA-Lib / Library)':<28} {'Domain':<24} {'Peak IC':<10} {'IC t-Stat':<11} {'Opt Hz':<8} {'OOS Stable'}"
    print("-" * len(ic_header))
    print(ic_header)
    print("-" * len(ic_header))
    for f in top_ic[:10]:
        oos_tag = "✅ YES" if f.get("oos_sign_consistent") else "⚪ NO"
        print(
            f"{f['feature']:<28} {f['edge_family']:<24} {f['peak_ic']:+8.4f}   "
            f"{f['ic_t_stat']:+8.2f}    {f['optimal_horizon_bars']:<8} {oos_tag}"
        )
    print("-" * len(ic_header))

    print("\n[2] TOP DATA-MINED QUANTILE & 2-FACTOR INTERACTION EDGES (Net of Friction):")
    header = f"{'Discovered Condition':<42} {'Dir':<6} {'N':<6} {'Half-Life':<10} {'t-Stat':<9} {'Net%':<8} {'Rule Expression'}"
    print("-" * 100)
    print(header)
    print("-" * 100)

    for a in anomalies[:10]:
        hl_str = f"{a.get('alpha_half_life_bars')} bars"
        t_str = f"{a.get('peak_t_statistic'):+5.2f}"
        net_str = f"{a.get('net_expected_return_pct', 0.0):+.2f}%"
        rule_preview = a.get("suggested_entry_long", "")[:32]
        print(
            f"{a['anomaly_id'][:40]:<42} {a['favored_direction']:<6} "
            f"{a['sample_count']:<6} {hl_str:<10} {t_str:<9} {net_str:<8} {rule_preview}"
        )
    print("-" * 100)
    print("=" * 100 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NujinSkills Model-Free Statistical & TA-Lib Feature IC Scanner")
    parser.add_argument("--data", type=str, default="data/candles_15m.csv", help="Path to OHLCV candle CSV")
    parser.add_argument("--id", "--experiment", "--session", dest="session_id", type=str, default="", help="Session ID to isolate briefing in .nujin/sessions/<id>/")
    parser.add_argument("--new-session", action="store_true", help="Create and activate a brand-new isolated session")
    parser.add_argument("--output", type=str, default=None, help="Explicit output JSON path")
    parser.add_argument("--json", action="store_true", help="Output raw JSON to stdout")

    args = parser.parse_args()

    asset_slug = os.path.basename(args.data).replace(".csv", "")
    if args.new_session:
        meta = create_session(session_id=args.session_id or None, symbol=asset_slug, activate=True)
        sid = meta["session_id"]
    else:
        sid = args.session_id or None

    paths = get_session_paths(session_id=sid, symbol=asset_slug, create_if_missing=True)
    out_path = args.output or paths["briefing"]

    briefing = generate_empirical_briefing(data_path=args.data, output_path=out_path, session_id=paths["session_id"])

    if args.json:
        print(json.dumps(briefing, indent=2))
    else:
        print_ascii_briefing(briefing)
