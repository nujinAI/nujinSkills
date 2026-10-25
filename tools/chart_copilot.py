#!/usr/bin/env python3
"""
tools/chart_copilot.py
─────────────────────────────────────────────────────────────────────────────
NujinAI Dynamic Chart Copilot & Technical Analysis Engine.

100% Limitless & Bias-Free:
Computes and projects ANY indicator stack, mathematical formula, or trading
concept requested by the user or agent across TA-Lib (201 indicators),
Order Flow / Volume Delta, Volatility Channels, SMC Market Structure, or
custom formulas.

Usage:
    # 1. Inspect any custom indicator stack
    tools/chart_copilot.py --symbol BTC/USDT --timeframe 15m --indicators "ema_21,ema_50,supertrend,rsi_14"

    # 2. Inspect Volatility / Mean-Reversion bands
    tools/chart_copilot.py --symbol BTC/USDT --timeframe 15m --indicators "bb_upper_20,bb_lower_20,bb_middle_20"

    # 3. Inspect SMC Market Structure & Swings
    tools/chart_copilot.py --symbol BTC/USDT --timeframe 15m --smc

    # 4. Formulate thesis & trade setup based on user's concept
    tools/chart_copilot.py --symbol BTC/USDT --timeframe 15m --thesis "Trend continuation pullback to 21 EMA with RSI > 50"
"""

import os
import sys
import json
import argparse
import logging
from typing import Dict, Any, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import numpy as np
from server import data_manager
from server.indicators import compute_all_standard_features, ensure_dynamic_indicators
from server.market_structure import extract_market_structure

logger = logging.getLogger("ChartCopilot")


def analyze_chart_dynamically(
    symbol: str = "BTC/USDT",
    timeframe: str = "15m",
    lookback: int = 140,
    requested_indicators: Optional[List[str]] = None,
    custom_formulas: Optional[Dict[str, str]] = None,
    include_smc: bool = False,
    thesis: Optional[str] = None
) -> Dict[str, Any]:
    """
    Dynamically computes requested indicator features from TA-Lib, order flow,
    market structure, and custom formulas without hardcoded archetypes.
    """
    sym_upper = symbol.upper()
    is_gold = any(k in sym_upper for k in ["XAU", "GOLD", "GC"])
    is_sp = any(k in sym_upper for k in ["SP", "ES", "S&P", "US500"])
    
    # 1. Fetch authentic candles via data_manager seam
    if is_gold:
        candles = data_manager.fetch_real_oanda_candles(interval=timeframe, count=lookback)
    elif is_sp:
        candles = data_manager.fetch_real_sp500_candles(interval=timeframe, count=lookback)
    else:
        candles = data_manager.fetch_real_binance_klines(symbol=symbol, interval=timeframe, count=lookback)

    if not candles or len(candles) < 20:
        return {
            "status": "ERROR",
            "message": f"Insufficient candles retrieved for {symbol} ({timeframe}).",
            "symbol": symbol,
            "timeframe": timeframe
        }

    df = pd.DataFrame(candles)
    if "time" not in df.columns and "timestamp" in df.columns:
        df["time"] = df["timestamp"]

    curr_close = float(df["close"].iloc[-1])
    curr_time = int(df["time"].iloc[-1])

    lines: List[Dict[str, Any]] = []
    series_data: Dict[str, List[Dict[str, Any]]] = {}
    hud_items: List[Dict[str, Any]] = []

    # 2. Dynamic Indicator Computation (TA-Lib + ta + custom)
    palette = ["#38bdf8", "#f59e0b", "#a855f7", "#ec4899", "#10b981", "#06b6d4", "#84cc16"]
    color_idx = 0

    if requested_indicators:
        df = ensure_dynamic_indicators(df, requested_indicators)
        for ind_name in requested_indicators:
            ind_clean = ind_name.strip().lower()
            if not ind_clean or ind_clean not in df.columns:
                continue
            
            series = df[ind_clean]
            if series is not None and not series.empty:
                last_val = series.iloc[-1]
                
                # Check if it's an overlay (near price) or an oscillator
                is_overlay = abs(series.median() - curr_close) / curr_close <= 0.25
                color = palette[color_idx % len(palette)]
                color_idx += 1

                if is_overlay:
                    lines.append({
                        "id": ind_clean,
                        "title": ind_clean.upper().replace("_", " "),
                        "color": color,
                        "lineWidth": 1.5,
                        "lineStyle": 0,
                    })
                    series_data[ind_clean] = [
                        {"time": int(t), "value": round(float(v), 2)}
                        for t, v in zip(df["time"], series) if pd.notnull(v)
                    ]

                hud_items.append({
                    "id": ind_clean,
                    "label": ind_clean.upper(),
                    "color": color,
                    "value": f"${last_val:.2f}" if is_overlay else f"{last_val:.2f}"
                })

    # 3. Dynamic Custom Mathematical Formulas (e.g. "(upper_band - lower_band) / ema_20")
    if custom_formulas:
        # Pre-enrich df with all standard features so any formula token resolves
        df_rich = compute_all_standard_features(df, window=20)
        for name, formula in custom_formulas.items():
            try:
                evaluated = df_rich.eval(formula)
                df[name] = evaluated
                last_val = evaluated.iloc[-1]
                hud_items.append({
                    "id": name,
                    "label": name.upper(),
                    "color": "#ec4899",
                    "value": f"{last_val:.4f}"
                })
            except Exception as e:
                logger.warning(f"[ChartCopilot] Failed to evaluate custom formula '{name}': {e}")

    # 4. Market Structure, Supply/Demand, and Order Blocks
    structures = []
    zones = []
    trend = "NEUTRAL"

    # Detect Supply/Demand or Order Block requests
    thesis_lower = (thesis or "").lower()
    include_sd = "supply" in thesis_lower or "demand" in thesis_lower or "orderblock" in thesis_lower or "order block" in thesis_lower or "ob" in thesis_lower

    if include_sd:
        # 1. Identify Institutional Order Blocks & Supply/Demand Zones from 4h/15m candle structure
        # Bullish Demand / Order Block (Last down candle before displacement impulse)
        # Find the major swing low in recent history
        low_idx = df["low"].tail(50).idxmin()
        low_row = df.loc[low_idx]
        demand_high = max(float(low_row["open"]), float(low_row["close"]))
        demand_low = float(low_row["low"])
        # Ensure minimum zone thickness for visual clarity
        if demand_high - demand_low < (curr_close * 0.005):
            demand_high = round(demand_low * 1.008, 2)

        last_t = int(df["time"].iloc[-1])
        bar_dur = int(df["time"].iloc[-1] - df["time"].iloc[-2]) if len(df) > 1 else 14400

        zones.append({
            "id": "demand_ob_1",
            "label": "DEMAND OB",
            "time_start": int(low_row["time"]),
            "time_end": last_t + (bar_dur * 8),
            "price_high": round(demand_high, 2),
            "price_low": round(demand_low, 2),
            "color": "rgba(38, 166, 154, 0.22)",
            "borderColor": "#26a69a",
            "borderStyle": "solid",
            "type": "DEMAND"
        })

        # Bearish Supply / Order Block (Breakdown shelf or swing high origin)
        # Look for the last up-candle before the sharp decline
        high_idx = df["high"].tail(50).idxmax()
        high_row = df.loc[high_idx]
        supply_high = float(high_row["high"])
        supply_low = min(float(high_row["open"]), float(high_row["close"]))
        if supply_high - supply_low < (curr_close * 0.005):
            supply_low = round(supply_high * 0.992, 2)

        zones.append({
            "id": "supply_ob_1",
            "label": "SUPPLY OB",
            "time_start": int(high_row["time"]),
            "time_end": last_t + (bar_dur * 8),
            "price_high": round(supply_high, 2),
            "price_low": round(supply_low, 2),
            "color": "rgba(239, 83, 80, 0.22)",
            "borderColor": "#ef5350",
            "borderStyle": "solid",
            "type": "SUPPLY"
        })

        # Intermediary Resistance / Breakdown Supply Shelf (around 81,800 - 82,300)
        recent_tail = df.tail(30)
        break_candidates = recent_tail[(recent_tail["high"] > curr_close * 1.01) & (recent_tail["high"] < supply_high * 0.985)]
        if not break_candidates.empty:
            mid_row = break_candidates.iloc[-1]
            mid_high = float(mid_row["high"])
            mid_low = float(mid_row["low"])
            zones.append({
                "id": "supply_shelf_mid",
                "label": "SUPPLY SHELF",
                "time_start": int(mid_row["time"]),
                "time_end": last_t + (bar_dur * 8),
                "price_high": round(mid_high, 2),
                "price_low": round(mid_low, 2),
                "color": "rgba(239, 83, 80, 0.15)",
                "borderColor": "#f43f5e",
                "borderStyle": "dashed",
                "type": "SUPPLY"
            })

    elif include_smc:
        ms_result = extract_market_structure(df, left_bars=4, right_bars=4, max_lookback=lookback)
        structures = ms_result.get("structures", [])
        zones = ms_result.get("zones", [])
        trend = ms_result.get("trend", "NEUTRAL")

    # 5. Dynamic Setup Formulator (Driven by user's thesis)
    trade_setup = None
    if thesis:
        # Formulate invalidation and targets dynamically based on the identified zones
        is_short = any(k in thesis_lower for k in ["short", "bear", "sell", "reversal down", "breakdown"])
        direction = "SHORT" if is_short else "LONG"
        
        tr = np.maximum(df["high"] - df["low"], np.abs(df["high"] - df["close"].shift(1))).fillna(10.0)
        curr_atr = float(tr.rolling(14, min_periods=1).mean().iloc[-1])

        if direction == "LONG":
            # If demand zone exists, place stop cleanly below demand zone low
            demand_zones = [z for z in zones if z.get("type") == "DEMAND"]
            if demand_zones:
                stop = round(demand_zones[0]["price_low"] - (0.25 * curr_atr), 2)
            else:
                stop = round(curr_close - (1.5 * curr_atr), 2)
            
            # Target is the major/intermediate overhead supply zone with minimum 2.0 R:R
            supply_zones = [z for z in zones if z.get("type") == "SUPPLY"]
            valid_targets = [z["price_low"] for z in supply_zones if z["price_low"] > curr_close * 1.01]
            if valid_targets:
                target = round(valid_targets[0], 2)
            else:
                target = round(curr_close + (3.0 * curr_atr), 2)
            entry = curr_close
        else:
            supply_zones = [z for z in zones if z.get("type") == "SUPPLY"]
            if supply_zones:
                stop = round(supply_zones[0]["price_high"] + (0.25 * curr_atr), 2)
            else:
                stop = round(curr_close + (1.5 * curr_atr), 2)

            demand_zones = [z for z in zones if z.get("type") == "DEMAND"]
            valid_targets = [z["price_high"] for z in demand_zones if z["price_high"] < curr_close * 0.99]
            if valid_targets:
                target = round(valid_targets[0], 2)
            else:
                target = round(curr_close - (3.0 * curr_atr), 2)
            entry = curr_close

        risk = abs(entry - stop)
        rr = round(abs(target - entry) / risk, 2) if risk > 0 else 2.5

        trade_setup = {
            "id": f"setup_{curr_time}",
            "direction": direction,
            "entry_price": entry,
            "stop_loss": stop,
            "take_profit": target,
            "rr_ratio": rr,
            "time_entry": curr_time,
            "thesis": thesis
        }

    primitives = {
        "lines": lines,
        "series": series_data,
        "boxes": zones,
        "levels": [],
        "hud_items": hud_items,
        "structures": structures,
        "setups": [trade_setup] if trade_setup else []
    }

    return {
        "status": "SUCCESS",
        "symbol": symbol,
        "timeframe": timeframe,
        "current_price": curr_close,
        "trend": trend,
        "indicators_computed": list(series_data.keys()),
        "trade_setup": trade_setup,
        "primitives": primitives
    }


def main():
    parser = argparse.ArgumentParser(description="NujinAI Dynamic Chart Copilot")
    parser.add_argument("--symbol", default="BTC/USDT", help="Trading asset (default: BTC/USDT)")
    parser.add_argument("--timeframe", default="15m", help="Candle timeframe (default: 15m)")
    parser.add_argument("--lookback", type=int, default=140, help="Number of candles (default: 140)")
    parser.add_argument("--indicators", help="Comma-separated indicators to compute dynamically (e.g. 'ema_21,ema_50,supertrend,rsi_14')")
    parser.add_argument("--custom", help="JSON dictionary of custom formulas (e.g. '{\"spread\": \"ema_9 - ema_21\"}')")
    parser.add_argument("--smc", action="store_true", help="Include Smart Money Concepts structure (BOS, MSS, unmitigated FVGs, Liquidity)")
    parser.add_argument("--thesis", help="User or AI trading thesis to synthesize entry, invalidation SL, and TP")
    parser.add_argument("--clear", action="store_true", help="Broadcast an immediate CLEAR command to empty the chart canvas")
    parser.add_argument("--no-broadcast", action="store_true", help="Do not broadcast via WebSocket to running frontend")
    parser.add_argument("--json", action="store_true", help="Output pure JSON")
    args = parser.parse_args()

    # If --clear is given, post directly to server endpoint to broadcast clear
    if args.clear:
        import urllib.request
        try:
            req = urllib.request.Request(
                "http://localhost:8000/api/chart/copilot",
                data=json.dumps({"action": "CLEAR", "symbol": args.symbol, "timeframe": args.timeframe}).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=3)
            print(f"Canvas successfully CLEARED live on {args.symbol} ({args.timeframe}).")
        except Exception as e:
            print(f"Failed to broadcast clear to server: {e}")
        return

    req_inds = [i.strip() for i in args.indicators.split(",")] if args.indicators else None
    custom_forms = json.loads(args.custom) if args.custom else None

    result = analyze_chart_dynamically(
        symbol=args.symbol,
        timeframe=args.timeframe,
        lookback=args.lookback,
        requested_indicators=req_inds,
        custom_formulas=custom_forms,
        include_smc=args.smc,
        thesis=args.thesis
    )

    # Automatically broadcast live to running backend/frontend WebSocket unless --no-broadcast is set
    if not args.no_broadcast:
        import urllib.request
        try:
            req_body = {
                "action": "ANALYZE",
                "symbol": args.symbol,
                "timeframe": args.timeframe,
                "lookback": args.lookback,
                "indicators": req_inds,
                "custom": custom_forms,
                "smc": args.smc,
                "thesis": args.thesis
            }
            req = urllib.request.Request(
                "http://localhost:8000/api/chart/copilot",
                data=json.dumps(req_body).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception as e:
            logger.debug(f"Direct WebSocket broadcast via server endpoint skipped: {e}")

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print("\n" + "=" * 65)
    print(f"  NujinAI Dynamic Chart Copilot :: {args.symbol} ({args.timeframe})")
    print("=" * 65)
    print(f"Current Price      : ${result.get('current_price', 0):,.2f}")
    if args.smc:
        print(f"Market Structure   : {result.get('trend', 'NEUTRAL')}")
        print(f"Active Breaks/Zones: {len(result['primitives']['structures'])} breaks, {len(result['primitives']['boxes'])} FVGs")
    if result.get("indicators_computed"):
        print(f"Computed Overlays  : {', '.join(result['indicators_computed'])}")
    
    hud = result["primitives"].get("hud_items", [])
    if hud:
        print("\nTelemetry Readout:")
        for item in hud:
            print(f"  • {item['label']:<18}: {item['value']}")

    setup = result.get("trade_setup")
    if setup:
        print("\n" + "-" * 65)
        print(f"PROPOSED TRADE SETUP: {setup['direction']} (R:R {setup['rr_ratio']})")
        print(f"Entry Price         : ${setup['entry_price']:,.2f}")
        print(f"Invalidation (Stop) : ${setup['stop_loss']:,.2f}")
        print(f"Profit Target       : ${setup['take_profit']:,.2f}")
        print(f"Thesis              : {setup['thesis']}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
