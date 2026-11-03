import logging
from typing import Optional
from fastapi import APIRouter, HTTPException

from server.api.deps import (
    manager,
    signal_store,
    strategy_registry,
    state_manager,
    telegram_gateway,
    broker_registry,
)
from server.schemas.signal import (
    CloseSignalRequest,
    ClearSignalsRequest,
    DeleteSignalRequest,
)

logger = logging.getLogger("NujinSignalsRouter")
router = APIRouter(tags=["Signals & Positions"])


@router.get("/api/signals")
async def get_signals(strategy: Optional[str] = None):
    signals_list = signal_store.get_all(strategy)
    active = signal_store.get_active(strategy)
    all_actives = signal_store.get_active_signals()
    return {
        "signals": signals_list,
        "active_signal": active,
        "active_signals": all_actives,
        "total": len(signals_list),
    }


@router.get("/api/signals/stats")
async def get_live_signal_stats(strategy: Optional[str] = None):
    """Live performance stats — delegates to SignalStore (single source of truth)."""
    return signal_store.get_stats(strategy)


@router.post("/api/signals/clear")
async def clear_signals(req: Optional[ClearSignalsRequest] = None):
    strat = req.strategy if req else None
    remaining = signal_store.clear(strat)
    await manager.broadcast({"event_type": "SIGNALS_CLEARED", "payload": {"strategy": strat, "remaining": len(remaining)}})

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
    return {"status": "SUCCESS", "message": f"Signals cleared{' for ' + strat if strat else ''}."}


@router.post("/api/signals/delete")
async def delete_signal_endpoint(req: DeleteSignalRequest):
    sigs = signal_store.get_all()
    remaining = [s for s in sigs if s.get("id") != req.id]
    from server.state_manager import _write_json_locked
    _write_json_locked(signal_store._path, remaining)
    state_manager.patch({"signals_count": len(remaining)})
    await manager.broadcast({"event_type": "SIGNAL_DELETED", "payload": {"id": req.id, "remaining": len(remaining)}})
    await manager.broadcast({"event_type": "SIGNALS_UPDATED", "payload": remaining})
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
    return {"status": "SUCCESS", "deleted_id": req.id, "total": len(remaining)}


@router.post("/api/signals/close")
@router.post("/api/strategy/close-position")
async def close_signal_position(req: CloseSignalRequest):
    # 1. Retrieve the signal being closed (if any)
    active_sig = None
    if req.id:
        for s in signal_store.get_active_signals():
            if str(s.get("id")) == str(req.id):
                active_sig = s
                break
    if not active_sig and req.strategy:
        active_sig = signal_store.get_active(req.strategy)

    exit_p = req.exit_price
    if not exit_p or exit_p <= 0:
        sym = (active_sig.get("pair") or active_sig.get("symbol")) if active_sig else ""
        if sym:
            from server.providers.base import ProviderRegistry
            try:
                p = ProviderRegistry.get_provider(sym)
                q = p.get_latest_quote()
                exit_p = float(q.get("price") or 0.0)
            except Exception:
                pass
        if (not exit_p or exit_p <= 0) and active_sig:
            exit_p = float(active_sig.get("price") or 0.0)

    # 2. Invoke Active Execution Broker to close live positions across all TradeLocker accounts
    try:
        broker = broker_registry.get_broker()
        if broker:
            symbol_to_close = (active_sig.get("pair") or active_sig.get("symbol")) if active_sig else ""
            pos_id = (active_sig.get("broker_order", {}).get("order_id")) if active_sig else None
            pos_id_to_close = str(pos_id or req.id or req.strategy or "ALL")

            logger.info(f"[Signals] 🚀 Triggering broker position close on {broker.name} for symbol '{symbol_to_close}' (pos_id: {pos_id_to_close})...")
            broker.close_position(
                position_id=pos_id_to_close,
                reason=req.exit_reason or "MANUAL_CLOSE",
                current_price=exit_p,
                symbol=symbol_to_close,
            )
    except Exception as e_broker_close:
        logger.error(f"[Signals] Error triggering broker position close: {e_broker_close}")

    # 3. Close in SignalStore
    closed = signal_store.close_position(
        signal_id=req.id,
        strategy=req.strategy,
        exit_price=exit_p,
        exit_reason=req.exit_reason or "MANUAL_CLOSE",
        pnl_pct=req.pnl_pct,
    )
    if not closed:
        raise HTTPException(status_code=404, detail="No active position found matching criteria")

    # 4. Dispatch Telegram notification for trade exit
    try:
        telegram_gateway.format_and_send_trade_close(closed)
    except Exception as e_tg:
        logger.warning(f"[Signals] Telegram trade close alert failed: {e_tg}")

    await manager.broadcast({"event_type": "SIGNAL_CLOSED", "payload": closed})

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
    return {"status": "SUCCESS", "closed_signal": closed}
