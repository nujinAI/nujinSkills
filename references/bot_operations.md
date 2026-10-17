# Live Bot Operations & Non-Disruptive Supervision Guide

This reference provides instructions for supervising and operating the live trading bot without interrupting running services or causing race conditions.

---

## ⚠️ 1. Cardinal Rule: The Bot is Live

When operating in this repository, **the trading engine and market data streamers may be actively running in the background**.

- **NEVER** kill or terminate active `python server/main.py` or streamer processes unless explicitly instructed by the user.
- **NEVER** re-bind to running ports (`8000` for backend, `3000` for frontend).
- **ALWAYS** interact with the running system through the safe CLI controllers (`bot_control.py`, `state_control.py`, and `strategy_manager.py`).

---

## 🔍 2. Non-Disruptive Health & State Inspection

### Check Bot Execution Status
To verify whether the bot is running, which strategies are active, and the current broker mode:
```bash
nujinSkills/.venv/bin/python3 tools/bot_control.py status
```
This queries the live backend API and returns:
- Process status & uptime.
- Active strategy name.
- Execution mode (`paper` vs. `live`).
- Broker connectivity status.

### Inspect Live Trading Performance & Signals
To query live performance metrics without disturbing execution:
```bash
nujinSkills/.venv/bin/python3 tools/state_control.py signal-stats
```
Outputs live Win Rate, Profit Factor, Realized PnL, and Sharpe ratio.

To view recently triggered entry/exit signals:
```bash
nujinSkills/.venv/bin/python3 tools/state_control.py signals
```

To inspect specific keys in the shared runtime state:
```bash
nujinSkills/.venv/bin/python3 tools/state_control.py get --key active_strategy
nujinSkills/.venv/bin/python3 tools/state_control.py get --key open_positions
```

---

## 🚀 3. Safe Strategy Hot-Deployment

When a new strategy is synthesized, audited, and approved through the 4-stage pipeline:

### Step 1: Register Strategy
Register the emitted strategy in `strategy_manager.py`:
```bash
nujinSkills/.venv/bin/python3 tools/strategy_manager.py add --file strategies/MyAlphaStrategy.py
```

### Step 2: Hot-Deploy to Paper Mode First
Deploy the strategy to the running engine in **paper trading mode** (dry-run):
```bash
nujinSkills/.venv/bin/python3 tools/bot_control.py deploy --strategy MyAlphaStrategy --mode paper
```
The server dynamically loads the strategy module without dropping active WebSocket connections or interrupting data feeds.

### Step 3: Monitor Live Signal Generation
Confirm that the strategy starts evaluating incoming candle ticks:
```bash
nujinSkills/.venv/bin/python3 tools/state_control.py signals --strategy MyAlphaStrategy
```

### Step 4: Promotion to Live Execution
Only after observing satisfactory live behavior in paper mode, promote to live execution if approved:
```bash
nujinSkills/.venv/bin/python3 tools/bot_control.py deploy --strategy MyAlphaStrategy --mode live
```

---

## 📡 4. Live Telemetry & Alerts

### Dispatch Cockpit Widgets
Stream real-time status cards to the Cockpit UI (`http://localhost:3000`):
```bash
nujinSkills/.venv/bin/python3 tools/ui_dispatcher.py --event UPSERT_WIDGET --payload '{
  "widget_id": "quant_research_status",
  "type": "card",
  "payload": {
    "title": "Alpha Research Pipeline",
    "status": "Cynic Audit Passed",
    "metric": "DSR 0.97"
  }
}'
```

### Send Telegram Notifications
Broadcast research milestones, backtest summaries, or strategy promotions:
```bash
nujinSkills/.venv/bin/python3 tools/telegram_broadcast.py broadcast --type update --title "New Strategy Deployed" -m "Alpha strategy 'MyAlphaStrategy' hot-deployed to paper mode with DSR 0.97."
```

---

## 🛡️ Data Integrity Guarantees

Live market data must never be synthesised. The XAU/USD feed (`server/xauusd_streamer.py`) polls an
OANDA spot quote, which carries a **price but no volume**, so:

- **Prices are served verbatim.** No random "micro-pip" jitter is applied to the close or to bid/ask.
- **Volume is labelled, never faked.** Bars built from the polled stream carry
  `volume_source: "derived_from_ticks"`; the background authentic sync sets `volume_source: "authentic"`
  when it fills a bar from real candles. Strategies that depend on volume must not run on bars whose
  `volume_source` is not `"authentic"`.
- **Gaps are reported, not interpolated.** If a gap cannot be backfilled with authentic candles, the
  engine sets `data_degraded = True` (with `data_gap_seconds`) and logs a warning instead of appending
  synthesised bars.

Any consumer that observes `data_degraded` should treat signals as unreliable until it clears. It does
clear: `_mark_data_recovered()` resets it (and `data_gap_seconds` to 0) the moment **authentic** bars
arrive — either because a backfill succeeded or because the background authentic sync merged real
candles. Bars whose volume was derived from the polled tick stream are not evidence that the series is
complete, so they never clear the flag.

---

## 🔐 Live Entry Arming Interlock

An order routed to a **live** broker environment is real money, and the adapter cannot tell an intended
live entry from an accidental one. Live entries therefore require one explicit, process-level switch:

```bash
export NUJIN_LIVE_TRADING=1     # arm live entries for this process
```

- **Unset (or any value other than `1`/`true`/`yes`/`on`)** — live entries are refused with status
  `BLOCKED_NOT_ARMED`. No client session is even created, no order is sent, and the strategy records
  the signal as `BLOCKED_NOT_ARMED` with `execution_mode: "NONE"` so no phantom position is tracked.
- **Armed** — the live path behaves exactly as before.
- **Demo accounts are unaffected** by the switch; the interlock only applies when the account's
  `environment` names a live gateway.
- **Exits are never gated.** `close_position()` and `modify_position()` are deliberately not blocked,
  even when entries are disarmed: an operator must always be able to flatten or protect a live position.

The refusal is loud — a warning in the log plus a Telegram receipt on the affected account — so a
disarmed strategy is visible rather than silently idle.
