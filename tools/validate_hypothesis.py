#!/usr/bin/env python3
"""
tools/validate_hypothesis.py - Strictly In-Sample Market Research & Hypothesis Pre-Validator.

Two compact, context-thrifty modes (both strictly isolate the first 66.7% In-Sample slice
and leave the final 33.3% Blind Out-of-Sample window completely locked):

1. Market Microstructure Research Profile:
   python tools/validate_hypothesis.py --profile --symbol OANDA:XAUUSD --tf 15m --days 60

2. Creative Strategy In-Sample Pre-Validation (Zero-Lookahead + Sub-Era + Friction + 4-Layer Telemetry):
   python tools/validate_hypothesis.py --strategy MyStrategy.py --days 60
"""
import argparse
import importlib.util
import inspect
import json
import os
import sys
import pandas as pd

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.data import fetch_ohlcv, resolve_market_symbol
from core.hypothesis_validator import (
    profile_market_microstructure,
    validate_strategy_in_sample,
)


def _bars_for_days(tf: str, days: int) -> int:
    tf_clean = tf.strip().lower()
    if tf_clean.endswith("m"):
        mins = max(1, int(tf_clean[:-1] or 15))
        bars_per_day = 1440 // mins
    elif tf_clean.endswith("h"):
        hrs = max(1, int(tf_clean[:-1] or 1))
        bars_per_day = 24 // hrs
    else:
        bars_per_day = 1
    return max(800, min(6000, int(days * bars_per_day * 1.15)))


def _fetch_is_slice(symbol: str, tf: str, days: int):
    sym = resolve_market_symbol(symbol)
    df = fetch_ohlcv(sym, timeframe=tf, count=_bars_for_days(tf, days))
    if df is None or len(df) < 120:
        print(f"[-] Insufficient market data fetched for {sym} ({tf}).", file=sys.stderr)
        sys.exit(1)

    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    elif df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    cutoff_ts = df.index[-1] - pd.Timedelta(days=days)
    df_win = df[df.index >= cutoff_ts].copy()
    if len(df_win) >= 120:
        df = df_win

    split_idx = int(len(df) * 0.667)
    return sym, df.iloc[:split_idx].copy(), len(df) - split_idx


def _load_strategy_instance(strategy_arg: str):
    if os.path.exists(strategy_arg):
        path = os.path.abspath(strategy_arg)
    else:
        fname = strategy_arg if strategy_arg.endswith(".py") else f"{strategy_arg}.py"
        candidates = [
            os.path.join(PROJECT_ROOT, "strategies", fname),
            os.path.join(PROJECT_ROOT, "..", "zillionsAlpha", "strategies", fname),
            os.path.join(PROJECT_ROOT, "..", "nujinPro", "strategies", fname),
        ]
        path = next((p for p in candidates if os.path.exists(p)), "")
        if not path:
            print(f"[-] Strategy file not found: {strategy_arg}", file=sys.stderr)
            sys.exit(1)

    mod_name = os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        print(f"[-] Failed to load module spec from {path}", file=sys.stderr)
        sys.exit(1)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    cls = getattr(mod, mod_name, None)
    if cls is None or not inspect.isclass(cls):
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if hasattr(obj, "generate_signals") and obj.__module__ == mod.__name__:
                cls = obj
                break
    if cls is None:
        print(f"[-] No strategy class with generate_signals() found in {path}", file=sys.stderr)
        sys.exit(1)
    return cls(), mod_name


def parse_args():
    p = argparse.ArgumentParser(description="NujinSkills In-Sample Market Profiler & Hypothesis Validator")
    p.add_argument("--profile", action="store_true", help="Run In-Sample market microstructure research profile")
    p.add_argument("--strategy", type=str, default=None, help="Strategy filename or path to validate In-Sample")
    p.add_argument("--symbol", type=str, default=None, help="Market symbol (auto-read from strategy if omitted)")
    p.add_argument("--tf", type=str, default=None, help="Timeframe (auto-read from strategy if omitted)")
    p.add_argument("--days", type=int, default=60, help="Total history window in days (66.7%% IS / 33.3%% locked OOS)")
    p.add_argument("--json", action="store_true", help="Output compact JSON")
    return p.parse_args()


def main():
    args = parse_args()

    if args.profile:
        symbol = args.symbol or "OANDA:XAUUSD"
        tf = args.tf or "15m"
        sym, df_is, oos_locked = _fetch_is_slice(symbol, tf, args.days)
        prof = profile_market_microstructure(df_is, sym, timeframe=tf)
        prof["blind_oos_bars_locked"] = oos_locked
        if args.json:
            print(json.dumps(prof, indent=2))
            return
        rm = prof["regime_mix_pct"]
        print("=" * 76)
        print(f"MARKET MICROSTRUCTURE PROFILE (IN-SAMPLE ONLY) | {sym} [{tf}]")
        print(f"IS Bars: {prof['in_sample_bars']} ({prof['date_start'][:10]} -> {prof['date_end'][:10]}) | Blind OOS Locked: {oos_locked}")
        print("-" * 76)
        print(f"  Price / Vol  : Mean={prof['mean_price']} | ATR14={prof['mean_atr14']} ({prof['atr_pct_of_price']:.3f}%) | Range CV={prof['range_volatility_cv']}")
        print(f"  Friction     : RT={prof['roundtrip_friction']} ({prof['friction_pct_of_1atr']:.1f}% of 1xATR -> min SL >= {prof['min_sl_atr_for_10pct_floor']}xATR)")
        print(f"  Dynamics     : {prof['behavioral_signature']} | Lag1 AC={prof['lag1_autocorr']:+.3f} | VR(5)={prof['variance_ratio_5']:.2f} | Eff20={prof['median_abs_efficiency_20']:.2f}")
        print(f"  Regime Mix   : Bull {rm['bull']}% | Bear {rm['bear']}% | Ranging {rm['ranging']}%")
        if prof["peak_utc_hours"]:
            print(f"  UTC Activity : Peak={prof['peak_utc_hours']} | Quiet={prof['quiet_utc_hours']}")
        print("=" * 76)
        return

    if not args.strategy:
        print("[-] Specify either `--profile --symbol <SYM> --tf <TF>` or `--strategy <Name.py>`.", file=sys.stderr)
        sys.exit(1)

    strat_obj, strat_name = _load_strategy_instance(args.strategy)
    symbol = args.symbol or getattr(strat_obj, "symbol", "OANDA:XAUUSD")
    tf = args.tf or getattr(strat_obj, "timeframe", "15m")
    sym, df_is, oos_locked = _fetch_is_slice(symbol, tf, args.days)
    rep = validate_strategy_in_sample(strat_obj, df_is, sym)
    rep["strategy"] = strat_name
    rep["timeframe"] = tf
    rep["blind_oos_bars_locked"] = oos_locked

    if args.json:
        print(json.dumps(rep, indent=2))
        return

    m = rep["in_sample_metrics"]
    c = rep["causality"]
    ld = m.get("layer_diagnostics", {})
    print("=" * 76)
    print(f"IN-SAMPLE HYPOTHESIS VALIDATOR | {strat_name} | {sym} [{tf}]")
    print(f"IS Bars: {rep['in_sample_bars']} | Blind OOS Locked: {oos_locked} | Verdict: {rep['verdict']}")
    print("-" * 76)
    print(f"  Causality    : {'PASS' if c['passed'] else 'FAIL'} ({c['detail']})")
    print(f"  IS Trades    : {m['num_trades']} | WR={m['win_rate']*100:.1f}% | Exp={m['expectancy_r']:+.3f}R | PF={m['profit_factor']} | AvgRR={m.get('avg_planned_rr', 0)}")
    print(f"  Robustness   : t-stat={m['t_stat']} | Perm p={m['perm_p_val']} | Sub-Eras={m['positive_eras']} ({m['sub_era_consistency']*100:.0f}%)")
    print(f"  Friction/Geo : Med Fric={m['median_friction_pct_sl']:.1f}% of SL (fail>10%: {m['pct_failing_friction_floor']:.0f}%) | InvalidSig={m['invalid_geometry_signals']}")
    if ld:
        cr = ld.get("context_regimes", {})
        reg_str = " | ".join(
            f"{k.title()}:{v['trades']}t({v['exp_r']:+.2f}R)" for k, v in cr.items()
        )
        print(f"  Context (IS) : {reg_str}")
        print(
            f"  Loc/Confirm  : Med MFE={ld['location_median_mfe_r']}R | Med MAE={ld['location_median_mae_r']}R | "
            f"FastStop(<=2b)={ld['confirmation_fast_stopout_rate']*100:.0f}% | Giveback={ld['geometry_winner_giveback_rate']*100:.0f}%"
        )
    if rep["issues"]:
        print("  Issues       : " + " ; ".join(rep["issues"]))
    if rep["layer_hints"]:
        print("  Layer Hints  : " + " ; ".join(rep["layer_hints"]))
    print("=" * 76)


if __name__ == "__main__":
    main()
