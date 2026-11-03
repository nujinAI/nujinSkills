from typing import Optional
from pydantic import BaseModel


class DeployBotRequest(BaseModel):
    strategy: Optional[str] = None
    strategy_name: Optional[str] = None
    mode: Optional[str] = "dry-run"


class StopBotRequest(BaseModel):
    strategy: Optional[str] = None
    strategy_name: Optional[str] = None


class SelectStrategyRequest(BaseModel):
    strategy: str
    days: Optional[int] = None
