<template>
  <header class="navbar min-h-12 h-12 bg-base-200/90 backdrop-blur-md border-b border-base-content/10 px-3 md:px-4 flex items-center justify-between text-xs font-mono select-none z-40 transition-colors">
    <!-- Left Section: Logo, Connection Status, Active Bots Badge -->
    <div class="flex items-center gap-2 md:gap-3 overflow-hidden">
      <div class="flex items-center gap-2 font-bold tracking-wider text-base-content shrink-0">
        <div class="w-6 h-6 rounded-lg bg-primary/20 border border-primary/40 flex items-center justify-center text-primary">
          <Terminal class="w-3.5 h-3.5" />
        </div>
        <span class="font-bold tracking-tight text-sm hidden sm:inline">NUJIN<span class="text-primary font-normal">_OS</span></span>
      </div>

      <!-- WebSocket Online / Offline Pill -->
      <div 
        class="badge badge-sm gap-1.5 py-2 px-2 font-semibold border-base-content/10 bg-base-300 shrink-0"
        :title="isConnected ? 'Real-Time Telemetry Stream Connected' : 'Disconnected, attempting auto-reconnect...'"
      >
        <span class="w-1.5 h-1.5 rounded-full" :class="isConnected ? 'bg-success animate-ping' : 'bg-warning'" />
        <span :class="isConnected ? 'text-success font-bold' : 'text-warning text-[10px]'">
          {{ isConnected ? 'LIVE' : 'SYNCING' }}
        </span>
      </div>

      <!-- Active Strategies Pill -->
      <div 
        v-if="activeBots.length > 0"
        class="badge badge-sm badge-success badge-outline bg-success/10 gap-1.5 py-2 px-2 text-[10px] hidden sm:flex shrink-0 cursor-pointer"
        @click="$emit('navigate', 'STRATEGIES')"
        :title="`Active Native Runners: ${activeBots.join(', ')}`"
      >
        <Activity class="w-3 h-3 text-success animate-pulse" />
        <span class="font-bold">{{ activeBots.length }} Active</span>
        <span class="opacity-75 hidden xl:inline truncate max-w-[120px]">
          ({{ activeBots[0] }}{{ activeBots.length > 1 ? ` +${activeBots.length - 1}` : '' }})
        </span>
      </div>

      <!-- Risk Safe Budget Pill -->
      <div 
        class="badge badge-sm gap-1 py-2 px-2 text-[10px] hidden md:flex shrink-0 cursor-pointer border"
        :class="isSafe ? 'badge-neutral bg-base-300 text-base-content/80' : 'badge-error bg-error/10 text-error border-error/40'"
        @click="$emit('navigate', 'RISK')"
        :title="`Remaining Daily Loss Budget: $${remainingBudget.toFixed(2)}`"
      >
        <ShieldCheck class="w-3 h-3" :class="isSafe ? 'text-success' : 'text-error'" />
        <span class="opacity-70">Budget:</span>
        <span class="font-bold font-mono">${{ remainingBudget.toFixed(0) }}</span>
      </div>
    </div>

    <!-- Center Section: Desktop Pill Navigation (Hidden on Mobile) -->
    <div class="hidden lg:flex items-center gap-1 bg-base-300/80 p-0.5 rounded-lg border border-base-content/10">
      <button
        v-for="tab in navTabs"
        :key="tab.id"
        @click="$emit('navigate', tab.id)"
        class="px-2.5 py-1 rounded-md text-xs font-mono font-medium transition-all flex items-center gap-1.5"
        :class="activeScreen === tab.id ? 'bg-primary text-primary-content font-bold shadow-xs' : 'text-base-content/70 hover:text-base-content hover:bg-base-200'"
      >
        <component :is="tab.icon" class="w-3.5 h-3.5" />
        <span>{{ tab.label }}</span>
        <span class="text-[9px] opacity-60">({{ tab.hotkey }})</span>
      </button>
    </div>

    <!-- Right Section: Audio, Theme Switcher, Clock -->
    <div class="flex items-center gap-1.5 md:gap-2 shrink-0">
      <!-- PWA Install Button -->
      <button
        v-if="isInstallable"
        @click="installPwa"
        class="btn btn-xs btn-primary gap-1 font-bold shadow-sm animate-pulse text-[11px]"
        title="Install NujinAI as a Progressive Web App (PWA)"
      >
        <Download class="w-3.5 h-3.5" />
        <span class="hidden sm:inline">Install PWA</span>
      </button>

      <!-- PWA Active Badge -->
      <div
        v-else-if="isStandalone"
        class="badge badge-xs badge-ghost border-primary/30 text-primary font-mono text-[9px] px-1.5 py-1 hidden sm:flex items-center gap-1"
        title="Running in Standalone PWA Mode"
      >
        <Smartphone class="w-3 h-3" />
        <span>PWA</span>
      </div>

      <!-- Local Clock (CET) -->
      <div class="hidden xl:flex items-center gap-1.5 px-2 py-1 rounded bg-base-300 border border-base-content/10 text-[11px] text-base-content/80">
        <Clock class="w-3.5 h-3.5 text-accent" />
        <span class="font-bold font-mono text-success">{{ localTimeStr }}</span>
      </div>

      <!-- Audio Alert Toggle -->
      <div class="join border border-base-content/10 rounded-lg overflow-hidden bg-base-300">
        <button
          @click="toggleSound"
          class="btn btn-xs btn-ghost join-item px-2 text-[10px] font-bold"
          :class="soundEnabled ? 'text-success' : 'text-base-content/40'"
          :title="soundEnabled ? 'Audio Chimes Active (Click to mute)' : 'Audio Muted (Click to unmute)'"
        >
          <Volume2 v-if="soundEnabled" class="w-3.5 h-3.5 text-success" />
          <VolumeX v-else class="w-3.5 h-3.5 text-base-content/40" />
        </button>
        <button
          @click="testTone"
          class="btn btn-xs btn-ghost join-item border-l border-base-content/10 px-1.5 text-[9px] text-base-content/60 hover:text-base-content uppercase font-bold hidden sm:inline-flex"
          title="Preview Signal Tone"
        >
          Test
        </button>
      </div>

      <!-- Theme Switcher Dropdown (Auto / Dark / Light) -->
      <div class="dropdown dropdown-end">
        <div 
          tabindex="0" 
          role="button" 
          class="btn btn-xs btn-circle btn-ghost border border-base-content/10"
          :title="`Theme: ${themeMode.toUpperCase()} (Click to change)`"
        >
          <Monitor v-if="themeMode === 'auto'" class="w-3.5 h-3.5 text-primary" />
          <Moon v-else-if="themeMode === 'dark'" class="w-3.5 h-3.5 text-secondary" />
          <Sun v-else class="w-3.5 h-3.5 text-warning" />
        </div>
        <ul tabindex="0" class="dropdown-content menu p-1 shadow-xl bg-base-300 rounded-box w-32 border border-base-content/10 text-xs z-50 mt-1">
          <li>
            <button @click="setThemeMode('auto')" :class="{ 'active font-bold text-primary': themeMode === 'auto' }">
              <Monitor class="w-3.5 h-3.5" /> Auto (OS)
            </button>
          </li>
          <li>
            <button @click="setThemeMode('dark')" :class="{ 'active font-bold text-secondary': themeMode === 'dark' }">
              <Moon class="w-3.5 h-3.5" /> Dark
            </button>
          </li>
          <li>
            <button @click="setThemeMode('light')" :class="{ 'active font-bold text-warning': themeMode === 'light' }">
              <Sun class="w-3.5 h-3.5" /> Light
            </button>
          </li>
        </ul>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';
import {
  Terminal,
  Activity,
  ShieldCheck,
  BarChart2,
  Send,
  Sliders,
  Layers,
  Clock,
  Volume2,
  VolumeX,
  Sun,
  Moon,
  Monitor,
  Download,
  Smartphone,
} from 'lucide-vue-next';
import { useTheme } from '../../composables/useTheme';
import { useAudio } from '../../composables/useAudio';
import { usePwa } from '../../composables/usePwa';

defineProps<{
  activeScreen: string;
  isConnected: boolean;
  activeBots: string[];
  isSafe: boolean;
  remainingBudget: number;
}>();

defineEmits<{
  (e: 'navigate', screen: string): void;
}>();

const { themeMode, setThemeMode } = useTheme();
const { soundEnabled, toggleSound, testTone } = useAudio();
const { isInstallable, isStandalone, installPwa } = usePwa();

const navTabs = [
  { id: 'CHART', label: 'Chart', icon: BarChart2, hotkey: 'F1' },
  { id: 'SIGNALS', label: 'Signals', icon: Send, hotkey: 'F2' },
  { id: 'BACKTEST', label: 'Backtest', icon: Sliders, hotkey: 'F3' },
  { id: 'STRATEGIES', label: 'Strategies', icon: Layers, hotkey: 'F4' },
  { id: 'RISK', label: 'Risk & Accounts', icon: ShieldCheck, hotkey: 'F5' },
];

const localTimeStr = ref<string>('');
let timeInterval: any = null;

const updateTime = () => {
  const now = new Date();
  localTimeStr.value = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
};

onMounted(() => {
  updateTime();
  timeInterval = setInterval(updateTime, 1000);
});

onUnmounted(() => {
  if (timeInterval) clearInterval(timeInterval);
});
</script>
