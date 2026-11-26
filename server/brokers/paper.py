"""
server/brokers/paper.py
─────────────────────────────────────────────────────────────
Default In-Memory & Local Database Simulated Execution Broker.
Requires zero external API credentials or third-party packages.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Any, List, Optional

from server.brokers.base import BaseExecutionBroker
from server.state_manager import signal_store

logger = logging.getLogger("PaperExecutionBroker")


class PaperExecutionBroker(BaseExecutionBroker):
    """
    Standard Paper Trading execution adapter.
    Logs trades locally into SignalStore with simulated fills.
    """

    def __init__(self):
        super().__init__(broker_id="paper", name="Nujin Simulated Paper Execution")
        self.initial_balance = self._resolve_initial_balance()
        self.balance = self.initial_balance
        self.is_connected = True

    @staticmethod
    def _resolve_initial_balance() -> float:
        """Dynamically resolves account balance from active account store or configured broker."""
        try:
            from server.state.accounts_store import accounts_store
            active_accs = accounts_store.get_all_active_accounts(decrypt=False)
            if active_accs:
                bal = active_accs[0].get("balance") or active_accs[0].get("initial_balance")
                if bal and float(bal) > 0:
                    return float(bal)
        except Exception:
            pass
        return 5000.0

    def connect(self, config: Optional[Dict[str, Any]] = None) -> bool:
        self.is_connected = True
        logger.info("[PaperBroker] Connected to local simulated trading engine.")
        return True

    def disconnect(self) -> None:
        self.is_connected = False

    def get_account_info(self) -> Dict[str, Any]:
        stats = signal_store.get_stats()
        realized_pnl = float(stats.get("total_pnl_pct", 0.0)) / 100.0 * self.initial_balance
        equity = self.balance + realized_pnl
        return {
            "broker_id": self.broker_id,
            "broker_name": self.name,
            "balance": round(self.balance, 2),
            "equity": round(equity, 2),
            "free_margin": round(equity, 2),
            "currency": "USD",
            "is_demo": True,
            "connected": self.is_connected,
        }

    def execute_order(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        fill_price = float(signal.get("price") or signal.get("entry_price") or 0.0)
        signal_id = str(signal.get("id") or int(time.time() * 1000))
        lots = float(signal.get("lots") or signal.get("lot_size") or 1.0)
        order_type = str(signal.get("order_type") or signal.get("type") or "MARKET").upper()
        action = str(signal.get("action") or signal.get("side") or "BUY").upper()
        is_long = action in ("BUY", "LONG")

        if order_type == "LIMIT":
            market_px = float(signal.get("market_price") or signal.get("live_exec_price") or 0.0)
            limit_px = fill_price
            immediate_fill = (
                (market_px > 0 and limit_px > 0)
                and ((market_px <= limit_px) if is_long else (market_px >= limit_px))
            )
            if immediate_fill:
                eff_fill = min(market_px, limit_px) if is_long else max(market_px, limit_px)
                logger.info(
                    f"[PaperBroker] 📝 Simulating immediate LIMIT fill for {signal.get('strategy')} "
                    f"{action} {signal.get('symbol') or signal.get('pair')} ({lots:.2f} lots) @ {eff_fill}"
                )
                return {
                    "status": "FILLED",
                    "order_id": f"paper_lim_{signal_id}",
                    "filled_price": eff_fill,
                    "filled_lots": lots,
                    "error": None,
                }
            logger.info(
                f"[PaperBroker] 📝 Resting simulated LIMIT order for {signal.get('strategy')} "
                f"{action} {signal.get('symbol') or signal.get('pair')} ({lots:.2f} lots) @ {limit_px}"
            )
            return {
                "status": "PENDING_ORDER",
                "order_id": f"paper_lim_{signal_id}",
                "filled_price": limit_px,
                "filled_lots": lots,
                "error": None,
            }

        logger.info(
            f"[PaperBroker] 📝 Simulating fill for {signal.get('strategy')} "
            f"{action} {signal.get('symbol') or signal.get('pair')} ({lots:.2f} lots) @ {fill_price}"
        )
        return {
            "status": "FILLED",
            "order_id": f"paper_{signal_id}",
            "filled_price": fill_price,
            "filled_lots": lots,
            "error": None,
        }

    def cancel_order(
        self,
        order_id: str,
        symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        logger.info(f"[PaperBroker] 🗑️ Cancelled resting simulated order {order_id} ({symbol or 'ALL'})")
        return {
            "status": "CANCELLED",
            "order_id": order_id,
            "error": None,
        }

    def close_position(
        self,
        position_id: str,
        reason: str = "MANUAL",
        current_price: Optional[float] = None,
        symbol: Optional[str] = None
    ) -> Dict[str, Any]:
        logger.info(f"[PaperBroker] 🏁 Position {position_id} ({symbol or 'ALL'}) closed locally: reason={reason}")
        return {
            "status": "CLOSED",
            "position_id": position_id,
            "exit_price": current_price or 0.0,
            "realized_pnl": 0.0,
            "error": None,
        }

    def modify_position(
        self,
        position_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        symbol: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        logger.info(f"[PaperBroker] 🛡️ Modified position {position_id} SL={stop_loss}, TP={take_profit}")
        return {
            "status": "MODIFIED",
            "position_id": position_id,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "error": None
        }

    def get_open_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        active = signal_store.get_active_signals()
        if symbol:
            return [s for s in active if s.get("symbol") == symbol or s.get("pair") == symbol]
        return active
