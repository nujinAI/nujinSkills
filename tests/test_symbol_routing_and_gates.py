import os
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd

from core.data import (
    _ROOT as DATA_ROOT,
    resolve_market_symbol,
    canonical_market_slug,
    get_market_price_precision,
    _timeframe_to_seconds,
    _tf_to_tv_resolution,
    parse_period_to_days,
    bars_for_days,
    resample_candles,
    fetch_candles_via_tv,
)
from core.friction import resolve_asset_friction, get_roundtrip_friction, compute_carry_cost
from core.simulation import run_discrete_simulation, resolve_strategy_close_eod
from core.cynic_gates import evaluate_gates, verify_monte_carlo, verify_oos_walkforward, verify_friction
from core.analytics import compute_institutional_tier
from core.portfolio import calculate_metrics
from server.constants import MIN_OOS_RETENTION_PCT
from server.state.trial_ledger import resolve_ledger_path, LEDGER_PATH


class TestUniversalEngineFixes(unittest.TestCase):
    def test_nq_and_spy_never_route_to_es(self):
        self.assertEqual(resolve_market_symbol("NQ1!"), "CME_MINI:NQ1!")
        self.assertNotEqual(resolve_market_symbol("NQ1!"), "CME_MINI:ES1!")
        self.assertEqual(resolve_market_symbol("MNQ"), "CME_MINI:NQ1!")
        self.assertEqual(resolve_market_symbol("MNQ (Futures)"), "CME_MINI:NQ1!")
        self.assertEqual(resolve_market_symbol("NASDAQ:QQQ"), "NASDAQ:QQQ")
        self.assertEqual(resolve_market_symbol("QQQ"), "NASDAQ:QQQ")
        self.assertEqual(resolve_market_symbol("AMEX:SPY"), "AMEX:SPY")
        self.assertEqual(resolve_market_symbol("SPY"), "AMEX:SPY")
        self.assertNotEqual(resolve_market_symbol("TESLA"), "CME_MINI:ES1!")
        self.assertEqual(resolve_market_symbol("ES1!"), "CME_MINI:ES1!")
        self.assertEqual(canonical_market_slug("NQ1!"), "NQ1")
        self.assertEqual(canonical_market_slug("AMEX:SPY"), "SPY")
        self.assertEqual(canonical_market_slug("NASDAQ:QQQ"), "QQQ")
        self.assertEqual(get_market_price_precision("EURUSD"), 5)
        self.assertEqual(get_market_price_precision("USDJPY"), 3)
        self.assertEqual(get_market_price_precision("NQ1!"), 2)

    def test_universal_dynamic_friction_and_overrides(self):
        # Exact benchmarks differ and carry non-zero fees
        es_spread, es_fee, es_slip = resolve_asset_friction("CME_MINI:ES1!", 6000.0)
        nq_spread, nq_fee, nq_slip = resolve_asset_friction("CME_MINI:NQ1!", 21000.0)
        self.assertNotEqual((es_spread, es_slip), (nq_spread, nq_slip))
        self.assertGreater(es_fee, 0.0)
        self.assertGreater(nq_fee, 0.0)

        # Universal dynamic asset-class inference for arbitrary user instruments (never crashes, never free)
        for sym, px in [
            ("NASDAQ:NVDA", 140.0),
            ("BINANCE:DOGEUSDT", 0.20),
            ("FX:AUDJPY", 100.50),
            ("CME:6E1!", 1.08),
            ("CUSTOM_LOCAL_INDEX", 500.0),
        ]:
            sp, fee, sl = resolve_asset_friction(sym, px)
            self.assertGreater(sp, 0.0, f"spread must be positive for {sym}")
            self.assertGreater(fee, 0.0, f"fee must be positive for {sym}")
            self.assertGreater(sl, 0.0, f"slippage must be positive for {sym}")

        # Explicit caller override wins cleanly
        ov = {"spread_pts": 0.12, "fee_pct": 0.0002, "slippage_pts": 0.03}
        self.assertEqual(resolve_asset_friction("NASDAQ:NVDA", 140.0, friction_override=ov), (0.12, 0.0002, 0.03))

        # Round-trip spread counted ONCE (not 2x)
        rt = get_roundtrip_friction("CME_MINI:ES1!", 6000.0)
        expected_rt = es_spread + (6000.0 * es_fee * 2.0) + (es_slip * 2.0)
        self.assertAlmostEqual(rt, expected_rt, places=8)

        # Optional carry cost defaults to 0.0 and scales smoothly when configured
        self.assertEqual(compute_carry_cost(1000.0, 48.0, 1, daily_carry_bps=0.0), 0.0)
        self.assertAlmostEqual(compute_carry_cost(1000.0, 48.0, 1, daily_carry_bps=5.0), 1.0, places=6)

    def test_data_root_inside_repo_and_dynamic_timeframes(self):
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.assertEqual(os.path.abspath(DATA_ROOT), repo_root)

        # Dynamic arbitrary timeframes
        self.assertEqual(_timeframe_to_seconds("30m"), 1800)
        self.assertEqual(_timeframe_to_seconds("2h"), 7200)
        self.assertEqual(_timeframe_to_seconds("6h"), 21600)
        self.assertEqual(_timeframe_to_seconds("1w"), 604800)
        self.assertEqual(_tf_to_tv_resolution("2h"), "120")
        self.assertEqual(_tf_to_tv_resolution("1w"), "1W")
        for bad_tf in ("banana", ""):
            with self.assertRaises(ValueError):
                _timeframe_to_seconds(bad_tf)
            with self.assertRaises(ValueError):
                _tf_to_tv_resolution(bad_tf)
        self.assertEqual(parse_period_to_days("90d"), 90)
        self.assertEqual(parse_period_to_days("6mo"), 180)
        self.assertEqual(parse_period_to_days("1y"), 365)

        # 2h and 30m produce genuinely different bar counts (not falling back to 5m!)
        self.assertLess(bars_for_days("2h", 90), bars_for_days("30m", 90))
        self.assertLess(bars_for_days("30m", 90), bars_for_days("5m", 90))

        # Resampling preserves full precision (no 2-decimal truncation)
        fx_candles = [
            {"timestamp": 1700000100, "open": 1.08432, "high": 1.08495, "low": 1.08411, "close": 1.08477, "volume": 10.0},
            {"timestamp": 1700000160, "open": 1.08477, "high": 1.08512, "low": 1.08460, "close": 1.08505, "volume": 12.0},
        ]
        res = resample_candles(fx_candles, "5m")
        self.assertEqual(len(res), 1)
        self.assertAlmostEqual(res[0]["open"], 1.08432, places=5)
        self.assertAlmostEqual(res[0]["high"], 1.08512, places=5)
        self.assertAlmostEqual(res[0]["close"], 1.08505, places=5)

    def test_close_eod_not_forced_and_optional_carry(self):
        class _SwingStrat:
            pass

        class _IntradayStrat:
            close_eod = True

        self.assertFalse(resolve_strategy_close_eod(_SwingStrat(), "BINANCE:BTCUSDT", "4h"))
        self.assertTrue(resolve_strategy_close_eod(_IntradayStrat(), "OANDA:XAUUSD", "5m"))

        # Bars crossing 21:00 UTC: default close_eod=False holds through to TP
        times = pd.date_range("2026-11-01 20:00:00", periods=6, freq="1h", tz="UTC")
        df = pd.DataFrame({
            "open":  [100.0, 100.0, 100.5, 101.0, 102.0, 103.0],
            "high":  [100.5, 101.0, 101.5, 102.5, 105.5, 106.0],
            "low":   [ 99.5,  99.5, 100.0, 100.5, 101.5, 102.5],
            "close": [100.0, 100.5, 101.0, 102.0, 105.0, 105.5],
            "atr":   [1.0] * 6,
        }, index=times)
        sig = pd.DataFrame({"entry_signal": [1, 0, 0, 0, 0, 0], "stop_loss": [95.0] * 6, "target": [105.0] * 6}, index=times)

        res_no_eod = run_discrete_simulation(df, sig, symbol="BINANCE:BTCUSDT", account_size=1000.0, max_hold_bars=24)
        self.assertEqual(res_no_eod["trades"][0].exit_reason, "TP")

        res_with_eod = run_discrete_simulation(df, sig, symbol="BINANCE:BTCUSDT", account_size=1000.0, max_hold_bars=24, close_eod=True)
        self.assertEqual(res_with_eod["trades"][0].exit_reason, "EOD")

        res_carry = run_discrete_simulation(df, sig, symbol="BINANCE:BTCUSDT", account_size=1000.0, max_hold_bars=24, daily_carry_bps=50.0)
        self.assertLess(res_carry["trades"][0].pnl_dollars, res_no_eod["trades"][0].pnl_dollars)

    def test_oos_gate_checks_actual_oos_count_and_pbo_and_retention(self):
        self.assertEqual(MIN_OOS_RETENTION_PCT, 50.0)

        # 25 total trades -> only 8 OOS trades (< 20 MIN_OOS_TRADES) MUST FAIL
        tiny_pos = [0.01] * 25
        res_tiny = verify_oos_walkforward(tiny_pos)
        self.assertEqual(res_tiny["status"], "FAIL")
        self.assertIn("Insufficient OOS trades", res_tiny["reason"])

        # Gate 6 net friction display never says "after 0.0 bps"
        fric = verify_friction([0.005] * 30, fee_bps=0.0, slippage_bps=0.0, returns_are_net=True, avg_friction_bps=6.4)
        self.assertEqual(fric["status"], "PASS")
        self.assertNotIn("0.0 bps", fric["reason"])
        self.assertIn("6.4 bps", fric["reason"])

    def test_custom_max_mdd_honored_in_gate3(self):
        rng = np.random.default_rng(7)
        returns = list(rng.normal(0.002, 0.008, size=80))
        res_strict = verify_monte_carlo(returns, max_mdd_99=0.01)
        res_relaxed = verify_monte_carlo(returns, max_mdd_99=0.25)
        self.assertEqual(res_strict["status"], "FAIL")
        self.assertEqual(res_relaxed["status"], "PASS")

        gates = evaluate_gates(returns, max_mdd_99=0.25, returns_are_net=True, avg_friction_bps=4.5)
        self.assertEqual(gates["gate_3_monte_carlo"]["status"], "PASS")
        self.assertIn("4.5 bps", gates["gate_6_friction"]["reason"])

    def test_small_sample_cannot_be_a_tier(self):
        summary = {
            "sharpe": 6.5,
            "profit_factor": 3.0,
            "win_rate": 0.70,
            "expectancy_bps": 45.0,
            "max_drawdown": 0.01,
            "dsr": 0.99,
            "total_trades": 18,
        }
        gates = {
            "gates_summary": {"gates_passed": 8, "gates_total": 8, "verdict": "APPROVED"},
            "gate_3_monte_carlo": {"status": "PASS", "mdd_99": 0.015},
            "gate_6_friction": {"status": "PASS"},
            "gate_5_regime_survival": {"status": "PASS", "score": 90.0},
            "gate_8_equity_linearity": {"status": "PASS", "r_squared": 0.95},
        }
        meta = compute_institutional_tier(summary, gates)
        self.assertNotIn("A-Tier", meta["tier"])
        self.assertNotIn("S-Tier", meta["tier"])

    def test_trial_ledger_active_session_not_dead_code(self):
        # Explicit custom path wins
        self.assertEqual(resolve_ledger_path(path="/tmp/custom_ledger.jsonl"), "/tmp/custom_ledger.jsonl")
        # Default LEDGER_PATH defers to active session when one is set
        with patch("server.state.trial_ledger.get_active_session_id", return_value="sess-abc"), \
             patch("server.state.trial_ledger.get_session_paths", return_value={"trial_ledger": "/tmp/sess-abc/trial_ledger.jsonl"}):
            self.assertEqual(resolve_ledger_path(path=LEDGER_PATH), "/tmp/sess-abc/trial_ledger.jsonl")

    def test_portfolio_metrics_dynamic_annualization(self):
        rets = np.array([0.01, -0.002, 0.008, 0.005, -0.001, 0.009])
        m = calculate_metrics(rets, periods_per_year=252.0)
        self.assertGreater(m["sharpe"], 0.0)
        self.assertGreater(m["total_return_pct"], 0.0)

    def test_fetch_candles_via_tv_handles_5_element_bars(self):
        class _FakeWS:
            def __init__(self, sym, tf, count):
                self.result_data = [{"v": [1700000100, 100.0, 102.0, 99.0, 101.0]}]

            def connect(self):
                pass

            def run(self):
                pass

        with patch("core.data.HAS_TV_WS", True), \
             patch("core.data.TradingViewWebSocket", _FakeWS):
            candles = fetch_candles_via_tv("OANDA:XAUUSD", "5m", count=1)

        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0]["close"], 101.0)
        self.assertEqual(candles[0]["volume"], 0.0)


if __name__ == "__main__":
    unittest.main()
