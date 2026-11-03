from typing import Optional
from pydantic import BaseModel


class UpdateStrategyStatusRequest(BaseModel):
    strategy: str
    status: str  # ACTIVE_LIVE | CRON_BACKTEST | DEACTIVATED
    exclusive: Optional[bool] = False


class RunStrategyBacktestRequest(BaseModel):
    strategy: str
    days: Optional[int] = 30
    timeframe: Optional[str] = None
    account_size: Optional[float] = None


class RemoveStrategyRequest(BaseModel):
    strategy: str
