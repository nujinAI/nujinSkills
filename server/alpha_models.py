"""
server/alpha_models.py
─────────────────────────────────────────────────────────────────────────────
Continuous Multi-Factor Alpha Forecasting & Meta-Labeling Engine (Pillar 5).

Implements:
  1. Causal IC-Weighted Continuous Alpha Forecast (`alpha_forecast` in [-1, +1]
     and `alpha_forecast_z` in [-3, +3]):
     - Standardizes orthogonal factors (Trend, Momentum, MTF Alignment, Volume Flow,
       and Value Envelope) using strictly backward-looking rolling Z-scores.
     - Dynamically weights each factor by its trailing causal Rank IC (past returns
       vs lagged factor values, zero lookahead bias).
  2. López de Prado Meta-Labeling Confidence Filter (`meta_label_prob` in [0, 1]):
     - Estimates the conditional probability P(Primary Trade Profitable | Regime,
       MTF Alignment, Efficiency Ratio, Volume Participation, Trailing Barrier Hit-Rate).
     - Used both as a high-precision entry filter (`meta_label_prob >= 0.55`) and
       as the Fractional Kelly conviction multiplier (`0.50x` to `1.35x`) in
       `server/risk_governor.py`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _causal_zscore(s: pd.Series, window: int = 50) -> pd.Series:
    mean = s.rolling(window, min_periods=5).mean()
    std = s.rolling(window, min_periods=5).std().replace(0, 1e-8).fillna(1.0)
    return ((s - mean) / std).clip(-3.5, 3.5).fillna(0.0)


def compute_continuous_alpha_and_meta_label(df: pd.DataFrame, lookback: int = 60) -> pd.DataFrame:
    """
    Enriches `df` with:
      - `alpha_forecast`: Continuous directional forecast in [-1.0, +1.0]
      - `alpha_forecast_z`: Standardized forecast Z-score in [-3.5, +3.5]
      - `meta_label_prob`: Conditional trade success probability in [0.0, 1.0]
      - `kelly_conviction`: Fractional Kelly sizing multiplier in [0.50, 1.35]
    All calculations are 100% causal (strictly backward-looking).
    """
    d = df.copy()
    c = d["close"].astype(float)

    # 1. Construct standardized orthogonal factor pillars
    f_trend = _causal_zscore(
        d["ema_spread_9_21_atr"] if "ema_spread_9_21_atr" in d.columns else c.pct_change(10).fillna(0.0),
        lookback,
    )
    f_mom = _causal_zscore(
        d["roc_10"] if "roc_10" in d.columns else c.pct_change(5).fillna(0.0),
        lookback,
    )
    f_mtf = (
        d["mtf_alignment_score"].astype(float).fillna(0.0)
        if "mtf_alignment_score" in d.columns
        else _causal_zscore(c.pct_change(20).fillna(0.0), lookback)
    )
    f_flow = _causal_zscore(
        d["cmf_20"] if "cmf_20" in d.columns else pd.Series(0.0, index=d.index),
        lookback,
    )
    # Mean-reversion factor (inverted Z-score so positive = oversold bounce)
    f_rev = -_causal_zscore(
        d["zscore_20"] if "zscore_20" in d.columns else c.pct_change(3).fillna(0.0),
        lookback,
    )

    # 2. Causal Rolling IC Weighting: correlate factor(t-4) with return(t-4 -> t)
    # Using purely realized past 4-bar return vs factor value 4 bars ago (zero lookahead!)
    realized_4b_ret = c.pct_change(4).fillna(0.0)
    ic_win = max(30, int(lookback))

    def _causal_ic_weight(factor_s: pd.Series) -> pd.Series:
        lagged_f = factor_s.shift(4).fillna(0.0)
        cov = lagged_f.rolling(ic_win, min_periods=15).cov(realized_4b_ret).fillna(0.0)
        std_f = lagged_f.rolling(ic_win, min_periods=15).std().replace(0, 1e-8).fillna(1.0)
        std_r = realized_4b_ret.rolling(ic_win, min_periods=15).std().replace(0, 1e-8).fillna(1.0)
        corr = (cov / (std_f * std_r)).clip(-0.5, 0.5).fillna(0.05)
        return corr

    w_trend = _causal_ic_weight(f_trend)
    w_mom = _causal_ic_weight(f_mom)
    w_mtf = _causal_ic_weight(f_mtf)
    w_flow = _causal_ic_weight(f_flow)
    w_rev = _causal_ic_weight(f_rev)

    w_sum = (w_trend.abs() + w_mom.abs() + w_mtf.abs() + w_flow.abs() + w_rev.abs()).replace(0, 1.0)

    raw_combo = (
        w_trend * f_trend
        + w_mom * f_mom
        + w_mtf * f_mtf
        + w_flow * f_flow
        + w_rev * f_rev
    ) / w_sum

    forecast_z = _causal_zscore(raw_combo, lookback)
    forecast_bounded = np.tanh(forecast_z * 0.65)

    d["alpha_forecast_z"] = forecast_z.round(4)
    d["alpha_forecast"] = pd.Series(forecast_bounded, index=d.index).round(4)

    # 3. Meta-Labeling Confidence Model: P(Primary Signal Succeeds | Regime & Structure)
    # Evaluates structural quality independent of direction:
    #   (a) Signal conviction magnitude |forecast_z|
    #   (b) Trend Efficiency Ratio (er_10) & VHF (vhf_28)
    #   (c) MTF coherence |mtf_alignment_score|
    #   (d) Institutional volume participation (relative_vol)
    #   (e) Causal trailing barrier success rate
    er_s = d["er_10"].astype(float).clip(0.0, 1.0) if "er_10" in d.columns else pd.Series(0.5, index=d.index)
    vhf_s = d["vhf_28"].astype(float).clip(0.0, 1.0) if "vhf_28" in d.columns else pd.Series(0.35, index=d.index)
    rvol_s = (d["relative_vol"].astype(float).clip(0.3, 3.0) / 1.5) if "relative_vol" in d.columns else pd.Series(0.7, index=d.index)
    mtf_coh = f_mtf.abs().clip(0.0, 1.5)

    # Trailing realized directional accuracy of the forecast (strictly causal: did sign(forecast[t-4]) match sign(ret[t-4->t])?)
    past_hit = ((np.sign(forecast_z.shift(4).fillna(0.0)) == np.sign(realized_4b_ret)) & (realized_4b_ret.abs() > 0)).astype(float)
    rolling_hit_rate = past_hit.rolling(40, min_periods=5).mean().fillna(0.52)

    # Logistic meta-probability score centered around 0.55
    meta_logit = (
        0.35 * (forecast_z.abs() - 0.8)
        + 0.45 * (er_s - 0.35)
        + 0.35 * (vhf_s - 0.30)
        + 0.25 * (rvol_s - 0.65)
        + 0.35 * (mtf_coh - 0.40)
        + 1.20 * (rolling_hit_rate - 0.50)
    )
    meta_prob = 1.0 / (1.0 + np.exp(-meta_logit))
    d["meta_label_prob"] = pd.Series(meta_prob, index=d.index).clip(0.10, 0.95).round(4)

    # Fractional Kelly conviction multiplier: scales [0.50, 1.35] from meta_label_prob
    d["kelly_conviction"] = (0.50 + (d["meta_label_prob"] - 0.35).clip(0.0, 0.60) * 1.40).clip(0.50, 1.35).round(3)

    return d
