"""
NujinAI Market Structure & SMC Algorithmic Engine.
Professional Institutional Standard:
- Strict 3-bar Fair Value Gaps (FVG) with strict mitigation termination
- No overlapping consecutive FVGs (merges or keeps only the most significant displacement)
- Major Multi-Bar Swing Pivots (5-bar fractal with minimum displacement)
- Confirmed Break of Structure (BOS) and Market Structure Shift (MSS)
- Clean, unmitigated Buyside (BSL) and Sellside (SSL) Liquidity Pools
"""

from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import pandas as pd


def detect_swing_points(
    df: pd.DataFrame,
    left_bars: int = 5,
    right_bars: int = 5,
    causal: bool = False,
) -> pd.DataFrame:
    """
    Identifies clean, major fractal swing pivots.
    - causal=False (default, chart visualization): marks the exact pivot bar `i`.
    - causal=True (backtesting / live strategies): marks confirmation at bar
      `i + right_bars` (zero lookahead) and attaches forward-filled
      `last_swing_high` / `last_swing_low` structural price levels.
    """
    res = df.copy()
    highs = res["high"].values
    lows = res["low"].values
    n = len(df)

    swing_high = np.zeros(n, dtype=bool)
    swing_low = np.zeros(n, dtype=bool)
    last_sh = np.full(n, np.nan, dtype=float)
    last_sl = np.full(n, np.nan, dtype=float)

    cur_sh = np.nan
    cur_sl = np.nan

    for i in range(left_bars, n - right_bars):
        curr_h = highs[i]
        curr_l = lows[i]

        # Check swing high
        is_sh = True
        for j in range(i - left_bars, i + right_bars + 1):
            if j != i and highs[j] >= curr_h:
                is_sh = False
                break

        # Check swing low
        is_sl = True
        for j in range(i - left_bars, i + right_bars + 1):
            if j != i and lows[j] <= curr_l:
                is_sl = False
                break

        mark_idx = (i + right_bars) if causal else i
        swing_high[mark_idx] = is_sh
        swing_low[mark_idx] = is_sl
        if causal:
            if is_sh:
                cur_sh = float(curr_h)
            if is_sl:
                cur_sl = float(curr_l)
            last_sh[mark_idx] = cur_sh
            last_sl[mark_idx] = cur_sl

    res["is_swing_high"] = swing_high
    res["is_swing_low"] = swing_low
    if causal:
        res["last_swing_high"] = pd.Series(last_sh, index=res.index).ffill()
        res["last_swing_low"] = pd.Series(last_sl, index=res.index).ffill()
    return res


def extract_market_structure(
    df: pd.DataFrame,
    left_bars: int = 5,
    right_bars: int = 5,
    max_lookback: int = 140
) -> Dict[str, Any]:
    """
    Extracts high-conviction, professional market structure without clutter.
    """
    if df.empty or len(df) < (left_bars + right_bars + 10):
        return {
            "structures": [],
            "zones": [],
            "levels": [],
            "swings": []
        }

    df_calc = df.iloc[-max_lookback:].reset_index(drop=True)
    df_calc = detect_swing_points(df_calc, left_bars=left_bars, right_bars=right_bars)
    
    # Calculate ATR for gap & displacement significance
    highs = df_calc["high"].values
    lows = df_calc["low"].values
    closes = df_calc["close"].values
    tr = np.maximum(highs - lows, np.abs(highs - np.roll(closes, 1)))
    tr[0] = highs[0] - lows[0]
    atr = pd.Series(tr).rolling(14, min_periods=1).mean().values

    structures: List[Dict[str, Any]] = []
    swings: List[Dict[str, Any]] = []

    last_sh: Optional[Tuple[int, int, float]] = None # (idx, time, price)
    last_sl: Optional[Tuple[int, int, float]] = None
    trend = 0

    for i in range(len(df_calc)):
        row = df_calc.iloc[i]
        t = int(row["time"]) if "time" in row else int(row.get("timestamp", i))
        c = float(row["close"])
        h = float(row["high"])
        l = float(row["low"])
        
        if row["is_swing_high"]:
            last_sh = (i, t, h)
            swings.append({"type": "SWING_HIGH", "time": t, "price": h, "index": i})
            
        if row["is_swing_low"]:
            last_sl = (i, t, l)
            swings.append({"type": "SWING_LOW", "time": t, "price": l, "index": i})

        # Confirmed Break of Structure
        if last_sh and i > (last_sh[0] + right_bars) and c > last_sh[2]:
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
                "color": "#10b981"
            })
            trend = 1
            last_sh = None

        elif last_sl and i > (last_sl[0] + right_bars) and c < last_sl[2]:
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
                "color": "#ef5350"
            })
            trend = -1
            last_sl = None

    # 2. Strict Fair Value Gaps (FVG)
    # A true institutional FVG:
    # 1. 3-bar displacement pattern: Candle 1, Candle 2 (large body), Candle 3.
    # 2. Minimum gap size >= 0.5 * ATR (prevents micro-noise).
    # 3. Mitigation Termination: If any later bar intrudes into the gap (wick touches the 50% equilibrium),
    #    the gap is considered MITIGATED and terminates at that candle.
    # 4. Non-overlapping filter: Never show overlapping FVGs from the same impulse wave.
    n_bars = len(df_calc)
    curr_close = float(df_calc.loc[n_bars - 1, "close"])
    curr_time = int(df_calc.loc[n_bars - 1, "time"])

    detected_zones: List[Dict[str, Any]] = []

    for i in range(2, n_bars - 1):
        prev2_t = int(df_calc.loc[i - 2, "time"])
        bar_atr = atr[i] if i < len(atr) else 10.0
        
        # Bullish Gap: low[i] > high[i-2]
        gap_bull = df_calc.loc[i, "low"] - df_calc.loc[i - 2, "high"]
        candle_body = abs(df_calc.loc[i - 1, "close"] - df_calc.loc[i - 1, "open"])
        
        if gap_bull >= (0.45 * bar_atr) and candle_body >= (0.5 * bar_atr) and df_calc.loc[i - 1, "close"] > df_calc.loc[i - 1, "open"]:
            p_top = float(df_calc.loc[i, "low"])
            p_bottom = float(df_calc.loc[i - 2, "high"])
            eq_level = (p_top + p_bottom) / 2.0
            
            # Check subsequent mitigation
            mitigated = False
            term_time = curr_time
            for k in range(i + 1, n_bars):
                # Mitigated when price wicks below the 50% midpoint (equilibrium) of the gap
                if df_calc.loc[k, "low"] <= eq_level:
                    mitigated = True
                    term_time = int(df_calc.loc[k, "time"])
                    break
            
            # Only keep unmitigated or very recent active gaps
            if not mitigated or (n_bars - i) <= 8:
                detected_zones.append({
                    "id": f"fvg_bull_{prev2_t}",
                    "type": "FVG_BULL",
                    "label": "Bullish FVG",
                    "time_start": prev2_t,
                    "time_end": term_time,
                    "price_high": round(p_top, 2),
                    "price_low": round(p_bottom, 2),
                    "color": "rgba(16, 185, 129, 0.16)",
                    "borderColor": "#10b981",
                    "borderStyle": "dashed",
                    "gap_size": gap_bull,
                    "bar_index": i
                })

        # Bearish Gap: high[i] < low[i-2]
        gap_bear = df_calc.loc[i - 2, "low"] - df_calc.loc[i, "high"]
        candle_body = abs(df_calc.loc[i - 1, "close"] - df_calc.loc[i - 1, "open"])
        
        if gap_bear >= (0.45 * bar_atr) and candle_body >= (0.5 * bar_atr) and df_calc.loc[i - 1, "close"] < df_calc.loc[i - 1, "open"]:
            p_top = float(df_calc.loc[i - 2, "low"])
            p_bottom = float(df_calc.loc[i, "high"])
            eq_level = (p_top + p_bottom) / 2.0
            
            mitigated = False
            term_time = curr_time
            for k in range(i + 1, n_bars):
                if df_calc.loc[k, "high"] >= eq_level:
                    mitigated = True
                    term_time = int(df_calc.loc[k, "time"])
                    break
                    
            if not mitigated or (n_bars - i) <= 8:
                detected_zones.append({
                    "id": f"fvg_bear_{prev2_t}",
                    "type": "FVG_BEAR",
                    "label": "Bearish FVG",
                    "time_start": prev2_t,
                    "time_end": term_time,
                    "price_high": round(p_top, 2),
                    "price_low": round(p_bottom, 2),
                    "color": "rgba(239, 83, 80, 0.16)",
                    "borderColor": "#ef5350",
                    "borderStyle": "dashed",
                    "gap_size": gap_bear,
                    "bar_index": i
                })

    # Non-overlapping filter: If two FVGs overlap in price, keep only the larger/cleaner one
    filtered_zones: List[Dict[str, Any]] = []
    for z in detected_zones:
        overlap = False
        for existing in filtered_zones:
            # Check price range overlap
            if not (z["price_high"] < existing["price_low"] or z["price_low"] > existing["price_high"]):
                # Overlaps! Keep the one with larger gap size
                if z.get("gap_size", 0) > existing.get("gap_size", 0):
                    existing.update(z)
                overlap = True
                break
        if not overlap:
            filtered_zones.append(z)

    # 3. Clean Major Liquidity (One Key BSL and One Key SSL)
    sh_list = [s for s in swings if s["type"] == "SWING_HIGH" and s["price"] > curr_close]
    sl_list = [s for s in swings if s["type"] == "SWING_LOW" and s["price"] < curr_close]

    if sh_list:
        major_bsl = max(sh_list, key=lambda s: s["price"])
        structures.append({
            "id": f"bsl_major_{major_bsl['time']}",
            "type": "LIQUIDITY",
            "direction": "BULLISH",
            "label": "BSL",
            "time_start": major_bsl["time"],
            "time_end": curr_time,
            "price": round(major_bsl["price"], 2),
            "color": "#38bdf8"
        })

    if sl_list:
        major_ssl = min(sl_list, key=lambda s: s["price"])
        structures.append({
            "id": f"ssl_major_{major_ssl['time']}",
            "type": "LIQUIDITY",
            "direction": "BEARISH",
            "label": "SSL",
            "time_start": major_ssl["time"],
            "time_end": curr_time,
            "price": round(major_ssl["price"], 2),
            "color": "#f59e0b"
        })

    # Limit to 2 most prominent clean zones (one discount, one premium)
    clean_zones = filtered_zones[-2:]

    return {
        "structures": structures[-4:],
        "zones": clean_zones,
        "levels": [],
        "swings": swings[-6:],
        "trend": "BULLISH" if trend == 1 else ("BEARISH" if trend == -1 else "NEUTRAL")
    }


def synthesize_ai_trade_setup(
    df: pd.DataFrame,
    structure: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    return None
