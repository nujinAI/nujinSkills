import logging
from typing import Any, Dict, List
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("NujinWebSocketRouter")
router = APIRouter(tags=["WebSocket Telemetry"])


class ConnectionManager:
    """Manages active browser WebSocket connections, state caching, and broadcasts."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.widget_state: Dict[str, Any] = {}
        self.signal_history: List[Dict[str, Any]] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        for widget in self.widget_state.values():
            await websocket.send_json({
                "event_type": "UPSERT_WIDGET",
                "payload": widget,
            })

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        event_type = message.get("event_type")
        payload = message.get("payload", {})

        if event_type == "UPSERT_WIDGET" and isinstance(payload, dict):
            widget_id = payload.get("id", payload.get("title", "default"))
            self.widget_state[widget_id] = payload
        elif event_type == "SIGNAL_TRIGGERED" and isinstance(payload, dict):
            self.signal_history.append(payload)

        to_remove = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                to_remove.append(connection)

        for dead_conn in to_remove:
            self.disconnect(dead_conn)


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            logger.debug(f"WS received: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
