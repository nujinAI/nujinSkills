#!/usr/bin/env python3
"""
tools/autoresearch_miner.py
─────────────────────────────────────────────────────────────────────────────
Multi-Paradigm Autonomous Quant Research & Strategy Evolution Engine.

Key architectural properties:
  • Dedicated Per-Session Isolation: Every research session operates inside
    `.nujin/sessions/<session_id>/` (with its own `trial_ledger.jsonl`,
    `empirical_briefing.json`, `features.csv`, `best_rule.json`, and
    `experiment_log.jsonl`) so a new user request is never limited or biased
    by files or trial counts from older user requests.
  • Data-Driven Discovery: Default archetype is `"auto"`, which inspects the
    empirical briefing's top-IC features and data-mined quantile/interaction rules
    or accepts any custom indicator formula.
  • Genuine Parameter Stability Perturbation (Gate 2): Evaluates a 3x3 grid of
    perturbed threshold / stop parameters on the candidate rules so Gate 2
    (`gate_2_parameter_stability`) is genuinely verified rather than left
    `INCONCLUSIVE`.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import py_compile
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from server.constants import (  # noqa: E402
    DSR_THRESHOLD,
    FEE_BPS,
    MAX_DRAWDOWN,
    MIN_EXPECTANCY_BPS,
    MIN_R2,
    MIN_SHARPE,
    MIN_TRADES_SIGNIFICANT,
    MIN_WIN_RATE,
    SLIPPAGE_BPS,
)
from server.cynic_gates import evaluate_gates  # noqa: E402
from server.session_store import (  # noqa: E402
    NUJIN_DIR,
    create_session,
    get_active_session_id,
    resolve_session_dir,
)
from server.trial_ledger import (  # noqa: E402
    fingerprint as _trial_fingerprint,
    n_trials_for_dsr,
    record_trial,
)

TOOL_NAME = "[NujinMiner]"
AUTORESEARCH_DIR = NUJIN_DIR


def resolve_research_dir(exp_id: str = "", new_session: bool = False) -> str:
    global AUTORESEARCH_DIR
    if new_session:
        meta = create_session(session_id=exp_id or None, activate=True)
        AUTORESEARCH_DIR = meta["session_dir"]
        return AUTORESEARCH_DIR
    sdir = resolve_session_dir(session_id=exp_id or None, create_if_missing=True)
    AUTORESEARCH_DIR = sdir
    return sdir


def get_python_exec() -> str:
    venv_py = os.path.abspath(".venv/bin/python")
    if os.path.exists(venv_py):
        return venv_py
    venv_py3 = os.path.abspath(".venv/bin/python3")
    if os.path.exists(venv_py3):
        return venv_py3
    return sys.executable


def ensure_gitignore() -> None:
    gitignore_path = ".gitignore"
    if os.path.exists(gitignore_path):
        with open(gitignore_path, "r", encoding="utf-8") as f:
            content = f.read()
        if ".nujin/" not in content and ".nujin" not in content:
            with open(gitignore_path, "a", encoding="utf-8") as f:
                f.write("\n# Nujin research state\n.nujin/\n")


def dispatch_telemetry(payload: Dict[str, Any]) -> None:
    dispatcher_script = os.path.join("tools", "ui_dispatcher.py")
    if os.path.exists(dispatcher_script):
        try:
            subprocess.run(
                [get_python_exec(), dispatcher_script, "--event", "UPSERT_WIDGET", "--payload", json.dumps(payload)],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            pass


# Multi-Paradigm Archetype Library
ARCHETYPE_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "trend_following": {
        "archetype": "trend_following",
        "entry_long": "ema_9 > ema_21 and ema_21 > ema_50 and adx_14 > 20 and rsi_14 > 52",
        "entry_short": "ema_9 < ema_21 and ema_21 < ema_50 and adx_14 > 20 and rsi_14 < 48",
        "exit": "bars >= 16",
        "max_bars_held": 16,
        "stoploss_pct": 0.015,
        "takeprofit_pct": 0.038,
        "risk_per_trade_pct": 0.0045,
        "trailing_stop": True,
        "bias": "DUAL",
    },
    "momentum_breakout": {
        "archetype": "momentum_breakout",
        "entry_long": "close > donchian_upper_20 and volume_zscore > 0.4 and adx_14 > 20",
        "entry_short": "close < donchian_lower_20 and volume_zscore > 0.4 and adx_14 > 20",
        "exit": "bars >= 14",
        "max_bars_held": 14,
        "stoploss_pct": 0.014,
        "takeprofit_pct": 0.036,
        "risk_per_trade_pct": 0.0045,
        "trailing_stop": True,
        "bias": "DUAL",
    },
    "volatility_squeeze": {
        "archetype": "volatility_squeeze",
        "entry_long": "vol_compression < 0.90 and close > sma_20 and macd_hist > 0 and rsi_14 > 54",
        "entry_short": "vol_compression < 0.90 and close < sma_20 and macd_hist < 0 and rsi_14 < 46",
        "exit": "bars >= 12",
        "max_bars_held": 12,
        "stoploss_pct": 0.014,
        "takeprofit_pct": 0.034,
        "risk_per_trade_pct": 0.0045,
        "trailing_stop": True,
        "bias": "DUAL",
    },
    "mtf_pullback": {
        "archetype": "mtf_pullback",
        "entry_long": "ema_50 > ema_200 and close <= ema_21 and close > ema_50 and rsi_14 < 46",
        "entry_short": "ema_50 < ema_200 and close >= ema_21 and close < ema_50 and rsi_14 > 54",
        "exit": "bars >= 12",
        "max_bars_held": 12,
        "stoploss_pct": 0.014,
        "takeprofit_pct": 0.032,
        "risk_per_trade_pct": 0.0045,
        "trailing_stop": False,
        "bias": "DUAL",
    },
    "zscore_reversion": {
        "archetype": "zscore_reversion",
        "entry_long": "zscore_20 < -2.0 and rsi_14 < 32",
        "entry_short": "zscore_20 > 2.0 and rsi_14 > 68",
        "exit": "bars >= 8",
        "max_bars_held": 8,
        "stoploss_pct": 0.014,
        "takeprofit_pct": 0.028,
        "risk_per_trade_pct": 0.0045,
        "trailing_stop": False,
        "bias": "DUAL",
    },
    "vwap_reversion": {
        "archetype": "vwap_reversion",
        "entry_long": "avwap_zscore < -1.8 and bb_pct_b < 0.12",
        "entry_short": "avwap_zscore > 1.8 and bb_pct_b > 0.88",
        "exit": "bars >= 8",
        "max_bars_held": 8,
        "stoploss_pct": 0.014,
        "takeprofit_pct": 0.028,
        "risk_per_trade_pct": 0.0045,
        "trailing_stop": False,
        "bias": "DUAL",
    },
    "mean_reversion": {
        "archetype": "mean_reversion",
        "entry_long": "zscore_20 < -1.9 and rsi_14 < 34",
        "entry_short": "zscore_20 > 1.9 and rsi_14 > 66",
        "exit": "bars >= 8",
        "max_bars_held": 8,
        "stoploss_pct": 0.014,
        "takeprofit_pct": 0.028,
        "risk_per_trade_pct": 0.0045,
        "trailing_stop": False,
        "bias": "DUAL",
    },
    "session_breakout": {
        "archetype": "session_breakout",
        "entry_long": "(killzone_london == 1 or killzone_ny == 1) and close > donchian_upper_10 and volume_zscore > 0.4",
        "entry_short": "(killzone_london == 1 or killzone_ny == 1) and close < donchian_lower_10 and volume_zscore > 0.4",
        "exit": "bars >= 10",
        "max_bars_held": 10,
        "stoploss_pct": 0.013,
        "takeprofit_pct": 0.030,
        "risk_per_trade_pct": 0.0045,
        "trailing_stop": True,
        "bias": "DUAL",
    },
    "price_action": {
        "archetype": "price_action",
        "entry_long": "engulfing_bullish == 1 and close > ema_50 and volume_zscore > 0.5",
        "entry_short": "engulfing_bearish == 1 and close < ema_50 and volume_zscore > 0.5",
        "exit": "bars >= 10",
        "max_bars_held": 10,
        "stoploss_pct": 0.014,
        "takeprofit_pct": 0.032,
        "risk_per_trade_pct": 0.0045,
        "trailing_stop": False,
        "bias": "DUAL",
    },
    "smc_liquidity": {
        "archetype": "smc_liquidity",
        "entry_long": "(sweep_low_rejection == 1 or trapped_shorts == 1) and volume_zscore > 0.8",
        "entry_short": "(sweep_high_rejection == 1 or trapped_longs == 1) and volume_zscore > 0.8",
        "exit": "bars >= 8",
        "max_bars_held": 8,
        "stoploss_pct": 0.015,
        "takeprofit_pct": 0.032,
        "risk_per_trade_pct": 0.0045,
        "trailing_stop": False,
        "bias": "DUAL",
    },
}


def _select_initial_rules_from_briefing(briefing_path: str, requested_archetype: str) -> Dict[str, Any]:
    if os.path.exists(briefing_path):
        try:
            with open(briefing_path, "r", encoding="utf-8") as f:
                bdata = json.load(f)
            syn = bdata.get("edge_family_synthesis", {})
            rec_arch = syn.get("recommended_archetype") or bdata.get("recommended_archetype") or "trend_following"
            chosen_arch = rec_arch if requested_archetype in ("", "auto") else requested_archetype
            base = dict(ARCHETYPE_TEMPLATES.get(chosen_arch, ARCHETYPE_TEMPLATES["trend_following"]))
            if requested_archetype in ("", "auto"):
                if syn.get("recommended_entry_long"):
                    base["entry_long"] = syn["recommended_entry_long"]
                if syn.get("recommended_entry_short"):
                    base["entry_short"] = syn["recommended_entry_short"]
                if syn.get("recommended_horizon_bars"):
                    hz = int(syn["recommended_horizon_bars"])
                    base["max_bars_held"] = max(4, hz)
                    base["exit"] = f"bars >= {base['max_bars_held']}"
            return base
        except Exception:
            pass

    arch_key = "trend_following" if requested_archetype in ("", "auto") else requested_archetype
    return dict(ARCHETYPE_TEMPLATES.get(arch_key, ARCHETYPE_TEMPLATES["trend_following"]))


def action_init(
    target: str,
    scope: str,
    context: str,
    archetype: str = "auto",
    initial_rules_input: str = "",
) -> None:
    print(f"{TOOL_NAME} Initializing isolated Nujin research session in {AUTORESEARCH_DIR}/...")
    os.makedirs(AUTORESEARCH_DIR, exist_ok=True)
    ensure_gitignore()

    briefing_path = os.path.join(AUTORESEARCH_DIR, "empirical_briefing.json")
    initial_rules = None
    if initial_rules_input:
        if os.path.exists(initial_rules_input):
            with open(initial_rules_input, "r", encoding="utf-8") as f:
                initial_rules = json.load(f)
        else:
            try:
                initial_rules = json.loads(initial_rules_input)
            except Exception:
                initial_rules = None

    if not initial_rules:
        initial_rules = _select_initial_rules_from_briefing(briefing_path, archetype)

    arch_name = initial_rules.get("archetype", archetype if archetype != "auto" else "trend_following")

    state: Dict[str, Any] = {
        "session_dir": AUTORESEARCH_DIR,
        "target": target or f"{arch_name.replace('_', ' ').title()} Alpha Discovery",
        "scope": scope or "Multi-Regime Historical Series",
        "context": context or f"Net Sharpe >= {MIN_SHARPE}, MaxDD <= {MAX_DRAWDOWN*100:.1f}%, DSR >= {DSR_THRESHOLD}",
        "archetype": arch_name,
        "run_number": 0,
        "best_score": 0,
        "best_validation_score": 0,
        "max_score": 7,
        "criteria_count": 7,
        "confidence_margin": 1,
        "plateau_counter": 0,
        "active_mutation_operator": "baseline",
    }

    if os.path.exists(briefing_path):
        try:
            with open(briefing_path, "r", encoding="utf-8") as f:
                briefing_data = json.load(f)
            state["empirical_macro_regime"] = briefing_data.get("macro_regime_characteristics", {})
            state["empirical_anomalies_count"] = briefing_data.get("statistically_significant_count", 0)
            print(
                f"{TOOL_NAME} Ingested session empirical briefing "
                f"({state['empirical_anomalies_count']} statistically significant anomalies; "
                f"recommended archetype: {briefing_data.get('recommended_archetype')})."
            )
        except Exception:
            pass

    state_path = os.path.join(AUTORESEARCH_DIR, "state.json")
    rules_path = os.path.join(AUTORESEARCH_DIR, "rules.json")
    best_rules_path = os.path.join(AUTORESEARCH_DIR, "best_rules.json")
    best_rule_single = os.path.join(AUTORESEARCH_DIR, "best_rule.json")
    results_path = os.path.join(AUTORESEARCH_DIR, "results.jsonl")

    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    with open(rules_path, "w", encoding="utf-8") as f:
        json.dump(initial_rules, f, indent=2)
    with open(best_rules_path, "w", encoding="utf-8") as f:
        json.dump(initial_rules, f, indent=2)
    with open(best_rule_single, "w", encoding="utf-8") as f:
        json.dump(initial_rules, f, indent=2)
    if not os.path.exists(results_path):
        with open(results_path, "w", encoding="utf-8") as f:
            pass

    print(f"{TOOL_NAME} Session state initialized (Archetype: {arch_name}).")


def action_scan(data_path: str = "data/candles_15m.csv") -> Dict[str, Any]:
    from tools.anomaly_scanner import generate_empirical_briefing, print_ascii_briefing

    print(f"{TOOL_NAME} Scanning {data_path} across all 6 orthogonal strategy families...")
    out_path = os.path.join(AUTORESEARCH_DIR, "empirical_briefing.json")
    briefing = generate_empirical_briefing(
        data_path,
        output_path=out_path,
        session_id=os.path.basename(AUTORESEARCH_DIR),
    )
    print_ascii_briefing(briefing)
    return briefing


def _mutate_numeric_thresholds(expr: str, factor: float) -> str:
    def replacer(match: re.Match) -> str:
        op = match.group(1)
        raw_num = match.group(2)
        val = float(raw_num)
        if val == 0.0:
            return match.group(0)
        new_val = val * factor if ">" in op else val * (2.0 - factor)
        if "." in raw_num:
            decimals = len(raw_num.split(".")[1])
            formatted = f"{new_val:.{decimals}f}"
        else:
            formatted = f"{int(round(new_val))}" if abs(new_val) >= 1 else f"{new_val:.2f}"
        return f"{op} {formatted}"

    pattern = r"([><]=?)\s*(-?[0-9]+\.?[0-9]*)"
    return re.sub(pattern, replacer, expr)


def _get_dynamic_candidate_constraint(existing_long: str, features_path: str = "") -> Tuple[Optional[str], Optional[str]]:
    # First consult empirical_briefing.json for data-mined top-IC TA-Lib/library features
    briefing_file = os.path.join(AUTORESEARCH_DIR, "empirical_briefing.json")
    if os.path.exists(briefing_file):
        try:
            with open(briefing_file, "r", encoding="utf-8") as f:
                b_data = json.load(f)
            for feat_info in b_data.get("top_predictive_library_features", []):
                col = feat_info.get("feature", "")
                if not col or col in existing_long:
                    continue
                q = feat_info.get("quantiles", {})
                q80, q20, q50 = q.get("q80"), q.get("q20"), q.get("q50")
                if q80 is None or q20 is None or q80 <= q20:
                    continue
                ic_val = float(feat_info.get("peak_ic", 0.0))
                if ic_val >= 0:
                    return f"{col} >= {q50}", f"{col} <= {q50}"
                else:
                    return f"{col} <= {q50}", f"{col} >= {q50}"
        except Exception:
            pass

    candidates = [
        ("adx_14 > 18", "adx_14 > 18"),
        ("volume_zscore > 0.3", "volume_zscore > 0.3"),
        ("ema_21 > ema_50", "ema_21 < ema_50"),
        ("macd_hist > 0", "macd_hist < 0"),
        ("hurst_proxy > 0.48", "hurst_proxy > 0.48"),
        ("rsi_14 > 50", "rsi_14 < 50"),
    ]
    for long_c, short_c in candidates:
        key_tok = long_c.split()[0]
        if key_tok not in existing_long:
            return long_c, short_c
    return None, None


def mutate_rules(
    rules: Dict[str, Any],
    operator: str,
    failures: List[str],
    features_path: str = "",
) -> Dict[str, Any]:
    mutated = dict(rules)

    if operator == "tighten_thresholds":
        if mutated.get("entry_long"):
            mutated["entry_long"] = _mutate_numeric_thresholds(mutated["entry_long"], factor=1.08)
        if mutated.get("entry_short"):
            mutated["entry_short"] = _mutate_numeric_thresholds(mutated["entry_short"], factor=1.08)
        mutated["stoploss_pct"] = round(max(0.005, float(mutated.get("stoploss_pct", 0.015)) * 0.92), 4)

    elif operator == "restructure_exit":
        half_life = None
        briefing_file = os.path.join(AUTORESEARCH_DIR, "empirical_briefing.json")
        if os.path.exists(briefing_file):
            try:
                with open(briefing_file, "r", encoding="utf-8") as f:
                    b_data = json.load(f)
                sig_anom = [
                    a for a in b_data.get("empirical_anomalies_detected", [])
                    if a.get("is_statistically_significant")
                ]
                if sig_anom:
                    half_life = int(sig_anom[0].get("alpha_half_life_bars", 12))
            except Exception:
                pass

        curr_bars = int(mutated.get("max_bars_held", 12))
        if half_life and half_life != curr_bars:
            new_bars = max(4, half_life)
        else:
            new_bars = int(curr_bars * 1.4) if curr_bars <= 12 else max(6, int(curr_bars * 0.75))

        mutated["max_bars_held"] = new_bars
        mutated["exit"] = f"bars >= {new_bars}"
        mutated["takeprofit_pct"] = round(
            max(float(mutated.get("stoploss_pct", 0.014)) * 1.8, float(mutated.get("takeprofit_pct", 0.032)) * 1.12),
            4,
        )

    elif operator == "add_constraint":
        long_c, short_c = _get_dynamic_candidate_constraint(mutated.get("entry_long", ""), features_path)
        if long_c and short_c:
            mutated["entry_long"] = f"{mutated['entry_long']} and {long_c}" if mutated.get("entry_long") else long_c
            mutated["entry_short"] = f"{mutated['entry_short']} and {short_c}" if mutated.get("entry_short") else short_c
        else:
            mutated["entry_long"] = _mutate_numeric_thresholds(mutated.get("entry_long", ""), factor=1.05)
            mutated["entry_short"] = _mutate_numeric_thresholds(mutated.get("entry_short", ""), factor=1.05)

    elif operator == "add_negative_example":
        if "adx_14" not in mutated.get("entry_long", ""):
            mutated["entry_long"] = f"{mutated['entry_long']} and adx_14 > 16"
            mutated["entry_short"] = f"{mutated['entry_short']} and adx_14 > 16"
        else:
            mutated["entry_long"] = _mutate_numeric_thresholds(mutated["entry_long"], factor=0.94)
            mutated["entry_short"] = _mutate_numeric_thresholds(mutated["entry_short"], factor=0.94)

    elif operator == "remove_bloat":
        for side in ["entry_long", "entry_short"]:
            expr = mutated.get(side, "")
            clauses = [c.strip() for c in expr.split(" and ") if c.strip()]
            if len(clauses) > 1:
                mutated[side] = " and ".join(clauses[:-1])

    elif operator == "directional_bias_flip":
        curr_bias = mutated.get("bias", "DUAL")
        new_bias = "LONG" if curr_bias == "DUAL" else ("SHORT" if curr_bias == "LONG" else "DUAL")
        mutated["bias"] = new_bias

    elif operator == "plateau_break":
        briefing_file = os.path.join(AUTORESEARCH_DIR, "empirical_briefing.json")
        switched = False
        if os.path.exists(briefing_file):
            try:
                with open(briefing_file, "r", encoding="utf-8") as f:
                    b_data = json.load(f)
                rankings = b_data.get("edge_family_synthesis", {}).get("family_rankings", [])
                curr_arch = mutated.get("archetype", "")
                for fam in rankings:
                    cand_arch = fam.get("archetype", "")
                    if cand_arch and cand_arch != curr_arch and fam.get("suggested_entry_long"):
                        mutated["archetype"] = cand_arch
                        mutated["entry_long"] = fam["suggested_entry_long"]
                        mutated["entry_short"] = fam.get("suggested_entry_short", fam["suggested_entry_long"])
                        mutated["max_bars_held"] = max(4, int(fam.get("optimal_horizon_bars", 12)))
                        mutated["exit"] = f"bars >= {mutated['max_bars_held']}"
                        switched = True
                        print(f"{TOOL_NAME} Plateau Break: Switched to orthogonal family '{fam.get('family')}' ({cand_arch})")
                        break
            except Exception:
                pass

        if not switched:
            arch_order = ["trend_following", "momentum_breakout", "volatility_squeeze", "mtf_pullback", "zscore_reversion", "session_breakout"]
            curr_arch = mutated.get("archetype", "trend_following")
            next_idx = (arch_order.index(curr_arch) + 1) % len(arch_order) if curr_arch in arch_order else 0
            next_arch = arch_order[next_idx]
            mutated = dict(ARCHETYPE_TEMPLATES[next_arch])
            print(f"{TOOL_NAME} Plateau Break: Rotated to orthogonal archetype '{next_arch}'.")

    return mutated


def _compute_perturbed_sharpe_matrix(df: Any, rules: Dict[str, Any]) -> List[List[float]]:
    from tools.vectorized_screener import evaluate_rule_dict_on_df

    thresh_factors = [0.92, 1.00, 1.08]
    sl_factors = [0.90, 1.00, 1.10]
    matrix: List[List[float]] = []

    base_sl = float(rules.get("stoploss_pct", 0.015))
    base_tp = float(rules.get("takeprofit_pct", 0.035))

    for tf in thresh_factors:
        row: List[float] = []
        for sf in sl_factors:
            p_rules = dict(rules)
            if tf != 1.0:
                if p_rules.get("entry_long"):
                    p_rules["entry_long"] = _mutate_numeric_thresholds(p_rules["entry_long"], tf)
                if p_rules.get("entry_short"):
                    p_rules["entry_short"] = _mutate_numeric_thresholds(p_rules["entry_short"], tf)
            p_rules["stoploss_pct"] = round(max(0.003, base_sl * sf), 4)
            p_rules["takeprofit_pct"] = round(max(0.006, base_tp * sf), 4)
            try:
                res = evaluate_rule_dict_on_df(df, p_rules, fee_bps=FEE_BPS, slippage_bps=SLIPPAGE_BPS)
                row.append(float(res.get("sharpe", 0.0)))
            except Exception:
                row.append(0.0)
        matrix.append(row)
    return matrix


def execute_screener_eval(rules: Dict[str, Any], features_path: str) -> Dict[str, Any]:
    import numpy as np
    import pandas as pd
    from server.indicators import compute_all_standard_features
    from tools.vectorized_screener import evaluate_rule_dict_on_df

    output_returns = os.path.join(AUTORESEARCH_DIR, "candidate_returns.json")
    df = pd.read_csv(features_path)
    df.columns = [c.lower() for c in df.columns]
    if "ema_21" not in df.columns and {"open", "high", "low", "close", "volume"}.issubset(df.columns):
        df = compute_all_standard_features(df, window=20)

    try:
        screener_res = evaluate_rule_dict_on_df(df, rules, fee_bps=FEE_BPS, slippage_bps=SLIPPAGE_BPS)
    except Exception as e:
        print(f"{TOOL_NAME} Screener evaluation error: {e}")
        return {
            "status": "REJECT",
            "sharpe": 0.0,
            "trades": 0,
            "win_rate": 0.0,
            "max_drawdown": 1.0,
            "profit_factor": 0.0,
            "expectancy_bps": 0.0,
            "r_squared": 0.0,
            "k_ratio": 0.0,
            "dsr": 0.0,
            "param_stability": "FAIL",
            "verdict": "REJECTED",
        }

    trade_returns = screener_res.get("trade_returns", [])
    with open(output_returns, "w", encoding="utf-8") as f:
        json.dump(trade_returns, f)

    if len(trade_returns) < 10:
        return {
            "status": "REJECT",
            "sharpe": screener_res.get("sharpe", 0.0),
            "trades": screener_res.get("trades", 0),
            "win_rate": screener_res.get("win_rate", 0.0),
            "max_drawdown": screener_res.get("max_drawdown", 0.0),
            "profit_factor": screener_res.get("profit_factor", 0.0),
            "expectancy_bps": screener_res.get("expectancy_bps", 0.0),
            "r_squared": screener_res.get("equity_r_squared", 0.0),
            "k_ratio": screener_res.get("k_ratio", 0.0),
            "dsr": 0.0,
            "param_stability": "INCONCLUSIVE",
            "verdict": "REJECTED",
        }

    metric_matrix = _compute_perturbed_sharpe_matrix(df, rules)
    ledger_path = os.path.join(AUTORESEARCH_DIR, "trial_ledger.jsonl")
    n_trials = n_trials_for_dsr(path=ledger_path)

    ret_arr = np.asarray(trade_returns, dtype=float)
    cynic_res = evaluate_gates(
        ret_arr,
        n_trials=n_trials,
        metric_matrix=np.asarray(metric_matrix, dtype=float),
        observed_sr=float(screener_res.get("sharpe", 0.0)),
        returns_are_net=True,
    )

    dsr_val = float(cynic_res.get("gate_1_dsr", {}).get("dsr") or 0.0)
    param_status = cynic_res.get("gate_2_parameter_stability", {}).get("status", "INCONCLUSIVE")

    return {
        "status": screener_res.get("status", "REJECT"),
        "sharpe": screener_res.get("sharpe", 0.0),
        "trades": screener_res.get("trades", 0),
        "win_rate": screener_res.get("win_rate", 0.0),
        "max_drawdown": screener_res.get("max_drawdown", 0.0),
        "profit_factor": screener_res.get("profit_factor", 0.0),
        "expectancy_bps": screener_res.get("expectancy_bps", 0.0),
        "r_squared": screener_res.get("equity_r_squared", 0.0),
        "k_ratio": screener_res.get("k_ratio", 0.0),
        "dsr": dsr_val,
        "param_stability": param_status,
        "verdict": cynic_res.get("verdict", "REJECTED"),
        "gates_passed": cynic_res.get("gates_summary", {}).get("gates_passed", 0),
        "gates_total": cynic_res.get("gates_summary", {}).get("gates_total", 8),
    }


def action_step(features_path: Optional[str] = None, rules_override: Optional[str] = None) -> Dict[str, Any]:
    state_path = os.path.join(AUTORESEARCH_DIR, "state.json")
    rules_path = os.path.join(AUTORESEARCH_DIR, "rules.json")
    best_rules_path = os.path.join(AUTORESEARCH_DIR, "best_rules.json")
    best_rule_single = os.path.join(AUTORESEARCH_DIR, "best_rule.json")
    results_path = os.path.join(AUTORESEARCH_DIR, "results.jsonl")
    ledger_path = os.path.join(AUTORESEARCH_DIR, "trial_ledger.jsonl")

    if not features_path:
        features_path = os.path.join(AUTORESEARCH_DIR, "features.csv")

    if not os.path.exists(state_path) or not os.path.exists(rules_path):
        print(f"{TOOL_NAME} No initialized session state found. Running 'init' first...")
        action_init(target="", scope="", context="", archetype="auto")

    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)

    if rules_override:
        if os.path.exists(rules_override):
            with open(rules_override, "r", encoding="utf-8") as f:
                current_rules = json.load(f)
        else:
            try:
                current_rules = json.loads(rules_override)
            except Exception:
                with open(rules_path, "r", encoding="utf-8") as f:
                    current_rules = json.load(f)
        with open(rules_path, "w", encoding="utf-8") as f:
            json.dump(current_rules, f, indent=2)
    else:
        with open(rules_path, "r", encoding="utf-8") as f:
            current_rules = json.load(f)

    with open(best_rules_path, "r", encoding="utf-8") as f:
        best_rules = json.load(f)

    run_num = state.get("run_number", 0) + 1
    print(f"\n{TOOL_NAME} ========================================================")
    print(f"{TOOL_NAME} STARTING AUTORESEARCH CYCLE #{run_num} (Archetype: {current_rules.get('archetype', state.get('archetype'))})")
    print(f"{TOOL_NAME} Session Workspace: {AUTORESEARCH_DIR}")
    print(f"{TOOL_NAME} ========================================================")

    if not os.path.exists(features_path):
        candles_path = "data/candles_15m.csv"
        if os.path.exists(candles_path):
            print(f"{TOOL_NAME} Generating session features {features_path} from {candles_path}...")
            subprocess.run(
                [get_python_exec(), "tools/feature_miner.py", "--input", candles_path, "--output", features_path],
                check=True,
            )
        else:
            print(f"{TOOL_NAME} ERROR: Neither {features_path} nor {candles_path} exist.")
            sys.exit(1)

    metrics = execute_screener_eval(current_rules, features_path)

    record_trial(
        kind="miner_step",
        fingerprint=_trial_fingerprint(current_rules),
        metrics={"sharpe": metrics.get("sharpe"), "dsr": metrics.get("dsr")},
        source="autoresearch_miner",
        path=ledger_path,
    )

    criteria = {
        "sharpe_gte_min": 1 if metrics["sharpe"] >= MIN_SHARPE else 0,
        "drawdown_lte_max": 1 if metrics["max_drawdown"] <= MAX_DRAWDOWN else 0,
        "sample_trades_gte_min": 1 if (
            metrics["trades"] >= MIN_TRADES_SIGNIFICANT and metrics["win_rate"] >= MIN_WIN_RATE
        ) else 0,
        "fee_drag_protected": 1 if metrics["expectancy_bps"] >= MIN_EXPECTANCY_BPS else 0,
        "dsr_gte_threshold": 1 if metrics["dsr"] >= DSR_THRESHOLD else 0,
        "param_plateau": 1 if metrics["param_stability"] == "PASS" else 0,
        "equity_linearity_gte_min": 1 if metrics.get("r_squared", 0.0) >= MIN_R2 else 0,
    }

    score = sum(criteria.values())
    validation_score = score

    pending = [c for c in ("param_plateau",) if metrics.get("param_stability") == "INCONCLUSIVE"]
    max_score = max(1, len(criteria) - len(pending))
    state["pending_criteria"] = pending
    failures = [crit for crit, val in criteria.items() if val == 0 and crit not in pending]

    best_v_score = state.get("best_validation_score", -1)
    best_sharpe = float(state.get("best_sharpe", -999.0))
    plateau_counter = state.get("plateau_counter", 0)

    is_keep = (validation_score > best_v_score) or (
        validation_score == best_v_score and float(metrics["sharpe"]) > best_sharpe
    )

    if is_keep:
        status = "KEEP"
        state["best_score"] = score
        state["best_validation_score"] = validation_score
        state["best_sharpe"] = float(metrics["sharpe"])
        state["plateau_counter"] = 0
        best_rules = dict(current_rules)
        with open(best_rules_path, "w", encoding="utf-8") as f:
            json.dump(best_rules, f, indent=2)
        with open(best_rule_single, "w", encoding="utf-8") as f:
            json.dump(best_rules, f, indent=2)
        print(f"{TOOL_NAME} Result: [KEEP] New Best Validation Score: {validation_score}/{max_score} (Sharpe: {metrics['sharpe']})!")
    else:
        status = "DISCARD"
        state["plateau_counter"] = plateau_counter + 1
        current_rules = dict(best_rules)
        print(f"{TOOL_NAME} Result: [DISCARD] Validation Score {validation_score}/{max_score} did not beat best {best_v_score}/{max_score}.")

    operators = [
        "add_constraint",
        "add_negative_example",
        "restructure_exit",
        "tighten_thresholds",
        "remove_bloat",
        "directional_bias_flip",
    ]

    if state["plateau_counter"] >= 4:
        chosen_op = "plateau_break"
        state["plateau_counter"] = 0
        print(f"{TOOL_NAME} Plateau breaker triggered. Rotating to orthogonal strategy family...")
    else:
        chosen_op = operators[(run_num - 1) % len(operators)]

    next_rules = mutate_rules(best_rules, chosen_op, failures, features_path=features_path)
    with open(rules_path, "w", encoding="utf-8") as f:
        json.dump(next_rules, f, indent=2)

    result_entry = {
        "run": run_num,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "score": score,
        "validation_score": validation_score,
        "max": max_score,
        "metrics": metrics,
        "criteria": criteria,
        "status": status,
        "mutation_operator": chosen_op,
        "failures": failures,
        "rules": current_rules,
    }

    with open(results_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(result_entry) + "\n")

    state["run_number"] = run_num
    state["active_mutation_operator"] = chosen_op
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    dispatch_telemetry({
        "id": "autoresearch_loop_telemetry",
        "component": "MetricCard",
        "title": "Autoresearch Alpha Swarm",
        "phase": f"CYCLE #{run_num}",
        "props": {
            "value": f"{status} (Score {validation_score}/{max_score})",
            "target": f"Best {state['best_validation_score']}/{max_score}",
            "status": "PASS" if is_keep else "WARN",
            "subtitle": f"Op: {chosen_op} | Sharpe: {metrics['sharpe']} | DSR: {metrics['dsr']}",
        },
    })

    print(f"{TOOL_NAME} Cycle #{run_num} Completed:")
    print(f"  Status:             {status}")
    print(f"  Score:              {validation_score}/{max_score} (Cynic Gates: {metrics.get('gates_passed', 0)}/{metrics.get('gates_total', 8)})")
    print(f"  Sharpe / Win Rate:  {metrics['sharpe']} / {metrics['win_rate']*100:.1f}%")
    print(f"  DSR / MaxDD / R^2:  {metrics['dsr']} / {metrics['max_drawdown']*100:.2f}% / {metrics.get('r_squared', 0.0):.2f}")
    print(f"  Param Stability:    {metrics.get('param_stability')}")
    print(f"  Next Mutation:      {chosen_op}")
    return result_entry


def action_run(cycles: int, features_path: Optional[str] = None, archetype: str = "auto") -> None:
    state_path = os.path.join(AUTORESEARCH_DIR, "state.json")
    if not os.path.exists(state_path):
        action_init(target="", scope="", context="", archetype=archetype)
    print(f"{TOOL_NAME} Initiating continuous autonomous research loop ({cycles} cycles)...")
    for _ in range(cycles):
        action_step(features_path)
        time.sleep(0.1)
    print(f"\n{TOOL_NAME} Finished batch of {cycles} cycles.")
    action_status()


def action_status() -> None:
    state_path = os.path.join(AUTORESEARCH_DIR, "state.json")
    results_path = os.path.join(AUTORESEARCH_DIR, "results.jsonl")
    best_rules_path = os.path.join(AUTORESEARCH_DIR, "best_rules.json")

    if not os.path.exists(state_path):
        print(f"{TOOL_NAME} No active autoresearch environment found in {AUTORESEARCH_DIR}/.")
        return

    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)

    runs = []
    if os.path.exists(results_path):
        with open(results_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        runs.append(json.loads(line.strip()))
                    except Exception:
                        pass

    best_rules = {}
    if os.path.exists(best_rules_path):
        with open(best_rules_path, "r", encoding="utf-8") as f:
            best_rules = json.load(f)

    print("\n" + "=" * 72)
    print(f"{TOOL_NAME} SESSION STATUS & TELEMETRY SUMMARY")
    print("=" * 72)
    print(f"  Session Directory:       {AUTORESEARCH_DIR}")
    print(f"  Target:                  {state.get('target')}")
    print(f"  Total Runs Executed:     {state.get('run_number', 0)}")
    print(f"  Best Validation Score:   {state.get('best_validation_score', 0)} / {state.get('max_score', 7)}")
    print(f"  Plateau Counter:         {state.get('plateau_counter', 0)} / 4")
    print(f"  Active Mutation Operator:{state.get('active_mutation_operator')}")
    print("-" * 72)
    print("  CURRENT BEST RULES:")
    print(f"    Archetype:  {best_rules.get('archetype')}")
    print(f"    LONG:       {best_rules.get('entry_long')}")
    print(f"    SHORT:      {best_rules.get('entry_short')}")
    print(f"    Holding:    {best_rules.get('max_bars_held')} bars")
    print(f"    SL / TP:    {best_rules.get('stoploss_pct')} / {best_rules.get('takeprofit_pct')}")
    print("-" * 72)
    if runs:
        print("  RECENT CYCLE HISTORY (Last 5):")
        for r in runs[-5:]:
            stat = r.get("status")
            sc = r.get("validation_score")
            mx = r.get("max")
            op = r.get("mutation_operator")
            sh = r.get("metrics", {}).get("sharpe", 0.0)
            dsr = r.get("metrics", {}).get("dsr", 0.0)
            r2 = r.get("metrics", {}).get("r_squared", 0.0)
            print(f"    Run #{r.get('run'):<3} [{stat:<7}] Score: {sc}/{mx} | Sharpe: {sh:<5} | DSR: {dsr:<5} | R2: {r2:<4} | Op: {op}")
    print("=" * 72 + "\n")


def action_improve_tool(tool_name: str) -> None:
    print(f"{TOOL_NAME} Running Meta-Autoresearch self-improvement audit on tool: {tool_name}...")
    tools_dir = "tools"
    target_path = os.path.join(tools_dir, tool_name) if not tool_name.startswith("tools/") else tool_name

    if not os.path.exists(target_path):
        print(f"{TOOL_NAME} ERROR: Tool file not found at {target_path}")
        sys.exit(1)

    findings = []
    try:
        py_compile.compile(target_path, doraise=True)
        findings.append("Syntax compilation: PASS")
    except Exception as e:
        findings.append(f"Syntax compilation: FAIL ({e})")

    with open(target_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    has_shebang = len(lines) > 0 and lines[0].startswith("#!/usr/bin/env python3")
    has_tool_name = any("TOOL_NAME =" in l or "TOOL_NAME=" in l for l in lines)
    findings.append(f"Shebang '#!/usr/bin/env python3': {'PASS' if has_shebang else 'WARN'}")
    findings.append(f"Standard TOOL_NAME constant: {'PASS' if has_tool_name else 'WARN'}")

    t0 = time.time()
    try:
        subprocess.run([get_python_exec(), target_path, "--help"], capture_output=True, text=True, timeout=5)
        duration_ms = (time.time() - t0) * 1000
        findings.append(f"CLI Help Invocation latency: {duration_ms:.1f}ms (PASS)")
    except Exception as e:
        findings.append(f"CLI Help Invocation: FAIL ({e})")

    print("\n" + "=" * 60)
    print(f"{TOOL_NAME} META-AUDIT REPORT: {target_path}")
    print("=" * 60)
    for f_item in findings:
        print(f"  • {f_item}")
    print("=" * 60 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="NujinSkills Multi-Paradigm Autonomous Quant Research Engine")
    parser.add_argument("action", choices=["init", "scan", "step", "run", "status", "improve-tool"], help="Autoresearch action")
    parser.add_argument("--id", "--experiment", "--session", dest="session_id", default="", help="Session ID to isolate research in .nujin/sessions/<id>/")
    parser.add_argument("--new-session", action="store_true", help="Start a brand-new isolated session")
    parser.add_argument("--target", default="", help="Optimization target description")
    parser.add_argument("--scope", default="", help="Target scope (symbol/timeframe)")
    parser.add_argument("--context", default="", help="Target constraints/context")
    parser.add_argument(
        "--archetype", "--dimension",
        default="auto",
        choices=[
            "auto",
            "trend_following",
            "momentum_breakout",
            "volatility_squeeze",
            "mtf_pullback",
            "zscore_reversion",
            "vwap_reversion",
            "mean_reversion",
            "session_breakout",
            "price_action",
            "smc_liquidity",
            "custom",
        ],
        help="Strategy archetype template (default: auto — selects best family from empirical briefing)",
    )
    parser.add_argument("--initial-rules", default="", help="JSON string or file path containing initial candidate rules")
    parser.add_argument("--rules-file", default="", help="Candidate rules JSON file or string to evaluate in this step")
    parser.add_argument("--features", default=None, help="Feature data CSV path (defaults to session features.csv)")
    parser.add_argument("--data", default="data/candles_15m.csv", help="Candle dataset path for scan")
    parser.add_argument("--cycles", "--max-iterations", type=int, default=5, help="Number of continuous cycles for 'run'")
    parser.add_argument("--tool", default="feature_miner.py", help="Tool filename for 'improve-tool'")
    args = parser.parse_args()

    active_dir = resolve_research_dir(
        args.session_id,
        new_session=(args.new_session or (args.action == "init" and not args.session_id and not get_active_session_id())),
    )
    features_file = args.features if args.features else os.path.join(active_dir, "features.csv")

    if args.action == "init":
        action_init(args.target, args.scope, args.context, archetype=args.archetype, initial_rules_input=args.initial_rules)
    elif args.action == "scan":
        action_scan(args.data)
    elif args.action == "step":
        action_step(features_file, rules_override=args.rules_file)
    elif args.action == "run":
        action_run(args.cycles, features_file, archetype=args.archetype)
    elif args.action == "status":
        action_status()
    elif args.action == "improve-tool":
        action_improve_tool(args.tool)


if __name__ == "__main__":
    main()
