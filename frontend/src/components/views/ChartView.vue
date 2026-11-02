<template>
  <div class="w-full h-full flex flex-col overflow-hidden bg-base-100">
    <!-- Toolbar -->
    <ChartToolbar
      :currentSymbol="currentSymbol"
      :currentTimeframe="currentTimeframe"
      :availableSymbols="availableSymbols"
      :availableTimeframes="availableTimeframes"
      :lastPrice="lastPrice"
      :priceStats="priceStats"
      :strategies="strategies"
      :selectedStrategy="selectedStrategy"
      @selectSymbol="handleSelectSymbol"
      @selectTimeframe="handleSelectTimeframe"
      @selectStrategy="handleSelectStrategy"
      @fitContent="handleFitContent"
      @jumpToLatest="handleJumpToLatest"
    />

    <!-- TradingView Main Canvas -->
    <div class="flex-1 w-full relative overflow-hidden">
      <TvChart
        ref="tvChartRef"
        :candles="candles"
        :theme="activeTheme"
        :loading="loadingCandles"
        :signals="signalsForChart"
        :targetedSignal="targetedSignal"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import ChartToolbar from '../chart/ChartToolbar.vue';
import TvChart from '../chart/TvChart.vue';
import { useMarketData } from '../../composables/useMarketData';
import { useStrategies, deduplicateStrategies, formatStrategyTitle } from '../../composables/useStrategies';
import { useSignals } from '../../composables/useSignals';
import { useTheme } from '../../composables/useTheme';

const tvChartRef = ref<InstanceType<typeof TvChart> | null>(null);

const {
  currentSymbol,
  currentTimeframe,
  availableSymbols,
  availableTimeframes,
  candles,
  loadingCandles,
  lastPrice,
  priceStats,
  loadCandles,
} = useMarketData();

const { managedStrategies, selectedStrategy, selectStrategy } = useStrategies();
const { signals, targetedSignal } = useSignals();
const { activeTheme } = useTheme();

const strategies = computed(() => {
  return deduplicateStrategies(managedStrategies.value).map((s) => ({
    name: s.file || `${s.name}.py`,
    display_name: formatStrategyTitle(s),
    symbol: s.symbol,
  }));
});

const signalsForChart = computed(() => {
  if (!selectedStrategy.value) return signals.value;
  const clean = selectedStrategy.value.replace('.py', '').toLowerCase();
  return signals.value.filter((s) => {
    const strat = (s.strategy || (s as any).strategy_name || '').toLowerCase();
    return !strat || strat.includes(clean) || clean.includes(strat);
  });
});

const handleSelectSymbol = (sym: string) => {
  loadCandles(sym, currentTimeframe.value);
};

const handleSelectTimeframe = (tf: string) => {
  loadCandles(currentSymbol.value, tf);
};

const handleSelectStrategy = (strat: string) => {
  selectStrategy(strat);
};

const handleFitContent = () => {
  tvChartRef.value?.fitContent();
};

const handleJumpToLatest = () => {
  tvChartRef.value?.jumpToLatest();
};

onMounted(() => {
  loadCandles();
});
</script>
