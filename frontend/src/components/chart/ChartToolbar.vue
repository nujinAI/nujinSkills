<template>
  <div class="w-full bg-base-200/90 border-b border-base-content/10 px-3 py-2 flex flex-wrap items-center justify-between gap-2 text-xs font-mono select-none">
    <!-- Left: Symbol Selector & Timeframe Pills -->
    <div class="flex items-center gap-2 flex-wrap">
      <!-- Symbol Dropdown -->
      <div class="dropdown">
        <div tabindex="0" role="button" class="btn btn-xs btn-neutral gap-1.5 font-bold font-mono">
          <span>{{ currentSymbolDisplay }}</span>
          <ChevronDown class="w-3 h-3 opacity-60" />
        </div>
        <ul tabindex="0" class="dropdown-content menu p-1 shadow-lg bg-base-300 rounded-box w-36 border border-base-content/10 z-50 text-xs">
          <li v-for="sym in availableSymbols" :key="sym.id">
            <button 
              @click="$emit('selectSymbol', sym.id)" 
              :class="{ 'active font-bold text-primary': currentSymbol === sym.id }"
            >
              {{ sym.label }}
            </button>
          </li>
        </ul>
      </div>

      <!-- Timeframe Segmented Control -->
      <div class="join border border-base-content/10 rounded-lg overflow-hidden bg-base-300/60">
        <button
          v-for="tf in availableTimeframes"
          :key="tf"
          @click="$emit('selectTimeframe', tf)"
          class="btn btn-xs join-item px-2 font-mono text-[11px]"
          :class="currentTimeframe === tf ? 'btn-primary text-primary-content font-bold' : 'btn-ghost text-base-content/70 hover:text-base-content'"
        >
          {{ tf }}
        </button>
      </div>

      <!-- Strategy Inspector Filter -->
      <div v-if="strategies.length > 0" class="dropdown hidden sm:inline-block">
        <div tabindex="0" role="button" class="btn btn-xs btn-ghost border border-base-content/10 gap-1.5 font-mono text-[11px] max-w-[180px] truncate">
          <Sliders class="w-3 h-3 text-secondary" />
          <span class="truncate">{{ cleanStrategyName || 'All Strategies' }}</span>
        </div>
        <ul tabindex="0" class="dropdown-content menu p-1 shadow-lg bg-base-300 rounded-box w-64 border border-base-content/10 z-50 text-xs max-h-60 overflow-y-auto">
          <li v-for="strat in strategies" :key="strat.name">
            <button 
              @click="$emit('selectStrategy', strat.name)"
              :class="{ 'active font-bold text-secondary': selectedStrategy === strat.name }"
              class="truncate text-left"
            >
              {{ strat.display_name || strat.name.replace('.py', '') }}
            </button>
          </li>
        </ul>
      </div>
    </div>

    <!-- Right: Live Quote, Price Change & Viewport Controls -->
    <div class="flex items-center gap-2.5 ml-auto">
      <!-- Live Price Flash -->
      <div class="flex items-baseline gap-2 px-2.5 py-1 rounded-lg bg-base-300/80 border border-base-content/10">
        <span class="text-sm md:text-base font-bold font-mono tracking-tight" :class="priceColorClass">
          ${{ formattedPrice }}
        </span>
        <span 
          v-if="priceStats.changePct != null" 
          class="text-[10px] font-mono font-semibold"
          :class="priceStats.change >= 0 ? 'text-success' : 'text-error'"
        >
          {{ priceStats.change >= 0 ? '+' : '' }}{{ priceStats.changePct.toFixed(2) }}%
        </span>
      </div>

      <!-- Jump to Latest / Reset Fit Buttons -->
      <button 
        @click="$emit('fitContent')"
        class="btn btn-xs btn-ghost border border-base-content/10 text-[10px] font-mono hover:text-base-content"
        title="Auto Fit Chart to Window"
      >
        <Maximize2 class="w-3 h-3 mr-1" />
        <span class="hidden md:inline">Fit</span>
      </button>

      <button 
        @click="$emit('jumpToLatest')"
        class="btn btn-xs btn-primary text-primary-content font-bold font-mono text-[10px]"
        title="Scroll to Real-Time Candle"
      >
        <FastForward class="w-3 h-3 mr-1" />
        <span>Live</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { ChevronDown, Sliders, Maximize2, FastForward } from 'lucide-vue-next';

const props = defineProps<{
  currentSymbol: string;
  currentTimeframe: string;
  availableSymbols: Array<{ id: string; label: string; display: string }>;
  availableTimeframes: string[];
  lastPrice: number | null;
  priceStats: { change: number; changePct: number; high24: number; low24: number };
  strategies: any[];
  selectedStrategy: string;
}>();

defineEmits<{
  (e: 'selectSymbol', sym: string): void;
  (e: 'selectTimeframe', tf: string): void;
  (e: 'selectStrategy', strat: string): void;
  (e: 'fitContent'): void;
  (e: 'jumpToLatest'): void;
}>();

const currentSymbolDisplay = computed(() => {
  const match = props.availableSymbols.find((s) => s.id === props.currentSymbol);
  return match ? match.label : props.currentSymbol;
});

const cleanStrategyName = computed(() => {
  return (props.selectedStrategy || '').replace('.py', '');
});

const formattedPrice = computed(() => {
  if (props.lastPrice == null || isNaN(props.lastPrice)) return '---.--';
  const isGold = props.currentSymbol.includes('XAU');
  return isGold ? props.lastPrice.toFixed(2) : props.lastPrice.toFixed(1);
});

const priceColorClass = computed(() => {
  if (props.priceStats.change > 0) return 'text-success';
  if (props.priceStats.change < 0) return 'text-error';
  return 'text-base-content';
});
</script>
