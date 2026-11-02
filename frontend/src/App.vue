<template>
  <div 
    class="w-screen h-[100dvh] flex flex-col overflow-hidden bg-base-100 text-base-content transition-colors duration-200 select-none font-sans"
    :data-theme="activeTheme"
  >
    <!-- Top Global App Navbar -->
    <AppNavbar
      :activeScreen="activeScreen"
      :isConnected="isConnected"
      :activeBots="activeBots"
      :isSafe="isSafe"
      :remainingBudget="remainingBudget"
      @navigate="handleNavigate"
    />

    <!-- Main Screens Viewports (v-show keeps chart canvas & WebSocket state alive) -->
    
    <!-- F1 — TradingView Live Candlestick & Volume Chart -->
    <main class="w-full flex-1 relative overflow-hidden pb-14 lg:pb-0" v-show="activeScreen === 'CHART'">
      <ChartView />
    </main>

    <!-- F2 — Real-Time Signal Stream & Open Positions -->
    <main class="w-full flex-1 overflow-hidden pb-14 lg:pb-0" v-show="activeScreen === 'SIGNALS'">
      <SignalsView @inspectSignal="handleInspectSignal" />
    </main>

    <!-- F3 — Quantitative Backtest & Cynic Falsification Deck -->
    <main class="w-full flex-1 overflow-hidden pb-14 lg:pb-0" v-show="activeScreen === 'BACKTEST'">
      <BacktestView />
    </main>

    <!-- F4 — Strategy Lifecycle & Quantitative Alpha Universe -->
    <main class="w-full flex-1 overflow-hidden pb-14 lg:pb-0" v-show="activeScreen === 'STRATEGIES'">
      <StrategiesView
        @navigateToChart="handleNavigateToChart"
        @navigateToBacktest="handleNavigateToBacktest"
      />
    </main>

    <!-- F5 — Broker Risk & Prop Firm Circuit Breaker Deck -->
    <main class="w-full flex-1 overflow-hidden pb-14 lg:pb-0" v-show="activeScreen === 'RISK'">
      <AccountRiskView />
    </main>

    <!-- Mobile-First Bottom Navigation Bar (Hidden on Desktop) -->
    <MobileBottomNav
      :activeScreen="activeScreen"
      :activePositionsCount="activePositions.length"
      :activeBotsCount="activeBots.length"
      @navigate="handleNavigate"
    />

    <!-- Real-Time Discovered Strategy Toast Alert -->
    <transition
      enter-active-class="transform transition ease-out duration-300"
      enter-from-class="translate-y-4 opacity-0 scale-95"
      enter-to-class="translate-y-0 opacity-100 scale-100"
      leave-active-class="transition ease-in duration-200"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="activeToast" class="fixed bottom-16 lg:bottom-4 right-4 z-50 max-w-sm">
        <div class="alert alert-info shadow-2xl border border-info/40 backdrop-blur-md bg-base-300/95 flex items-center justify-between gap-3 text-xs rounded-xl">
          <div class="flex items-center gap-2.5 overflow-hidden">
            <Sparkles class="w-5 h-5 text-info shrink-0 animate-bounce" />
            <div class="truncate">
              <div class="font-bold flex items-center gap-1.5 text-base-content">
                <span>New Strategy Discovered!</span>
                <span class="badge badge-xs badge-info font-mono">{{ activeToast.timeframe || '15m' }}</span>
              </div>
              <div class="text-[11px] font-mono text-base-content/80 truncate">
                {{ activeToast.display_name || activeToast.strategy }}
              </div>
            </div>
          </div>
          <div class="flex items-center gap-1.5 shrink-0">
            <button 
              @click="inspectDiscovered(activeToast.file || activeToast.strategy)"
              class="btn btn-xs btn-primary font-bold font-mono"
            >
              Inspect
            </button>
            <button 
              @click="activeToast = null"
              class="btn btn-xs btn-ghost btn-circle text-base-content/60 hover:text-base-content"
            >
              ✕
            </button>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted } from 'vue';
import { Sparkles } from 'lucide-vue-next';
import AppNavbar from './components/navigation/AppNavbar.vue';
import MobileBottomNav from './components/navigation/MobileBottomNav.vue';
import ChartView from './components/views/ChartView.vue';
import SignalsView from './components/views/SignalsView.vue';
import BacktestView from './components/views/BacktestView.vue';
import StrategiesView from './components/views/StrategiesView.vue';
import AccountRiskView from './components/views/AccountRiskView.vue';

import { useTheme } from './composables/useTheme';
import { useWebSocket } from './composables/useWebSocket';
import { useStrategies } from './composables/useStrategies';
import { useSignals } from './composables/useSignals';
import { useRiskStatus } from './composables/useRiskStatus';
import type { SignalData } from './types';

type ScreenType = 'CHART' | 'SIGNALS' | 'BACKTEST' | 'STRATEGIES' | 'RISK';

const activeScreen = ref<ScreenType>('CHART');

const { activeTheme } = useTheme();
const { isConnected, latestDiscoveredStrategy } = useWebSocket();
const { activeBots, pollStrategies, selectStrategy } = useStrategies();
const { activePositions, fetchSignals, inspectSignal } = useSignals();
const { isSafe, remainingBudget, fetchRiskData } = useRiskStatus();

const activeToast = ref<any>(null);
let toastTimer: any = null;

const handleNavigate = (screen: string) => {
  activeScreen.value = screen as ScreenType;
};

const handleInspectSignal = (sig: SignalData) => {
  if (sig.strategy) {
    const clean = sig.strategy.replace('Strategy', '');
    selectStrategy(clean);
  }
  inspectSignal(sig);
  activeScreen.value = 'CHART';
};

const handleNavigateToChart = (strat: string) => {
  selectStrategy(strat);
  activeScreen.value = 'CHART';
};

const handleNavigateToBacktest = (strat: string) => {
  selectStrategy(strat);
  activeScreen.value = 'BACKTEST';
};

const inspectDiscovered = (strat: string) => {
  selectStrategy(strat);
  activeScreen.value = 'STRATEGIES';
  activeToast.value = null;
};

// Toast notification for newly discovered strategies
watch(latestDiscoveredStrategy, (discovered) => {
  if (discovered) {
    activeToast.value = discovered;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      activeToast.value = null;
    }, 8000);
  }
});

// Global Hotkeys: F1-F5 & Ctrl+Space
const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'F1') {
    e.preventDefault();
    activeScreen.value = 'CHART';
  } else if (e.key === 'F2') {
    e.preventDefault();
    activeScreen.value = 'SIGNALS';
  } else if (e.key === 'F3') {
    e.preventDefault();
    activeScreen.value = 'BACKTEST';
  } else if (e.key === 'F4') {
    e.preventDefault();
    activeScreen.value = 'STRATEGIES';
  } else if (e.key === 'F5') {
    e.preventDefault();
    activeScreen.value = 'RISK';
  } else if (e.key === ' ' && e.ctrlKey) {
    e.preventDefault();
    const screens: ScreenType[] = ['CHART', 'SIGNALS', 'BACKTEST', 'STRATEGIES', 'RISK'];
    const curIdx = screens.indexOf(activeScreen.value);
    activeScreen.value = screens[(curIdx + 1) % screens.length];
  }
};

let syncInterval: any = null;

onMounted(() => {
  window.addEventListener('keydown', handleKeyDown);

  // Initial data hydration
  pollStrategies();
  fetchSignals();
  fetchRiskData();

  // Periodic safety sync (every 30s)
  syncInterval = setInterval(() => {
    if (!isConnected.value) {
      pollStrategies();
      fetchSignals();
      fetchRiskData();
    }
  }, 30000);
});

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeyDown);
  if (syncInterval) clearInterval(syncInterval);
  if (toastTimer) clearTimeout(toastTimer);
});
</script>
