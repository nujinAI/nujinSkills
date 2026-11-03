from typing import Optional
from pydantic import BaseModel


class CloseSignalRequest(BaseModel):
    id: Optional[int] = None
    strategy: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = "MANUAL_CLOSE"
    pnl_pct: Optional[float] = None


class ClearSignalsRequest(BaseModel):
    strategy: Optional[str] = None


class DeleteSignalRequest(BaseModel):
    id: int
