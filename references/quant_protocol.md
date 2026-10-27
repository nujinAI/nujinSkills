# Institutional Quant Protocol — Execution Geometry & 4-Gate Verification

This document establishes the end-to-end standard for quantitative research, hypothesis formulation, risk-normalized execution geometry, dynamic candle ingestion, and 4-gate verification in NujinAI.

---

## 1. Core Quantitative Principles: The Edge is in the Execution Geometry

In non-stationary, adversarial financial markets, predictive certainty through data density (L2/L3 order books or indicator stacking) is an illusion. Passive orders are non-binding (spoofing/layering) and institutional volume is hidden (TWAP/VWAP, dark pools).

Therefore, trading edge is established through **Execution Geometry and Convexity**:
1. **Objective Invalidation:** An unambiguous structural price level where the trade premise is disproven.
2. **Dynamic $1R$ Dollar Risk Normalization:**
   $$\text{Position Size (Units)} = \frac{\text{Account Capital} \times \text{Risk Fraction } (1R)}{|\text{Entry Price} - \text{Stop Loss}|}$$
   Every trade risks the exact same dollar budget ($1R$). A loss costs strictly $-1R$, while expansions capture $+2.5R$ to $+5R+$.
3. **Friction Floor:**
   $$\frac{\text{Total Round-Trip Friction (Spread + Commission + Slippage)}}{\text{Stop-Loss Distance } (1R)} \le 10\%$$
   If friction exceeds 10% of the stop distance, the timeframe or setup is automatically rejected.
4. **Pessimistic Intrabar Resolution:**
   If a single bar touches both Stop-Loss and Target, the simulator strictly assumes the Stop-Loss triggered first.

---

## 2. Dynamic Candle Fetching (Zero Static CSV Limits)

Never restrict research to truncated static CSVs. In Nujin, market data is dynamically ingested and cached via `tools/core/data_tool.py`:
- **Free Market Coverage:** Any asset (`GC=F`, `BTC-USD`, `SPY`, `QQQ`, `EURUSD=X`, `CL=F`).
- **Flexible Timeframes:** `1m`, `5m`, `15m`, `1h`, `4h`, `1d`.
- **Pure Primitives:** Generates OHLCV, True Range, Wilder's 14 ATR, normalized bar range, and volume relative to median without lagging indicator sprawl.

---

## 3. The 4-Step Scientific Research Loop

```
[ STEP 1: COMPILE USER INTENT & RISK BUDGET ]
  Tools: python3 tools/core/risk_calc.py "<user prompt>"
  -> Calculates exact $1R dollar risk, max daily losses, and consistency caps.

[ STEP 2: DYNAMIC DATA FETCH & FRICTION CHECK ]
  Tools: tools.core.data_tool.fetch_ohlcv(...)
  Tools: tools.core.friction_calc.check_friction_hurdle(...)
  -> Verifies friction is <= 10% of stop distance.

[ STEP 3: FORMULATE STRUCTURAL THESIS & GENERATE SIGNALS ]
  The AI reasons about an anchor (session opens, volatility compression, structural bounds).
  Constructs signals: entry, stop_loss, target.

[ STEP 4: EXECUTE & AUDIT ]
  Tools: tools.core.backtest_engine.run_discrete_backtest(...)
  Tools: tools.core.auditor_tool.audit_trade_log(...)
  -> Tests 4 Institutional Gates:
     Gate 1: Expectancy & Profit Factor (PF >= 1.25, Exp >= 0.10R).
     Gate 2: Top-5 Outlier Win Removal (Net PnL must stay positive).
     Gate 3: 50/50 Chronological Regime Split (Profitable in both halves).
     Gate 4: Monte Carlo 1,000 Runs (Strict 95th % Max DD and Daily DD limits).

  * If any gate fails: Analyze diagnostics -> adjust thesis/timeframe -> re-test.
  * When ALL gates pass: Deploy into strategies/<StrategyName>.py.
```
