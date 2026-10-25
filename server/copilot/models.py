# server/copilot/models.py
"""
Strict typed geometric and analytical models for NujinAI Chart Copilot.
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class IndicatorSeriesPrimitive(BaseModel):
    id: str
    title: str
    color: str
    lineWidth: float = 1.5
    lineStyle: int = 0  # 0: Solid, 1: Dotted, 2: Dashed
    data: List[Dict[str, Any]] = Field(default_factory=list)


class ZoneBoxPrimitive(BaseModel):
    id: str
    label: str
    time_start: int
    time_end: int
    price_high: float
    price_low: float
    color: str
    borderColor: str
    borderStyle: str = "solid"
    type: str  # "DEMAND", "SUPPLY", "ORDER_BLOCK", "FVG", "ZONE"


class StructuralLevelPrimitive(BaseModel):
    id: str
    label: str
    price: float
    time_start: Optional[int] = None
    time_end: Optional[int] = None
    color: str = "#38bdf8"
    style: str = "dashed"
    direction: Optional[str] = None  # "BULLISH", "BEARISH"


class TradeSetupPrimitive(BaseModel):
    id: str
    direction: str  # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float
    rr_ratio: float
    time_entry: int
    thesis: str


class CopilotPrimitives(BaseModel):
    series: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    lines: List[Dict[str, Any]] = Field(default_factory=list)
    boxes: List[ZoneBoxPrimitive] = Field(default_factory=list)
    levels: List[StructuralLevelPrimitive] = Field(default_factory=list)
    structures: List[Dict[str, Any]] = Field(default_factory=list)
    setups: List[TradeSetupPrimitive] = Field(default_factory=list)
    hud_items: List[Dict[str, Any]] = Field(default_factory=list)


class CopilotResponse(BaseModel):
    status: str = "SUCCESS"
    symbol: str = "BTC/USDT"
    timeframe: str = "15m"
    current_price: float = 0.0
    trend: str = "NEUTRAL"
    primitives: CopilotPrimitives = Field(default_factory=CopilotPrimitives)
    trade_setup: Optional[TradeSetupPrimitive] = None
