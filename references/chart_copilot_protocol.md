# Chart Copilot Guide

This guide instructs the AI on how to interact with the interactive chart canvas and handle user requests for market analysis, indicator overlays, and trade ideas.

---

## Operating Instructions

1. **Follow the User's Request Directly:**
   - Compute and render whatever indicators, metrics, or market concepts the user asks for.
   - If the user asks for specific indicators (e.g., Moving Averages, RSI, Bollinger Bands, VWAP, Order Flow), compute and plot those indicators.
   - If the user asks for a trade idea or setup, formulate it using the metrics or criteria they specify.
   - If the user asks to clear or clean the chart, clear the canvas immediately.

2. **Keep the Canvas Clean by Default:**
   - Raw candles are shown by default.
   - Overlays and markup are only drawn when requested.

3. **Live WebSocket Execution:**
   - All chart updates are sent over WebSockets in real time without reloading the page.

---

## Tool Usage (`tools/chart_copilot.py`)

Run commands with `.venv/bin/python tools/chart_copilot.py`:

- **Clear the Canvas:**
  ```bash
  .venv/bin/python tools/chart_copilot.py --symbol BTC/USDT --clear
  ```

- **Overlay Indicators:**
  ```bash
  .venv/bin/python tools/chart_copilot.py --symbol BTC/USDT --timeframe 15m --indicators "ema_20,ema_50,rsi_14"
  ```

- **Evaluate Custom Formulas:**
  ```bash
  .venv/bin/python tools/chart_copilot.py --symbol BTC/USDT --timeframe 15m --custom "(close - sma_50) / atr_14"
  ```

- **Formulate a Trade Setup / Thesis:**
  ```bash
  .venv/bin/python tools/chart_copilot.py --symbol BTC/USDT --timeframe 15m --thesis "<user's thesis or strategy>" --indicators "<indicators requested>"
  ```

- **Programmatic JSON Mode:**
  ```bash
  .venv/bin/python tools/chart_copilot.py --symbol BTC/USDT --timeframe 15m --indicators "ema_20,rsi_14" --json
  ```

---

## Response Guidelines

- **Direct & Actionable:** Answer specifically what the user asked for.
- **Empirical:** Cite exact price levels, indicator values, and calculated targets/stops.
- **Adaptive:** Adapt to any style, indicator, or concept requested without forcing or assuming any specific framework.
