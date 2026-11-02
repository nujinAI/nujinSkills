<template>
  <div class="relative w-full h-full flex flex-col font-mono select-none overflow-hidden bg-base-100">
    <!-- Crosshair HUD Overlay Bar -->
    <div class="h-7 min-h-7 bg-base-200/60 border-b border-base-content/5 px-3 flex items-center justify-between text-[11px] text-base-content/70 font-mono z-10">
      <div v-if="hoveredBar" class="flex items-center gap-3 overflow-x-auto no-scrollbar">
        <span class="text-base-content/50">{{ hoveredBar.timeStr }}</span>
        <span>O: <strong class="text-base-content">{{ formatPrice(hoveredBar.open) }}</strong></span>
        <span>H: <strong class="text-base-content">{{ formatPrice(hoveredBar.high) }}</strong></span>
        <span>L: <strong class="text-base-content">{{ formatPrice(hoveredBar.low) }}</strong></span>
        <span>C: <strong :class="hoveredBar.close >= hoveredBar.open ? 'text-success' : 'text-error'">{{ formatPrice(hoveredBar.close) }}</strong></span>
        <span v-if="hoveredBar.volume">Vol: <strong class="text-base-content/90">{{ hoveredBar.volume.toLocaleString() }}</strong></span>
      </div>
      <div v-else-if="candles.length > 0" class="flex items-center gap-3 text-base-content/50">
        <span>Latest:</span>
        <span class="text-base-content font-bold">{{ formatPrice(candles[candles.length - 1].close) }}</span>
        <span>Bars: {{ candles.length }}</span>
      </div>
      <div v-else class="text-base-content/40">
        Waiting for stream candles...
      </div>
    </div>

    <!-- Chart Canvas Container -->
    <div class="relative flex-1 w-full h-full overflow-hidden" ref="chartContainerRef">
      <!-- Loading Spinner -->
      <div v-if="loading && candles.length === 0" class="absolute inset-0 flex items-center justify-center bg-base-100/70 backdrop-blur-xs z-30">
        <div class="flex items-center gap-2 text-primary font-bold text-xs bg-base-300 px-4 py-2 rounded-xl border border-base-content/10 shadow-lg">
          <span class="loading loading-spinner loading-sm" />
          <span>CONNECTING_MARKET_FEED...</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, shallowRef, computed, watch, onMounted, onUnmounted, nextTick } from 'vue';
import {
  createChart,
  ColorType,
  CrosshairMode,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type Time,
} from 'lightweight-charts';
import type { Candle } from '../../composables/useMarketData';
import type { SignalData } from '../../types';

const props = withDefaults(
  defineProps<{
    candles: Candle[];
    theme: 'dark' | 'light';
    loading?: boolean;
    signals?: SignalData[];
    targetedSignal?: SignalData | null;
  }>(),
  {
    loading: false,
    signals: () => [],
    targetedSignal: null,
  }
);

const chartContainerRef = ref<HTMLElement | null>(null);
const chart = shallowRef<IChartApi | null>(null);
const candleSeries = shallowRef<ISeriesApi<'Candlestick'> | null>(null);
const volumeSeries = shallowRef<ISeriesApi<'Histogram'> | null>(null);

const hoveredBar = ref<{
  timeStr: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
} | null>(null);

let resizeObserver: ResizeObserver | null = null;

const getThemeColors = (isDark: boolean) => ({
  bg: isDark ? '#0b0f17' : '#ffffff',
  text: isDark ? '#94a3b8' : '#475569',
  grid: isDark ? 'rgba(255, 255, 255, 0.04)' : 'rgba(0, 0, 0, 0.04)',
  border: isDark ? 'rgba(255, 255, 255, 0.08)' : 'rgba(0, 0, 0, 0.08)',
  crosshair: isDark ? '#38bdf8' : '#0284c7',
  upCandle: '#10b981',
  downCandle: '#ef4444',
  upVol: isDark ? 'rgba(16, 185, 129, 0.25)' : 'rgba(16, 185, 129, 0.35)',
  downVol: isDark ? 'rgba(239, 68, 68, 0.25)' : 'rgba(239, 68, 68, 0.35)',
});

const initChart = () => {
  if (!chartContainerRef.value) return;

  const isDark = props.theme === 'dark';
  const colors = getThemeColors(isDark);
  const containerW = chartContainerRef.value.clientWidth || 800;
  const containerH = chartContainerRef.value.clientHeight || 500;

  const instance = createChart(chartContainerRef.value, {
    width: containerW,
    height: containerH,
    layout: {
      background: { type: ColorType.Solid, color: colors.bg },
      textColor: colors.text,
      fontFamily: '"JetBrains Mono", ui-monospace, monospace',
      fontSize: 11,
    },
    grid: {
      vertLines: { color: colors.grid, style: LineStyle.Dotted },
      horzLines: { color: colors.grid, style: LineStyle.Dotted },
    },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: {
        color: colors.crosshair,
        width: 1,
        style: LineStyle.Dashed,
        labelBackgroundColor: colors.bg,
      },
      horzLine: {
        color: colors.crosshair,
        width: 1,
        style: LineStyle.Dashed,
        labelBackgroundColor: colors.bg,
      },
    },
    rightPriceScale: {
      borderColor: colors.border,
      scaleMargins: { top: 0.1, bottom: 0.2 },
    },
    timeScale: {
      borderColor: colors.border,
      timeVisible: true,
      secondsVisible: false,
    },
  });

  // 1. Candlestick series
  const candlesApi = instance.addCandlestickSeries({
    upColor: colors.upCandle,
    downColor: colors.downCandle,
    borderUpColor: colors.upCandle,
    borderDownColor: colors.downCandle,
    wickUpColor: colors.upCandle,
    wickDownColor: colors.downCandle,
  });

  // 2. Volume series
  const volumeApi = instance.addHistogramSeries({
    priceFormat: { type: 'volume' },
    priceScaleId: '',
  });

  volumeApi.priceScale().applyOptions({
    scaleMargins: { top: 0.8, bottom: 0 },
  });

  chart.value = instance;
  candleSeries.value = candlesApi;
  volumeSeries.value = volumeApi;

  // Crosshair move subscription
  instance.subscribeCrosshairMove((param) => {
    if (!param.time || !param.seriesData) {
      hoveredBar.value = null;
      return;
    }
    const barData = param.seriesData.get(candlesApi) as any;
    if (barData) {
      const volData = param.seriesData.get(volumeApi) as any;
      const t = Number(param.time);
      const date = new Date(t * 1000);
      const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', month: 'short', day: '2-digit' });
      hoveredBar.value = {
        timeStr,
        open: barData.open,
        high: barData.high,
        low: barData.low,
        close: barData.close,
        volume: volData?.value,
      };
    } else {
      hoveredBar.value = null;
    }
  });

  // Resize Observer
  resizeObserver = new ResizeObserver((entries) => {
    if (!entries || entries.length === 0) return;
    const { width, height } = entries[0].contentRect;
    if (width > 0 && height > 0) {
      instance.applyOptions({ width, height });
    }
  });
  resizeObserver.observe(chartContainerRef.value);

  updateData();
};

const updateData = () => {
  if (!candleSeries.value || !volumeSeries.value || props.candles.length === 0) return;

  const isDark = props.theme === 'dark';
  const colors = getThemeColors(isDark);

  const candleData = props.candles.map((c) => ({
    time: c.time as Time,
    open: c.open,
    high: c.high,
    low: c.low,
    close: c.close,
  }));

  const volData = props.candles.map((c) => ({
    time: c.time as Time,
    value: c.volume || 1,
    color: c.close >= c.open ? colors.upVol : colors.downVol,
  }));

  candleSeries.value.setData(candleData);
  volumeSeries.value.setData(volData);

  updateMarkers();
};

const updateMarkers = () => {
  if (!candleSeries.value) return;

  const markers: SeriesMarker<Time>[] = [];
  const signals = props.signals || [];

  for (const s of signals) {
    const rawTime = Number(s.time || (s as any).timestamp);
    if (!rawTime || isNaN(rawTime)) continue;
    const timeSec = rawTime > 1e11 ? Math.floor(rawTime / 1000) : rawTime;

    const action = (s.action || (s as any).side || '').toUpperCase();
    const isLong = action === 'BUY' || action === 'LONG';
    const isShort = action === 'SELL' || action === 'SHORT';

    if (isLong) {
      markers.push({
        time: timeSec as Time,
        position: 'belowBar',
        color: '#10b981',
        shape: 'arrowUp',
        text: `BUY @ ${s.price ? s.price.toFixed(1) : ''}`,
      });
    } else if (isShort) {
      markers.push({
        time: timeSec as Time,
        position: 'aboveBar',
        color: '#ef4444',
        shape: 'arrowDown',
        text: `SELL @ ${s.price ? s.price.toFixed(1) : ''}`,
      });
    }
  }

  // Sort markers by time ascending
  markers.sort((a, b) => Number(a.time) - Number(b.time));
  candleSeries.value.setMarkers(markers);
};

// Update colors when theme changes
watch(
  () => props.theme,
  (newTheme) => {
    if (!chart.value || !candleSeries.value || !volumeSeries.value) return;
    const isDark = newTheme === 'dark';
    const colors = getThemeColors(isDark);

    chart.value.applyOptions({
      layout: {
        background: { type: ColorType.Solid, color: colors.bg },
        textColor: colors.text,
      },
      grid: {
        vertLines: { color: colors.grid },
        horzLines: { color: colors.grid },
      },
      crosshair: {
        vertLine: { color: colors.crosshair, labelBackgroundColor: colors.bg },
        horzLine: { color: colors.crosshair, labelBackgroundColor: colors.bg },
      },
      rightPriceScale: { borderColor: colors.border },
      timeScale: { borderColor: colors.border },
    });

    candleSeries.value.applyOptions({
      upColor: colors.upCandle,
      downColor: colors.downCandle,
      borderUpColor: colors.upCandle,
      borderDownColor: colors.downCandle,
      wickUpColor: colors.upCandle,
      wickDownColor: colors.downCandle,
    });

    // Re-apply volume data colors
    updateData();
  }
);

watch(() => props.candles, () => {
  updateData();
}, { deep: true });

watch(() => props.signals, () => {
  updateMarkers();
}, { deep: true });

// Jump to inspected signal
watch(
  () => props.targetedSignal,
  (target) => {
    if (!target || !chart.value) return;
    const rawTime = Number(target.time || (target as any).timestamp);
    if (!rawTime) return;
    const timeSec = rawTime > 1e11 ? Math.floor(rawTime / 1000) : rawTime;
    chart.value.timeScale().scrollToPosition(-10, true);
  }
);

const fitContent = () => {
  chart.value?.timeScale().fitContent();
};

const jumpToLatest = () => {
  chart.value?.timeScale().scrollToRealTime();
};

const formatPrice = (p?: number) => {
  if (p == null || isNaN(p)) return '-';
  return p.toFixed(2);
};

defineExpose({
  fitContent,
  jumpToLatest,
});

onMounted(() => {
  nextTick(() => {
    initChart();
  });
});

onUnmounted(() => {
  if (resizeObserver) {
    resizeObserver.disconnect();
    resizeObserver = null;
  }
  if (chart.value) {
    chart.value.remove();
    chart.value = null;
  }
});
</script>
