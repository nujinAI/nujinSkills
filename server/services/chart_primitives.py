import os
import sys
import logging
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional
from server.market_structure import extract_market_structure, synthesize_ai_trade_setup

logger = logging.getLogger("ChartPrimitives")

COLOR_PALETTE = [
    "#38bdf8", # Sky Blue (Fast EMA)
    "#f59e0b", # Amber (Mid EMA / Level)
    "#a855f7", # Purple (Slow EMA)
    "#ec4899", # Pink
    "#10b981", # Emerald (Support / Lower Band)
    "#f43f5e", # Rose (Resistance / Upper Band)
    "#06b6d4", # Cyan
    "#84cc16", # Lime
]

def _classify_line(col_name: str, idx: int) -> Dict[str, Any]:
    c_lower = col_name.lower()
    title = col_name.replace("_", " ").title()
    line_width = 1.5
    line_style = 0 # 0: Solid, 1: Dotted, 2: Dashed

    if "ema" in c_lower or "sma" in c_lower:
        title = col_name.upper()
        if "fast" in c_lower or any(f"_{s}" in c_lower for s in [7, 9, 10, 13]):
            color = "#38bdf8"
        elif "mid" in c_lower or any(f"_{s}" in c_lower for s in [20, 21, 30, 34]):
            color = "#f59e0b"
        elif "slow" in c_lower or any(f"_{s}" in c_lower for s in [50, 89, 100]):
            color = "#a855f7"
        else:
            color = "#ec4899"
    elif "upper" in c_lower or "high" in c_lower or "res" in c_lower:
        color = "#f43f5e"
        line_style = 2 # Dashed
        line_width = 1.0
    elif "lower" in c_lower or "low" in c_lower or "sup" in c_lower:
        color = "#10b981"
        line_style = 2 # Dashed
        line_width = 1.0
    elif "mid" in c_lower or "middle" in c_lower or "poc" in c_lower:
        color = "#94a3b8"
        line_style = 1 # Dotted
        line_width = 1.0
    else:
        color = COLOR_PALETTE[idx % len(COLOR_PALETTE)]

    return {
        "id": col_name,
        "title": title,
        "color": color,
        "lineWidth": line_width,
        "lineStyle": line_style
    }

def extract_strategy_primitives(
    strategy_name: Optional[str], 
    candles: List[Dict[str, Any]],
    include_ai_copilot: bool = True
) -> Dict[str, Any]:
    """
    Extracts chart visual primitives for the frontend.
    Dual-Capability:
    1. Strategy Mode: If strategy_name is provided, populates strategy-specific indicators and overlays.
    2. AI Copilot Mode: Automatically analyzes market structure (swings, BOS, MSS), unmitigated FVGs,
       liquidity pools, and high-probability trade setups (Entry, Invalidation SL, Target TP, R:R).
    """
    if not candles:
        return {
            "lines": [], 
            "series": {}, 
            "boxes": [], 
            "levels": [], 
            "hud_items": [], 
            "structures": [], 
            "setups": []
        }

    strat = None
    if strategy_name:
        try:
            from server.backtest_engine import load_strategy_instance
            strat = load_strategy_instance(strategy_name)
        except Exception as e:
            logger.warning(f"[ChartPrimitives] Could not load strategy {strategy_name}: {e}")

    df = pd.DataFrame(candles)
    if "time" not in df.columns and "timestamp" in df.columns:
        df["time"] = df["timestamp"]

    # If strategy has populate_indicators, execute it in Python
    if strat and hasattr(strat, "populate_indicators"):
        try:
            df = strat.populate_indicators(df, {})
        except Exception as e:
            logger.error(f"[ChartPrimitives] populate_indicators error for {strategy_name}: {e}")

    # Check for custom get_chart_primitives method
    if strat and hasattr(strat, "get_chart_primitives"):
        try:
            res = strat.get_chart_primitives(df)
            if isinstance(res, dict):
                return res
        except Exception as e:
            logger.warning(f"[ChartPrimitives] Custom get_chart_primitives failed: {e}")

    # Auto-extract primitives dynamically
    standard_cols = {"open", "high", "low", "close", "volume", "time", "timestamp", "enter_long", "enter_short", "exit_long", "exit_short"}
    
    lines_cfg = []
    series_data = {}
    boxes: List[Dict[str, Any]] = []
    levels: List[Dict[str, Any]] = []
    hud_items: List[Dict[str, Any]] = []
    structures: List[Dict[str, Any]] = []
    setups: List[Dict[str, Any]] = []

    # 1. Line Series Auto-Discovery (EMAs, Bands, Channels, S&R)
    indicator_cols = [c for c in df.columns if c not in standard_cols and pd.api.types.is_numeric_dtype(df[c])]
    close_median = df["close"].median() if "close" in df.columns else 1.0
    valid_line_cols = []

    non_price_keywords = [
        "vol", "volume", "delta", "mom", "sig", "score", "zscore", "z_score",
        "count", "ratio", "pnl", "return", "range", "wick", "atr", "sl", "tp",
        "target", "stop", "hour", "session", "regime", "trend", "valid", "active",
        "is_swing"
    ]

    for col in indicator_cols:
        col_lower = col.lower()
        if any(k in col_lower for k in non_price_keywords):
            continue
        series = df[col].dropna()
        if len(series) == 0:
            continue
        med_val = series.median()
        if abs(med_val - close_median) / close_median <= 0.15:
            valid_line_cols.append(col)

    custom_manifest = getattr(strat, "chart_indicators", None) if strat else None
    if custom_manifest and isinstance(custom_manifest, list):
        for cfg in custom_manifest:
            cid = cfg.get("id")
            if cid in df.columns:
                pts = [{"time": int(t), "value": round(float(v), 4)} for t, v in zip(df["time"], df[cid]) if pd.notnull(v)]
                lines_cfg.append(cfg)
                series_data[cid] = pts
    else:
        for idx, col in enumerate(valid_line_cols[:6]):
            cfg = _classify_line(col, idx)
            pts = [{"time": int(t), "value": round(float(v), 4)} for t, v in zip(df["time"], df[col]) if pd.notnull(v)]
            lines_cfg.append(cfg)
            series_data[col] = pts

    # 2. Market Structure & SMC Analysis (swings, BOS, MSS, unmitigated FVGs, liquidity pools)
    # Default to completely clean canvas unless explicit SMC/analysis mode is requested
    # (structures, boxes, levels, setups remain empty by default)

    # 3. Horizontal Reference Levels (Only for genuine macro anchors if requested)
    # Session open is excluded from chart canvas price scale by default to prevent distorting candle view

    # 4. HUD Telemetry Items for Latest Bar
    last_idx = len(df) - 1
    if last_idx >= 0:
        for cfg in lines_cfg:
            cid = cfg["id"]
            val = df[cid].iloc[last_idx] if cid in df.columns else None
            hud_items.append({
                "id": cid,
                "label": cfg["title"],
                "color": cfg["color"],
                "value": f"${val:.2f}" if pd.notnull(val) else "–"
            })
        
        for sub_col in ["rsi_14", "rsi_7", "volume_zscore", "adx_14"]:
            if sub_col in df.columns:
                val = df[sub_col].iloc[last_idx]
                if pd.notnull(val):
                    hud_items.append({
                        "id": sub_col,
                        "label": sub_col.upper(),
                        "color": "#38bdf8" if "rsi" in sub_col else "#a855f7",
                        "value": f"{val:.2f}"
                    })

    return {
        "lines": lines_cfg,
        "series": series_data,
        "boxes": boxes,
        "levels": levels,
        "hud_items": hud_items,
        "structures": structures,
        "setups": setups
    }
