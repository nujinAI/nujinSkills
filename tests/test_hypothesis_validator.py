"""
Unit tests for core.hypothesis_validator and causal swing detection in core.market_structure.
"""
import numpy as np
import pandas as pd

from core.hypothesis_validator import (
    check_causality_prefix_invariance,
    check_feature_collinearity,
    profile_market_microstructure,
    validate_strategy_in_sample,
)
from core.market_structure import detect_swing_points


def _make_ohlcv(n: int = 400, seed: int = 7, drift: float = 0.0005) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    rets = rng.normal(drift, 0.004, size=n)
    close = 2500.0 * np.exp(np.cumsum(rets))
    open_p = np.roll(close, 1)
    open_p[0] = close[0]
    span = np.abs(rng.normal(4.0, 1.5, size=n)) + 1.0
    high = np.maximum(open_p, close) + span * 0.5
    low = np.minimum(open_p, close) - span * 0.5
    vol = rng.integers(100, 1000, size=n).astype(float)
    return pd.DataFrame(
        {"open": open_p, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


class _CausalDummyStrategy:
    symbol = "OANDA:XAUUSD"
    timeframe = "15m"

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        c = df["close"].astype(float)
        h = df["high"].astype(float)
        l = df["low"].astype(float)
        ma = c.rolling(20, min_periods=20).mean()
        atr = (h - l).rolling(14, min_periods=14).mean().bfill()
        sigs = pd.DataFrame(index=df.index)
        sigs["entry_signal"] = 0
        sigs["stop_loss"] = 0.0
        sigs["target"] = 0.0

        long_c = (c > ma) & (c.shift(1) <= ma.shift(1))
        short_c = (c < ma) & (c.shift(1) >= ma.shift(1))
        sigs.loc[long_c, "entry_signal"] = 1
        sigs.loc[long_c, "stop_loss"] = c[long_c] - 2.0 * atr[long_c]
        sigs.loc[long_c, "target"] = c[long_c] + 3.0 * atr[long_c]
        sigs.loc[short_c, "entry_signal"] = -1
        sigs.loc[short_c, "stop_loss"] = c[short_c] + 2.0 * atr[short_c]
        sigs.loc[short_c, "target"] = c[short_c] - 3.0 * atr[short_c]
        return sigs


class _LeakyLookaheadStrategy:
    symbol = "OANDA:XAUUSD"
    timeframe = "15m"

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        c = df["close"].astype(float)
        # Deliberate future leak: uses shift(-1)
        future_up = c.shift(-1) > c
        sigs = pd.DataFrame(index=df.index)
        sigs["entry_signal"] = 0
        sigs["stop_loss"] = 0.0
        sigs["target"] = 0.0
        sigs.loc[future_up, "entry_signal"] = 1
        sigs.loc[future_up, "stop_loss"] = c[future_up] - 5.0
        sigs.loc[future_up, "target"] = c[future_up] + 10.0
        return sigs


def test_causal_swing_points_prefix_invariance():
    df = _make_ohlcv(200)
    full = detect_swing_points(df, left_bars=3, right_bars=3, causal=True)
    for cutoff in (80, 120, 160, 195):
        sub = detect_swing_points(df.iloc[:cutoff], left_bars=3, right_bars=3, causal=True)
        assert bool(sub["is_swing_high"].iloc[-1]) == bool(full["is_swing_high"].iloc[cutoff - 1])
        assert bool(sub["is_swing_low"].iloc[-1]) == bool(full["is_swing_low"].iloc[cutoff - 1])
        f_sh = full["last_swing_high"].iloc[cutoff - 1]
        s_sh = sub["last_swing_high"].iloc[-1]
        if pd.notna(f_sh) or pd.notna(s_sh):
            assert np.isclose(f_sh, s_sh)


def test_prefix_invariance_passes_causal_and_catches_lookahead():
    df = _make_ohlcv(300)
    ok_res = check_causality_prefix_invariance(_CausalDummyStrategy(), df)
    assert ok_res["passed"] is True
    assert ok_res["mismatches"] == 0

    bad_res = check_causality_prefix_invariance(_LeakyLookaheadStrategy(), df)
    assert bad_res["passed"] is False
    assert bad_res["mismatches"] > 0


def test_market_microstructure_profile():
    df = _make_ohlcv(300, drift=0.0008)
    prof = profile_market_microstructure(df, "OANDA:XAUUSD", timeframe="15m")
    assert prof["in_sample_bars"] == 300
    assert prof["mean_atr14"] > 0
    assert prof["friction_pct_of_1atr"] > 0
    assert set(prof["regime_mix_pct"].keys()) == {"bull", "bear", "ranging"}
    assert len(prof["peak_utc_hours"]) == 4


def test_collinearity_detector_flags_stacked_oscillators():
    rng = np.random.default_rng(1)
    x = rng.normal(0, 1, size=200)
    df_feats = pd.DataFrame({
        "rsi_like": x,
        "stoch_like": x * 0.98 + rng.normal(0, 0.05, size=200),
        "vol_regime": rng.normal(0, 1, size=200),
    })
    res = check_feature_collinearity(df_feats, threshold=0.85)
    assert res["checked"] is True
    assert res["passed"] is False
    assert res["collinear_pairs"][0]["f1"] == "rsi_like"
    assert res["collinear_pairs"][0]["f2"] == "stoch_like"


def test_validate_strategy_in_sample_runs_cleanly():
    df = _make_ohlcv(400)
    rep = validate_strategy_in_sample(_CausalDummyStrategy(), df, "OANDA:XAUUSD")
    assert rep["causality"]["passed"] is True
    assert rep["verdict"] in ("READY_FOR_CYNIC_AUDIT", "NEEDS_REFINEMENT")
    assert "layer_diagnostics" in rep["in_sample_metrics"]


def test_api_cheatsheet_drift_guard():
    """Verifies every core function documented in references/api_cheatsheet.md exists and matches key args."""
    import importlib
    import inspect

    expected = {
        "core.indicators": {
            "sma": ["series", "period"],
            "ema": ["series", "period"],
            "wma": ["series", "period"],
            "hma": ["series", "period"],
            "kama": ["series", "period"],
            "rsi": ["series", "period"],
            "macd": ["series", "fast", "slow", "signal"],
            "stochastic": ["high", "low", "close", "k_period", "d_period"],
            "roc": ["series", "period"],
            "cci": ["high", "low", "close", "period"],
            "williams_r": ["high", "low", "close", "period"],
            "true_range": ["high", "low", "close"],
            "atr": ["high", "low", "close", "period"],
            "adx": ["high", "low", "close", "period"],
            "bollinger_bands": ["series", "period", "std_dev"],
            "keltner_channels": ["high", "low", "close", "period", "atr_mult"],
            "donchian_channels": ["high", "low", "period", "causal"],
            "supertrend": ["high", "low", "close", "period", "multiplier"],
            "obv": ["close", "volume"],
            "cmf": ["high", "low", "close", "volume", "period"],
            "zscore": ["series", "period"],
            "rolling_linreg_slope": ["series", "period"],
            "hurst_proxy": ["close", "window"],
            "rolling_vwap": ["close", "volume", "period"],
            "compute_talib_token": ["df", "token"],
            "ensure_dynamic_indicators": ["df", "expressions"],
            "add_causal_mtf_features": ["df"],
            "add_cross_asset_context": ["df", "benchmark_df", "window"],
            "add_pandas_ta_suite": ["df"],
        },
        "core.market_structure": {
            "detect_swing_points": ["df", "left_bars", "right_bars", "causal"],
        },
        "core.feature_factory": {
            "compute_all_features": ["df"],
            "compute_selected_features": ["df", "feature_names"],
        },
        "core.data": {
            "fetch_ohlcv": ["symbol", "timeframe", "count", "period", "use_cache"],
            "resolve_market_symbol": ["symbol"],
        },
        "core.friction": {
            "resolve_asset_friction": ["symbol", "price"],
            "get_roundtrip_friction": ["symbol", "price", "atr"],
            "check_friction_hurdle": ["symbol", "entry_price", "stop_distance"],
        },
        "core.risk": {
            "parse_prompt_to_risk": ["prompt", "active_balance"],
            "calculate_position_units": ["dollar_risk_1r", "entry_price", "stop_loss"],
        },
    }

    for mod_name, funcs in expected.items():
        mod = importlib.import_module(mod_name)
        for fn_name, expected_params in funcs.items():
            fn = getattr(mod, fn_name, None)
            assert fn is not None, f"Missing documented API: {mod_name}.{fn_name}"
            actual_params = list(inspect.signature(fn).parameters.keys())
            assert actual_params == expected_params, (
                f"Signature drift in {mod_name}.{fn_name}: {actual_params} != {expected_params}"
            )

