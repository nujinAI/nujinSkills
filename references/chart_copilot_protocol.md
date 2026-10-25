# NujinAI Chart Copilot Protocol

The **Chart Copilot** enables NujinAI and the user to collaboratively inspect live charts, explore any quantitative hypothesis, and render dynamic indicator overlays, mathematical models, and trade ideas live on the chart canvas.

---

## 1. Core Operating Philosophy

1. **Zero Predefined Bias:**
   - The system does not assume, favor, or default to any single trading paradigm, methodology, or indicator set.
   - The canvas starts 100% clean (raw OHLCV candles).
   - What gets calculated and drawn is driven entirely by what the user requests or the specific quantitative hypothesis being tested.

2. **Limitless Analytical Palette:**
   - Any technical indicator (all 200+ TA-Lib indicators: EMAs, SMAs, MACD, RSI, Bollinger Bands, Keltner Channels, Ichimoku, ADX, ATR, etc.).
   - Volume & Order Flow metrics (Cumulative Volume Delta / CVD, Volume Profile, VWAP, Anchored VWAP, TWAP, OBV, CMF).
   - Statistical & Volatility metrics (Z-Score bands, Rolling Hurst, Historical Volatility, ATR envelopes, Donchian channels).
   - Structural & Price Action patterns (Swing pivots, Support/Resistance zones, Breakouts, Channels, Chart patterns, Imbalances).
   - Custom Mathematical Formulas (Arbitrary math evaluated on candle data, e.g., `(close - vwap) / atr_14`).

3. **Live, Interactive & Stateless Feedback:**
   - Operations occur live in real time over WebSockets:
     - When the user says *"clean"* / *"clear"*, the canvas clears immediately.
     - When the user asks to inspect specific indicators (e.g. *"overlay 20 EMA, 50 SMA, and RSI"*), the engine computes and renders them on the fly.
     - When the user asks for a trade thesis or pattern inspection, the engine formulates the exact math requested and renders relevant levels and setup projections.

```
                      ┌──────────────────────────────────────────────┐
                      │              User Prompt in Chat             │
                      │  ("Overlay VWAP + 20 EMA and check 15m BTC") │
                      └──────────────────────┬───────────────────────┘
                                             │
                                             ▼
                      ┌──────────────────────────────────────────────┐
                      │           tools/chart_copilot.py             │
                      │    (Universal TA-Lib & Quant Engine)         │
                      └──────────────────────┬───────────────────────┘
                                             │
                    ┌────────────────────────┴────────────────────────┐
                    ▼                                                 ▼
       [ Structured Brief in Chat ]                      [ Live WebSocket Visuals ]
       • User-Requested Metrics / Signals                • Dynamic Indicator Plots (Lines/Bands)
       • Market Context & Volatility                     • Key Price Levels / Anchors
       • Hypothesis Evaluation                           • Trade Setup Boxes (if requested)
```

---

## 2. Universal Visual Primitives

The visual rendering engine supports universal, lightweight primitives that adapt to any analytical requirement:

### 1. Dynamic Indicator Lines & Bands
- Overlay continuous series onto the main price chart (e.g. moving averages, VWAP, Bollinger Bands, trailing stops).
- Render sub-chart oscillators (e.g. RSI, MACD, Stochastics, Volume Delta).
- TradingView-style styling with configurable colors, line widths, and opacity.

### 2. Horizontal Rays & Price Levels
- Support and resistance levels, previous day/week highs and lows, session opens, pivot highs/lows, breakout triggers.
- Clean text badges positioned intelligently to avoid candle overlap.

### 3. Price Zones & Channels
- Value areas, consolidation ranges, channel bounds, volatility corridors, or imbalance regions.
- Rendered as translucent horizontal or diagonal boxes.

### 4. Interactive Position / Setup Projections
- When a trade idea is evaluated, an interactive setup box projects:
  - **Entry Level**
  - **Invalidation / Stop Loss**
  - **Profit Target(s)**
  - **Risk:Reward Ratio (R:R)**

---

## 3. Autonomous Tool Usage

When the user asks to analyze a chart, overlay indicators, or explore trade ideas, use the `tools/chart_copilot.py` CLI or the backend `/api/chart/copilot` endpoint.

### Common Usage Examples:

1. **Clear the Canvas:**
   ```bash
   .venv/bin/python tools/chart_copilot.py --symbol BTC/USDT --clear
   ```

2. **Inspect with Specific Indicators:**
   ```bash
   .venv/bin/python tools/chart_copilot.py --symbol BTC/USDT --timeframe 15m --indicators "ema_20,ema_50,rsi_14"
   ```

3. **Evaluate a Custom Formula:**
   ```bash
   .venv/bin/python tools/chart_copilot.py --symbol BTC/USDT --timeframe 15m --custom "(close - sma_50) / atr_14"
   ```

4. **Formulate a Trade Setup based on User's Strategy / Hypothesis:**
   ```bash
   .venv/bin/python tools/chart_copilot.py --symbol BTC/USDT --timeframe 15m --thesis "Mean reversion from lower Bollinger Band" --indicators "bbands_20_2,rsi_14"
   ```

5. **JSON Output for Programmatic Agent Ingestion:**
   ```bash
   .venv/bin/python tools/chart_copilot.py --symbol BTC/USDT --timeframe 15m --indicators "vwap,atr_14" --json
   ```

---

## 4. Response Guidelines

When responding to the user about chart analysis:
1. **Focus on what the user asked for:** Do not impose unrequested concepts or setups.
2. **State Empirical Values:** Quote the exact indicator values, volatility, and calculated price levels.
3. **Transparent Logic:** Clearly explain why levels or signals triggered according to the specific criteria requested.
4. **Actionable & Mathematical:** If presenting a trade idea, always provide exact numerical entry, invalidation, target, and risk-to-reward ratio.
