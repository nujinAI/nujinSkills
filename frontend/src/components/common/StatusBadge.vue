<template>
  <span 
    class="badge badge-sm font-mono font-semibold gap-1.5 transition-colors border"
    :class="computedClasses"
  >
    <span v-if="hasDot" class="w-1.5 h-1.5 rounded-full" :class="dotClass" />
    <span>{{ labelText }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue';

const props = withDefaults(
  defineProps<{
    status?: string;
    hasDot?: boolean;
    size?: 'xs' | 'sm' | 'md';
  }>(),
  {
    status: '',
    hasDot: true,
    size: 'sm',
  }
);

const labelText = computed(() => {
  const s = props.status || 'UNKNOWN';
  if (s === 'ACTIVE_LIVE') return 'LIVE';
  if (s === 'CRON_BACKTEST') return 'CRON';
  if (s === 'DEACTIVATED') return 'PAUSED';
  if (s === 'FILLED') return 'FILLED';
  if (s === 'CLOSED') return 'CLOSED';
  return s;
});

const computedClasses = computed(() => {
  const s = (props.status || '').toUpperCase();
  const sizeClass = props.size === 'xs' ? 'badge-xs py-1 px-1.5 text-[10px]' : 'py-2 px-2.5 text-xs';

  if (s === 'ACTIVE_LIVE' || s === 'LIVE' || s === 'ONLINE' || s === 'SAFE' || s.includes('S-TIER')) {
    return `${sizeClass} badge-success bg-success/10 border-success/30 text-success`;
  }
  if (s === 'CRON_BACKTEST' || s === 'CRON' || s === 'PENDING' || s === 'WARNING' || s.includes('A-TIER')) {
    return `${sizeClass} badge-warning bg-warning/10 border-warning/30 text-warning`;
  }
  if (s === 'ERROR' || s === 'BREACH' || s === 'OFFLINE' || s === 'STOP_LOSS') {
    return `${sizeClass} badge-error bg-error/10 border-error/30 text-error`;
  }
  if (s.includes('B-TIER') || s === 'INFO') {
    return `${sizeClass} badge-info bg-info/10 border-info/30 text-info`;
  }
  return `${sizeClass} badge-neutral bg-base-300 border-base-content/10 text-base-content/60`;
});

const dotClass = computed(() => {
  const s = (props.status || '').toUpperCase();
  if (s === 'ACTIVE_LIVE' || s === 'LIVE' || s === 'ONLINE' || s === 'SAFE') return 'bg-success animate-pulse';
  if (s === 'CRON_BACKTEST' || s === 'CRON' || s === 'PENDING' || s === 'WARNING') return 'bg-warning';
  if (s === 'ERROR' || s === 'BREACH' || s === 'OFFLINE') return 'bg-error';
  return 'bg-base-content/40';
});
</script>
