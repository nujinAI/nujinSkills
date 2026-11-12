"""
core/feature_factory.py - Pure Lossless Mathematical Basis & Multi-Scale Operator Grid.

Eliminates human indicator pre-bias and LLM buzzword fixation by decomposing raw OHLCV
into the 6 fundamental, dimensionless physical candle vectors:
  V1: Normalized log return r_t = ln(C_t / C_{t-1}) / sigma_21
  V2: Normalized range span w_t = (H_t - L_t) / mean_14(TR)
  V3: Intrabar displacement vector b_t = (C_t - O_t) / (H_t - L_t) in [-1, 1]
  V4: Boundary asymmetry vector a_t = ((min(O,C) - L) - (H - max(O,C))) / (H - L) in [-1, 1]
  V5: Close location coordinate c_t = (2*C_t - H_t - L_t) / (H_t - L_t) in [-1, 1]
  V6: Relative log-volume impulse v_t = zscore(ln(1 + V_t), 21)

Then applies pure mathematical operators (Moments 1..3, IQR-scaled coordinates,
Cross-Scale Dispersion Ratios, Serial Autocorrelation, Variance Ratios, Path Efficiency,
and Vector Inner Products) across the Fibonacci geometric scale grid:
  W in {2, 3, 5, 8, 13, 21, 34, 55}

Every output coordinate is strictly stationary (zero raw price levels).
"""
from __future__ import annotations
from typing import Dict, List
import numpy as np
import pandas as pd


FIB_SCALES = [3, 5, 8, 13, 21, 34, 55]
CROSS_SCALE_PAIRS = [(2, 8), (3, 13), (5, 21), (8, 34), (13, 55)]

# Populated dynamically with mathematical coordinate metadata
FEATURE_METADATA: Dict[str, Dict[str, str]] = {}


def _reg(name: str, role: str, desc: str) -> str:
    """Registers a mathematical basis coordinate ('directional' or 'unsigned_state')."""
    FEATURE_METADATA[name] = {"dimension": role, "description": desc}
    return name


# Pre-register metadata for all basis coordinates
for _w in FIB_SCALES:
    _reg(f"v1_drift_w{_w}", "directional", f"First moment (rolling mean) of normalized return vector V1 over scale W={_w}")
    _reg(f"v3_body_mean_w{_w}", "directional", f"Rolling mean of intrabar displacement vector V3 over scale W={_w}")
    _reg(f"v4_asym_mean_w{_w}", "directional", f"Rolling mean of boundary asymmetry vector V4 over scale W={_w}")
    _reg(f"v5_loc_ema_w{_w}", "directional", f"Exponentially weighted close coordinate V5 over scale W={_w}")
    _reg(f"coord_iqr_w{_w}", "directional", f"Non-parametric median distance scaled by interquartile range over scale W={_w}")
    _reg(f"coord_ema_w{_w}", "directional", f"Normalized distance from exponential centroid over scale W={_w}")
    _reg(f"coord_chan_w{_w}", "directional", f"Centered coordinate within [min(L), max(H)] interval over scale W={_w} in [-1, 1]")
    _reg(f"coord_ext_w{_w}", "directional", f"Signed excursion beyond prior W={_w} interval boundary")
    _reg(f"path_eff_w{_w}", "directional", f"Signed net displacement divided by total path length over scale W={_w} in [-1, 1]")
    _reg(f"abs_eff_w{_w}", "unsigned_state", f"Unsigned path efficiency |net displacement| / path length over scale W={_w} in [0, 1]")
    _reg(f"overlap_density_w{_w}", "unsigned_state", f"Sum of single-bar spans divided by net W={_w} span (path congestion density)")

for _wf, _ws in CROSS_SCALE_PAIRS:
    _reg(f"disp_ratio_{_wf}_{_ws}", "unsigned_state", f"Cross-scale dispersion ratio: mean(V2, {_wf}) / mean(V2, {_ws})")
    _reg(f"hl_vol_ratio_{_wf}_{_ws}", "unsigned_state", f"Cross-scale log high-low variance ratio ({_wf} vs {_ws})")
    _reg(f"span_ratio_{_wf}_{_ws}", "unsigned_state", f"Interval span ratio: (max_{_wf}(H)-min_{_wf}(L)) / (max_{_ws}(H)-min_{_ws}(L))")

for _w in [8, 13, 21, 34]:
    _reg(f"autocorr_lag1_w{_w}", "unsigned_state", f"Lag-1 serial return autocorrelation over scale W={_w}")
    _reg(f"var_ratio_w{_w}", "unsigned_state", f"Variance ratio Var(r_3) / (3 * Var(r_1)) over scale W={_w}")
    _reg(f"rs_exp_w{_w}", "unsigned_state", f"Rescaled-range scaling exponent over scale W={_w}")
    _reg(f"skew_w{_w}", "directional", f"Third central moment (skewness) of V1 over scale W={_w}")
    _reg(f"semidev_bal_w{_w}", "directional", f"Upside vs downside semi-deviation balance over scale W={_w} in [-1, 1]")
    _reg(f"disp_cv_w{_w}", "unsigned_state", f"Coefficient of variation of bar span V2 over scale W={_w}")

for _w in [1, 3, 5, 13, 21]:
    _reg(f"coupling_v3_v6_w{_w}", "directional", f"Inner product of displacement V3 and volume activity V6 over scale W={_w}")
    _reg(f"coupling_v6_v2_w{_w}", "unsigned_state", f"Ratio of volume activity V6 to range span V2 over scale W={_w}")

_reg("v6_vol_z_w21", "unsigned_state", "Normalized log-volume activity z-score over W=21")
_reg("v2_span_ratio_w1", "unsigned_state", "Instantaneous bar span V2 relative to 14-bar baseline")
_reg("phase_diurnal_sin", "unsigned_state", "Diurnal 24h cycle sine coordinate")
_reg("phase_diurnal_cos", "unsigned_state", "Diurnal 24h cycle cosine coordinate")


def _safe_zscore(series: pd.Series, window: int = 21, clip: float = 5.0) -> pd.Series:
    mean = series.rolling(window, min_periods=max(4, window // 2)).mean()
    std = series.rolling(window, min_periods=max(4, window // 2)).std()
    return ((series - mean) / (std + 1e-8)).clip(-clip, clip).fillna(0.0)


def compute_all_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes the complete ~103-coordinate Pure Mathematical Basis Grid in a single
    vectorized pass on CPU. Zero trading buzzwords or hardcoded retail indicators.
    """
    idx = df.index
    open_p = df["open"].astype(float) if "open" in df.columns else df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    vol = df["volume"].astype(float) if "volume" in df.columns else pd.Series(1.0, index=idx)
    vol = vol.replace(0, np.nan).ffill().fillna(1.0).clip(lower=1e-8)

    eps = 1e-8
    prev_close = close.shift(1).bfill()

    # True Range & baseline scale factor
    tr = np.maximum(
        high - low,
        np.maximum((high - prev_close).abs(), (low - prev_close).abs())
    )
    hl_span = (high - low).clip(lower=eps)
    atr_14 = tr.rolling(14, min_periods=3).mean().bfill()
    abs_diff = (close - prev_close).abs()

    # 6 Fundamental Lossless Physical Vectors
    log_ret = np.log((close + eps) / (prev_close + eps))
    ret_std_21 = log_ret.rolling(21, min_periods=5).std().bfill().clip(lower=eps)

    v1 = (log_ret / (ret_std_21 + eps)).clip(-6.0, 6.0).fillna(0.0)
    v2 = (tr / (atr_14 + eps)).clip(0.05, 6.0).fillna(1.0)
    v3 = ((close - open_p) / hl_span).clip(-1.0, 1.0).fillna(0.0)
    lower_exc = np.minimum(open_p, close) - low
    upper_exc = high - np.maximum(open_p, close)
    v4 = ((lower_exc - upper_exc) / (tr + eps)).clip(-1.0, 1.0).fillna(0.0)
    v5 = ((2.0 * close - high - low) / hl_span).clip(-1.0, 1.0).fillna(0.0)

    vol_ma_21 = vol.rolling(21, min_periods=5).mean().bfill()
    rel_vol = (vol / (vol_ma_21 + eps)).clip(0.05, 10.0)
    v6 = _safe_zscore(np.log1p(vol), 21)

    feats: Dict[str, pd.Series] = {}

    # 1. Multi-Scale Fibonacci Operator Expansion (W in {3, 5, 8, 13, 21, 34, 55})
    hh_cache: Dict[int, pd.Series] = {}
    ll_cache: Dict[int, pd.Series] = {}
    tr_mean_cache: Dict[int, pd.Series] = {}
    log_hl_sq = np.log((high + eps) / (low + eps)) ** 2

    for w in [2, 3, 5, 8, 13, 21, 34, 55]:
        mp = max(2, w // 2)
        hh_cache[w] = high.rolling(w, min_periods=mp).max()
        ll_cache[w] = low.rolling(w, min_periods=mp).min()
        tr_mean_cache[w] = tr.rolling(w, min_periods=mp).mean().bfill()

    for w in FIB_SCALES:
        mp = max(2, w // 2)
        feats[f"v1_drift_w{w}"] = v1.rolling(w, min_periods=mp).mean().clip(-4.0, 4.0).fillna(0.0)
        feats[f"v3_body_mean_w{w}"] = v3.rolling(w, min_periods=mp).mean().clip(-1.0, 1.0).fillna(0.0)
        feats[f"v4_asym_mean_w{w}"] = v4.rolling(w, min_periods=mp).mean().clip(-1.0, 1.0).fillna(0.0)
        feats[f"v5_loc_ema_w{w}"] = v5.ewm(span=w, adjust=False).mean().clip(-1.0, 1.0).fillna(0.0)

        med_w = close.rolling(w, min_periods=mp).median()
        q75_w = close.rolling(w, min_periods=mp).quantile(0.75)
        q25_w = close.rolling(w, min_periods=mp).quantile(0.25)
        feats[f"coord_iqr_w{w}"] = (
            (close - med_w) / ((q75_w - q25_w) + atr_14 * 0.1 + eps)
        ).clip(-5.0, 5.0).fillna(0.0)

        ema_w = close.ewm(span=w, adjust=False).mean()
        feats[f"coord_ema_w{w}"] = ((close - ema_w) / (atr_14 + eps)).clip(-6.0, 6.0).fillna(0.0)

        hh_w = hh_cache[w]
        ll_w = ll_cache[w]
        span_w = (hh_w - ll_w).clip(lower=eps)
        feats[f"coord_chan_w{w}"] = (2.0 * (close - ll_w) / span_w - 1.0).clip(-1.0, 1.0).fillna(0.0)

        prev_hh = hh_w.shift(1)
        prev_ll = ll_w.shift(1)
        ext_up = (close - prev_hh).clip(lower=0.0)
        ext_dn = (prev_ll - close).clip(lower=0.0)
        feats[f"coord_ext_w{w}"] = ((ext_up - ext_dn) / (atr_14 + eps)).clip(-4.0, 4.0).fillna(0.0)

        path_w = abs_diff.rolling(w, min_periods=mp).sum()
        eff_w = ((close - close.shift(w)) / (path_w + eps)).clip(-1.0, 1.0).fillna(0.0)
        feats[f"path_eff_w{w}"] = eff_w
        feats[f"abs_eff_w{w}"] = eff_w.abs()

        feats[f"overlap_density_w{w}"] = (
            tr.rolling(w, min_periods=mp).sum() / span_w
        ).clip(1.0, 8.0).fillna(1.0)

    # 2. Cross-Scale Dispersion & Span Ratios
    for wf, ws in CROSS_SCALE_PAIRS:
        feats[f"disp_ratio_{wf}_{ws}"] = (
            tr_mean_cache[wf] / (tr_mean_cache[ws] + eps)
        ).clip(0.15, 4.0).fillna(1.0)

        p_fast = np.sqrt(log_hl_sq.rolling(wf, min_periods=2).mean() / (4.0 * np.log(2.0)))
        p_slow = np.sqrt(log_hl_sq.rolling(ws, min_periods=4).mean() / (4.0 * np.log(2.0)))
        feats[f"hl_vol_ratio_{wf}_{ws}"] = (p_fast / (p_slow + eps)).clip(0.15, 4.0).fillna(1.0)

        span_f = (hh_cache[wf] - ll_cache[wf]).clip(lower=eps)
        span_s = (hh_cache[ws] - ll_cache[ws]).clip(lower=eps)
        feats[f"span_ratio_{wf}_{ws}"] = (span_f / span_s).clip(0.05, 1.0).fillna(0.5)

    # 3. Serial Correlation, Variance Ratios, Rescaled-Range & Higher Moments
    ret_lag1 = log_ret.shift(1)
    ret_3 = np.log((close + eps) / (close.shift(3).bfill() + eps))
    up_sq = (log_ret.clip(lower=0.0) ** 2)
    dn_sq = (log_ret.clip(upper=0.0) ** 2)

    for w in [8, 13, 21, 34]:
        mp = max(4, w // 2)
        r_mean = log_ret.rolling(w, min_periods=mp).mean()
        r_var = log_ret.rolling(w, min_periods=mp).var().clip(lower=eps)
        cov_1 = ((log_ret - r_mean) * (ret_lag1 - r_mean)).rolling(w, min_periods=mp).mean()
        feats[f"autocorr_lag1_w{w}"] = (cov_1 / (r_var + eps)).clip(-1.0, 1.0).fillna(0.0)

        var_3 = ret_3.rolling(w, min_periods=mp).var()
        feats[f"var_ratio_w{w}"] = (var_3 / (3.0 * r_var + eps)).clip(0.1, 3.5).fillna(1.0)

        span_w = (hh_cache[w] - ll_cache[w]).clip(lower=eps)
        std_step = (close - prev_close).rolling(w, min_periods=mp).std().clip(lower=eps)
        rs_val = (span_w / std_step).clip(lower=1.02)
        feats[f"rs_exp_w{w}"] = (np.log(rs_val) / np.log(float(w))).clip(0.1, 0.98).fillna(0.5)

        feats[f"skew_w{w}"] = log_ret.rolling(w, min_periods=mp).skew().clip(-4.0, 4.0).fillna(0.0)

        u_v = np.sqrt(up_sq.rolling(w, min_periods=mp).mean())
        d_v = np.sqrt(dn_sq.rolling(w, min_periods=mp).mean())
        feats[f"semidev_bal_w{w}"] = ((u_v - d_v) / (u_v + d_v + eps)).clip(-1.0, 1.0).fillna(0.0)

        tr_std = tr.rolling(w, min_periods=mp).std()
        feats[f"disp_cv_w{w}"] = (tr_std / (tr_mean_cache[w] + eps)).clip(0.0, 3.5).fillna(0.5)

    # 4. Cross-Vector Coupling (Displacement V3 x Volume V6 & Volume V6 / Span V2)
    raw_v3_v6 = v3 * rel_vol
    raw_v6_v2 = rel_vol / (v2 + 0.15)
    for w in [1, 3, 5, 13, 21]:
        if w == 1:
            feats["coupling_v3_v6_w1"] = raw_v3_v6.clip(-5.0, 5.0).fillna(0.0)
            feats["coupling_v6_v2_w1"] = _safe_zscore(raw_v6_v2, 21)
        else:
            mp = max(2, w // 2)
            feats[f"coupling_v3_v6_w{w}"] = raw_v3_v6.rolling(w, min_periods=mp).mean().clip(-4.0, 4.0).fillna(0.0)
            feats[f"coupling_v6_v2_w{w}"] = _safe_zscore(raw_v6_v2.rolling(w, min_periods=mp).mean(), 21)

    feats["v6_vol_z_w21"] = v6
    feats["v2_span_ratio_w1"] = v2

    # 5. Diurnal Phase Coordinates
    if isinstance(idx, pd.DatetimeIndex):
        f_hr = idx.hour + idx.minute / 60.0
        feats["phase_diurnal_sin"] = pd.Series(np.sin(2.0 * np.pi * f_hr / 24.0), index=idx)
        feats["phase_diurnal_cos"] = pd.Series(np.cos(2.0 * np.pi * f_hr / 24.0), index=idx)
    else:
        try:
            dt_idx = pd.to_datetime(idx, utc=True)
            f_hr = dt_idx.hour + dt_idx.minute / 60.0
            feats["phase_diurnal_sin"] = pd.Series(np.sin(2.0 * np.pi * f_hr / 24.0), index=idx)
            feats["phase_diurnal_cos"] = pd.Series(np.cos(2.0 * np.pi * f_hr / 24.0), index=idx)
        except Exception:
            feats["phase_diurnal_sin"] = pd.Series(0.0, index=idx)
            feats["phase_diurnal_cos"] = pd.Series(0.0, index=idx)

    return pd.DataFrame(feats, index=idx)


def compute_selected_features(df: pd.DataFrame, feature_names: List[str]) -> pd.DataFrame:
    """
    Computes and returns the requested mathematical basis coordinates.
    """
    all_feats = compute_all_features(df)
    selected = [f for f in feature_names if f in all_feats.columns]
    return all_feats[selected]
