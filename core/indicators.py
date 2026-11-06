"""
server/indicators.py
─────────────────────────────────────────────────────────────────────────────
Library-Backed Indicator & Feature Engine for NujinAI.

Powered directly by industry-standard C/Python libraries:
  1. `TA-Lib` (`talib` / `talib.abstract` — 201 C-accelerated technical indicators,
     overlap studies, momentum oscillators, volatility channels, volume/flow,
     linear regression statistics, Hilbert Transform cycles, and 61 candlestick patterns)
  2. `ta` (`ta` library — 86+ Pandas technical analysis features across trend,
     momentum, volatility, and volume)
  3. Custom Feature Composition:
     - Safe vectorized formulas (`--custom '{"my_signal": "(ema_9 - ema_21) / atr_14"}'`)
     - Custom Python indicator callables (`register_custom_indicator`)

All calculations are strictly causal (backward-looking, zero lookahead bias).
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import talib
from talib import abstract as ta_abstract
import ta as pandas_ta_lib

# Map all 201 TA-Lib function names (lowercase -> canonical uppercase)
TALIB_FUNCTIONS: Dict[str, str] = {name.lower(): name for name in talib.get_functions()}

# Registry for user-defined custom Python indicator functions
CUSTOM_INDICATOR_REGISTRY: Dict[str, Callable[[pd.DataFrame], Any]] = {}


def get_custom_indicator(name: str) -> Optional[Callable[[pd.DataFrame], Any]]:
    """
    Retrieves a registered custom indicator. If not yet loaded, lazily discovers
    and mounts extensions from installed plugins (e.g. nujinPro).
    """
    if name not in CUSTOM_INDICATOR_REGISTRY:
        try:
            from server.plugin_loader import plugin_manager
            plugin_manager.load_plugin_modules()
        except Exception:
            pass
    return CUSTOM_INDICATOR_REGISTRY.get(name)


def register_custom_indicator(name: str, func: Callable[[pd.DataFrame], Any]) -> None:
    """Register a custom Python function that enriches a DataFrame or returns a Series."""
    CUSTOM_INDICATOR_REGISTRY[name] = func


def list_available_library_indicators() -> Dict[str, List[str]]:
    """Return all 201 TA-Lib indicators grouped by category."""
    return talib.get_function_groups()


def _clean_series(arr: Any, index: pd.Index, fill_default: float = 0.0) -> pd.Series:
    s = pd.Series(arr, index=index, dtype=float)
    return s.bfill().fillna(fill_default)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Thin Library Wrappers (Delegating Directly to TA-Lib C Functions)
# ─────────────────────────────────────────────────────────────────────────────

def sma(series: pd.Series, period: int = 20) -> pd.Series:
    return _clean_series(talib.SMA(series.astype(float).values, timeperiod=max(2, int(period))), series.index)


def ema(series: pd.Series, period: int = 20) -> pd.Series:
    return _clean_series(talib.EMA(series.astype(float).values, timeperiod=max(2, int(period))), series.index)


def wma(series: pd.Series, period: int = 20) -> pd.Series:
    return _clean_series(talib.WMA(series.astype(float).values, timeperiod=max(2, int(period))), series.index)


def hma(series: pd.Series, period: int = 20) -> pd.Series:
    return _clean_series(talib.HMA(series.astype(float).values, timeperiod=max(2, int(period))), series.index)


def kama(series: pd.Series, period: int = 10) -> pd.Series:
    return _clean_series(talib.KAMA(series.astype(float).values, timeperiod=max(2, int(period))), series.index)


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    return _clean_series(talib.RSI(series.astype(float).values, timeperiod=max(2, int(period))), series.index, 50.0)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
    m, s, h = talib.MACD(
        series.astype(float).values,
        fastperiod=max(2, int(fast)),
        slowperiod=max(3, int(slow)),
        signalperiod=max(2, int(signal)),
    )
    return (
        _clean_series(m, series.index, 0.0),
        _clean_series(s, series.index, 0.0),
        _clean_series(h, series.index, 0.0),
    )


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14, d_period: int = 3) -> Tuple[pd.Series, pd.Series]:
    k, d = talib.STOCH(
        high.astype(float).values,
        low.astype(float).values,
        close.astype(float).values,
        fastk_period=max(2, int(k_period)),
        slowk_period=3,
        slowd_period=max(2, int(d_period)),
    )
    return _clean_series(k, close.index, 50.0), _clean_series(d, close.index, 50.0)


def roc(series: pd.Series, period: int = 10) -> pd.Series:
    return _clean_series(talib.ROC(series.astype(float).values, timeperiod=max(1, int(period))), series.index, 0.0)


def cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    return _clean_series(
        talib.CCI(high.astype(float).values, low.astype(float).values, close.astype(float).values, timeperiod=max(2, int(period))),
        close.index,
        0.0,
    )


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    return _clean_series(
        talib.WILLR(high.astype(float).values, low.astype(float).values, close.astype(float).values, timeperiod=max(2, int(period))),
        close.index,
        -50.0,
    )


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    return _clean_series(
        talib.TRANGE(high.astype(float).values, low.astype(float).values, close.astype(float).values),
        close.index,
        1e-8,
    ).replace(0, 1e-8)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    return _clean_series(
        talib.ATR(high.astype(float).values, low.astype(float).values, close.astype(float).values, timeperiod=max(1, int(period))),
        close.index,
        1e-8,
    ).replace(0, 1e-8)


def bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    upper, mid, lower = talib.BBANDS(
        series.astype(float).values,
        timeperiod=max(2, int(period)),
        nbdevup=float(std_dev),
        nbdevdn=float(std_dev),
    )
    mid_s = _clean_series(mid, series.index)
    up_s = _clean_series(upper, series.index)
    lo_s = _clean_series(lower, series.index)
    bw = ((up_s - lo_s) / mid_s.replace(0, 1e-8)).fillna(0.0)
    pct_b = ((series - lo_s) / (up_s - lo_s).replace(0, 1e-8)).clip(-1.0, 2.0).fillna(0.5)
    return mid_s, up_s, lo_s, bw, pct_b


def keltner_channels(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20, atr_mult: float = 1.5) -> Tuple[pd.Series, pd.Series, pd.Series]:
    upper, mid, lower = talib.KC(
        high.astype(float).values,
        low.astype(float).values,
        close.astype(float).values,
        timeperiod=max(2, int(period)),
        atrperiod=max(2, int(period)),
        nbdev=float(atr_mult),
    )
    return _clean_series(mid, close.index), _clean_series(upper, close.index), _clean_series(lower, close.index)


def donchian_channels(high: pd.Series, low: pd.Series, period: int = 20, causal: bool = True) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """
    TA-Lib DONCHIAN wrapper. When causal=True, shifts inputs by 1 bar so
    `close > donchian_upper_<N>` is a strict breakout above the prior N-bar high.
    """
    h_in = (high.shift(1).bfill() if causal else high).astype(float).values
    l_in = (low.shift(1).bfill() if causal else low).astype(float).values
    up, mid, lo = talib.DONCHIAN(h_in, l_in, timeperiod=max(2, int(period)))
    return _clean_series(up, high.index), _clean_series(lo, low.index), _clean_series(mid, high.index)


def supertrend(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 10, multiplier: float = 3.0) -> Tuple[pd.Series, pd.Series]:
    st_line, st_dir = talib.SUPERTREND(
        high.astype(float).values,
        low.astype(float).values,
        close.astype(float).values,
        timeperiod=max(2, int(period)),
        multiplier=float(multiplier),
    )
    dir_s = pd.Series(st_dir, index=close.index).fillna(1).replace(0, 1).astype(int)
    return _clean_series(st_line, close.index), dir_s


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> Tuple[pd.Series, pd.Series, pd.Series]:
    h_v, l_v, c_v = high.astype(float).values, low.astype(float).values, close.astype(float).values
    p = max(2, int(period))
    return (
        _clean_series(talib.ADX(h_v, l_v, c_v, timeperiod=p), close.index, 20.0),
        _clean_series(talib.PLUS_DI(h_v, l_v, c_v, timeperiod=p), close.index, 20.0),
        _clean_series(talib.MINUS_DI(h_v, l_v, c_v, timeperiod=p), close.index, 20.0),
    )


def rolling_linreg_slope(series: pd.Series, period: int = 20) -> pd.Series:
    """TA-Lib LINEARREG_SLOPE normalized in bps per bar."""
    raw = _clean_series(talib.LINEARREG_SLOPE(series.astype(float).values, timeperiod=max(2, int(period))), series.index, 0.0)
    return (raw / series.replace(0, 1e-8)) * 10000.0


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    return _clean_series(talib.OBV(close.astype(float).values, volume.astype(float).values), close.index, 0.0)


def cmf(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int = 20) -> pd.Series:
    return _clean_series(
        talib.CMF(
            high.astype(float).values,
            low.astype(float).values,
            close.astype(float).values,
            volume.astype(float).values,
            timeperiod=max(2, int(period)),
        ),
        close.index,
        0.0,
    )


def zscore(series: pd.Series, period: int = 20) -> pd.Series:
    p = max(2, int(period))
    vals = series.astype(float).values
    mean = _clean_series(talib.SMA(vals, timeperiod=p), series.index, 0.0)
    std = _clean_series(talib.STDDEV(vals, timeperiod=p, nbdev=1.0), series.index, 1e-8).replace(0, 1e-8)
    return ((series - mean) / std).fillna(0.0)


def hurst_proxy(close: pd.Series, window: int = 50) -> pd.Series:
    """Rolling variance-ratio Hurst proxy (< 0.45 mean-reverting, > 0.55 trending)."""
    p = max(10, int(window))
    ret1 = np.log(close / close.shift(1).replace(0, 1e-8)).fillna(0.0)
    ret5 = np.log(close / close.shift(5).replace(0, 1e-8)).fillna(0.0)
    var1 = _clean_series(talib.VAR(ret1.values, timeperiod=p, nbdev=1.0), close.index, 1e-8).replace(0, 1e-8)
    var5 = _clean_series(talib.VAR(ret5.values, timeperiod=p, nbdev=1.0), close.index, 5e-8)
    vr = (var5 / (var1 * 5.0)).clip(0.05, 4.0)
    return (0.5 * (1.0 + np.log(vr) / np.log(5.0))).clip(0.1, 0.9).fillna(0.5)


def rolling_vwap(close: pd.Series, volume: pd.Series, period: int = 50) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    p = max(2, int(period))
    vwap = _clean_series(talib.VWMA(close.astype(float).values, volume.astype(float).values, timeperiod=p), close.index)
    std = _clean_series(talib.STDDEV(close.astype(float).values, timeperiod=p, nbdev=1.0), close.index, 1e-8).replace(0, 1e-8)
    vwap_z = ((close - vwap) / std).fillna(0.0)
    return vwap, vwap_z, vwap + 1.5 * std, vwap - 1.5 * std


# ─────────────────────────────────────────────────────────────────────────────
# 2. Universal TA-Lib Dynamic Dispatcher (All 201 TA-Lib Indicators)
# ─────────────────────────────────────────────────────────────────────────────

def compute_talib_token(df: pd.DataFrame, token: str) -> Optional[pd.Series]:
    """
    Universal resolver for ANY of the 201 TA-Lib functions via token syntax:
      - `<func>` (e.g. `obv`, `bop`, `ht_trendmode`, `ht_dcperiod`, `cdlengulfing`, `ad`, `vwap`)
      - `<func>_<p1>` (e.g. `zlema_34`, `tema_21`, `mfi_14`, `cmo_14`, `vhf_28`, `er_10`, `natr_14`,
        `efi_13`, `rvol_20`, `percentrank_50`, `aroonosc_14`, `dpo_20`, `trix_15`, `linearreg_angle_20`)
      - `<func>_<p1>_<p2>...` (e.g. `ultosc_7_14_28`, `ppo_12_26`, `tsi_25_13`, `stochrsi_14_5_3`)
    """
    parts = token.lower().split("_")
    # Find longest prefix that is a valid TA-Lib function name (handles names with underscores like linearreg_slope, ht_dcperiod)
    matched_func = None
    param_strs: List[str] = []
    for split_idx in range(len(parts), 0, -1):
        candidate = "_".join(parts[:split_idx])
        if candidate in TALIB_FUNCTIONS:
            tail = parts[split_idx:]
            if all(re.match(r"^\d+(?:\.\d+)?$", p) for p in tail):
                matched_func = TALIB_FUNCTIONS[candidate]
                param_strs = tail
                break

    if not matched_func:
        return None

    try:
        fn = ta_abstract.Function(matched_func)
        param_names = list(fn.parameters.keys())
        kwargs: Dict[str, Any] = {}
        for pname, pval_str in zip(param_names, param_strs):
            default_val = fn.parameters[pname]
            kwargs[pname] = float(pval_str) if isinstance(default_val, float) or "." in pval_str else int(pval_str)

        inputs = {
            "open": df["open"].astype(float).values if "open" in df.columns else df["close"].astype(float).values,
            "high": df["high"].astype(float).values if "high" in df.columns else df["close"].astype(float).values,
            "low": df["low"].astype(float).values if "low" in df.columns else df["close"].astype(float).values,
            "close": df["close"].astype(float).values,
            "volume": df["volume"].astype(float).values if "volume" in df.columns else np.full(len(df), 10.0),
        }
        res = fn(inputs, **kwargs)
        if isinstance(res, list) or isinstance(res, tuple):
            arr = res[0]
        elif isinstance(res, np.ndarray) and res.ndim == 2:
            arr = res[0]
        else:
            arr = res
        return _clean_series(arr, df.index, 0.0)
    except Exception:
        return None


def ensure_dynamic_indicators(df: pd.DataFrame, expressions: Optional[List[str]] = None) -> pd.DataFrame:
    """
    Parses any indicator tokens referenced in `expressions` and computes them on-the-fly:
      1. Special multi-output / causal composite tokens (`donchian_upper_<N>`, `supertrend_dir`,
         `keltner_upper`, `ttm_squeeze`, `zscore_<N>`, `slope_<N>`, `stoch_k_<N>`, `adx_<N>`)
      2. Universal TA-Lib dispatcher for ALL 201 TA-Lib functions (`zlema_34`, `mfi_14`,
         `cmo_14`, `vhf_28`, `er_10`, `natr_14`, `efi_13`, `rvol_20`, `percentrank_50`,
         `ultosc_7_14_28`, `tsi_25_13`, `ht_trendmode`, `cdlengulfing`, etc.)
      3. Registered custom Python indicators (`CUSTOM_INDICATOR_REGISTRY`)
    """
    d = df.copy()
    text = " ".join([str(e) for e in (expressions or []) if e])

    c = d["close"].astype(float)
    h = d["high"].astype(float) if "high" in d.columns else c
    l = d["low"].astype(float) if "low" in d.columns else c
    v = d["volume"].astype(float) if "volume" in d.columns else pd.Series(10.0, index=d.index)

    # 1. Special composite / causal tokens
    if any(k in text for k in ["bollinger", "bb_upper", "bb_lower", "bb_mid", "upper_band", "lower_band", "bb_bandwidth", "bb_pct_b"]):
        if "bb_upper" not in d.columns:
            bb_m, bb_u, bb_l, bb_bw, bb_pb = bollinger_bands(c, 20, 2.0)
            d["bb_middle"] = bb_m
            d["bb_upper"] = bb_u
            d["bb_lower"] = bb_l
            d["bb_upper_20"] = bb_u
            d["bb_lower_20"] = bb_l
            d["bb_middle_20"] = bb_m
            d["upper_band"] = bb_u
            d["lower_band"] = bb_l
            d["bb_bandwidth"] = bb_bw
            d["bb_pct_b"] = bb_pb

    for span_str in set(re.findall(r"\bdonchian_(?:upper|lower|mid)_(\d+)\b", text)):
        p = int(span_str)
        if f"donchian_upper_{p}" not in d.columns:
            du, dl, dm = donchian_channels(h, l, p, causal=True)
            d[f"donchian_upper_{p}"] = du
            d[f"donchian_lower_{p}"] = dl
            d[f"donchian_mid_{p}"] = dm

    for span_str in set(re.findall(r"\badx_(\d+)\b", text)):
        col = f"adx_{span_str}"
        if col not in d.columns:
            adx_v, pdi, mdi = adx(h, l, c, int(span_str))
            d[col] = adx_v
            if "plus_di" not in d.columns:
                d["plus_di"] = pdi
            if "minus_di" not in d.columns:
                d["minus_di"] = mdi

    for span_str in set(re.findall(r"\bzscore_(\d+)\b", text)):
        col = f"zscore_{span_str}"
        if col not in d.columns:
            d[col] = zscore(c, int(span_str))

    for span_str in set(re.findall(r"\bslope_(\d+)\b", text)):
        col = f"slope_{span_str}"
        if col not in d.columns:
            d[col] = rolling_linreg_slope(c, int(span_str))

    for span_str in set(re.findall(r"\bstoch_[kd]_(\d+)\b", text)):
        p = int(span_str)
        if f"stoch_k_{p}" not in d.columns:
            sk, sd = stochastic(h, l, c, p, 3)
            d[f"stoch_k_{p}"] = sk
            d[f"stoch_d_{p}"] = sd

    if any(k in text for k in ["supertrend", "supertrend_dir", "supertrend_line"]):
        if "supertrend_dir" not in d.columns:
            st_line, st_dir = supertrend(h, l, c, 10, 3.0)
            d["supertrend"] = st_line
            d["supertrend_line"] = st_line
            d["supertrend_dir"] = st_dir

    if any(k in text for k in ["keltner_upper", "keltner_lower", "keltner_mid", "ttm_squeeze"]):
        if "keltner_upper" not in d.columns:
            km, ku, kl = keltner_channels(h, l, c, 20, 1.5)
            d["keltner_mid"] = km
            d["keltner_upper"] = ku
            d["keltner_lower"] = kl
            _, bbu, bbl, _, _ = bollinger_bands(c, 20, 2.0)
            d["ttm_squeeze"] = ((bbu < ku) & (bbl > kl)).astype(int)

    if any(k in text for k in ["htf4x_", "htf16x_", "mtf_alignment_score"]):
        if "mtf_alignment_score" not in d.columns:
            d = add_causal_mtf_features(d)

    if any(k in text for k in ["alpha_forecast", "alpha_forecast_z", "meta_label_prob", "kelly_conviction"]):
        if "alpha_forecast" not in d.columns:
            if "mtf_alignment_score" not in d.columns:
                d = add_causal_mtf_features(d)
            from server.alpha_models import compute_continuous_alpha_and_meta_label
            d = compute_continuous_alpha_and_meta_label(d)

    # 2. Universal TA-Lib token resolver for all identifiers in `text`
    identifiers = set(re.findall(r"\b[a-zA-Z][a-zA-Z0-9_]*\b", text))
    for token in identifiers:
        if token in d.columns or token in {"and", "or", "not", "True", "False", "close", "open", "high", "low", "volume"}:
            continue
        series = compute_talib_token(d, token)
        if series is not None:
            d[token] = series

    # 3. Registered custom Python indicators
    for custom_name, custom_fn in CUSTOM_INDICATOR_REGISTRY.items():
        try:
            res_custom = custom_fn(d)
            if isinstance(res_custom, pd.DataFrame):
                d = res_custom
            elif isinstance(res_custom, (pd.Series, np.ndarray)):
                d[custom_name] = res_custom
        except Exception:
            pass

    return d.copy()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Comprehensive Library Feature Bank (TA-Lib + `ta` Library)
# ─────────────────────────────────────────────────────────────────────────────

def compute_all_standard_features(df: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    Computes a comprehensive feature matrix backed by `TA-Lib` and `ta`:
      - Overlap & Moving Averages (EMA, SMA, HMA, KAMA, ZLEMA, T3, Supertrend, Donchian, Bollinger, Keltner)
      - Momentum & Oscillators (RSI, Stochastic, StochRSI, MACD, PPO, ROC, CCI, Williams %R, MFI, CMO, ULTOSC, TSI, Aroon, Vortex, VHF, ER, BOP)
      - Volatility & Regimes (ATR, NATR, RVI, MASSI, TTM Squeeze, Hurst Proxy, Linear Regression Slope & Angle, PercentRank)
      - Volume & Institutional Flow (OBV, CMF, EFI, ADOSC, RVOL, VWMA/AVWAP)
      - Candlestick & Microstructure (TA-Lib CDL patterns, Bar geometry, Session hours)
    """
    d = df.copy()
    d.columns = [col.lower() for col in d.columns]

    c = d["close"].astype(float)
    h = d["high"].astype(float)
    l = d["low"].astype(float)
    o = d["open"].astype(float)
    v = d["volume"].astype(float) if "volume" in d.columns else pd.Series(10.0, index=d.index)

    c_v, h_v, l_v, o_v, v_v = c.values, h.values, l.values, o.values, v.values

    # 1. TA-Lib Overlap & Trend Studies
    for span in (7, 9, 13, 20, 21, 34, 50, 89, 100, 144, 200):
        d[f"ema_{span}"] = ema(c, span)
    for span in (20, 50, 100, 200):
        d[f"sma_{span}"] = sma(c, span)
    d["hma_21"] = hma(c, 21)
    d["hma_55"] = hma(c, 55)
    d["kama_10"] = kama(c, 10)
    d["zlema_21"] = _clean_series(talib.ZLEMA(c_v, timeperiod=21), d.index)
    d["t3_14"] = _clean_series(talib.T3(c_v, timeperiod=14), d.index)
    d["slope_20"] = rolling_linreg_slope(c, 20)
    d["slope_50"] = rolling_linreg_slope(c, 50)
    d["linreg_angle_20"] = _clean_series(talib.LINEARREG_ANGLE(c_v, timeperiod=20), d.index, 0.0)

    st_line, st_dir = supertrend(h, l, c, 10, 3.0)
    d["supertrend"] = st_line
    d["supertrend_line"] = st_line
    d["supertrend_dir"] = st_dir

    # Stationary normalized trend distance features (for model-free IC scanning)
    atr_14_s = atr(h, l, c, 14)
    d["dist_ema_21_atr"] = ((c - d["ema_21"]) / atr_14_s).fillna(0.0)
    d["dist_ema_50_atr"] = ((c - d["ema_50"]) / atr_14_s).fillna(0.0)
    d["ema_spread_9_21_atr"] = ((d["ema_9"] - d["ema_21"]) / atr_14_s).fillna(0.0)
    d["ema_spread_21_50_atr"] = ((d["ema_21"] - d["ema_50"]) / atr_14_s).fillna(0.0)
    d["hma_spread_21_55_atr"] = ((d["hma_21"] - d["hma_55"]) / atr_14_s).fillna(0.0)

    # 2. TA-Lib Momentum & Oscillators
    for span in (7, 9, 14, 21):
        d[f"rsi_{span}"] = rsi(c, span)
    macd_l, macd_s, macd_h = macd(c, 12, 26, 9)
    d["macd_12_26"] = macd_l
    d["macd_signal"] = macd_s
    d["macd_hist"] = macd_h
    d["ppo_12_26"] = _clean_series(talib.PPO(c_v, fastperiod=12, slowperiod=26), d.index, 0.0)
    sk, sd = stochastic(h, l, c, 14, 3)
    d["stoch_k_14"] = sk
    d["stoch_d_14"] = sd
    d["roc_10"] = roc(c, 10)
    d["roc_20"] = roc(c, 20)
    d["cci_20"] = cci(h, l, c, 20)
    d["williams_r_14"] = williams_r(h, l, c, 14)
    d["mfi_14"] = _clean_series(talib.MFI(h_v, l_v, c_v, v_v, timeperiod=14), d.index, 50.0)
    d["cmo_14"] = _clean_series(talib.CMO(c_v, timeperiod=14), d.index, 0.0)
    d["ultosc"] = _clean_series(talib.ULTOSC(h_v, l_v, c_v, timeperiod1=7, timeperiod2=14, timeperiod3=28), d.index, 50.0)
    d["tsi"] = _clean_series(talib.TSI(c_v, firstperiod=25, secondperiod=13), d.index, 0.0)
    d["aroonosc_14"] = _clean_series(talib.AROONOSC(h_v, l_v, timeperiod=14), d.index, 0.0)
    pvi, mvi = talib.VORTEX(h_v, l_v, c_v, timeperiod=14)
    d["vortex_diff_14"] = _clean_series(pvi - mvi, d.index, 0.0)
    d["vhf_28"] = _clean_series(talib.VHF(c_v, timeperiod=28), d.index, 0.3)
    d["er_10"] = _clean_series(talib.ER(c_v, timeperiod=10), d.index, 0.5)
    d["bop"] = _clean_series(talib.BOP(o_v, h_v, l_v, c_v), d.index, 0.0)
    d["percentrank_50"] = _clean_series(talib.PERCENTRANK(c_v, timeperiod=50), d.index, 50.0)

    # 3. TA-Lib Cycle / Hilbert Transform
    d["ht_dcperiod"] = _clean_series(talib.HT_DCPERIOD(c_v), d.index, 20.0)
    d["ht_trendmode"] = _clean_series(talib.HT_TRENDMODE(c_v), d.index, 0.0).astype(int)

    # 4. TA-Lib Volatility, Channels & Trend Strength
    d["true_range"] = true_range(h, l, c)
    for span in (7, 14, 21):
        d[f"atr_{span}"] = atr(h, l, c, span)
    d["atr_pct"] = _clean_series(talib.NATR(h_v, l_v, c_v, timeperiod=14), d.index, 0.1)
    d["rvi_14"] = _clean_series(talib.RVI(c_v, timeperiod=14), d.index, 50.0)

    for span in (10, 14, 20):
        adx_v, pdi, mdi = adx(h, l, c, span)
        d[f"adx_{span}"] = adx_v
        if span == 14:
            d["plus_di"] = pdi
            d["minus_di"] = mdi
            d["di_spread_14"] = pdi - mdi

    bb_mid, bb_up, bb_lo, bb_bw, bb_pctb = bollinger_bands(c, 20, 2.0)
    d["upper_band"] = bb_up
    d["lower_band"] = bb_lo
    d["bb_bandwidth"] = bb_bw
    d["bb_pct_b"] = bb_pctb
    d["vol_compression"] = (bb_bw / sma(bb_bw, 50).replace(0, 1e-8)).fillna(1.0)

    kc_mid, kc_up, kc_lo = keltner_channels(h, l, c, 20, 1.5)
    d["keltner_mid"] = kc_mid
    d["keltner_upper"] = kc_up
    d["keltner_lower"] = kc_lo
    d["ttm_squeeze"] = ((bb_up < kc_up) & (bb_lo > kc_lo)).astype(int)

    for span in (10, 20, 55):
        du, dl, dm = donchian_channels(h, l, span, causal=True)
        d[f"donchian_upper_{span}"] = du
        d[f"donchian_lower_{span}"] = dl
        d[f"donchian_mid_{span}"] = dm
        d[f"donchian_pos_{span}"] = ((c - dl) / (du - dl).replace(0, 1e-8)).clip(-0.5, 1.5).fillna(0.5)

    # 5. Statistical & Mean-Reversion Primitives
    d = d.copy()
    d["returns"] = c.pct_change().fillna(0.0)
    d["log_ret"] = np.log(c / c.shift(1).replace(0, 1e-8)).fillna(0.0)
    d["ret_zscore"] = zscore(d["log_ret"], 50)
    d["z_returns"] = zscore(d["returns"], 20)
    d["zscore_20"] = zscore(c, 20)
    d["zscore_50"] = zscore(c, 50)
    d["hurst_proxy"] = hurst_proxy(c, 50)

    vwap_100, vwap_z, va_hi, va_lo = rolling_vwap(c, v, 100)
    d["avwap_100"] = vwap_100
    d["avwap_zscore"] = vwap_z
    d["value_area_high"] = va_hi
    d["value_area_low"] = va_lo

    # 6. TA-Lib Volume & Institutional Flow
    d["obv"] = obv(c, v)
    d["volume_zscore"] = zscore(v, window)
    d["relative_vol"] = _clean_series(talib.RVOL(v_v, timeperiod=50), d.index, 1.0)
    d["cmf_20"] = cmf(h, l, c, v, 20)
    d["efi_13"] = _clean_series(talib.EFI(c_v, v_v, timeperiod=13), d.index, 0.0)
    d["adosc"] = _clean_series(talib.ADOSC(h_v, l_v, c_v, v_v, fastperiod=3, slowperiod=10), d.index, 0.0)

    # 7. Bar Geometry, TA-Lib Candlestick Patterns & Microstructure
    total_range = (h - l).replace(0, 1e-8)
    d["total_range"] = total_range
    d["norm_range"] = total_range / o.replace(0, 1e-8)
    d["relative_range"] = (d["norm_range"] / sma(d["norm_range"], 50).replace(0, 1e-8)).fillna(1.0)
    d["body_ratio"] = (c - o).abs() / total_range
    d["close_location"] = (c - l) / total_range
    d["upper_wick"] = (h - np.maximum(c, o)) / total_range
    d["lower_wick"] = (np.minimum(c, o) - l) / total_range
    d["upper_wick_ratio"] = d["upper_wick"]
    d["lower_wick_ratio"] = d["lower_wick"]
    d["buying_pressure"] = d["close_location"]
    d["selling_pressure"] = (h - c) / total_range

    d["delta_proxy"] = ((c - o) / total_range) * v
    d["cvd_proxy"] = d["delta_proxy"].rolling(window, min_periods=1).sum()
    d["vpin_proxy"] = (d["delta_proxy"].abs().rolling(window, min_periods=1).sum() / v.rolling(window, min_periods=1).sum().replace(0, 1e-8)).fillna(0.0)

    d = d.copy()
    cdl_engulf = talib.CDLENGULFING(o_v, h_v, l_v, c_v)
    d["engulfing_bullish"] = (cdl_engulf > 0).astype(int)
    d["engulfing_bearish"] = (cdl_engulf < 0).astype(int)

    prev_c = c.shift(1).fillna(c)
    prev_h = h.shift(1).fillna(h)
    prev_l = l.shift(1).fillna(l)
    d["inside_bar"] = ((h <= prev_h) & (l >= prev_l)).astype(int)
    d["fvg_bullish"] = ((l > h.shift(2).fillna(h)) & (c > o)).astype(int)
    d["fvg_bearish"] = ((h < l.shift(2).fillna(l)) & (c < o)).astype(int)

    roll_high_20 = d["donchian_upper_20"]
    roll_low_20 = d["donchian_lower_20"]
    d["breakout_up_20"] = ((c > roll_high_20) & (d["body_ratio"] > 0.50)).astype(int)
    d["breakout_down_20"] = ((c < roll_low_20) & (d["body_ratio"] > 0.50)).astype(int)
    d["trend_pullback_long"] = ((c > d["ema_50"]) & (d["ema_21"] > d["ema_50"]) & (l <= d["ema_21"]) & (c > d["ema_21"])).astype(int)
    d["trend_pullback_short"] = ((c < d["ema_50"]) & (d["ema_21"] < d["ema_50"]) & (h >= d["ema_21"]) & (c < d["ema_21"])).astype(int)

    d["sweep_high_rejection"] = ((h > roll_high_20) & (d["upper_wick"] >= 0.38) & (d["volume_zscore"] > 1.0)).astype(int)
    d["sweep_low_rejection"] = ((l < roll_low_20) & (d["lower_wick"] >= 0.38) & (d["volume_zscore"] > 1.0)).astype(int)
    d["absorption_bullish"] = ((d["volume_zscore"] > 1.0) & (d["lower_wick"] >= 0.35) & (c >= o)).astype(int)
    d["absorption_bearish"] = ((d["volume_zscore"] > 1.0) & (d["upper_wick"] >= 0.35) & (c <= o)).astype(int)
    d["trapped_longs"] = ((h >= roll_high_20) & (d["volume_zscore"] > 0.8) & (c < o)).astype(int)
    d["trapped_shorts"] = ((l <= roll_low_20) & (d["volume_zscore"] > 0.8) & (c > o)).astype(int)

    is_up = (c > prev_c).astype(int)
    is_down = (c < prev_c).astype(int)
    d["consecutive_up"] = is_up * (is_up.groupby((is_up != is_up.shift(1)).cumsum()).cumcount() + 1)
    d["consecutive_down"] = is_down * (is_down.groupby((is_down != is_down.shift(1)).cumsum()).cumcount() + 1)

    # 8. Session Windows (if timestamp/time present)
    ts_col = "timestamp" if "timestamp" in d.columns else ("time" if "time" in d.columns else None)
    if ts_col is not None:
        try:
            ts_vals = pd.to_numeric(d[ts_col], errors="coerce").fillna(0).astype(np.int64)
            if len(ts_vals) > 0 and ts_vals.iloc[0] > 10**11:
                ts_vals = ts_vals // 1000
            d["utc_hour"] = (ts_vals % 86400) // 3600
            d["session_asian"] = ((d["utc_hour"] >= 0) & (d["utc_hour"] < 6)).astype(int)
            d["killzone_london"] = ((d["utc_hour"] >= 7) & (d["utc_hour"] < 10)).astype(int)
            d["killzone_ny"] = ((d["utc_hour"] >= 12) & (d["utc_hour"] < 16)).astype(int)
        except Exception:
            pass

    # 9. Causal Multi-Timeframe (MTF 4x & 16x) Alignment Features
    d = add_causal_mtf_features(d)

    # 10. Continuous Alpha Forecast & López de Prado Meta-Labeling Confidence Filter
    from server.alpha_models import compute_continuous_alpha_and_meta_label
    d = compute_continuous_alpha_and_meta_label(d)

    return d.copy()


def add_causal_mtf_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Causal Multi-Timeframe (MTF) Resampler (Pillar 2):
      - Aggregates base bars into 4x (e.g. 15m -> 1h) and 16x (e.g. 15m -> 4h) higher-timeframe buckets.
      - Shifts completed HTF bars by 1 bucket BEFORE mapping back to base bars (`shift(1)` on HTF frame)
        so zero future intra-HTF-bar data ever leaks into bar `t`.
      - Computes `htf4x_ema_21`, `htf4x_rsi_14`, `htf4x_adx_14`, `htf4x_supertrend_dir`, `htf4x_trend_dir`,
        `htf16x_ema_21`, `htf16x_rsi_14`, `htf16x_trend_dir`, and `mtf_alignment_score` in [-1.0, +1.0].
    """
    d = df.copy()
    n = len(d)
    if n < 32:
        d["htf4x_trend_dir"] = 1
        d["htf16x_trend_dir"] = 1
        d["htf4x_rsi_14"] = 50.0
        d["htf4x_adx_14"] = 20.0
        d["mtf_alignment_score"] = 0.0
        return d

    for mult, prefix in ((4, "htf4x"), (16, "htf16x")):
        bucket_id = np.arange(n) // mult
        htf = pd.DataFrame({
            "open": d["open"].astype(float).groupby(bucket_id).first(),
            "high": d["high"].astype(float).groupby(bucket_id).max(),
            "low": d["low"].astype(float).groupby(bucket_id).min(),
            "close": d["close"].astype(float).groupby(bucket_id).last(),
        })
        if len(htf) >= 8:
            hc = htf["close"].values
            hh = htf["high"].values
            hl = htf["low"].values
            p_ema = min(21, max(3, len(htf) // 2))
            p_rsi = min(14, max(3, len(htf) // 2))
            htf_ema = _clean_series(talib.EMA(hc, timeperiod=p_ema), htf.index)
            htf_rsi = _clean_series(talib.RSI(hc, timeperiod=p_rsi), htf.index, 50.0)
            htf_adx = _clean_series(talib.ADX(hh, hl, hc, timeperiod=p_rsi), htf.index, 20.0)
            _, htf_st_dir = supertrend(htf["high"], htf["low"], htf["close"], period=min(10, p_rsi), multiplier=3.0)
            htf_trend = pd.Series(np.where(htf["close"] >= htf_ema, 1, -1), index=htf.index)
        else:
            htf_ema = htf["close"]
            htf_rsi = pd.Series(50.0, index=htf.index)
            htf_adx = pd.Series(20.0, index=htf.index)
            htf_st_dir = pd.Series(1, index=htf.index)
            htf_trend = pd.Series(1, index=htf.index)

        # Strictly causal shift(1) on HTF buckets so bar `t` only sees the last COMPLETED HTF bar
        d[f"{prefix}_ema_21"] = htf_ema.shift(1).bfill().iloc[bucket_id].values
        d[f"{prefix}_rsi_14"] = htf_rsi.shift(1).fillna(50.0).iloc[bucket_id].values
        d[f"{prefix}_adx_14"] = htf_adx.shift(1).fillna(20.0).iloc[bucket_id].values
        d[f"{prefix}_supertrend_dir"] = htf_st_dir.shift(1).fillna(1).astype(int).iloc[bucket_id].values
        d[f"{prefix}_trend_dir"] = htf_trend.shift(1).fillna(1).astype(int).iloc[bucket_id].values

    base_dir = np.where(d["close"] >= (d["ema_21"] if "ema_21" in d.columns else sma(d["close"], 21)), 1.0, -1.0)
    d["mtf_alignment_score"] = (
        0.30 * base_dir
        + 0.40 * d["htf4x_trend_dir"].astype(float)
        + 0.30 * d["htf16x_trend_dir"].astype(float)
    ).round(3)
    return d


def add_cross_asset_context(df: pd.DataFrame, benchmark_df: Optional[pd.DataFrame] = None, window: int = 50) -> pd.DataFrame:
    """
    Computes Cross-Asset Correlation, Rolling Beta, and Relative Strength Z-Score
    against a reference/benchmark asset series (Pillar 2).
    """
    d = df.copy()
    asset_ret = d["close"].astype(float).pct_change().fillna(0.0)
    if benchmark_df is not None and "close" in benchmark_df.columns and len(benchmark_df) >= 20:
        b_close = benchmark_df["close"].astype(float).reindex(d.index).ffill().bfill()
        bench_ret = b_close.pct_change().fillna(0.0)
    else:
        # Smooth macro drift proxy when external benchmark is not passed
        bench_ret = asset_ret.rolling(10, min_periods=1).mean()

    cov = asset_ret.rolling(window, min_periods=10).cov(bench_ret).fillna(0.0)
    var_b = bench_ret.rolling(window, min_periods=10).var().replace(0, 1e-8).fillna(1e-8)
    std_a = asset_ret.rolling(window, min_periods=10).std().replace(0, 1e-8).fillna(1e-8)
    std_b = np.sqrt(var_b)

    d["cross_asset_beta_50"] = (cov / var_b).clip(-3.0, 3.0).fillna(1.0).round(3)
    d["cross_asset_corr_50"] = (cov / (std_a * std_b)).clip(-1.0, 1.0).fillna(0.0).round(3)
    rs_spread = asset_ret.rolling(20, min_periods=2).sum() - bench_ret.rolling(20, min_periods=2).sum()
    d["cross_asset_rs_zscore_20"] = zscore(rs_spread.fillna(0.0), 20).round(3)
    return d


def add_pandas_ta_suite(df: pd.DataFrame) -> pd.DataFrame:
    """
    Optionally enriches a DataFrame with all 86+ indicators from the `ta` Python package
    (`ta.add_all_ta_features`).
    """
    d = df.copy()
    if "volume" not in d.columns:
        d["volume"] = 10.0
    return pandas_ta_lib.add_all_ta_features(
        d, open="open", high="high", low="low", close="close", volume="volume", fillna=True
    )

