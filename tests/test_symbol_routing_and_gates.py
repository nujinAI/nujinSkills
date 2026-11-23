import unittest
import numpy as np

from core.data import resolve_market_symbol, canonical_market_slug, get_market_price_precision
from core.friction import resolve_asset_friction
from core.cynic_gates import evaluate_gates, verify_monte_carlo
from core.analytics import compute_institutional_tier
from server.constants import MIN_OOS_RETENTION_PCT


class TestSymbolRoutingAndGates(unittest.TestCase):
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

    def test_friction_exact_lookup_and_no_silent_fallback(self):
        es_spread, es_fee, es_slip = resolve_asset_friction("CME_MINI:ES1!", 6000.0)
        nq_spread, nq_fee, nq_slip = resolve_asset_friction("CME_MINI:NQ1!", 21000.0)
        self.assertNotEqual((es_spread, es_slip), (nq_spread, nq_slip))
        self.assertGreater(es_fee, 0.0)
        self.assertGreater(nq_fee, 0.0)
        with self.assertRaises(ValueError):
            resolve_asset_friction("UNKNOWN_TICKER_XYZ", 100.0)

    def test_oos_retention_matches_docs(self):
        self.assertEqual(MIN_OOS_RETENTION_PCT, 50.0)

    def test_custom_max_mdd_honored_in_gate3(self):
        # Construct returns with ~4% drawdown: fails 3% default, passes 5% mandate
        rng = np.random.default_rng(7)
        returns = list(rng.normal(0.002, 0.008, size=80))
        res_strict = verify_monte_carlo(returns, max_mdd_99=0.01)
        res_relaxed = verify_monte_carlo(returns, max_mdd_99=0.25)
        self.assertEqual(res_strict["status"], "FAIL")
        self.assertEqual(res_relaxed["status"], "PASS")

        gates = evaluate_gates(returns, max_mdd_99=0.25)
        self.assertEqual(gates["gate_3_monte_carlo"]["status"], "PASS")

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


if __name__ == "__main__":
    unittest.main()
