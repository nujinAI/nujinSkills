from fastapi import FastAPI
from server.api.routes import all_routers
from server.api.websocket import router as ws_router


def register_routes(app: FastAPI) -> None:
    """Mounts all domain routers and websocket router onto the FastAPI application."""
    for router in all_routers:
        app.include_router(router)
    app.include_router(ws_router)
