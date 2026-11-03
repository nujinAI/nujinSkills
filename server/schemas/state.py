from typing import Any, Dict, Optional
from pydantic import BaseModel


class UpdateStateRequest(BaseModel):
    active_strategy: Optional[str] = None
    target_profile: Optional[str] = None
    status: Optional[str] = None
    backtest_summary: Optional[Dict[str, Any]] = None
