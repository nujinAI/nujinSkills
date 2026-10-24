"""
tests/test_indicators_and_session_isolation.py
─────────────────────────────────────────────────────────────────────────────
Verifies the upgraded NujinSkills architecture:
  1. Universal Standard + Custom Indicator Registry (`server/indicators.py`)
  2. Dedicated Per-Session Workspace Isolation (`server/session_store.py` & `server/trial_ledger.py`)
  3. Multi-Paradigm Anomaly Scanner across all 6 Orthogonal Edge Families (`tools/anomaly_scanner.py`)
  4. Fast Vectorized Screener with dynamic indicator resolution (`tools/vectorized_screener.py`)
  5. Automated Gate 2 Parameter Perturbation (`server/backtest_engine.py` & `server/cynic_gates.py`)
"""

from __future__ import annotations

import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from server.cynic_gates import PASS, evaluate_gates
from server.indicators import (
    compute_all_standard_features,
    ensure_dynamic_indicators,
    register_custom_indicator,
)
from server.session_store import create_session, get_session_paths
from server.trial_ledger import count_trials, n_trials_for_dsr, record_trial
from tools.anomaly_scanner import generate_empirical_briefing
from tools.vectorized_screener import evaluate_rule_dict_on_df


def _synthetic_ohlcv(n: int = 350, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    # Create a persistent trend with realistic noise
    drift = np.linspace(0, 0.25, n)
    cycle = 0.03 * np.sin(np.linspace(0, 8 * np.pi, n))
    noise = rng.normal(0, 0.004, size=n).cumsum()
    close = 100.0 * np.exp(drift + cycle + noise)
    open_p = np.roll(close, 1)
    open_p[0] = close[0]
    spread = np.abs(rng.normal(0.4, 0.15, size=n))
    high = np.maximum(open_p, close) + spread
    low = np.minimum(open_p, close) - spread
    volume = rng.uniform(100, 1000, size=n)
    timestamps = 1_700_000_000 + np.arange(n) * 900
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": open_p,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def test_dynamic_and_standard_indicators_resolve_cleanly():
    df = _synthetic_ohlcv(250)
    feat = compute_all_standard_features(df, window=20)
    for col in (
        "ema_9", "ema_21", "ema_50", "hma_21", "kama_10",
        "supertrend", "supertrend_dir", "donchian_upper_20", "donchian_lower_20",
        "rsi_14", "macd_hist", "adx_14", "atr_14", "zscore_20",
        "ttm_squeeze", "hurst_proxy", "slope_20", "avwap_100", "obv", "cmf_20",
    ):
        assert col in feat.columns, f"Missing standard feature column: {col}"

    # Arbitrary parameterized tokens & any of the 201 TA-Lib functions resolved on the fly
    dyn = ensure_dynamic_indicators(
        df.copy(),
        [
            "ema_37 > hma_55 and rsi_5 > 50 and donchian_upper_30 > close and zscore_40 < 1.5 "
            "and zlema_34 > tema_21 and mfi_14 > 40 and vhf_28 > 0.3 and ultosc_7_14_28 > 50 and percentrank_50 > 20"
        ],
    )
    for token in (
        "ema_37", "hma_55", "rsi_5", "donchian_upper_30", "zscore_40",
        "zlema_34", "tema_21", "mfi_14", "vhf_28", "ultosc_7_14_28", "percentrank_50",
    ):
        assert token in dyn.columns, f"Dynamic TA-Lib/indicator token '{token}' was not resolved"


def test_custom_indicator_registration_and_evaluation():
    df = _synthetic_ohlcv(200)
    register_custom_indicator(
        "custom_trend_impulse",
        lambda d: (d["close"] - d["close"].rolling(10, min_periods=1).mean()) / d["close"].rolling(10, min_periods=1).std().replace(0, 1e-6),
    )
    resolved = ensure_dynamic_indicators(df.copy(), ["custom_trend_impulse > 1.0"])
    assert "custom_trend_impulse" in resolved.columns


def test_per_session_isolation_prevents_trial_and_file_spillover(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="nujin-sessions-") as tmp:
        import server.session_store as ss

        monkeypatch.setattr(ss, "NUJIN_DIR", tmp)
        monkeypatch.setattr(ss, "SESSIONS_DIR", os.path.join(tmp, "sessions"))
        monkeypatch.setattr(ss, "ACTIVE_SESSION_FILE", os.path.join(tmp, "active_session.json"))

        # Session A records 25 distinct hypothesis trials
        s_a = create_session(session_id="session_alpha", symbol="BTCUSDT", timeframe="15m", activate=True)
        paths_a = get_session_paths(session_id="session_alpha")
        for idx in range(25):
            record_trial(kind="miner_step", fingerprint=f"fp_a_{idx}", path=paths_a["trial_ledger"])
        assert count_trials(path=paths_a["trial_ledger"]) == 25
        assert n_trials_for_dsr(path=paths_a["trial_ledger"]) == 25

        # Session B starts fresh for a new user request — its DSR trial count must not inherit Session A's 25 trials
        s_b = create_session(session_id="session_beta", symbol="XAUUSD", timeframe="1m", activate=True)
        paths_b = get_session_paths(session_id="session_beta")
        assert s_a["session_dir"] != s_b["session_dir"]
        assert count_trials(path=paths_b["trial_ledger"]) == 0
        assert n_trials_for_dsr(path=paths_b["trial_ledger"]) == 2  # MIN_TRIALS floor


def test_multi_paradigm_scanner_evaluates_all_six_families():
    df = _synthetic_ohlcv(300)
    with tempfile.TemporaryDirectory(prefix="nujin-scan-") as tmp:
        csv_path = os.path.join(tmp, "candles.csv")
        out_path = os.path.join(tmp, "briefing.json")
        df.to_csv(csv_path, index=False)

        briefing = generate_empirical_briefing(data_path=csv_path, output_path=out_path, session_id="test_scan")
        assert "top_predictive_library_features" in briefing
        assert len(briefing["top_predictive_library_features"]) >= 10
        assert "edge_family_synthesis" in briefing
        assert "recommended_archetype" in briefing
        families_seen = {a["edge_family"] for a in briefing["empirical_anomalies_detected"]}
        assert len(families_seen) >= 3


def test_vectorized_screener_supports_custom_formulas_and_rejects_bad_syntax():
    df = _synthetic_ohlcv(300)
    rules = {
        "entry_long": "ema_9 > ema_21 and custom_spread > 0.0",
        "entry_short": "ema_9 < ema_21 and custom_spread < 0.0",
        "custom_indicators": {"custom_spread": "(ema_9 - ema_21) / atr_14"},
        "stoploss_pct": 0.015,
        "takeprofit_pct": 0.035,
        "max_bars_held": 12,
        "risk_per_trade_pct": 0.0045,
    }
    res = evaluate_rule_dict_on_df(df, rules)
    assert "sharpe" in res
    assert res["trades"] > 0

    # Invalid syntax must raise ValueError rather than silently falling back to a default rule
    with pytest.raises(Exception):
        evaluate_rule_dict_on_df(df, {"entry_long": "nonexistent_variable_xyz >>> 123"})


def test_eight_gates_can_achieve_approved_with_perturbed_matrix():
    rng = np.random.default_rng(11)
    # Consistent positive-expectancy R-normalized trade returns
    returns = rng.normal(0.0030, 0.0022, size=90)
    perturbed_matrix = np.array([[2.8, 3.1], [2.9, 3.0]], dtype=float)
    stop_dists = np.full(len(returns), 25.0)

    gates = evaluate_gates(
        returns,
        n_trials=10,
        metric_matrix=perturbed_matrix,
        observed_sr=3.1,
        returns_are_net=True,
    )
    assert gates["gate_2_parameter_stability"]["status"] == PASS
    assert gates["gate_8_equity_linearity"]["status"] == PASS
    assert gates["gates_summary"]["verdict"] == "APPROVED"
    assert gates["gates_summary"]["gates_passed"] == 8
