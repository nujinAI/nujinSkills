<template>
  <div class="flex flex-col items-center justify-center py-12 px-4 text-center">
    <div class="w-12 h-12 rounded-full bg-base-300/60 border border-base-content/10 flex items-center justify-center mb-3 text-base-content/40">
      <component v-if="icon" :is="icon" class="w-6 h-6" />
      <span v-else>✦</span>
    </div>
    <h4 class="text-sm font-bold text-base-content">{{ title }}</h4>
    <p v-if="description" class="text-xs text-base-content/60 max-w-sm mt-1 mb-4">{{ description }}</p>
    <slot />
  </div>
</template>

<script setup lang="ts">
import type { Component } from 'vue';

defineProps<{
  title: string;
  description?: string;
  icon?: Component;
}>();
</script>
