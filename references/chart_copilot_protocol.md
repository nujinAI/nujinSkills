# NujinAI Chart Copilot Protocol

The **Chart Copilot** enables NujinAI (Antigravity) and the user to collaboratively inspect live charts, analyze market structure mathematically, and project institutional trade setups directly onto the visual canvas.

---

## 1. Core Architecture

The system operates in two non-conflicting visual modes:
- **Strategy Mode (Default):** Inspects historical strategy backtests, signals, and strategy-specific indicator manifests.
- **AI Copilot Mode:** Autonomous live market vision powered by institutional Smart Money Concepts (SMC), Volume, and TA-Lib indicators.

```
                      ┌────────────────────────────┐
                      │    User Prompt in Chat     │
                      │ ("Analyze BTC 15m chart")  │
                      └─────────────┬──────────────┘
                                    │
                                    ▼
                      ┌────────────────────────────┐
                      │    tools/chart_copilot.py  │
                      │   (Python SMC Math Engine) │
                      └─────────────┬──────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
       [ Structured Brief in Chat ]       [ Live SVG Primitives ]
       • Market Regime / Trend            • Confirmed BOS & MSS Rays
       • Unmitigated Fair Value Gaps      • Discount / Premium FVGs
       • BSL & SSL Liquidity Targets      • Anchored BSL / SSL Rays
       • Concrete Trade Setup & R:R       • Interactive Setup Box
```

---

## 2. Institutional SMC Visual Primitives

### 1. Structural Breaks (BOS & MSS)
- **BOS (Break of Structure):** Trend continuation when a candle close breaks past a previous swing pivot in the direction of the trend.
- **MSS (Market Structure Shift / CHoCH):** Trend reversal when a candle close breaks past the opposing swing pivot.
- **Visuals:** Horizontal dashed lines connecting swing origin to the breakout candle, with clean color-coded badges (`#10b981` Bullish, `#ef5350` Bearish) offset to the right of the candle wicks.

### 2. Fair Value Gaps (FVG)
- **Definition:** 3-bar displacement imbalance where $Low[t] > High[t-2]$ (Bullish) or $High[t] < Low[t-2]$ (Bearish).
- **Displacement Threshold:** Minimum gap width and displacement body $\ge 0.45 \times \text{ATR}$ to filter intraday noise.
- **Equilibrium Mitigation:** Once price retraces into the 50% midpoint of the gap, the FVG is considered mitigated and terminates.
- **Deduplication:** Overlapping FVGs from the same impulse move are merged into a single clean zone.

### 3. Liquidity Pools (BSL & SSL)
- **BSL (Buyside Liquidity):** Resting buy-stops above major swing highs.
- **SSL (Sellside Liquidity):** Resting sell-stops below major swing lows.
- **Visuals:** Candle-anchored rays originating from the swing pivot wicks and projecting cleanly to current price.

---

## 3. CLI & Autonomous Agent Tool Usage

Whenever the user asks:
- *"Analyze the chart for BTC / Gold / ES"*
- *"What's the current market structure on 15m?"*
- *"Give me a trade idea based on what you see on the chart"*

### Execute via CLI Tool:
```bash
python tools/chart_copilot.py --symbol BTC/USDT --timeframe 15m
```

### JSON Mode (for programmatic ingestion):
```bash
python tools/chart_copilot.py --symbol BTC/USDT --timeframe 15m --json
```

### Response Format:
1. **Regime & Trend Bias:** (e.g. Bullish order flow following MSS).
2. **Key Structural Levels:**
   - Nearest discount Bullish FVG or premium Bearish FVG.
   - Nearest Buyside Liquidity (BSL) or Sellside Liquidity (SSL) target.
3. **Actionable Trade Setup:**
   - **Direction:** Long or Short
   - **Entry Price:** Limit at the boundary of the unmitigated FVG.
   - **Invalidation (Stop Loss):** Placed strictly beyond the FVG or swing invalidation point.
   - **Target (Take Profit):** Resting opposing liquidity pool.
   - **Risk:Reward (R:R):** Exact mathematical ratio.
