# 5-Phase Institutional Alpha Pipeline

Paradigm-agnostic pipeline for researching markets, engineering creative 4-layer strategies, pre-validating hypotheses strictly In-Sample, and stress-testing across unseen Blind Out-of-Sample data.

---

```
[ Phase 1: Mandate & In-Sample Market Research ]
  -> Parse user constraints; profile asset microstructure (`validate_hypothesis.py --profile`)
     and optionally run `scan_edge.py`. Choose style/approach empirically if unspecified.

[ Phase 2: Authentic Ingestion & Blind Out-of-Sample Isolation ]
  -> Chronologically partition authentic candles: 66.7% In-Sample (research & iteration)
     and 33.3% Blind Out-of-Sample (strictly locked until Phase 5).

[ Phase 3: Creative 4-Layer Architecture & Synthesis ]
  -> Engineer Context -> Location (Zone) -> Confirmation -> Structural Invalidation using
     any causal math/indicators/structure (see `references/strategy_craft.md`).

[ Phase 4: In-Sample Hypothesis Pre-Validation (`tools/validate_hypothesis.py`) ]
  -> Prove Zero Lookahead (prefix-invariance), 5-Slice Sub-Era Invariance, Friction Floor,
     and healthy Context / Location / Confirmation diagnostics before touching Blind OOS.

[ Phase 5: Adversarial 8-Gate Cynic Falsification & Autonomous Autopsy ]
  -> Audit on IS + Blind OOS via `tools/run_backtest_audit.py`. On rejection, diagnose
     strictly In-Sample with `tools/autopsy_strategy.py` and refine structurally.
```

---

## Phase 1: Mandate & Market Research First
- Parse user constraints (asset, horizon, drawdown, or explicit style/indicator domain) and derive dynamic risk budgets via `core.risk.parse_prompt_to_risk(...)`.
- **When the user does not specify a style or thesis**, never blindly default to a single scanner or canned playbook: profile the asset's In-Sample microstructure (`tools/validate_hypothesis.py --profile`)—volatility, friction-to-ATR feasibility, return persistence/reversion, regime mix, and peak UTC hours—and optionally probe `tools/scan_edge.py` to select the highest-fit paradigm empirically.

## Phase 2: Authentic Ingestion & Blind OOS Lock
- Ingest authentic candles matching the traded venue (Spot/CFD, Futures, Crypto, Equities).
- **Inviolable 2/3 vs. 1/3 Chronological Split:** All research, feature engineering, profiling, and pre-validation occur strictly inside the first **66.7% In-Sample** segment. The final **33.3% Blind OOS** stays untouched until Phase 5.

## Phase 3: Creative 4-Layer Strategy Construction
- Structure hypotheses around **Context → Location (Zone) → Confirmation → Structural Invalidation** (adapted creatively to the paradigm; see [`references/strategy_craft.md`](strategy_craft.md)).
- Indicators are allowed when they fit the thesis, strictly as orthogonal, scale-normalized, causal state sensors—never standalone retail triggers or collinear stacks.
- Keep tunable parameters minimal and thesis-justified; size exclusively via fractional equity risk (`risk_pct_1r`) with objective structural invalidation.

## Phase 4: In-Sample Hypothesis Pre-Validation
- Run `python tools/validate_hypothesis.py --strategy <Name>.py --days <DAYS>` strictly on the 66.7% In-Sample split:
  - Must pass **Prefix-Invariance Causality** (zero lookahead).
  - Verify positive net expectancy, **5-Slice Sub-Era Invariance**, **Friction Floor** ($\le 10\%$ of SL), and 4-layer diagnostics (no severe regime bleed, excessive 1–2 bar stop-outs, or invalid SL/TP geometry).

## Phase 5: Adversarial 8-Gate Cynic Audit & Autonomous Iteration
- Run `python tools/run_backtest_audit.py --strategy <Name>.py --days <DAYS>` across In-Sample and unseen Blind OOS (see [`references/cynic_gates_protocol.md`](cynic_gates_protocol.md)).
- **Forbidden:** Brute-force parameter decimal sweeps or recycling old strategies.
- **Required:** Diagnose gate failures strictly In-Sample via `tools/autopsy_strategy.py` (4-layer diagnostics + ML shallow-tree diagnosis), refine the failing structural layer or pivot thesis, re-validate In-Sample, and re-audit until all 8 gates PASS.
