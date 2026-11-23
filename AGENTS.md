# Agent Guidelines: NujinSkills Repository

Directives for agents developing, maintaining, or modifying the `nujinSkills` codebase.

---

## 1. Single Source of Truth (`core/`)

All quantitative math, risk sizing, simulation, and audit logic must reside strictly in `core/`.
- **Never duplicate math:** Do not write ad-hoc indicator math, isolated backtest loops, or custom risk models in `tools/`, `server/`, or scripts.
- **Extend core:** If a new indicator or structural rule is needed, implement it in `core/` and add unit tests under `tests/`.

```
                  ┌────────────────────────────────────────────────────────┐
                  │              THE ONE SHARED LIBRARY (core/)            │
                  │   cynic_gates.py     data.py         friction.py       │
                  │   indicators.py      market_structure.py               │
                  │   risk.py            simulation.py   portfolio.py      │
                  │   regimes.py         analytics.py                      │
                  └───────────────────────────┬────────────────────────────┘
                                              │
        ┌─────────────────────────────────────┼─────────────────────────────────────┐
        ▼                                     ▼                                     ▼
┌──────────────┐                    ┌──────────────────┐                    ┌──────────────┐
│   CLI TOOLS  │                    │      SERVER      │                    │   FRONTEND   │
│   (tools/)   │                    │ (FastAPI/Sockets)│                    │ (Vue/Tailwind)│
└──────────────┘                    └──────────────────┘                    └──────────────┘
```

---

## 2. Canonical Tool Registry (`tools/`)

Use standard CLI tools instead of inventing one-off scripts:

| Tool | Purpose | Command |
|---|---|---|
| `tools.validate_hypothesis` | In-Sample market profiler & zero-lookahead hypothesis validator | `python tools/validate_hypothesis.py --profile --symbol <TICKER> --tf <TF> --days 60` |
| `tools.scan_edge` | Optional ML basis & permutation anomaly scanner | `python tools/scan_edge.py --symbol <TICKER> --tf <TF> --days 60` |
| `tools.run_backtest_audit` | Backtest & 8-Gate Cynic audit | `python tools/run_backtest_audit.py --strategy <path>` |
| `tools.autopsy_strategy` | In-Sample 4-layer & ML failure diagnosis | `python tools/autopsy_strategy.py --audit-json data/audit_report.json` |
| `tools.preflight` | Architecture & test suite verifier | `.venv/bin/python -m tools.preflight` |
| `tools.strategy_manager` | Strategy discovery, ranking & tiers | `python tools/strategy_manager.py rank` |
| `tools.state_control` | Telemetry state inspection & sync | `python tools/state_control.py get` |
| `tools.bot_control` | Live / dry-run bot control | `python tools/bot_control.py deploy --strategy <path> --mode dry-run` |
| `tools.chart_copilot` | Multi-timeframe chart visualizer | `python tools/chart_copilot.py --symbol OANDA:XAUUSD` |
| `tools.server_control` | Telemetry server lifecycle daemon | `python tools/server_control.py start --port 8000 --daemon` |
| `tools.frontend_control` | Cockpit UI lifecycle daemon | `python tools/frontend_control.py start --port 3000 --daemon` |

## 3. Autonomous Strategy Protocol Mandate
- When requested to build or research a trading strategy, agents MUST follow the 5-Phase Protocol in [`SKILL.md`](SKILL.md) and [`references/strategy_craft.md`](references/strategy_craft.md).
- NEVER audit, retrofit, or recycle existing strategies. Always research fresh In-Sample market data (`tools/validate_hypothesis.py --profile` and optionally `tools/scan_edge.py`) and pre-validate causality & friction clearance before auditing on Blind OOS.

---

## 3. Development Invariants

1. **Preflight Verification:** Always execute before concluding repository tasks:
   ```bash
   .venv/bin/python -m tools.preflight
   ```
2. **Strategy Creation Scope:** If the task is developing a trading strategy (rather than engine development), follow [`SKILL.md`](SKILL.md) and deploy into `../zillionsAlpha/` or `../nujinPro/`.
