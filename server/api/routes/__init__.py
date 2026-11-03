from server.api.routes.health import router as health_router
from server.api.routes.bot import router as bot_router
from server.api.routes.strategies import router as strategies_router
from server.api.routes.signals import router as signals_router
from server.api.routes.brokers import router as brokers_router
from server.api.routes.market import router as market_router
from server.api.routes.risk import router as risk_router
from server.api.routes.copilot import router as copilot_router

all_routers = [
    health_router,
    bot_router,
    strategies_router,
    signals_router,
    brokers_router,
    market_router,
    risk_router,
    copilot_router,
]

__all__ = [
    "all_routers",
    "health_router",
    "bot_router",
    "strategies_router",
    "signals_router",
    "brokers_router",
    "market_router",
    "risk_router",
    "copilot_router",
]
