#!/usr/bin/env python3
"""
tools/chart_copilot.py
NujinAI Chart Copilot CLI & Analysis Tool.

Inspects live market data for any symbol & timeframe, extracts institutional
market structure (Swings, BOS, MSS, unmitigated FVGs, BSL/SSL pools),
synthesizes an actionable trade setup with 1R risk invalidation, and pushes
visual primitives directly to the frontend chart canvas.

Usage:
    tools/chart_copilot.py [--symbol BTC/USDT] [--timeframe 15m] [--lookback 140] [--json]
"""

import os
import sys
import json
import argparse
import logging
from typing import Dict, Any

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from server.market_structure import extract_market_structure, detect_swing_points
from server.chart_primitives import extract_strategy_primitives
from server import data_manager

logger = logging.getLogger("ChartCopilot")


def analyze_market_chart(
    symbol: str = "BTC/USDT",
    timeframe: str = "15m",
    lookback: int = 140
) -> Dict[str, Any]:
    """
    Fetches real candles, computes institutional SMC structure,
    and returns a structured copilot briefing with visual primitives.
    """
    sym_upper = symbol.upper()
    is_gold = any(k in sym_upper for k in ["XAU", "GOLD", "GC"])
    is_sp = any(k in sym_upper for k in ["SP", "ES", "S&P", "US500"])
    
    # 1. Fetch authentic candles through data_manager module seam
    if is_gold:
        candles = data_manager.fetch_real_oanda_candles(interval=timeframe, count=lookback)
    elif is_sp:
        candles = data_manager.fetch_real_sp500_candles(interval=timeframe, count=lookback)
    else:
        candles = data_manager.fetch_real_binance_klines(symbol=symbol, interval=timeframe, count=lookback)

    if not candles or len(candles) < 25:
        return {
            "status": "ERROR",
            "message": f"Insufficient candles retrieved for {symbol} ({timeframe}).",
            "symbol": symbol,
            "timeframe": timeframe
        }

    df = pd.DataFrame(candles)
    if "time" not in df.columns and "timestamp" in df.columns:
        df["time"] = df["timestamp"]

    # 2. Extract clean market structure
    ms_result = extract_market_structure(df, left_bars=5, right_bars=5, max_lookback=lookback)
    
    structures = ms_result.get("structures", [])
    zones = ms_result.get("zones", [])
    trend = ms_result.get("trend", "NEUTRAL")
    
    curr_close = float(df["close"].iloc[-1])
    curr_time = int(df["time"].iloc[-1])

    # 3. Formulate Actionable Institutional Trade Setup
    bsl_pool = next((s for s in reversed(structures) if s.get("type") == "LIQUIDITY" and s.get("direction") == "BULLISH"), None)
    ssl_pool = next((s for s in reversed(structures) if s.get("type") == "LIQUIDITY" and s.get("direction") == "BEARISH"), None)
    
    trade_idea = None

    # Bullish Setup: Uptrend/MSS Bullish with Discount FVG Support
    bull_fvg = next((z for z in reversed(zones) if z["type"] == "FVG_BULL" and z["price_high"] <= curr_close * 1.002), None)
    if trend in ["BULLISH", "NEUTRAL"] and bull_fvg:
        entry = float(bull_fvg["price_high"])
        stop = round(float(bull_fvg["price_low"]) * 0.9990, 2)
        risk = entry - stop
        if risk > 0:
            target = float(bsl_pool["price"]) if bsl_pool and bsl_pool["price"] > entry else round(entry + (risk * 3.0), 2)
            rr = round((target - entry) / risk, 2)
            trade_idea = {
                "direction": "LONG",
                "entry_price": entry,
                "stop_loss": stop,
                "take_profit": target,
                "rr_ratio": rr,
                "thesis": f"Long limit at Bullish FVG (${bull_fvg['price_low']} - ${bull_fvg['price_high']}) targeting BSL liquidity."
            }

    # Bearish Setup: Downtrend/MSS Bearish with Premium FVG Resistance
    bear_fvg = next((z for z in reversed(zones) if z["type"] == "FVG_BEAR" and z["price_low"] >= curr_close * 0.998), None)
    if not trade_idea and trend in ["BEARISH", "NEUTRAL"] and bear_fvg:
        entry = float(bear_fvg["price_low"])
        stop = round(float(bear_fvg["price_high"]) * 1.0010, 2)
        risk = stop - entry
        if risk > 0:
            target = float(ssl_pool["price"]) if ssl_pool and ssl_pool["price"] < entry else round(entry - (risk * 3.0), 2)
            rr = round((entry - target) / risk, 2)
            trade_idea = {
                "direction": "SHORT",
                "entry_price": entry,
                "stop_loss": stop,
                "take_profit": target,
                "rr_ratio": rr,
                "thesis": f"Short limit into Bearish FVG (${bear_fvg['price_low']} - ${bear_fvg['price_high']}) targeting SSL liquidity."
            }

    # 4. Compile chart primitives for the UI
    primitives = extract_strategy_primitives(None, candles, include_ai_copilot=True)
    if trade_idea:
        primitives["setups"] = [{
            "id": f"setup_{curr_time}",
            **trade_idea,
            "time_entry": curr_time
        }]

    return {
        "status": "SUCCESS",
        "symbol": symbol,
        "timeframe": timeframe,
        "current_price": curr_close,
        "trend": trend,
        "market_structure": {
            "structures_count": len(structures),
            "unmitigated_fvgs": len(zones),
            "bsl_target": bsl_pool["price"] if bsl_pool else None,
            "ssl_target": ssl_pool["price"] if ssl_pool else None,
        },
        "trade_setup": trade_idea,
        "primitives": primitives
    }


def main():
    parser = argparse.ArgumentParser(description="NujinAI Chart Copilot CLI")
    parser.add_argument("--symbol", default="BTC/USDT", help="Trading asset (default: BTC/USDT)")
    parser.add_argument("--timeframe", default="15m", help="Candle timeframe (default: 15m)")
    parser.add_argument("--lookback", type=int, default=140, help="Number of candles (default: 140)")
    parser.add_argument("--json", action="store_true", help="Output pure JSON")
    args = parser.parse_args()

    result = analyze_market_chart(
        symbol=args.symbol,
        timeframe=args.timeframe,
        lookback=args.lookback
    )

    if args.json:
        print(json.dumps(result, indent=2))
        return

    print("\n" + "=" * 65)
    print(f"  NujinAI Chart Copilot :: {args.symbol} ({args.timeframe})")
    print("=" * 65)
    print(f"Current Price : ${result.get('current_price', 0):,.2f}")
    print(f"Regime / Trend: {result.get('trend', 'NEUTRAL')}")
    ms = result.get("market_structure", {})
    print(f"Structures    : {ms.get('structures_count', 0)} breaks active")
    print(f"Active FVGs   : {ms.get('unmitigated_fvgs', 0)} unmitigated zones")
    if ms.get("bsl_target"):
        print(f"Buyside (BSL) : ${ms['bsl_target']:,.2f}")
    if ms.get("ssl_target"):
        print(f"Sellside (SSL): ${ms['ssl_target']:,.2f}")
    print("-" * 65)

    setup = result.get("trade_setup")
    if setup:
        print(f"TRADE IDEA    : {setup['direction']} (R:R {setup['rr_ratio']})")
        print(f"Entry Area    : ${setup['entry_price']:,.2f}")
        print(f"Invalidation  : ${setup['stop_loss']:,.2f}")
        print(f"Target Profit : ${setup['take_profit']:,.2f}")
        print(f"Thesis        : {setup['thesis']}")
    else:
        print("TRADE IDEA    : No high-conviction unmitigated FVG setup currently.")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
