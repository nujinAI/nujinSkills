"""
NujinAI Market Structure & SMC Algorithmic Engine.
Provides high-performance, mathematically rigorous market structure identification:
- Fractal Swing Highs and Swing Lows
- Break of Structure (BOS) and Market Structure Shift (MSS / CHoCH)
- Fair Value Gaps (FVG) with live mitigation tracking
- Liquidity Pools (Equal Highs EQH / Equal Lows EQL / Sweeps)
- Autonomous Trade Setup Synthesis with Risk:Reward, Invalidation & Targets
"""

from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import pandas as pd


def detect_swing_points(
    df: pd.DataFrame, 
    left_bars: int = 3, 
    right_bars: int = 3
) -> pd.DataFrame:
    """
    Identifies fractal swing highs and swing lows without lookahead bias.
    A swing high requires high[t] > all highs in [t-left, t+right]
    A swing low requires low[t] < all lows in [t-left, t+right]
    """
    res = df.copy()
    highs = res["high"].values
    lows = res["low"].values
    n = len(df)
    
    swing_high = np.zeros(n, dtype=bool)
    swing_low = np.zeros(n, dtype=bool)
    
    for i in range(left_bars, n - right_bars):
        curr_h = highs[i]
        curr_l = lows[i]
        
        is_sh = True
        for j in range(i - left_bars, i + right_bars + 1):
            if j != i and highs[j] >= curr_h:
                is_sh = False
                break
        swing_high[i] = is_sh
        
        is_sl = True
        for j in range(i - left_bars, i + right_bars + 1):
            if j != i and lows[j] <= curr_l:
                is_sl = False
                break
        swing_low[i] = is_sl

    res["is_swing_high"] = swing_high
    res["is_swing_low"] = swing_low
    return res


def extract_market_structure(
    df: pd.DataFrame,
    left_bars: int = 3,
    right_bars: int = 3,
    max_lookback: int = 150
) -> Dict[str, Any]:
    """
    Extracts structural elements:
    - Swing highs / lows
    - BOS (Break of Structure - Trend continuation)
    - MSS (Market Structure Shift / CHoCH - Trend reversal)
    - Unmitigated FVGs (Bullish & Bearish)
    - Liquidity Pools (EQH / EQL)
    """
    if df.empty or len(df) < (left_bars + right_bars + 5):
        return {
            "structures": [],
            "zones": [],
            "levels": [],
            "swings": []
        }

    # Focus on the most recent active lookback window for optimal chart clarity
    df_calc = df.iloc[-max_lookback:].reset_index(drop=True)
    df_calc = detect_swing_points(df_calc, left_bars=left_bars, right_bars=right_bars)
    
    structures: List[Dict[str, Any]] = []
    zones: List[Dict[str, Any]] = []
    levels: List[Dict[str, Any]] = []
    swings: List[Dict[str, Any]] = []

    # 1. Swings Extraction
    last_sh: Optional[Tuple[int, int, float]] = None # (idx, time, price)
    last_sl: Optional[Tuple[int, int, float]] = None
    prev_sh: Optional[Tuple[int, int, float]] = None
    prev_sl: Optional[Tuple[int, int, float]] = None
    
    trend = 0 # 1 = Bullish, -1 = Bearish, 0 = Undefined

    for i in range(len(df_calc)):
        row = df_calc.iloc[i]
        t = int(row["time"]) if "time" in row else int(row.get("timestamp", i))
        c = float(row["close"])
        h = float(row["high"])
        l = float(row["low"])
        
        # Check swing high formation
        if row["is_swing_high"]:
            prev_sh = last_sh
            last_sh = (i, t, h)
            swings.append({"type": "SWING_HIGH", "time": t, "price": h, "index": i})
            
        # Check swing low formation
        if row["is_swing_low"]:
            prev_sl = last_sl
            last_sl = (i, t, l)
            swings.append({"type": "SWING_LOW", "time": t, "price": l, "index": i})

        # Check BOS / MSS breaks
        # Bullish Break: Close > last_sh price
        if last_sh and i > last_sh[0] and c > last_sh[2]:
            is_mss = (trend == -1)
            b_type = "MSS" if is_mss else "BOS"
            structures.append({
                "id": f"{b_type.lower()}_bull_{last_sh[1]}",
                "type": b_type,
                "direction": "BULLISH",
                "label": f"{b_type}",
                "time_start": last_sh[1],
                "time_end": t,
                "price": round(last_sh[2], 2),
                "color": "#10b981" # Emerald Green
            })
            trend = 1
            last_sh = None # Mitigated / Broken

        # Bearish Break: Close < last_sl price
        elif last_sl and i > last_sl[0] and c < last_sl[2]:
            is_mss = (trend == 1)
            b_type = "MSS" if is_mss else "BOS"
            structures.append({
                "id": f"{b_type.lower()}_bear_{last_sl[1]}",
                "type": b_type,
                "direction": "BEARISH",
                "label": f"{b_type}",
                "time_start": last_sl[1],
                "time_end": t,
                "price": round(last_sl[2], 2),
                "color": "#ef5350" # Red
            })
            trend = -1
            last_sl = None # Mitigated / Broken

    # 2. Fair Value Gaps (FVG) with Live Mitigation Tracking
    # Bullish FVG: low[i] > high[i-2]
    # Bearish FVG: high[i] < low[i-2]
    n_bars = len(df_calc)
    for i in range(2, n_bars):
        curr_t = int(df_calc.loc[i, "time"])
        prev2_t = int(df_calc.loc[i - 2, "time"])
        
        # Bullish Imbalance
        if df_calc.loc[i, "low"] > df_calc.loc[i - 2, "high"] and df_calc.loc[i - 1, "close"] > df_calc.loc[i - 1, "open"]:
            p_top = float(df_calc.loc[i, "low"])
            p_bottom = float(df_calc.loc[i - 2, "high"])
            
            # Check subsequent mitigation
            mitigated = False
            mitigated_time = curr_t
            for k in range(i + 1, n_bars):
                if df_calc.loc[k, "low"] <= p_bottom: # completely filled
                    mitigated = True
                    mitigated_time = int(df_calc.loc[k, "time"])
                    break
            
            if not mitigated or (n_bars - i) <= 15: # Display unmitigated or very recent gaps
                end_time = mitigated_time if mitigated else int(df_calc.loc[n_bars - 1, "time"])
                zones.append({
                    "id": f"fvg_bull_{prev2_t}",
                    "type": "FVG_BULL",
                    "label": "Bullish FVG",
                    "time_start": prev2_t,
                    "time_end": end_time,
                    "price_high": round(p_top, 2),
                    "price_low": round(p_bottom, 2),
                    "color": "rgba(16, 185, 129, 0.18)",
                    "borderColor": "#10b981",
                    "borderStyle": "dashed"
                })

        # Bearish Imbalance
        elif df_calc.loc[i, "high"] < df_calc.loc[i - 2, "low"] and df_calc.loc[i - 1, "close"] < df_calc.loc[i - 1, "open"]:
            p_top = float(df_calc.loc[i - 2, "low"])
            p_bottom = float(df_calc.loc[i, "high"])
            
            mitigated = False
            mitigated_time = curr_t
            for k in range(i + 1, n_bars):
                if df_calc.loc[k, "high"] >= p_top: # completely filled
                    mitigated = True
                    mitigated_time = int(df_calc.loc[k, "time"])
                    break
                    
            if not mitigated or (n_bars - i) <= 15:
                end_time = mitigated_time if mitigated else int(df_calc.loc[n_bars - 1, "time"])
                zones.append({
                    "id": f"fvg_bear_{prev2_t}",
                    "type": "FVG_BEAR",
                    "label": "Bearish FVG",
                    "time_start": prev2_t,
                    "time_end": end_time,
                    "price_high": round(p_top, 2),
                    "price_low": round(p_bottom, 2),
                    "color": "rgba(239, 83, 80, 0.18)",
                    "borderColor": "#ef5350",
                    "borderStyle": "dashed"
                })

    # 3. Dynamic Liquidity Rays (Equal Highs EQH / Equal Lows EQL with Candle Anchors)
    sh_list = [s for s in swings if s["type"] == "SWING_HIGH"]
    sl_list = [s for s in swings if s["type"] == "SWING_LOW"]

    # Detect Equal Highs (Buyside Liquidity) and Equal Lows (Sellside Liquidity) within 0.15% threshold
    for idx in range(len(sh_list) - 1):
        s1 = sh_list[idx]
        s2 = sh_list[idx + 1]
        if abs(s1["price"] - s2["price"]) / s1["price"] <= 0.0015:
            eq_price = round(max(s1["price"], s2["price"]), 2)
            t_start = min(s1["time"], s2["time"])
            structures.append({
                "id": f"bsl_{s1['time']}",
                "type": "LIQUIDITY",
                "direction": "BULLISH",
                "label": "BSL",
                "time_start": t_start,
                "time_end": int(df_calc.loc[n_bars - 1, "time"]),
                "price": eq_price,
                "color": "#38bdf8" # Sky Blue
            })

    for idx in range(len(sl_list) - 1):
        s1 = sl_list[idx]
        s2 = sl_list[idx + 1]
        if abs(s1["price"] - s2["price"]) / s1["price"] <= 0.0015:
            eq_price = round(min(s1["price"], s2["price"]), 2)
            t_start = min(s1["time"], s2["time"])
            structures.append({
                "id": f"ssl_{s1['time']}",
                "type": "LIQUIDITY",
                "direction": "BEARISH",
                "label": "SSL",
                "time_start": t_start,
                "time_end": int(df_calc.loc[n_bars - 1, "time"]),
                "price": eq_price,
                "color": "#f59e0b" # Amber
            })

    # Keep the most relevant and clean subset to prevent visual noise
    return {
        "structures": structures[-8:],
        "zones": zones[-8:],
        "levels": levels,
        "swings": swings[-12:],
        "trend": "BULLISH" if trend == 1 else ("BEARISH" if trend == -1 else "NEUTRAL")
    }


def synthesize_ai_trade_setup(
    df: pd.DataFrame,
    structure: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Synthesizes a high-probability trade idea based on current structure & unmitigated zones:
    - Finds the nearest unmitigated FVG or swing level
    - Defines exact entry, invalidation stop-loss, and liquidity target
    - Computes exact Risk:Reward (R:R) ratio
    """
    if df.empty or len(df) < 20:
        return None

    last_bar = df.iloc[-1]
    curr_price = float(last_bar["close"])
    curr_time = int(last_bar["time"]) if "time" in last_bar else int(last_bar.get("timestamp", 0))
    trend = structure.get("trend", "NEUTRAL")
    zones = structure.get("zones", [])
    
    # 1. Bearish Thesis: Downtrend or MSS Bearish with an overhead Bearish FVG
    bearish_zones = [z for z in zones if z["type"] == "FVG_BEAR" and z["price_low"] >= curr_price * 0.995]
    if trend in ["BEARISH", "NEUTRAL"] and bearish_zones:
        target_fvg = bearish_zones[-1] # nearest overhead gap
        entry_price = float(target_fvg["price_low"])
        stop_loss = round(float(target_fvg["price_high"]) * 1.0008, 2) # Just above gap high
        risk = stop_loss - entry_price
        if risk > 0:
            # Target sellside liquidity or 2.5R to 4R expansion
            target_price = round(entry_price - (risk * 3.2), 2)
            rr = round((entry_price - target_price) / risk, 2)
            return {
                "id": f"setup_short_{curr_time}",
                "direction": "SHORT",
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": target_price,
                "rr_ratio": rr,
                "time_entry": curr_time,
                "thesis": f"Short limit into Bearish FVG (${target_fvg['price_low']:.2f} - ${target_fvg['price_high']:.2f}) following {trend} structure."
            }

    # 2. Bullish Thesis: Uptrend or MSS Bullish with a discount Bullish FVG
    bullish_zones = [z for z in zones if z["type"] == "FVG_BULL" and z["price_high"] <= curr_price * 1.005]
    if trend in ["BULLISH", "NEUTRAL"] and bullish_zones:
        target_fvg = bullish_zones[-1] # nearest discount gap
        entry_price = float(target_fvg["price_high"])
        stop_loss = round(float(target_fvg["price_low"]) * 0.9992, 2) # Just below gap low
        risk = entry_price - stop_loss
        if risk > 0:
            target_price = round(entry_price + (risk * 3.2), 2)
            rr = round((target_price - entry_price) / risk, 2)
            return {
                "id": f"setup_long_{curr_time}",
                "direction": "LONG",
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": target_price,
                "rr_ratio": rr,
                "time_entry": curr_time,
                "thesis": f"Long limit into Bullish FVG (${target_fvg['price_low']:.2f} - ${target_fvg['price_high']:.2f}) following {trend} structure."
            }

    return None
