import logging
import os
from typing import Optional
from fastapi import APIRouter

from server.api.deps import (
    manager,
    bot_supervisor,
    strategy_registry,
    state_manager,
)
from server.schemas.bot import SelectStrategyRequest
from server.schemas.strategy import (
    UpdateStrategyStatusRequest,
    RunStrategyBacktestRequest,
    RemoveStrategyRequest,
)
from server.backtest_engine import run_real_backtest

logger = logging.getLogger("NujinStrategiesRouter")
router = APIRouter(tags=["Strategies & Backtesting"])


@router.post("/api/strategies/select")
async def select_and_run_strategy(req: SelectStrategyRequest):
    logger.info(f"Strategy selected for inspection: {req.strategy}")
    clean_name = req.strategy.replace(".py", "")
    strat_record = strategy_registry.get(clean_name)

    curr_sys_state = state_manager.get()
    is_active_sys = (clean_name == curr_sys_state.get("active_strategy"))
    trade_markers = strat_record.get("trade_markers") or (curr_sys_state.get("trade_markers", []) if is_active_sys else [])
    trades_detail = strat_record.get("trades_detail") or (curr_sys_state.get("trades_detail", []) if is_active_sys else [])

    cached_days = strat_record.get("latest_backtest", {}).get("duration_days") if strat_record else None
    days_match = (req.days is None) or (cached_days is not None and abs(float(cached_days) - float(req.days)) <= 2.5)
    if strat_record and strat_record.get("latest_backtest") and len(trade_markers) > 0 and len(trades_detail) > 0 and days_match:
        logger.info(f"[SelectStrategy] Returning cached audited backtest ({cached_days}d) with {len(trade_markers)} markers for {clean_name}")
        summary = strat_record.get("latest_backtest", {})
        gates = strat_record.get("falsification_gates", {})
        eq = strat_record.get("backtest_equity_curve", [])
        symbol = strat_record.get("symbol", "XAU/USD")
        timeframe = strat_record.get("timeframe", "1m")
        thesis = strat_record.get("thesis", f"Autonomous Alpha Model: {clean_name}")
        thesis_props = {
            "thesis": thesis,
            "counterparty": "Trapped breakout liquidity / volatility expansion",
            "invalidation": "Stop-loss triggered beyond structural extreme",
            "target_profile": strat_record.get("target_profile", f"{clean_name} Profile"),
        }

        tp = strat_record.get("time_period") or {
            "start_time": summary.get("start_time"),
            "end_time": summary.get("end_time"),
            "start_date": summary.get("start_date"),
            "end_date": summary.get("end_date"),
            "duration_days": summary.get("duration_days"),
            "period_label": summary.get("period_label"),
            "candles_count": summary.get("candles_count"),
        }

        result = {
            "strategy": clean_name,
            "symbol": symbol,
            "timeframe": timeframe,
            "summary": summary,
            "time_period": tp,
            "falsification_gates": gates,
            "equity_curve": eq,
            "thesis_props": thesis_props,
            "trade_markers": trade_markers,
            "trades_detail": trades_detail,
            "drift_history": strat_record.get("cron_config", {}).get("drift_history", []),
            "strategy_record": strat_record,
        }
        await manager.broadcast({"event_type": "BACKTEST_UPDATED", "payload": result})
        return result

    result = run_real_backtest(req.strategy, save_as_active=False, days=req.days or 30)
    await manager.broadcast({"event_type": "BACKTEST_UPDATED", "payload": result})
    return result


@router.get("/api/backtest")
async def get_backtest_results(strategy: Optional[str] = None):
    if strategy:
        return run_real_backtest(strategy, save_as_active=False)
    active_strat = strategy_registry.get_active_strategy_name()
    return run_real_backtest(active_strat, save_as_active=False)


@router.get("/api/strategies")
async def list_strategies():
    strategies_dir = os.path.join(os.getcwd(), "strategies")
    os.makedirs(strategies_dir, exist_ok=True)

    managed = strategy_registry.get_all(sync=True)

    strategy_files = []
    for s in managed:
        file_name = s.get("file") or f"{s.get('name')}.py"
        rel_path = s.get("path") or f"strategies/{file_name}"
        abs_path = os.path.join(os.getcwd(), rel_path)
        stat_size = 0
        stat_mtime = 0
        if os.path.exists(abs_path):
            st = os.stat(abs_path)
            stat_size = st.st_size
            stat_mtime = st.st_mtime
        raw_sym = s.get("symbol")
        if not raw_sym or str(raw_sym).lower() in ["pair", "symbol", "none", "self.symbol"] or str(raw_sym).startswith("self."):
            if any(k in file_name.upper() for k in ["XAU", "GOLD"]):
                strat_sym = "XAU/USD"
            elif any(k in file_name.upper() for k in ["SP", "ES", "OPENING"]):
                strat_sym = "S&P 500 (ES)"
            else:
                strat_sym = "BTC/USDT"
        else:
            strat_sym = raw_sym

        strategy_files.append({
            "name": file_name,
            "path": rel_path,
            "is_pro": s.get("is_pro", False),
            "plugin_name": s.get("plugin_name"),
            "plugin_id": s.get("plugin_id"),
            "display_name": s.get("display_name", file_name.replace(".py", "")),
            "symbol": strat_sym,
            "timeframe": s.get("timeframe", "5m" if any(k in file_name.upper() for k in ["XAU", "GOLD"]) else ("1m" if any(k in file_name.upper() for k in ["SP", "ES", "OPENING"]) else "15m")),
            "size_bytes": stat_size,
            "last_modified": stat_mtime,
            "status": s.get("status", "DEACTIVATED"),
            "rank": s.get("rank", 99),
            "tier": s.get("tier", "C-Tier"),
            "sharpe": s.get("latest_backtest", {}).get("sharpe", 0.0),
            "win_rate": s.get("latest_backtest", {}).get("win_rate", 0.0),
        })

    return {"strategies": strategy_files, "total": len(strategy_files)}


@router.post("/api/strategies/sync")
async def sync_strategies_endpoint():
    """Explicit endpoint to force strategy filesystem re-scan & WebSocket broadcast."""
    all_strats = strategy_registry.sync_with_filesystem()
    portfolio = strategy_registry.get_portfolio_summary()
    distribution = strategy_registry.get_distribution_analytics()
    payload = {
        "strategies": all_strats,
        "portfolio_summary": portfolio,
        "distribution_analytics": distribution,
    }
    await manager.broadcast({"event_type": "STRATEGIES_UPDATED", "payload": payload})
    return {"status": "SUCCESS", "total": len(all_strats), **payload}


@router.get("/api/strategies/manage")
async def get_managed_strategies():
    """Returns full list of managed strategies with rankings, stats, portfolio summary, and distribution analytics."""
    strats = strategy_registry.get_all(sync=True)
    portfolio = strategy_registry.get_portfolio_summary()
    distribution = strategy_registry.get_distribution_analytics()
    return {
        "strategies": strats,
        "total": len(strats),
        "portfolio_summary": portfolio,
        "distribution_analytics": distribution,
    }


@router.get("/api/strategies/manage/portfolio")
async def get_portfolio_overview():
    """Returns aggregated portfolio performance across all active strategies plus drift distribution."""
    return {
        "portfolio_summary": strategy_registry.get_portfolio_summary(),
        "distribution_analytics": strategy_registry.get_distribution_analytics(),
    }


@router.get("/api/portfolio/correlation")
async def get_portfolio_correlation(threshold: float = 0.50, strategies: Optional[str] = None, data_path: str = "data/candles_15m.csv"):
    """
    Returns pairwise correlation matrix, regime slicing attribution,
    ensemble metrics, and redundancy/complementarity audit flags.
    """
    try:
        from tools.portfolio_cynic import evaluate_portfolio
        s_list = [s.strip() for s in strategies.split(",") if s.strip()] if strategies else None
        report = evaluate_portfolio(strategy_names=s_list, data_path=data_path, correlation_threshold=threshold)
        return report
    except Exception as e:
        logger.error(f"[PortfolioCynic] Error computing portfolio correlation: {e}")
        return {
            "error": str(e),
            "strategies": [],
            "correlation_matrix": {},
            "spearman_matrix": {},
            "individual_metrics": {},
            "regime_breakdown": {},
            "portfolio_ensemble": {},
            "pairwise_analysis": [],
        }


@router.post("/api/strategies/manage/status")
async def update_managed_strategy_status(req: UpdateStrategyStatusRequest):
    """Update strategy lifecycle status: ACTIVE_LIVE, CRON_BACKTEST, DEACTIVATED with multi-strategy support."""
    updated = strategy_registry.update_status(req.strategy, req.status, exclusive=bool(req.exclusive))
    if req.status == "ACTIVE_LIVE":
        bot_supervisor.deploy_strategy(req.strategy, mode="dry-run")
        await manager.broadcast({"event_type": "STATE_UPDATED", "payload": state_manager.get()})
    elif req.status in ("CRON_BACKTEST", "DEACTIVATED"):
        bot_supervisor.stop_strategy(req.strategy)
        await manager.broadcast({"event_type": "STATE_UPDATED", "payload": state_manager.get()})

    all_strats = strategy_registry.get_all(sync=False)
    portfolio = strategy_registry.get_portfolio_summary()
    distribution = strategy_registry.get_distribution_analytics()

    payload = {
        "strategies": all_strats,
        "portfolio_summary": portfolio,
        "distribution_analytics": distribution,
    }
    await manager.broadcast({"event_type": "STRATEGIES_UPDATED", "payload": payload})
    return {"status": "SUCCESS", "strategy": updated, **payload}


@router.post("/api/strategies/manage/run-backtest")
async def run_managed_strategy_backtest(req: RunStrategyBacktestRequest):
    """Execute on-demand quantitative backtest for a strategy and update registry."""
    clean_name = req.strategy.replace(".py", "")
    curr_active = state_manager.get().get("active_strategy", "").replace(".py", "")
    is_active = (clean_name == curr_active)
    result = run_real_backtest(
        req.strategy,
        save_as_active=is_active,
        days=req.days or 30,
        timeframe_override=req.timeframe,
        account_size=req.account_size,
    )
    strategy_registry.record_backtest(req.strategy, result, is_cron=False)
    all_strats = strategy_registry.get_all(sync=False)
    portfolio = strategy_registry.get_portfolio_summary()
    distribution = strategy_registry.get_distribution_analytics()
    payload = {
        "strategies": all_strats,
        "portfolio_summary": portfolio,
        "distribution_analytics": distribution,
    }
    await manager.broadcast({"event_type": "STRATEGIES_UPDATED", "payload": payload})
    return {"status": "SUCCESS", "result": result, **payload}


@router.post("/api/strategies/manage/cron-trigger")
async def trigger_cron_evaluations():
    """Trigger periodic backtest evaluations across all strategies marked CRON_BACKTEST."""
    strats = strategy_registry.get_all(sync=False)
    cron_targets = [s for s in strats if s.get("status") == "CRON_BACKTEST"]
    evaluated = []
    for s in cron_targets:
        try:
            res = run_real_backtest(s["file"], save_as_active=False)
            strategy_registry.record_backtest(s["name"], res, is_cron=True)
            evaluated.append(s["name"])
        except Exception as e:
            logger.error(f"[CronScheduler] Backtest failed for {s['name']}: {e}")
    all_strats = strategy_registry.get_all(sync=False)
    portfolio = strategy_registry.get_portfolio_summary()
    distribution = strategy_registry.get_distribution_analytics()
    payload = {
        "strategies": all_strats,
        "portfolio_summary": portfolio,
        "distribution_analytics": distribution,
    }
    await manager.broadcast({"event_type": "STRATEGIES_UPDATED", "payload": payload})
    return {"status": "SUCCESS", "evaluated": evaluated, **payload}


@router.get("/api/strategies/manage/rankings")
async def get_strategy_rankings():
    """Returns sorted quantitative leaderboard with ranking breakdown, sub-scores, tiers, and tier distribution."""
    strats = strategy_registry.get_all(sync=False)
    strats_sorted = sorted(strats, key=lambda s: s.get("ranking_score", 0.0), reverse=True)
    distribution = strategy_registry.get_distribution_analytics()
    return {
        "status": "SUCCESS",
        "rankings": strats_sorted,
        "total": len(strats_sorted),
        "tier_distribution": distribution.get("tier_distribution", {}),
        "sharpe_distribution": distribution.get("sharpe_distribution", {})
    }


@router.post("/api/strategies/manage/rank")
async def recalculate_strategy_rankings():
    """
    Recalculates multi-pillar quantitative rankings and tiers across all strategies.
    Saves updated state to data/strategies.json and broadcasts STRATEGIES_UPDATED via WebSocket.
    """
    ranked = strategy_registry.recalculate_and_save()
    portfolio = strategy_registry.get_portfolio_summary()
    distribution = strategy_registry.get_distribution_analytics()
    payload = {
        "strategies": ranked,
        "portfolio_summary": portfolio,
        "distribution_analytics": distribution,
    }
    await manager.broadcast({"event_type": "STRATEGIES_UPDATED", "payload": payload})
    return {
        "status": "SUCCESS",
        "message": f"Successfully recalculated rankings across {len(ranked)} strategies.",
        "top_strategy": ranked[0].get("name") if ranked else None,
        "total": len(ranked),
        **payload,
    }


@router.post("/api/strategies/manage/remove")
async def remove_strategy_endpoint(req: RemoveStrategyRequest):
    """Safely remove a strategy from disk, re-sync registry, and broadcast update to Cockpit."""
    success = strategy_registry.remove_strategy(req.strategy)
    all_strats = strategy_registry.get_all(sync=True)
    portfolio = strategy_registry.get_portfolio_summary()
    distribution = strategy_registry.get_distribution_analytics()
    payload = {
        "strategies": all_strats,
        "portfolio_summary": portfolio,
        "distribution_analytics": distribution,
    }
    await manager.broadcast({"event_type": "STRATEGIES_UPDATED", "payload": payload})
    await manager.broadcast({"event_type": "STATE_UPDATED", "payload": state_manager.get()})
    return {"status": "SUCCESS" if success else "NOT_FOUND", "strategy": req.strategy, **payload}
