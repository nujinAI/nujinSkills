import { ref, computed, watch } from 'vue';
import { useWebSocket } from './useWebSocket';

export interface Candle {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

const currentSymbol = ref<string>('XAUUSD');
const currentTimeframe = ref<string>('15m');
const candles = ref<Candle[]>([]);
const loadingCandles = ref<boolean>(false);
const lastPrice = ref<number | null>(null);

export function useMarketData() {
  const { latestMarketTick } = useWebSocket();

  const availableSymbols = [
    { id: 'XAUUSD', label: 'XAU/USD', display: 'Gold' },
    { id: 'SP500', label: 'S&P 500', display: 'US 500' },
    { id: 'BTCUSDT', label: 'BTC/USDT', display: 'Bitcoin' },
  ];

  const availableTimeframes = ['1m', '5m', '15m', '1h', '1d'];

  const loadCandles = async (sym?: string, tf?: string, count: number = 2000) => {
    const s = sym || currentSymbol.value;
    const t = tf || currentTimeframe.value;
    currentSymbol.value = s;
    currentTimeframe.value = t;

    loadingCandles.value = true;
    try {
      const url = `/api/candles?symbol=${encodeURIComponent(s)}&timeframe=${encodeURIComponent(t)}&count=${count}&mode=live`;
      const res = await fetch(url);
      if (res.ok) {
        const json = await res.json();
        const raw = json.data || [];
        // Format, sanitize and deduplicate sorted by timestamp
        const seen = new Set<number>();
        const formatted: Candle[] = [];

        for (const c of raw) {
          const rawTime = Number(c.time || c.timestamp);
          if (!rawTime || isNaN(rawTime)) continue;
          // Ensure time is in seconds
          const timeSec = rawTime > 1e11 ? Math.floor(rawTime / 1000) : rawTime;
          if (seen.has(timeSec)) continue;
          seen.add(timeSec);

          formatted.push({
            time: timeSec,
            open: Number(c.open),
            high: Number(c.high),
            low: Number(c.low),
            close: Number(c.close),
            volume: c.volume != null ? Number(c.volume) : 0,
          });
        }

        formatted.sort((a, b) => a.time - b.time);
        candles.value = formatted;

        if (formatted.length > 0) {
          lastPrice.value = formatted[formatted.length - 1].close;
        }
      }
    } catch (e) {
      console.error('[useMarketData] Failed to load candles:', e);
    } finally {
      loadingCandles.value = false;
    }
  };

  // Sync real-time ticks from WebSocket
  watch(latestMarketTick, (tick) => {
    if (!tick) return;
    const tickSym = (tick.symbol || '').replace(/[^a-zA-Z0-9]/g, '').toUpperCase();
    const activeSym = currentSymbol.value.replace(/[^a-zA-Z0-9]/g, '').toUpperCase();

    if (tickSym && (tickSym === activeSym || tickSym.includes(activeSym) || activeSym.includes(tickSym))) {
      if (tick.price != null) {
        lastPrice.value = tick.price;
      }
      if (tick.candle && candles.value.length > 0) {
        const rawTickTime = Number(tick.candle.time || (tick.candle as any).timestamp);
        const tickTimeSec = rawTickTime > 1e11 ? Math.floor(rawTickTime / 1000) : rawTickTime;
        const lastCandle = candles.value[candles.value.length - 1];

        if (lastCandle && lastCandle.time === tickTimeSec) {
          // Update current active bar
          lastCandle.high = Math.max(lastCandle.high, tick.candle.high);
          lastCandle.low = Math.min(lastCandle.low, tick.candle.low);
          lastCandle.close = tick.candle.close;
          if (tick.candle.volume != null) {
            lastCandle.volume = tick.candle.volume;
          }
        } else if (lastCandle && tickTimeSec > lastCandle.time) {
          // Append new bar
          candles.value.push({
            time: tickTimeSec,
            open: tick.candle.open,
            high: tick.candle.high,
            low: tick.candle.low,
            close: tick.candle.close,
            volume: tick.candle.volume || 0,
          });
        }
      }
    }
  });

  const priceStats = computed(() => {
    if (candles.value.length < 2) {
      return { change: 0, changePct: 0, high24: 0, low24: 0 };
    }
    const current = lastPrice.value || candles.value[candles.value.length - 1].close;
    const first = candles.value[0].close;
    const change = current - first;
    const changePct = first !== 0 ? (change / first) * 100 : 0;

    let high = -Infinity;
    let low = Infinity;
    for (const c of candles.value) {
      if (c.high > high) high = c.high;
      if (c.low < low) low = c.low;
    }

    return {
      current,
      change,
      changePct,
      high24: high,
      low24: low,
    };
  });

  return {
    currentSymbol,
    currentTimeframe,
    availableSymbols,
    availableTimeframes,
    candles,
    loadingCandles,
    lastPrice,
    priceStats,
    loadCandles,
  };
}
