<template>
  <div 
    class="card bg-base-200/80 border border-base-content/10 p-3 md:p-4 rounded-xl shadow-xs transition-all hover:border-base-content/20 flex flex-col justify-between"
  >
    <div class="flex items-center justify-between gap-2 mb-1.5">
      <span class="text-[11px] font-medium uppercase tracking-wider text-base-content/60 flex items-center gap-1.5">
        <component v-if="icon" :is="icon" class="w-3.5 h-3.5 text-primary opacity-80" />
        {{ label }}
      </span>
      <div v-if="badge" class="badge badge-xs font-mono font-bold" :class="badgeClass">
        {{ badge }}
      </div>
    </div>

    <div class="flex items-baseline justify-between gap-2 mt-auto">
      <div class="text-lg md:text-xl font-bold font-mono tracking-tight" :class="valueClass">
        {{ value }}
      </div>
      <div v-if="trend" class="text-[11px] font-mono font-semibold flex items-center gap-0.5" :class="trendClass">
        <span v-if="trend === 'up'">↑</span>
        <span v-else-if="trend === 'down'">↓</span>
        <span>{{ trendValue }}</span>
      </div>
    </div>

    <div v-if="subtext" class="text-[10px] text-base-content/50 font-mono mt-1 truncate">
      {{ subtext }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, type Component } from 'vue';

const props = withDefaults(
  defineProps<{
    label: string;
    value: string | number;
    subtext?: string;
    badge?: string;
    trend?: 'up' | 'down' | 'neutral';
    trendValue?: string;
    icon?: Component;
    variant?: 'default' | 'success' | 'warning' | 'error' | 'primary';
  }>(),
  {
    variant: 'default',
  }
);

const valueClass = computed(() => {
  switch (props.variant) {
    case 'success':
      return 'text-success';
    case 'warning':
      return 'text-warning';
    case 'error':
      return 'text-error';
    case 'primary':
      return 'text-primary';
    default:
      return 'text-base-content';
  }
});

const badgeClass = computed(() => {
  switch (props.variant) {
    case 'success':
      return 'badge-success bg-success/10 text-success border-success/30';
    case 'warning':
      return 'badge-warning bg-warning/10 text-warning border-warning/30';
    case 'error':
      return 'badge-error bg-error/10 text-error border-error/30';
    case 'primary':
      return 'badge-primary bg-primary/10 text-primary border-primary/30';
    default:
      return 'badge-neutral bg-base-300 text-base-content/70';
  }
});

const trendClass = computed(() => {
  if (props.trend === 'up') return 'text-success';
  if (props.trend === 'down') return 'text-error';
  return 'text-base-content/60';
});
</script>
