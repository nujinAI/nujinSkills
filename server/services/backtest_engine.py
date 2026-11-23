"""
server/services/backtest_engine.py - Canonical Unified Backtest Engine.
Orchestrates quantitative dual-directional backtesting, Cynic audit gates,
and persists telemetry using shared core/ analytics and discrete simulation.
"""
import os
import sys
import json
import time
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

import contextlib
from server.state_manager import state_manager, strategy_registry
from server import data_manager
from server.cynic_gates import compute_dsr, verify_monte_carlo, evaluate_gates
from server.trial_ledger import record_trial, n_trials_for_dsr
from server.constants import trade_annualization_factor, MAX_MDD_99
from core.friction import get_roundtrip_friction
from core.simulation import run_discrete_simulation, resolve_strategy_close_eod
from core.data import bars_for_days, get_market_price_precision
from core.regimes import classify_market_regimes, compute_regime_breakdown
from core.analytics import (
    compute_summary_metrics,
    compute_equity_curve,
    compute_return_distribution,
    compute_account_growth_models,
)

# Re-export strategy loader and stability auditor functions for 100% backwards compatibility
from server.services.strategy_loader import (
    _ensure_freqtrade_shim,
    load_strategy_instance,
    resolve_strategy_metadata,
)
from server.services.stability_auditor import (
    compute_strategy_parameter_stability_matrix,
)

logger = logging.getLogger("BacktestEngine")
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def resolve_default_account_size(user_override: Optional[float] = None) -> float:
    """
    Single Source of Truth resolver for active account balance.
    Prioritizes explicit user override -> active connected broker account -> $5,000 baseline.
    """
    if user_override and float(user_override) > 0:
        return float(user_override)
    try:
        from server.accounts_store import accounts_store
        active_accs = accounts_store.get_all_active_accounts()
        if active_accs:
            for acc in active_accs:
                bal = acc.get("balance") or acc.get("initial_balance")
                if bal and float(bal) > 0:
                    return float(bal)
    except Exception:
        pass
    try:
        accts_file = os.path.join(_ROOT, "data", "broker_accounts.json")
        if os.path.exists(accts_file):
            with open(accts_file) as f:
                d = json.load(f)
                for a in d.get("accounts", []):
                    if a.get("is_active"):
                        bal = a.get("balance") or a.get("initial_balance")
                        if bal and float(bal) > 0:
                            return float(bal)
    except Exception:
        pass
    return 5000.0


def _derive_dataset_time_period(
    df_c: pd.DataFrame,
    trades_detail: List[Dict[str, Any]],
    days: Optional[int],
    timeframe: str
) -> Dict[str, Any]:
    """Derives precise timestamp ranges and labels for the evaluated backtest period."""
    valid_ts = df_c[df_c['timestamp'] > 1000000000]['timestamp'] if 'timestamp' in df_c.columns else pd.Series([])
    ds_end_ts = int(valid_ts.iloc[-1]) if len(valid_ts) > 0 else (int(trades_detail[-1]["exit_time"]) if trades_detail else int(time.time()))
    if days and days > 0 and len(valid_ts) > 0:
        raw_start = ds_end_ts - int(days * 86400)
        ds_start_ts = max(raw_start, int(valid_ts.iloc[0]))
        duration_days = round((ds_end_ts - ds_start_ts) / 86400, 1)
        candles_count = int((df_c['timestamp'] >= ds_start_ts).sum())
    else:
        ds_start_ts = int(valid_ts.iloc[0]) if len(valid_ts) > 0 else (int(trades_detail[0]["entry_time"]) if trades_detail else int(time.time()))
        duration_days = round((ds_end_ts - ds_start_ts) / 86400, 1)
        candles_count = len(df_c)

    dt_start = datetime.fromtimestamp(ds_start_ts, tz=timezone.utc)
    dt_end = datetime.fromtimestamp(ds_end_ts, tz=timezone.utc)
    start_date_str = dt_start.strftime("%Y-%m-%d %H:%M UTC")
    end_date_str = dt_end.strftime("%Y-%m-%d %H:%M UTC")
    provider_max_reached = bool(days and days > 0 and duration_days < (float(days) - 1.5))
    if provider_max_reached:
        period_label = f"{dt_start.strftime('%Y-%m-%d')} → {dt_end.strftime('%Y-%m-%d')} ({duration_days:.1f}d — max {timeframe} depth)"
    else:
        period_label = f"{dt_start.strftime('%Y-%m-%d')} → {dt_end.strftime('%Y-%m-%d')} ({duration_days:.1f}d)"

    return {
        "start_time": ds_start_ts,
        "end_time": ds_end_ts,
        "start_date": start_date_str,
        "end_date": end_date_str,
        "duration_days": duration_days,
        "period_label": period_label,
        "candles_count": candles_count,
        "provider_max_reached": provider_max_reached,
        "first_trade_time": trades_detail[0]["entry_time"] if trades_detail else ds_start_ts,
        "last_trade_time": trades_detail[-1]["exit_time"] if trades_detail else ds_end_ts,
    }


@contextlib.contextmanager
def _audit_lock(lock_path: str):
    """Advisory exclusive lock protecting shared data/ files during concurrent audits."""
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    try:
        import fcntl
    except ImportError:
        fcntl = None
    fh = open(lock_path, "a+", encoding="utf-8")
    try:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def _resolve_effective_mdd(max_mdd: Optional[float], strat_inst: Any = None) -> float:
    """Resolves MDD99 ceiling dynamically: explicit arg -> strategy attribute -> NUJIN_MAX_MDD_99 env -> default MAX_MDD_99."""
    if max_mdd is not None and float(max_mdd) > 0:
        return float(max_mdd)
    if strat_inst is not None:
        strat_mdd = getattr(strat_inst, "max_mdd", getattr(strat_inst, "max_mdd_99", None))
        if strat_mdd is not None and float(strat_mdd) > 0:
            return float(strat_mdd)
    env_mdd = os.environ.get("NUJIN_MAX_MDD_99")
    if env_mdd:
        try:
            val = float(env_mdd)
            if val > 0:
                return val
        except ValueError:
            pass
    return float(MAX_MDD_99)


def run_real_backtest(
    strategy_name: str = "",
    save_as_active: bool = False,
    timeframe_override: Optional[str] = None,
    days: Optional[int] = None,
    account_size: Optional[float] = None,
    max_mdd: Optional[float] = None,
    run_dir: Optional[str] = None,
) -> dict:
    """
    Executes real quantitative dual-directional (LONG & SHORT) backtest and DSR cynic audit.
    Zero hardcoded strategy logic: dynamically evaluates strategy definitions and rules
    loaded from strategies/*.py, data/strategies.json, and data/state.json as Single Source of Truth.
    Thread/process-safe via per-run isolation (`run_dir`) and advisory file locking.
    """
    data_dir = os.path.join(_ROOT, "data")
    lock_cm = contextlib.nullcontext() if run_dir else _audit_lock(os.path.join(data_dir, ".audit.lock"))
    with lock_cm:
        return _run_real_backtest_impl(
            strategy_name=strategy_name,
            save_as_active=save_as_active,
            timeframe_override=timeframe_override,
            days=days,
            account_size=account_size,
            max_mdd=max_mdd,
            run_dir=run_dir,
        )


def _run_real_backtest_impl(
    strategy_name: str = "",
    save_as_active: bool = False,
    timeframe_override: Optional[str] = None,
    days: Optional[int] = None,
    account_size: Optional[float] = None,
    max_mdd: Optional[float] = None,
    run_dir: Optional[str] = None,
) -> dict:
    curr_sys_state = state_manager.get()
    if not strategy_name:
        strategy_name = strategy_registry.get_active_strategy_name()

    clean_name = strategy_name.replace(".py", "")
    logger.info(f"[BacktestEngine] Running dynamic quantitative backtest for strategy: {clean_name} (save_as_active={save_as_active})")

    meta = resolve_strategy_metadata(clean_name, timeframe_override=timeframe_override)
    symbol = meta["symbol"]
    timeframe = meta["timeframe"]
    thesis_props = meta["thesis_props"]

    work_dir = os.path.abspath(run_dir) if run_dir else os.path.join(_ROOT, "data")
    os.makedirs(work_dir, exist_ok=True)
    features_file = os.path.join(work_dir, "features.csv")
    returns_file = os.path.join(work_dir, "candidate_returns.json")

    # 1. Resolve Candle Dataset and Sync via Dynamic Single Source of Truth
    from core.data import fetch_ohlcv
    canon_sym = data_manager.resolve_market_symbol(symbol)
    candles_file = data_manager.get_market_dataset_path(canon_sym, timeframe, check_legacy=True)

    days_req = int(days) if (days and days > 0) else 30
    needed_count = bars_for_days(timeframe, days_req, buffer=1.15, min_bars=500, max_bars=15000)

    period_str = f"{max(days_req, 30)}d"
    logger.info(f"[BacktestEngine] Single Source of Truth fetch for {canon_sym} ({timeframe}, count={needed_count}, days={days_req}) via core.data...")
    try:
        df_dynamic = fetch_ohlcv(symbol=canon_sym, timeframe=timeframe, count=needed_count, period=period_str, use_cache=True)
        if df_dynamic is not None and not df_dynamic.empty:
            df_dynamic_reset = df_dynamic.copy()
            if not isinstance(df_dynamic_reset.index, pd.RangeIndex):
                df_dynamic_reset = df_dynamic_reset.reset_index(drop=True)
            if "time" in df_dynamic_reset.columns and "timestamp" not in df_dynamic_reset.columns:
                df_dynamic_reset["timestamp"] = df_dynamic_reset["time"]
            elif "timestamp" in df_dynamic_reset.columns and "time" not in df_dynamic_reset.columns:
                df_dynamic_reset["time"] = df_dynamic_reset["timestamp"]

            data_manager._save_canonical_and_legacy(canon_sym, timeframe, df_dynamic_reset, legacy_path=candles_file, source="data_tool_backtest")
    except Exception as e_dyn:
        logger.warning(f"[BacktestEngine] core.data fetch note: {e_dyn}, checking existing dataset on disk")

    if not os.path.exists(candles_file):
        raise FileNotFoundError(f"[BacktestEngine] Candle dataset file not found: {candles_file}")

    # Generate fresh features.csv atomically in-process using canonical core indicator library
    try:
        from core.indicators import compute_all_standard_features
        df_raw = pd.read_csv(candles_file)
        if not df_raw.empty:
            df_feat = compute_all_standard_features(df_raw)
            tmp_feat = f"{features_file}.{os.getpid()}.tmp"
            df_feat.to_csv(tmp_feat, index=False)
            os.replace(tmp_feat, features_file)
            logger.info(f"[BacktestEngine] Synchronized fresh feature set ({len(df_feat)} rows) to {features_file}")
    except Exception as e_feat:
        logger.warning(f"[BacktestEngine] Feature generation note: {e_feat}")

    # 2. Dynamic Strategy Loading & Indicator Computation
    strat_inst = load_strategy_instance(clean_name)
    effective_mdd = _resolve_effective_mdd(max_mdd, strat_inst)
    eff_close_eod = resolve_strategy_close_eod(strat_inst, canon_sym, timeframe)
    eod_hour = int(getattr(strat_inst, "eod_close_hour_utc", 21)) if strat_inst is not None else 21
    daily_carry_bps = float(getattr(strat_inst, "daily_carry_bps", 0.0) or 0.0) if strat_inst is not None else 0.0
    friction_override = getattr(strat_inst, "friction_override", None) if strat_inst is not None else None
    price_prec = get_market_price_precision(canon_sym)

    df_c = pd.read_csv(candles_file)
    df_c = df_c.dropna(subset=['open', 'high', 'low', 'close'])
    if 'timestamp' in df_c.columns:
        df_c['timestamp'] = df_c['timestamp'].ffill().bfill().fillna(0).astype(np.int64)
    df_c = df_c.reset_index(drop=True)
    if len(df_c) < 50:
        raise ValueError(f"[BacktestEngine] Candle dataset contains insufficient rows: {len(df_c)}")

    # 3. Dynamic Simulation Execution via core.simulation
    trade_markers: List[Dict[str, Any]] = []
    trades_detail: List[Dict[str, Any]] = []
    cutoff_time = (int(df_c['timestamp'].iloc[-1]) - int(days * 86400)) if (days and days > 0 and len(df_c) > 0 and 'timestamp' in df_c.columns) else 0

    if strat_inst and hasattr(strat_inst, "generate_signals"):
        df_idx = df_c.copy()
        df_idx['dt'] = pd.to_datetime(df_idx['timestamp'], unit='s', utc=True)
        df_idx = df_idx.set_index('dt')
        signals = strat_inst.generate_signals(df_idx)

        target_acct_size = resolve_default_account_size(account_size)
        acct_size = float(getattr(strat_inst, "account_size", target_acct_size))
        risk_pct = float(getattr(strat_inst, "risk_pct_1r", getattr(strat_inst, "risk_per_trade_pct", 0.0038)))
        dollar_risk = acct_size * risk_pct
        max_daily_l = int(getattr(strat_inst, "max_daily_losses", 1))
        daily_cap_pct = getattr(strat_inst, "daily_profit_cap_pct", None)
        daily_cap = (acct_size * daily_cap_pct) if daily_cap_pct else getattr(strat_inst, "daily_profit_cap", None)
        max_hold_b = int(getattr(strat_inst, "max_hold_bars", 6))

        res_disc = run_discrete_simulation(
            df=df_idx,
            signals=signals,
            symbol=canon_sym,
            account_size=acct_size,
            dollar_risk_1r=dollar_risk,
            max_daily_losses=max_daily_l,
            daily_profit_cap=daily_cap,
            max_hold_bars=max_hold_b,
            close_eod=eff_close_eod,
            eod_close_hour_utc=eod_hour,
            daily_carry_bps=daily_carry_bps,
            friction_override=friction_override,
        )

        for t in res_disc["trades"]:
            entry_ts = int(t.entry_time.timestamp()) if hasattr(t.entry_time, 'timestamp') else int(t.entry_time)
            exit_ts = int(t.exit_time.timestamp()) if hasattr(t.exit_time, 'timestamp') else int(t.exit_time)
            if entry_ts < cutoff_time:
                continue

            side = "LONG" if t.direction == 1 else "SHORT"
            pnl_pct = round((t.pnl_dollars / acct_size) * 100.0, 4)
            # Single Source of Truth: match exact round-trip friction charged by simulator (never double-count spread)
            rt_cost_pts = get_roundtrip_friction(canon_sym, t.entry_price, friction_override=friction_override)
            friction_bps = round((rt_cost_pts / max(float(t.entry_price), 1e-9)) * 10000.0, 1)

            exit_reason_map = {
                "TP": "TAKE_PROFIT",
                "SL": "STOP_LOSS",
                "TIME_STOP": "TIME_EXPIRATION",
                "EOD": "EOD"
            }
            exit_reason = exit_reason_map.get(t.exit_reason, t.exit_reason)
            price_fmt = f"${t.entry_price:.{price_prec}f}"

            trade_markers.append({
                "time": entry_ts,
                "position": "belowBar" if side == "LONG" else "aboveBar",
                "color": "#26a69a" if side == "LONG" else "#ef5350",
                "shape": "arrowUp" if side == "LONG" else "arrowDown",
                "text": f"[BT] {side} {price_fmt}",
                "entry_price": round(float(t.entry_price), price_prec),
                "raw_signal_price": round(float(t.entry_price), price_prec),
                "stop_loss": round(float(t.stop_loss), price_prec),
                "take_profit": round(float(t.target), price_prec),
                "side": side
            })
            trade_markers.append({
                "time": exit_ts,
                "position": "aboveBar" if side == "LONG" else "belowBar",
                "color": "#26a69a" if t.pnl_dollars >= 0 else "#ef5350",
                "shape": "arrowDown" if side == "LONG" else "arrowUp",
                "text": f"[BT] EXIT {pnl_pct:+.2f}%"
            })

            trades_detail.append({
                "id": len(trades_detail) + 1,
                "side": side,
                "entry_time": entry_ts,
                "entry_price": round(float(t.entry_price), price_prec),
                "raw_signal_price": round(float(t.entry_price), price_prec),
                "stop_loss": round(float(t.stop_loss), price_prec),
                "take_profit": round(float(t.target), price_prec),
                "exit_time": exit_ts,
                "exit_price": round(float(t.exit_price), price_prec),
                "raw_exit_price": round(float(t.exit_price), price_prec),
                "exit_reason": exit_reason,
                "friction_bps": friction_bps,
                "pnl_pct": pnl_pct,
                "pnl_dollars": round(float(t.pnl_dollars), 2),
                "pnl_r": round(float(t.pnl_r), 3)
            })
    else:
        logger.error(f"[BacktestEngine] Strategy {clean_name} does not provide generate_signals(). Cannot run backtest.")

    if len(trades_detail) == 0:
        raise RuntimeError(
            f"[BacktestEngine] Backtest produced zero trades for {clean_name} on {candles_file}. "
            "Verify that candle data exists and that strategy entry conditions can trigger."
        )

    # 4. Save Candidate Returns atomically for Cynic Audit
    returns_arr = np.array([tr["pnl_pct"] / 100.0 for tr in trades_detail], dtype=float)
    tmp_ret = f"{returns_file}.{os.getpid()}.tmp"
    with open(tmp_ret, "w") as f:
        json.dump(returns_arr.tolist(), f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_ret, returns_file)

    # 5. Cynic Audit Gate Evaluation
    mean_ret = float(np.mean(returns_arr))
    std_ret = float(np.std(returns_arr))
    sharpe = float((mean_ret / max(std_ret, 1e-6)) * trade_annualization_factor())

    record_trial(
        kind="backtest",
        fingerprint=clean_name,
        metrics={"sharpe": round(sharpe, 2), "trades": len(returns_arr)},
        source="backtest_engine",
    )
    trials_penalized = n_trials_for_dsr()
    dsr_res = compute_dsr(returns_arr, trials_penalized)
    real_dsr = float(dsr_res.get("dsr", 0.0))
    mc_res = verify_monte_carlo(returns_arr, max_mdd_99=effective_mdd)
    real_mdd_99 = float(mc_res.get("mdd_99", 0.0))
    avg_friction_bps = float(np.mean([tr["friction_bps"] for tr in trades_detail])) if trades_detail else 0.0

    # Derive accurate dataset time period
    time_period_info = _derive_dataset_time_period(df_c, trades_detail, days, timeframe)

    # 6. Post-Trade Analytics via canonical core/analytics & core/regimes
    backtest_summary = compute_summary_metrics(
        trades_detail=trades_detail,
        account_size=acct_size,
        time_info=time_period_info,
        dsr=real_dsr,
        mdd_99=real_mdd_99
    )

    regime_map = classify_market_regimes(df_c)
    regime_breakdown = compute_regime_breakdown(trades_detail, regime_map)
    equity_curve = compute_equity_curve(trades_detail)
    all_pnls = [tr["pnl_pct"] for tr in trades_detail]
    return_distribution = compute_return_distribution(all_pnls)

    account_summary = compute_account_growth_models(
        trades_detail=trades_detail,
        account_size=acct_size,
        account_mult=1.0
    )
    account_growth_models = account_summary.get("account_tiers", {})

    state = {
        "active_strategy": clean_name if save_as_active else curr_sys_state.get("active_strategy", clean_name),
        "target_profile": thesis_props["target_profile"],
        "symbol": canon_sym,
        "timeframe": timeframe,
        "status": "ACTIVE_DEPLOYED" if save_as_active else curr_sys_state.get("status", "PREVIEW"),
        "backtest_summary": backtest_summary,
        "summary": backtest_summary,
        "account_summary": account_summary,
        "account_growth_models": account_growth_models,
        "time_period": time_period_info,
        "signals_count": len(trades_detail),
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "trade_markers": trade_markers,
        "trades_detail": trades_detail,
        "equity_curve": equity_curve,
        "return_distribution": return_distribution,
        "regime_breakdown": regime_breakdown,
        "thesis_props": thesis_props
    }

    # 7. Cynic Gate Matrix Verification
    perturbed_matrix = compute_strategy_parameter_stability_matrix(
        df_c=df_c,
        strat_inst=strat_inst,
        observed_sr=sharpe,
        symbol=canon_sym,
        account_size=acct_size,
        close_eod=eff_close_eod,
        eod_close_hour_utc=eod_hour,
        daily_carry_bps=daily_carry_bps,
        friction_override=friction_override,
    )

    falsification_gates = evaluate_gates(
        returns_arr,
        n_trials=trials_penalized,
        strategy_name=clean_name,
        metric_matrix=perturbed_matrix,
        observed_sr=sharpe,
        regime_breakdown=regime_breakdown,
        returns_are_net=True,
        max_mdd_99=effective_mdd,
        avg_friction_bps=avg_friction_bps,
    )
    state["falsification_gates"] = falsification_gates

    result = {
        "strategy": clean_name,
        "symbol": symbol,
        "timeframe": timeframe,
        "state": state,
        "candidate_returns": returns_arr.tolist(),
        "summary": backtest_summary,
        "time_period": time_period_info,
        "thesis_props": thesis_props,
        "trade_markers": trade_markers,
        "trades_detail": trades_detail,
        "equity_curve": equity_curve,
        "account_summary": account_summary,
        "account_growth_models": account_growth_models,
        "return_distribution": return_distribution,
        "regime_breakdown": regime_breakdown,
        "falsification_gates": falsification_gates
    }

    # 8. Update Single Source of Truth
    if save_as_active:
        state_manager.set_full(state)

    try:
        strat_record = strategy_registry.record_backtest(clean_name, result, is_cron=False)
        if strat_record:
            result["drift_history"] = strat_record.get("cron_config", {}).get("drift_history", [])
            result["strategy_record"] = strat_record
    except Exception as e_reg:
        logger.warning(f"[BacktestEngine] Could not record backtest in strategy_registry: {e_reg}")

    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run Real Quantitative Backtest")
    parser.add_argument("--strategy", type=str, default="", help="Strategy name")
    parser.add_argument("--timeframe", type=str, default=None, help="Timeframe override")
    parser.add_argument("--days", type=int, default=None, help="Lookback days window")
    parser.add_argument("--account-size", type=float, default=None, help="Account size ($)")
    parser.add_argument("--save-active", action="store_true", help="Save as active strategy in state.json")
    args = parser.parse_args()

    res = run_real_backtest(
        strategy_name=args.strategy,
        save_as_active=args.save_active,
        timeframe_override=args.timeframe,
        days=args.days,
        account_size=args.account_size
    )
    s = res["summary"]
    print(f"\n=== BACKTEST COMPLETE: {res['strategy']} ===")
    print(f"Symbol: {res['symbol']} | Timeframe: {res['timeframe']}")
    print(f"Account: ${s.get('account_size', 5000):,.2f} | Net PnL: ${s.get('net_pnl_dollars', 0):+,.2f} ({s.get('net_pnl_pct', 0):+.2f}%)")
    print(f"Trades: {s['trades']} | Win Rate: {s['win_rate']*100:.1f}% | Profit Factor: {s['profit_factor']}")
    print(f"Sharpe: {s['sharpe']} | DSR: {s['dsr']} | Max DD: {s['max_drawdown']*100:.2f}%")
    print(f"Period: {s['period_label']} ({s['candles_count']} bars)")
