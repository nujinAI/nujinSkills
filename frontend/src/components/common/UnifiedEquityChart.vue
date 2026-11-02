<template>
  <div class="w-full flex flex-col font-mono select-none" ref="containerRef">
    <!-- Header summary if enabled -->
    <div v-if="showHeader" class="flex flex-wrap items-center justify-between gap-2 mb-2 pb-2 border-b border-base-content/10">
      <div class="flex items-center gap-2">
        <span class="text-xs font-bold text-base-content/80 flex items-center gap-1.5">
          <TrendingUp class="w-3.5 h-3.5 text-primary" />
          {{ title || 'EQUITY TRAJECTORY' }}
        </span>
        <span v-if="tradesCount" class="badge badge-xs badge-neutral text-base-content/60 font-mono">
          {{ tradesCount }} trades
        </span>
      </div>

      <div class="flex items-center gap-3 text-xs">
        <div v-if="hoveredPoint" class="flex items-center gap-2 text-primary font-bold">
          <span>Point #{{ hoveredIndex + 1 }}:</span>
          <span>${{ formatNumber(hoveredPoint.equity) }}</span>
          <span :class="hoveredPoint.drawdown > 0 ? 'text-error' : 'text-success'">
            (-{{ (hoveredPoint.drawdown * 100).toFixed(1) }}% DD)
          </span>
        </div>
        <div v-else class="flex items-center gap-3">
          <span class="text-base-content/60">Net PnL:</span>
          <span :class="netPnl >= 0 ? 'text-success font-bold' : 'text-error font-bold'">
            {{ netPnl >= 0 ? '+' : '' }}${{ formatNumber(netPnl) }} ({{ netPnlPct.toFixed(1) }}%)
          </span>
          <span class="text-base-content/40">|</span>
          <span class="text-base-content/60">Max DD:</span>
          <span class="text-error font-bold">-{{ maxDdPct.toFixed(1) }}%</span>
        </div>
      </div>
    </div>

    <!-- Chart Canvas / SVG Container -->
    <div 
      class="relative w-full rounded-lg overflow-hidden bg-base-300/30 border border-base-content/5"
      :style="{ height: `${height}px` }"
      @mousemove="handleMouseMove"
      @mouseleave="hoveredPoint = null"
      @touchstart="handleTouch"
      @touchmove="handleTouch"
      @touchend="hoveredPoint = null"
    >
      <svg v-if="normalizedPoints.length > 1" class="w-full h-full" :viewBox="`0 0 ${svgWidth} ${svgHeight}`" preserveAspectRatio="none">
        <defs>
          <linearGradient id="equityGradSuccess" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#10b981" stop-opacity="0.25" />
            <stop offset="100%" stop-color="#10b981" stop-opacity="0.0" />
          </linearGradient>
          <linearGradient id="equityGradDanger" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#ef4444" stop-opacity="0.25" />
            <stop offset="100%" stop-color="#ef4444" stop-opacity="0.0" />
          </linearGradient>
        </defs>

        <!-- Horizontal Baseline Grid -->
        <line
          v-if="baselineY != null"
          x1="0"
          :y1="baselineY"
          :x2="svgWidth"
          :y2="baselineY"
          stroke="currentColor"
          stroke-dasharray="3 3"
          class="text-base-content/15"
          stroke-width="1"
        />

        <!-- Shaded Area Fill -->
        <polygon
          :points="areaPointsString"
          :fill="netPnl >= 0 ? 'url(#equityGradSuccess)' : 'url(#equityGradDanger)'"
        />

        <!-- Equity Line -->
        <polyline
          :points="linePointsString"
          fill="none"
          :stroke="netPnl >= 0 ? '#10b981' : '#ef4444'"
          stroke-width="2"
          stroke-linejoin="round"
          stroke-linecap="round"
        />

        <!-- Active Hover Crosshair -->
        <g v-if="hoveredPoint">
          <line
            :x1="hoveredPoint.x"
            y1="0"
            :x2="hoveredPoint.x"
            :y2="svgHeight"
            stroke="currentColor"
            class="text-primary/40"
            stroke-width="1"
            stroke-dasharray="2 2"
          />
          <circle
            :cx="hoveredPoint.x"
            :cy="hoveredPoint.y"
            r="4"
            class="fill-primary stroke-base-100"
            stroke-width="2"
          />
        </g>
      </svg>

      <!-- Empty State inside chart -->
      <div v-else class="w-full h-full flex items-center justify-center text-xs text-base-content/40">
        No equity curve points available yet
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { TrendingUp } from 'lucide-vue-next';

const props = withDefaults(
  defineProps<{
    equityCurve?: any[];
    initialBalance?: number;
    title?: string;
    height?: number;
    showHeader?: boolean;
  }>(),
  {
    equityCurve: () => [],
    initialBalance: 5000,
    title: '',
    height: 200,
    showHeader: true,
  }
);

const containerRef = ref<HTMLElement | null>(null);
const svgWidth = 600;
const svgHeight = 200;
const padding = { top: 15, bottom: 15 };

const hoveredPoint = ref<any | null>(null);
const hoveredIndex = ref<number>(-1);

const parsedCurve = computed(() => {
  const raw = props.equityCurve || [];
  if (!Array.isArray(raw) || raw.length === 0) return [];

  const points: { step: number; equity: number; drawdown?: number }[] = [];
  const base = props.initialBalance || 5000;
  let current = base;

  for (let i = 0; i < raw.length; i++) {
    const item = raw[i];
    if (typeof item === 'number') {
      points.push({ step: i, equity: item });
    } else if (item && typeof item === 'object') {
      if (item.equity != null) {
        points.push({ step: i, equity: Number(item.equity), drawdown: item.drawdown != null ? Number(item.drawdown) : undefined });
      } else if (item.equity_pct != null) {
        // Backend returns equity_pct starting at 100.0
        const eqVal = (base * Number(item.equity_pct)) / 100.0;
        const dd = item.drawdown_pct != null ? Number(item.drawdown_pct) / 100.0 : undefined;
        points.push({ step: i, equity: eqVal, drawdown: dd });
      } else if (item.balance != null) {
        points.push({ step: i, equity: Number(item.balance) });
      } else if (item.value != null) {
        points.push({ step: i, equity: Number(item.value) });
      } else if (item.pnl != null || item.pnl_pct != null) {
        const delta = Number(item.pnl || item.pnl_pct);
        current += delta;
        points.push({ step: i, equity: current });
      }
    }
  }

  // Prepend initial balance if first point is after trade 1
  if (points.length > 0 && points[0].equity !== props.initialBalance) {
    return [{ step: 0, equity: props.initialBalance }, ...points];
  }
  return points;
});

const tradesCount = computed(() => Math.max(0, parsedCurve.value.length - 1));

const netPnl = computed(() => {
  if (parsedCurve.value.length === 0) return 0;
  const start = parsedCurve.value[0].equity;
  const end = parsedCurve.value[parsedCurve.value.length - 1].equity;
  return end - start;
});

const netPnlPct = computed(() => {
  if (parsedCurve.value.length === 0) return 0;
  const start = parsedCurve.value[0].equity;
  return start !== 0 ? (netPnl.value / start) * 100 : 0;
});

const maxDdPct = computed(() => {
  if (parsedCurve.value.length === 0) return 0;
  let peak = -Infinity;
  let maxDd = 0;
  for (const p of parsedCurve.value) {
    if (p.equity > peak) peak = p.equity;
    const dd = peak > 0 ? (peak - p.equity) / peak : 0;
    if (dd > maxDd) maxDd = dd;
  }
  return maxDd * 100;
});

const normalizedPoints = computed(() => {
  const pts = parsedCurve.value;
  if (pts.length < 2) return [];

  let min = Infinity;
  let max = -Infinity;
  let peak = -Infinity;

  for (const p of pts) {
    if (p.equity < min) min = p.equity;
    if (p.equity > max) max = p.equity;
  }

  // Add slight margin so line doesn't clip
  const range = max - min || 1;
  const effectiveMin = min - range * 0.05;
  const effectiveMax = max + range * 0.05;
  const effectiveRange = effectiveMax - effectiveMin || 1;

  const innerH = svgHeight - padding.top - padding.bottom;

  return pts.map((p, idx) => {
    if (p.equity > peak) peak = p.equity;
    const drawdown = p.drawdown != null ? p.drawdown : (peak > 0 ? (peak - p.equity) / peak : 0);
    const x = (idx / (pts.length - 1)) * svgWidth;
    const normY = (p.equity - effectiveMin) / effectiveRange;
    const y = svgHeight - padding.bottom - normY * innerH;

    return {
      x,
      y,
      equity: p.equity,
      drawdown,
      idx,
    };
  });
});

const baselineY = computed(() => {
  const pts = parsedCurve.value;
  if (pts.length < 2) return null;
  let min = Infinity;
  let max = -Infinity;
  for (const p of pts) {
    if (p.equity < min) min = p.equity;
    if (p.equity > max) max = p.equity;
  }
  const range = max - min || 1;
  const effectiveMin = min - range * 0.05;
  const effectiveMax = max + range * 0.05;
  const innerH = svgHeight - padding.top - padding.bottom;
  const base = props.initialBalance;
  if (base < effectiveMin || base > effectiveMax) return null;
  const normY = (base - effectiveMin) / (effectiveMax - effectiveMin);
  return svgHeight - padding.bottom - normY * innerH;
});

const linePointsString = computed(() => {
  return normalizedPoints.value.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
});

const areaPointsString = computed(() => {
  const pts = normalizedPoints.value;
  if (pts.length === 0) return '';
  const first = pts[0];
  const last = pts[pts.length - 1];
  const bottomY = svgHeight;
  return `${first.x.toFixed(1)},${bottomY} ${linePointsString.value} ${last.x.toFixed(1)},${bottomY}`;
});

const handleMouseMove = (e: MouseEvent) => {
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
  const relX = (e.clientX - rect.left) / rect.width;
  resolveHoverFromFraction(relX);
};

const handleTouch = (e: TouchEvent) => {
  if (!e.touches[0]) return;
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
  const relX = (e.touches[0].clientX - rect.left) / rect.width;
  resolveHoverFromFraction(relX);
};

const resolveHoverFromFraction = (relX: number) => {
  const pts = normalizedPoints.value;
  if (pts.length === 0) return;
  const targetX = Math.max(0, Math.min(1, relX)) * svgWidth;
  let closest = pts[0];
  let minDiff = Infinity;
  for (const p of pts) {
    const diff = Math.abs(p.x - targetX);
    if (diff < minDiff) {
      minDiff = diff;
      closest = p;
    }
  }
  hoveredPoint.value = closest;
  hoveredIndex.value = closest.idx;
};

const formatNumber = (num?: number) => {
  if (num == null || isNaN(num)) return '0.00';
  return num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};
</script>
