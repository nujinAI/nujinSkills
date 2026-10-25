#!/usr/bin/env python3
"""
tools/chart_copilot.py
─────────────────────────────────────────────────────────────────────────────
Autonomous Chart Copilot CLI.
Dispatches requests to the server/copilot modular engine and broadcasts
live visual primitives via WebSockets to the active chart canvas.
Never needs manual modification to support new concepts.
"""

import os
import sys
import json
import argparse
import urllib.request
import logging

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from server.copilot.dispatcher import run_copilot_analysis

logger = logging.getLogger("ChartCopilot")


def main():
    parser = argparse.ArgumentParser(description="NujinAI Dynamic Chart Copilot")
    parser.add_argument("--symbol", default="BTC/USDT", help="Asset symbol (default: BTC/USDT)")
    parser.add_argument("--timeframe", default="15m", help="Timeframe (default: 15m)")
    parser.add_argument("--lookback", type=int, default=140, help="Candles lookback")
    parser.add_argument("--indicators", help="Comma-separated indicators (e.g. 'ema_20,ema_50,rsi_14')")
    parser.add_argument("--no-zones", action="store_true", help="Disable automatic supply/demand zone extraction")
    parser.add_argument("--thesis", help="User or AI trading thesis to synthesize entry, invalidation SL, and TP")
    parser.add_argument("--clear", action="store_true", help="Broadcast an immediate CLEAR action")
    parser.add_argument("--json", action="store_true", help="Output pure JSON")
    args = parser.parse_args()

    if args.clear:
        try:
            req = urllib.request.Request(
                "http://localhost:8000/api/chart/copilot",
                data=json.dumps({"action": "CLEAR", "symbol": args.symbol, "timeframe": args.timeframe}).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            urllib.request.urlopen(req, timeout=3)
            print(f"Canvas successfully CLEARED live on {args.symbol} ({args.timeframe}).")
        except Exception as e:
            print(f"Failed to broadcast clear: {e}")
        return

    req_inds = [i.strip() for i in args.indicators.split(",")] if args.indicators else None

    # Execute deterministic analysis
    res_obj = run_copilot_analysis(
        symbol=args.symbol,
        timeframe=args.timeframe,
        lookback=args.lookback,
        requested_indicators=req_inds,
        include_zones=not args.no_zones,
        thesis=args.thesis
    )
    result = res_obj.dict()

    # Broadcast live over HTTP -> WebSocket bridge
    try:
        req_body = {
            "action": "ANALYZE",
            "symbol": args.symbol,
            "timeframe": args.timeframe,
            "lookback": args.lookback,
            "indicators": req_inds,
            "include_zones": not args.no_zones,
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
    print(f"  NujinAI Chart Copilot :: {args.symbol} ({args.timeframe})")
    print("=" * 65)
    print(f"Current Price      : ${result.get('current_price', 0):,.2f}")
    
    zones = result["primitives"].get("boxes", [])
    if zones:
        print(f"Active Zones       : {len(zones)} institutional zones identified")
        for z in zones:
            print(f"  • {z['label']:<12}: ${z['price_low']:,.2f} – ${z['price_high']:,.2f}")

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
