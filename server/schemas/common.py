from typing import Any, Dict
from pydantic import BaseModel


class EventEnvelope(BaseModel):
    event_type: str
    payload: Dict[str, Any]
