import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

from server.api.deps import (
    manager,
    bot_supervisor,
    strategy_registry,
    state_manager,
)
from server.runtime.background import (
    cron_backtest_scheduler,
    strategy_auto_discovery_watcher,
    strategy_runner_auto_healer,
)

logger = logging.getLogger("NujinLifespan")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Modern 2026 FastAPI lifespan context manager.
    Asset-agnostic execution OS: boots background watchers and dynamic market feeds.
    """
    # ── Startup Phase ──────────────────────────────────────────────────────────
    bot_supervisor.set_broadcast_callback(manager.broadcast)
    logger.info("[NujinSkillsServer] Launching Periodic Strategy Cron Backtest Scheduler...")
    asyncio.create_task(cron_backtest_scheduler())
    logger.info("[NujinSkillsServer] Launching Strategy Auto-Discovery File Watcher...")
    asyncio.create_task(strategy_auto_discovery_watcher())

    # Launch interactive Telegram bot listener for multi-account onboarding & trade management
    try:
        from server.telegram.telegram_listener import run_telegram_listener
        asyncio.create_task(run_telegram_listener())
        logger.info("[NujinSkillsServer] Telegram Interactive Listener task launched.")
    except Exception as e_tl:
        logger.warning(f"[NujinSkillsServer] Could not launch Telegram listener: {e_tl}")

    # Dynamically warm up authentic market data providers for active strategies via ProviderRegistry
    from server.providers.base import ProviderRegistry
    active_strats = [s for s in strategy_registry.get_all(sync=False) if s.get("status") == "ACTIVE_LIVE"]
    warmed_targets = set()
    for s in active_strats:
        sym = s.get("symbol") or "BTC/USDT"
        tf = s.get("timeframe") or "15m"
        warmed_targets.add((sym, tf))

    if not warmed_targets:
        curr_state = state_manager.get()
        warmed_targets.add((curr_state.get("symbol", "BTC/USDT"), curr_state.get("timeframe", "15m")))

    for sym, tf in warmed_targets:
        try:
            p = ProviderRegistry.get_provider(sym, tf)
            asyncio.create_task(p.start())
            logger.info(f"[NujinSkillsServer] Dynamic market provider started for {sym} ({tf})")
        except Exception as e_p:
            logger.warning(f"[NujinSkillsServer] Error starting dynamic provider for {sym} ({tf}): {e_p}")

    # Automatically resume existing managed active strategies only if system status is RUNNING
    try:
        curr_sys_status = state_manager.get().get("status", "STOPPED")
        if curr_sys_status != "STOPPED":
            active_strats = [s["name"] for s in strategy_registry.get_all(sync=False) if s.get("status") == "ACTIVE_LIVE"]
            for s_name in active_strats:
                bot_supervisor.deploy_strategy(s_name, mode="dry-run")
                logger.info(f"[NujinSkillsServer] Resumed managed active strategy: {s_name}")
        else:
            logger.info("[NujinSkillsServer] System status is STOPPED. Skipping automatic strategy deployment on startup.")
    except Exception as e:
        logger.warning(f"[NujinSkillsServer] Error checking/resuming active strategies on startup: {e}")

    # Launch Strategy Runner Auto-Healer Watchdog Loop
    asyncio.create_task(strategy_runner_auto_healer())

    # Dynamically initialize any background services exposed by active plugins (zero hardcoding)
    from server.plugin_loader import plugin_manager
    asyncio.create_task(plugin_manager.start_plugin_services())

    yield

    # ── Shutdown Phase ─────────────────────────────────────────────────────────
    logger.info("[NujinSkillsServer] Gracefully shutting down telemetry and execution server...")
