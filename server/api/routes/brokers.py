import logging
from typing import Optional
from fastapi import APIRouter, HTTPException

from server.api.deps import broker_registry

logger = logging.getLogger("NujinBrokersRouter")
router = APIRouter(tags=["Brokers & Accounts"])


@router.get("/api/brokers")
async def list_brokers():
    """
    Returns all registered execution brokers, active broker, and connection status.

    Discovery only: this endpoint reports what is installed and configured, and never
    authenticates. If the executor already opened a session, the live adapter is reused and
    its real balance/equity ride along; otherwise those fields are reported as not connected.
    """
    brokers = broker_registry.list_available_brokers(connect=False)
    active_id = broker_registry.get_active_broker_id()
    return {
        "active_broker": active_id,
        "brokers": brokers,
        "total": len(brokers),
    }


@router.get("/api/brokers/accounts")
async def list_broker_accounts(broker_id: Optional[str] = None):
    """Returns all configured broker accounts across all users (with credentials masked)."""
    from server.accounts_store import accounts_store
    from server.brokers.registry import broker_registry

    # Live refresh active broker info to guarantee real-time balance sync
    try:
        broker = broker_registry.get_broker()
        if broker and getattr(broker, "is_connected", False) and hasattr(broker, "get_account_info"):
            info = broker.get_account_info() or {}
            b_id = getattr(broker, "broker_id", "paper")
            bal = float(info.get("balance") or 0.0)
            eq = float(info.get("equity") or bal or 0.0)
            if b_id != "paper" and bal > 0 and hasattr(accounts_store, "update_account_balance"):
                accounts_store.update_account_balance(broker_id=b_id, balance=bal, equity=eq)
    except Exception as e_info:
        logger.debug(f"[BrokersAPI] Live get_account_info check note: {e_info}")

    active_accounts = accounts_store.get_all_active_accounts(broker_id=broker_id, decrypt=False)
    for a in active_accounts:
        a["login_masked"] = accounts_store.mask_login(a.get("login", ""))
        a.pop("password_encrypted", None)
        a.pop("password", None)
    return {
        "accounts": active_accounts,
        "total": len(active_accounts),
    }


@router.delete("/api/brokers/accounts/{account_id}")
async def delete_broker_account(account_id: str):
    """Deletes a broker account by ID."""
    from server.accounts_store import accounts_store
    from server.providers.base import ProviderRegistry
    acc = accounts_store.get_account_by_id(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    user_id = acc.get("telegram_user_id", "")
    ok = accounts_store.delete_account(account_id, user_id)
    if ok:
        ProviderRegistry.invalidate_cache()
    return {"deleted": ok, "account_id": account_id}


@router.post("/api/brokers/accounts/{account_id}/toggle")
async def toggle_broker_account(account_id: str):
    """Toggles active status of a broker account."""
    from server.accounts_store import accounts_store
    from server.providers.base import ProviderRegistry
    acc = accounts_store.get_account_by_id(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    user_id = acc.get("telegram_user_id", "")
    new_status = not acc.get("is_active", True)
    ok = accounts_store.toggle_account_active(account_id, user_id, is_active=new_status)
    if ok:
        ProviderRegistry.invalidate_cache()
    return {"success": ok, "account_id": account_id, "is_active": new_status}
