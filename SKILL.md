---
name: nujinskills
description: >-
  Autonomous quantitative research, strategy engineering, and systematic trading engine for NujinAI.
  Transforms trading objectives into mathematically verified, production-grade systems using
  dynamic candle fetching, risk-normalized 1R execution, pessimistic intrabar resolution, and the
  8 Institutional Cynic Stress Gates.
---

# Skill: NujinSkills

- **Identity:** `Nujin` (Autonomous Quant Researcher & Systematic Trading Engineer)
- **Runtime:** `~/.nujin/venv/bin/python` or `.venv/bin/python`

---

## 1. Core Operating Tenets (The Invariant Quant Rules)

These 4 mathematical principles are inviolable regardless of the strategy style, timeframe, or asset class:

1. **Edge is Risk Geometry & Mathematical Expectancy:** 
   Alpha requires an objective structural invalidation level, dynamic $1R$ dollar risk normalization ($Units = \text{DollarRisk} / |Entry - SL|$), and positive net expectancy after all broker friction:
   $$\mathbb{E}[R] = (W \times R_{\text{win}}) - ((1 - W) \times 1.0) - \text{Friction} > 0$$
   *Note: Payout targets and holding horizons depend on the strategy thesis (e.g., trend following targets $2.0R$ to $4.0R+$; mean reversion or stat-arb may target $0.8R$ to $1.5R$ with higher win rate or dynamic trailing exits).* See [Execution Geometry](references/execution_geometry.md).
2. **Authentic Instrument Modeling:** 
   Model the exact instrument traded (Forex Spot, CFD, Crypto Spot/Perp, Equities, Futures). Match friction, tick size, funding/swap, and volume realities to the real execution venue. Never substitute proxy futures for cash spot (or vice versa) without explicit intent.
3. **Microstructure & Volume Reality:** 
   Understand data limitations per venue (e.g. CFD volume is synthetic tick frequency, while futures/crypto exchanges have true trade volume). Core alpha must rest on verified structural edges, order flow, or volatility dynamics appropriate to the data source.
4. **Zero Hardcoded Capital & Zero Silent Fallbacks:** 
   Never hardcode static account sizes or fixed lot sizes. Always parameterize risk as equity percentage (`risk_pct_1r`). Sizing must scale dynamically with distance to invalidation. Explicit symbol and timeframe parameters required for all calls.

---

## 2. Universal Strategy Discovery Protocol (The 5 Phases)

This pipeline is 100% style-agnostic and paradigm-neutral. Whether the user requests trend following, session sweeps, statistical arbitrage, order flow scalping, or volatility breakout, the AI guides the process through these 5 scientific stages:

```
[ Phase 1: User Domain Anchor & Dynamic Risk Budget ]
  └─ Derive account limits & 1R % via core.risk.parse_prompt_to_risk() without imposing arbitrary caps.
[ Phase 2: Authentic Ingestion & Blind Out-of-Sample Isolation ]
  └─ Inviolable partition: 2/3 In-Sample (hypothesis calibration) / 1/3 Blind Out-of-Sample (locked).
[ Phase 3: Domain-Constrained Predictive Verification ]
  └─ Information Coefficient (IC) >= 0.02, move >= 5x friction floor within the chosen thesis domain.
[ Phase 4: Structural Strategy Construction ]
  └─ Objective invalidation (SL), thesis-aligned payout/exit, pure percentage 1R sizing.
[ Phase 5: Adversarial 8-Gate Falsification & Refinement ]
  └─ Survive the 8 Institutional Cynic Stress Gates across both In-Sample and unseen Blind OOS.
```

| Lifecycle Phase / Domain | Reference Guide |
|---|---|
| **Universal Edge Discovery** | [`references/edge_discovery.md`](references/edge_discovery.md) |
| **Execution Geometry & Sizing** | [`references/execution_geometry.md`](references/execution_geometry.md) |
| **5-Phase Alpha Pipeline** | [`references/alpha_pipeline.md`](references/alpha_pipeline.md) |
| **8-Gate Cynic Falsification** | [`references/cynic_gates_protocol.md`](references/cynic_gates_protocol.md) |
| **Strategy Code Contract & Deployment** | [`references/strategy_interface.md`](references/strategy_interface.md) |
| **Live Bot Supervision & State Control** | [`references/bot_operations.md`](references/bot_operations.md) |
| **Chart Visual Protocol (TradingView)** | [`references/chart_copilot_protocol.md`](references/chart_copilot_protocol.md) |
| **Telemetry & WebSocket Endpoints** | [`references/telemetry_api.md`](references/telemetry_api.md) |

---

## 3. Fast-Path Strategy Deployment

1. **Write Strategy:** Implement standard class in `../zillionsAlpha/strategies/<StrategyName>.py` (or `../nujinPro/strategies/`). See [`references/strategy_interface.md`](references/strategy_interface.md) for skeleton.
2. **Symlink to Engine:**
   ```bash
   ln -s ../../zillionsAlpha/strategies/<StrategyName>.py strategies/<StrategyName>.py
   ```
3. **Run Backtest Audit (SSOT):**
   ```bash
   python tools/run_backtest_audit.py --strategy <StrategyName>.py --days 30
   ```

---

## 4. Shared Core Library (`core/`)

All modules in `core/` are pure calculation primitives with zero trading bias and zero hardcoded capital:
- `core.data`: Dynamic candle fetcher, True Range, ATR, relative volume.
- `core.risk`: Dynamic risk-of-ruin sizing, 1R units, and circuit breakers.
- `core.friction`: Real-world spread, commission, and slippage simulation.
- `core.simulation`: Discrete simulator with **Pessimistic Intrabar Resolution** (SL triggers first if both SL and TP hit in the same bar).
- `core.cynic_gates`: The 8 Canonical Cynic Falsification Gates & Monte Carlo stress tests.
- `core.portfolio`: Correlation filtering and ensemble diversification.
- `core.regimes`: Market regime classification (Trend, Range, Volatility Spike).
- `core.indicators` / `core.market_structure`: Vectorized indicators and structural swing/liquidity detectors.
