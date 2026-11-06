import asyncio
import logging
import os
from server.api.deps import (
    manager,
    strategy_registry,
    bot_supervisor,
)
from server.backtest_engine import run_real_backtest

logger = logging.getLogger("NujinBackgroundWorkers")


async def cron_backtest_scheduler():
    """Periodically evaluates CRON_BACKTEST strategies once a day (86400s) to track drift."""
    while True:
        await asyncio.sleep(86400)
        try:
            strats = strategy_registry.get_all(sync=False)
            cron_targets = [s for s in strats if s.get("status") == "CRON_BACKTEST"]
            if cron_targets:
                logger.info(f"[CronScheduler] Daily evaluation of {len(cron_targets)} CRON_BACKTEST strategies...")
                for s in cron_targets:
                    try:
                        res = run_real_backtest(s["file"], save_as_active=False)
                        strategy_registry.record_backtest(s["name"], res, is_cron=True)
                    except Exception as e_c:
                        logger.warning(f"[CronScheduler] Error evaluating {s['name']}: {e_c}")
                all_strats = strategy_registry.get_all(sync=False)
                portfolio = strategy_registry.get_portfolio_summary()
                distribution = strategy_registry.get_distribution_analytics()
                await manager.broadcast({
                    "event_type": "STRATEGIES_UPDATED",
                    "payload": {
                        "strategies": all_strats,
                        "portfolio_summary": portfolio,
                        "distribution_analytics": distribution,
                    },
                })
        except Exception as e:
            logger.error(f"[CronScheduler] Daily loop error: {e}")


async def strategy_auto_discovery_watcher():
    """
    Watches strategies/*.py directory and data/strategies.json for changes.
    When a new strategy is created (by AI agent, CLI tool, or user):
      1. Automatically registers it in strategy_registry.
      2. Automatically executes an initial quantitative backtest in a worker thread.
      3. Broadcasts STRATEGY_DISCOVERED and STRATEGIES_UPDATED over WebSocket.
    When an existing strategy is modified or deleted:
      Syncs filesystem and broadcasts STRATEGIES_UPDATED.
    """
    strategies_dir = os.path.join(os.getcwd(), "strategies")
    os.makedirs(strategies_dir, exist_ok=True)
    strategies_json = os.path.join(os.getcwd(), "data", "strategies.json")

    def _get_strategies_snapshot():
        snap = {}
        if os.path.exists(strategies_dir):
            for fname in os.listdir(strategies_dir):
                if fname.endswith(".py") and not fname.startswith("__"):
                    fpath = os.path.join(strategies_dir, fname)
                    try:
                        st = os.stat(fpath)
                        snap[fname] = (st.st_mtime, st.st_size)
                    except OSError:
                        pass
        return snap

    def _get_json_mtime():
        if os.path.exists(strategies_json):
            try:
                return os.path.getmtime(strategies_json)
            except OSError:
                return 0.0
        return 0.0

    known_files = _get_strategies_snapshot()
    last_json_mtime = _get_json_mtime()
    logger.info(f"[StrategyWatcher] Initialized real-time strategy watcher with {len(known_files)} strategies on disk.")

    while True:
        await asyncio.sleep(1.5)
        try:
            curr_files = _get_strategies_snapshot()
            curr_json_mtime = _get_json_mtime()

            new_files = set(curr_files.keys()) - set(known_files.keys())
            removed_files = set(known_files.keys()) - set(curr_files.keys())
            modified_files = {
                f for f in curr_files.keys() & known_files.keys()
                if curr_files[f] != known_files[f]
            }

            has_file_changes = bool(new_files or removed_files or modified_files)
            json_changed_externally = (curr_json_mtime != last_json_mtime and not has_file_changes)

            if has_file_changes:
                logger.info(f"[StrategyWatcher] Detected strategy changes: new={list(new_files)}, modified={list(modified_files)}, removed={list(removed_files)}")

                all_strats = strategy_registry.sync_with_filesystem()

                for new_file in new_files:
                    clean_name = new_file.replace(".py", "")
                    meta = strategy_registry._infer_metadata(new_file)
                    logger.info(f"[StrategyWatcher] 🚀 New strategy discovered: {new_file} ({meta.get('display_name')}). Emitting discovery & running initial backtest...")

                    await manager.broadcast({
                        "event_type": "STRATEGY_DISCOVERED",
                        "payload": {
                            "strategy": clean_name,
                            "file": new_file,
                            "display_name": meta.get("display_name", clean_name),
                            "target_profile": meta.get("target_profile", ""),
                            "thesis": meta.get("thesis", ""),
                            "symbol": meta.get("symbol", "BTC/USDT"),
                            "timeframe": meta.get("timeframe", "15m"),
                        },
                    })

                    try:
                        await asyncio.to_thread(run_real_backtest, new_file, save_as_active=False)
                        logger.info(f"[StrategyWatcher] Initial backtest complete for {new_file}")
                    except Exception as bt_err:
                        logger.warning(f"[StrategyWatcher] Initial backtest error for {new_file}: {bt_err}")

                all_strats = strategy_registry.get_all(sync=False)
                portfolio = strategy_registry.get_portfolio_summary()
                distribution = strategy_registry.get_distribution_analytics()

                await manager.broadcast({
                    "event_type": "STRATEGIES_UPDATED",
                    "payload": {
                        "strategies": all_strats,
                        "portfolio_summary": portfolio,
                        "distribution_analytics": distribution,
                    },
                })

                known_files = curr_files
                last_json_mtime = _get_json_mtime()

            elif json_changed_externally:
                last_json_mtime = curr_json_mtime
                logger.info(f"[StrategyWatcher] data/strategies.json changed externally. Broadcasting update...")
                all_strats = strategy_registry.get_all(sync=False)
                portfolio = strategy_registry.get_portfolio_summary()
                distribution = strategy_registry.get_distribution_analytics()

                await manager.broadcast({
                    "event_type": "STRATEGIES_UPDATED",
                    "payload": {
                        "strategies": all_strats,
                        "portfolio_summary": portfolio,
                        "distribution_analytics": distribution,
                    },
                })

        except Exception as e:
            logger.error(f"[StrategyWatcher] Auto-discovery loop error: {e}")


async def strategy_runner_auto_healer():
    """
    Active Execution Watchdog:
    Runs continuously every 15 seconds to audit all ACTIVE_LIVE strategies.
    If an active strategy has lost its native background runner (native_active: False),
    it automatically revives the runner and re-subscribes it to market ticks/bars.
    """
    logger.info("[AutoHealer] Strategy Runner Watchdog active (15s heartbeat).")
    while True:
        try:
            await asyncio.sleep(15)
            active_strats = [s["name"] for s in strategy_registry.get_all(sync=False) if s.get("status") == "ACTIVE_LIVE"]
            for s_name in active_strats:
                r_info = bot_supervisor.runners.get(s_name)
                native_runner = r_info.get("native_runner") if r_info else None
                is_active = bool(native_runner and native_runner.is_running)
                if not is_active:
                    logger.warning(f"[AutoHealer] ⚠️ Inactive runner detected for ACTIVE_LIVE strategy '{s_name}'. Reviving execution pipeline...")
                    bot_supervisor.deploy_strategy(s_name, mode="dry-run")
                    logger.info(f"[AutoHealer] ✅ Successfully revived and re-subscribed runner for '{s_name}'.")
        except Exception as e_heal:
            logger.error(f"[AutoHealer] Error in watchdog heartbeat: {e_heal}")
