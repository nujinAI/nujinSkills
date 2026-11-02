<template>
  <nav class="lg:hidden fixed bottom-0 left-0 right-0 z-40 bg-base-200/95 backdrop-blur-md border-t border-base-content/10 px-2 py-1.5 flex items-center justify-around select-none">
    <button
      v-for="item in items"
      :key="item.id"
      @click="$emit('navigate', item.id)"
      class="flex flex-col items-center justify-center flex-1 py-1 px-1 rounded-lg transition-all relative"
      :class="activeScreen === item.id ? 'text-primary font-bold' : 'text-base-content/60 hover:text-base-content'"
    >
      <div class="relative">
        <component :is="item.icon" class="w-5 h-5" />
        <span 
          v-if="item.badgeCount && item.badgeCount > 0" 
          class="absolute -top-1.5 -right-2 badge badge-xs badge-primary font-mono text-[9px] px-1"
        >
          {{ item.badgeCount }}
        </span>
      </div>
      <span class="text-[10px] mt-0.5 tracking-tight font-mono">{{ item.label }}</span>
    </button>
  </nav>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { BarChart2, Send, Sliders, Layers, ShieldCheck } from 'lucide-vue-next';

const props = defineProps<{
  activeScreen: string;
  activePositionsCount?: number;
  activeBotsCount?: number;
}>();

defineEmits<{
  (e: 'navigate', screen: string): void;
}>();

const items = computed(() => [
  { id: 'CHART', label: 'Chart', icon: BarChart2 },
  { id: 'SIGNALS', label: 'Signals', icon: Send, badgeCount: props.activePositionsCount },
  { id: 'BACKTEST', label: 'Backtest', icon: Sliders },
  { id: 'STRATEGIES', label: 'Strategies', icon: Layers, badgeCount: props.activeBotsCount },
  { id: 'RISK', label: 'Risk', icon: ShieldCheck },
]);
</script>
