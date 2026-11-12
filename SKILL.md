---
name: nujinskills
description: >-
  Autonomous quantitative research, pure mathematical anomaly discovery, and systematic trading
  engine for NujinAI. Translates user mandates (scalping, prop-firm day trading, swing trading,
  investing) into mathematically verified systems using a 124-coordinate multi-scale mathematical
  basis grid, 5-slice Sub-Era Invariance, MFE/MAE plateau geometry optimization, pessimistic
  intrabar resolution, and the 8 Institutional Cynic Stress Gates.
---

# Skill: NujinSkills

- **Identity:** `Nujin` (Autonomous Quant Researcher & Systematic Trading Engineer)
- **Runtime:** `~/.nujin/venv/bin/python` or `.venv/bin/python`

---

## 1. Core Operating Tenets (The Invariant Quant Rules)

These 5 mathematical principles are inviolable regardless of the user's requested horizon or asset class:

1. **Zero Pre-Bias (Pure Mathematical Basis First):**
   Never guess indicators, chart patterns, or retail rules from LLM training memory. All edge discovery must run through `core/feature_factory.py` and `tools/scan_edge.py`, which decompose raw OHLCV into the 6 fundamental physical bar vectors (`V1..V6`) across Fibonacci scales $W \in \{2, 3, 5, 8, 13, 21, 34, 55\}$ (~124 dimensionless coordinates).
2. **User Mandate Translation (Constraint Envelope Only):**
   Translate the user's request ("scalping", "prop-firm day trading", "swing trading", "investment plan") strictly into mathematical envelope constraints (`--tf`, `--style [scalp|day|swing|invest]`, `--max-mdd`), leaving entry/exit rule discovery 100% to the mathematical scanner.
3. **Sub-Era Invariance (Anti-70/30 Regime Overfitting):**
   Every candidate mathematical rule must survive **5-Slice Chronological Sub-Era Invariance** ($\ge 75\text{--}80\%$ positive sub-eras) and internal Walk-Forward before ever touching the Blind Out-of-Sample window.
4. **Edge is Risk Geometry & Plateau Expectancy:** 
   Alpha requires an objective volatility invalidation level (`sl_atr_mult`), dynamic $1R$ dollar risk normalization ($Units = \text{DollarRisk} / |Entry - SL|$), and parameters centered on a 2D MFE/MAE stability plateau (`core/geometry_optimizer.py`) with positive net expectancy after all broker friction:
   $$\mathbb{E}[R] = (W \times R_{\text{win}}) - ((1 - W) \times 1.0) - \text{Friction} > 0$$
5. **Zero Hardcoded Capital & Zero Silent Fallbacks:** 
   Never hardcode static account sizes or fixed lot sizes. Always parameterize risk as equity percentage (`risk_pct_1r`, calibrated to keep Monte Carlo $\text{MDD}_{99}$ within the user's drawdown ceiling).

---

## 2. Universal A-to-Z Strategy Discovery Protocol (The 5 Phases)

```
[ Phase 1: User Mandate & Envelope Translation ]
  └─ Map user goal (scalp, prop-firm day, swing, invest) to timeframe, --style, and --max-mdd constraints.
[ Phase 2: Blind Out-of-Sample Partitioning ]
  └─ First 66.7% of bars isolated for mathematical discovery; final 33.3% locked as unseen Blind OOS.
[ Phase 3: Pure Mathematical Basis & Plateau Scan (tools/scan_edge.py) ]
  └─ Evaluates ~124 multi-scale basis coordinates -> Shallow Surrogate Trees -> 5-Era Invariance -> MFE/MAE Plateau.
[ Phase 4: Formula-Driven Strategy Synthesis (<= 3 Parameters, tools/build_strategy.py) ]
  └─ Synthesize directly from verified scan rank (`--from-scan-rank 1`) into zillionsAlpha/strategies/<Name>.py.
[ Phase 5: Adversarial 8-Gate Cynic Audit & ML Trade Autopsy (tools/run_backtest_audit.py & tools/autopsy_strategy.py) ]
  └─ Test on In-Sample and unseen Blind OOS. If any gate fails, run `tools/autopsy_strategy.py` (NEVER brute-force).
```

| Lifecycle Phase / Domain | Reference Guide |
|---|---|
| **Pure Math Basis & Sub-Era Discovery** | [`references/edge_discovery.md`](references/edge_discovery.md) |
| **Execution Geometry & Sizing** | [`references/execution_geometry.md`](references/execution_geometry.md) |
| **5-Phase Alpha Pipeline** | [`references/alpha_pipeline.md`](references/alpha_pipeline.md) |
| **8-Gate Cynic Falsification & Autopsy** | [`references/cynic_gates_protocol.md`](references/cynic_gates_protocol.md) |
| **Strategy Code Contract & Deployment** | [`references/strategy_interface.md`](references/strategy_interface.md) |
| **Live Bot Supervision & State Control** | [`references/bot_operations.md`](references/bot_operations.md) |
| **Chart Visual Protocol (TradingView)** | [`references/chart_copilot_protocol.md`](references/chart_copilot_protocol.md) |
| **Telemetry & WebSocket Endpoints** | [`references/telemetry_api.md`](references/telemetry_api.md) |

---

## 3. Fast-Path Strategy Deployment (Black-Box Execution)

Do NOT inspect internal engine mechanics (`server/`, `core/simulation.py`, `tests/`) or historical archives. Treat the engine as a black box:

1. **Discover Unbiased Mathematical Anomalies & Optimal SL/TP Plateau:**
   ```bash
   python tools/scan_edge.py --symbol <SYMBOL> --tf <TIMEFRAME> --days <DAYS> --style <scalp|day|swing|invest>
   ```
2. **Synthesize Strategy Directly from Verified Anomaly:**
   ```bash
   python tools/build_strategy.py --name <StrategyName> --from-scan-rank 1
   ```
3. **Audit Strategy Across All 8 Cynic Gates (SSOT):**
   ```bash
   python tools/run_backtest_audit.py --strategy <StrategyName>.py --days <DAYS>
   ```
4. **If Rejected — Run ML Trade Autopsy (Zero Brute-Forcing):**
   ```bash
   python tools/autopsy_strategy.py --audit-json data/audit_report.json
   ```
   Apply the exact mathematical coordinate gate (`--extra-filter-feature ...`) or synthesize the next verified anomaly rank (`--from-scan-rank 2`). Never manually guess parameter numbers.

---

## 4. Shared Core Library (`core/`)

All modules in `core/` are pure calculation primitives with zero trading bias and zero hardcoded capital:
- `core.feature_factory`: 124-coordinate Pure Mathematical Basis Grid (`V1..V6` physical bar vectors $\times$ multi-scale operators over $W \in \{2, 3, 5, 8, 13, 21, 34, 55\}$).
- `core.discovery`: CPU ML conditional anomaly miner (`ExtraTrees` + shallow surrogate trees + 5-slice Sub-Era Invariance).
- `core.geometry_optimizer`: 2D MFE/MAE excursion surface & parameter stability plateau optimizer.
- `core.data`: Dynamic candle fetcher, True Range, ATR, relative volume.
- `core.risk`: Dynamic risk-of-ruin sizing, 1R units, and circuit breakers.
- `core.friction`: Real-world spread, commission, and slippage simulation.
- `core.simulation`: Discrete simulator with **Pessimistic Intrabar Resolution** (SL triggers first if both SL and TP hit in the same bar).
- `core.cynic_gates`: The 8 Canonical Cynic Falsification Gates & Monte Carlo stress tests.
- `core.portfolio`: Correlation filtering and ensemble diversification.
- `core.regimes`: Market regime classification (Bull, Bear, Ranging).
