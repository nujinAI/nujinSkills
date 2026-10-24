#!/usr/bin/env python3
"""
tools/drift_monitor.py
─────────────────────────────────────────────────────────────────────────────
CLI for Pillar 7: Live-vs-Backtest Alpha Decay & Auto-Quarantine Monitor.

Usage:
  python tools/drift_monitor.py --check-live
  python tools/drift_monitor.py --live-returns "[0.002, -0.005, -0.006, -0.004, -0.005]" --bt-returns .nujin/sessions/<id>/candidate_returns.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.drift_monitor import (
    audit_and_quarantine_live_strategies,
    evaluate_live_vs_backtest_drift,
)


def _load_list(arg: str):
    if not arg:
        return None
    if os.path.exists(arg):
        with open(arg, "r", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(arg)


def main() -> None:
    parser = argparse.ArgumentParser(description="NujinSkills Live-vs-Backtest CUSUM Drift Monitor")
    parser.add_argument("--check-live", action="store_true", help="Audit active strategies in data/state.json and auto-quarantine if drifting")
    parser.add_argument("--live-returns", type=str, default="", help="JSON array or file path of realized live trade returns")
    parser.add_argument("--bt-returns", type=str, default="", help="JSON array or file path of backtest trade returns")
    parser.add_argument("--no-quarantine", action="store_true", help="Report only without demoting live bot mode")
    args = parser.parse_args()

    if args.live_returns:
        live_r = _load_list(args.live_returns) or []
        bt_r = _load_list(args.bt_returns) if args.bt_returns else None
        res = evaluate_live_vs_backtest_drift(live_r, backtest_returns=bt_r)
        print(json.dumps(res, indent=2))
        return

    reports = audit_and_quarantine_live_strategies(auto_quarantine=not args.no_quarantine)
    print(json.dumps({"drift_reports": reports}, indent=2))


if __name__ == "__main__":
    main()
