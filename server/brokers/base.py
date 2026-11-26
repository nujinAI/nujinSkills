"""
server/brokers/base.py
─────────────────────────────────────────────────────────────
Abstract Base Class for Execution Broker & Exchange Adapters.

Enables Nujin to deploy automated execution across any broker, prop firm,
or exchange plugin (e.g. Binance, Bybit, Interactive Brokers, OANDA)
without modifying strategy logic.
"""

from __future__ import annotations

import abc
import asyncio
import logging
from typing import Callable, Dict, Any, List, Optional, Set

logger = logging.getLogger("ExecutionBroker")


class BaseExecutionBroker(abc.ABC):
    """
    Standard interface for all execution adapters.
    """

    def __init__(self, broker_id: str, name: str):
        self.broker_id = broker_id
        self.name = name
        self.is_connected = False
        self._event_callbacks: Set[Callable[[Dict[str, Any]], Any]] = set()

    @property
    def supports_multi_account(self) -> bool:
        """Indicates whether this broker adapter supports concurrent multi-account execution."""
        return False

    @property
    def supports_server_side_brackets(self) -> bool:
        """
        True when the broker natively enforces attached SL/TP server-side.
        Allows runners to rely on fast reconciliation + safety backstop rather than double-closing.
        """
        return False

    def subscribe_execution_events(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        """Register callback for real-time execution/fill/close events (for streaming broker plugins)."""
        self._event_callbacks.add(callback)

    def unsubscribe_execution_events(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        self._event_callbacks.discard(callback)

    def _emit_execution_event(self, event: Dict[str, Any]) -> None:
        """Dispatches an execution event to registered callbacks safely from sync or async contexts."""
        for cb in list(self._event_callbacks):
            try:
                res = cb(event)
                if asyncio.iscoroutine(res):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(res)
                    except RuntimeError:
                        res.close()
            except Exception as e:
                logger.debug(f"[{self.broker_id}] Execution event callback note: {e}")

    def get_cached_account_info(self, max_age: float = 15.0) -> Dict[str, Any]:
        """Fast account-info lookup allowing broker adapters to reuse a fresh snapshot."""
        return self.get_account_info()

    def get_cached_open_positions(
        self,
        symbol: Optional[str] = None,
        max_age: float = 5.0,
    ) -> Optional[List[Dict[str, Any]]]:
        """Fast open-positions lookup allowing broker adapters to reuse a fresh snapshot."""
        return self.get_open_positions(symbol=symbol)

    def reconcile_order_fill(
        self,
        order_id: str,
        symbol: str,
        side: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Optional post-order async fill lookup returning
        {"filled_price": float, "position_id": Optional[str], "status": Optional[str]} or None.
        """
        return None

    def validate_credentials(self, config: Dict[str, Any]) -> tuple[bool, str]:
        """
        Validates a set of credentials without modifying the primary adapter session.
        Returns (is_valid: bool, message_or_error: str).
        """
        return True, "Validation passed"

    def get_market_data_provider(self, symbol: str, timeframe: str = "1m") -> Optional[Any]:
        """
        Optional hook for broker adapters that can stream their own live prices/candles.
        Returns an instance of BaseMarketDataProvider or None if using default feeds.
        """
        return None

    def get_latest_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Optional snapshot quote from broker execution book.
        Returns {symbol, price, bid, ask, timestamp, source} or None.
        """
        return None

    def get_contract_size(self, symbol: str) -> Optional[float]:
        """
        Optional broker-authoritative contract size (units per 1.00 lot) for `symbol`.
        Returns None when unavailable (callers on live brokers must fail closed).
        """
        return None

    def get_point_value(
        self,
        symbol: str,
        price: float,
        account_currency: str = "USD",
    ) -> Optional[float]:
        """
        Optional broker-authoritative account-currency PnL per 1.0 price move per 1.00 lot.
        Defaults to `get_contract_size(symbol)` for account-currency-quoted instruments.
        """
        return self.get_contract_size(symbol)

    def get_pending_orders(self, symbol: Optional[str] = None) -> Optional[List[Dict[str, Any]]]:
        """
        Optional hook returning resting pending (LIMIT / STOP) orders on the broker.
        Returns None on API failure so callers never falsely assume an order disappeared.
        """
        return None

    def cancel_order(
        self,
        order_id: str,
        symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Optional hook to cancel a resting pending (LIMIT / STOP) order on the broker.
        """
        return {"status": "UNSUPPORTED", "order_id": order_id, "error": "cancel_order not implemented"}

    @abc.abstractmethod
    def connect(self, config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Initializes connection / session with the broker using credentials.
        Returns True if authenticated successfully.
        """
        pass

    @abc.abstractmethod
    def disconnect(self) -> None:
        """Gracefully terminates active broker session or WebSocket stream."""
        pass

    @abc.abstractmethod
    def get_account_info(self) -> Dict[str, Any]:
        """
        Returns account balance & margin status:
        {
            "balance": float,
            "equity": float,
            "free_margin": float,
            "currency": str,
            "is_demo": bool
        }
        """
        pass

    @abc.abstractmethod
    def execute_order(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes an order on the exchange/broker from a Nujin signal.
        signal schema:
          - action: "BUY" | "SELL" | "LONG" | "SHORT"
          - symbol: str (e.g. "BTC/USDT", "XAUUSD")
          - price: float
          - stop_loss: Optional[float]
          - take_profit: Optional[float]
          - strategy: str

        Returns order confirmation dict:
        {
            "status": "FILLED" | "REJECTED",
            "order_id": str,
            "filled_price": float,
            "filled_lots": float,
            "error": Optional[str]
        }
        """
        pass

    @abc.abstractmethod
    def close_position(
        self,
        position_id: str,
        reason: str = "MANUAL",
        current_price: Optional[float] = None,
        symbol: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Closes an open position on the broker.
        Returns confirmation dict:
        {
            "status": "CLOSED" | "FAILED",
            "position_id": str,
            "exit_price": float,
            "realized_pnl": float,
            "error": Optional[str]
        }
        """
        pass

    def modify_position(
        self,
        position_id: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        symbol: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Modifies Stop Loss or Take Profit of an open position on the broker.
        Returns confirmation dict:
        {
            "status": "MODIFIED" | "FAILED" | "NOT_SUPPORTED",
            "position_id": str,
            "stop_loss": Optional[float],
            "take_profit": Optional[float],
            "error": Optional[str]
        }
        """
        return {"status": "NOT_SUPPORTED", "position_id": position_id, "error": "Not implemented"}

    @abc.abstractmethod
    def get_open_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns list of currently open positions from the broker."""
        pass

