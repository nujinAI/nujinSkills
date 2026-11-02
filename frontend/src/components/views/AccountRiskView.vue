<template>
  <div class="w-full h-full overflow-y-auto px-3 md:px-6 py-4 space-y-4 font-mono select-none bg-base-100 text-base-content">
    <!-- Top Risk Summary Ribbon -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-2.5 md:gap-4">
      <StatTile
        label="Circuit Breaker"
        :value="drawdownStatus?.status || 'SAFE'"
        :variant="isSafe ? 'success' : 'error'"
        :icon="ShieldCheck"
        :subtext="drawdownStatus?.message || 'Within daily risk limit'"
      />
      <StatTile
        label="Remaining Budget"
        :value="`$${remainingBudget.toFixed(2)}`"
        :variant="remainingBudget > 50 ? 'success' : 'warning'"
        :icon="DollarSign"
        subtext="Daily loss buffer"
      />
      <StatTile
        label="Today's Realized PnL"
        :value="`${(drawdownStatus?.today_realized_pnl_usd || 0) >= 0 ? '+' : ''}$${(drawdownStatus?.today_realized_pnl_usd || 0).toFixed(2)}`"
        :variant="(drawdownStatus?.today_realized_pnl_usd || 0) >= 0 ? 'success' : 'error'"
        :icon="Activity"
        :subtext="`${drawdownStatus?.today_losses_count || 0} losing trades today`"
      />
      <StatTile
        label="Total Equity"
        :value="`$${totalBalance.toFixed(2)}`"
        :icon="Layers"
        variant="primary"
        subtext="Active broker accounts"
      />
    </div>

    <!-- Broker Accounts Card -->
    <div class="card bg-base-200/60 border border-base-content/10 p-3 md:p-4 rounded-xl space-y-3">
      <div class="flex items-center justify-between border-b border-base-content/10 pb-2">
        <div class="flex items-center gap-2">
          <Terminal class="w-4 h-4 text-primary" />
          <h3 class="font-bold text-xs uppercase tracking-wider text-base-content">Connected Broker Accounts</h3>
          <span class="badge badge-xs badge-primary font-mono">{{ brokerAccounts.length }}</span>
        </div>
        <button
          @click="fetchRiskData"
          class="btn btn-xs btn-ghost border border-base-content/10 text-[10px]"
          title="Refresh Balance"
        >
          <RefreshCw class="w-3 h-3" />
        </button>
      </div>

      <div v-if="brokerAccounts.length > 0" class="grid grid-cols-1 md:grid-cols-2 gap-3">
        <div
          v-for="acc in brokerAccounts"
          :key="acc.id"
          class="p-3 rounded-xl bg-base-300/80 border border-base-content/10 space-y-2 shadow-xs"
        >
          <div class="flex items-start justify-between gap-2">
            <div>
              <div class="font-bold text-xs text-base-content">{{ acc.label || acc.broker_id }}</div>
              <div class="text-[10px] text-base-content/60 font-mono">
                {{ acc.login_masked }} ({{ acc.environment.toUpperCase() }})
              </div>
            </div>
            <StatusBadge :status="acc.is_active ? 'ONLINE' : 'OFFLINE'" size="xs" />
          </div>

          <div class="grid grid-cols-2 gap-2 bg-base-200/60 p-2 rounded-lg text-xs font-mono">
            <div>
              <span class="text-base-content/50 block text-[9px] uppercase">Balance</span>
              <strong class="text-base-content font-bold">${{ acc.balance?.toFixed(2) }}</strong>
            </div>
            <div>
              <span class="text-base-content/50 block text-[9px] uppercase">Initial</span>
              <strong class="text-base-content/70">${{ acc.initial_balance?.toFixed(2) }}</strong>
            </div>
          </div>
        </div>
      </div>

      <EmptyState
        v-else
        title="No Accounts Configured"
        description="Add broker credentials in Nujin configuration."
        :icon="Terminal"
      />
    </div>

    <!-- GFT Prop Firm Risk Rules & Trading Windows -->
    <div class="card bg-base-200/60 border border-base-content/10 p-3 md:p-4 rounded-xl space-y-3">
      <div class="flex items-center justify-between border-b border-base-content/10 pb-2">
        <div class="flex items-center gap-2">
          <Clock class="w-4 h-4 text-secondary" />
          <h3 class="font-bold text-xs uppercase tracking-wider text-base-content">Prop Firm Rules & Active Windows</h3>
        </div>
        <span class="badge badge-xs badge-neutral font-mono">GFT Standard</span>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
        <div class="p-3 rounded-xl bg-base-300/50 border border-base-content/5 space-y-1">
          <span class="text-base-content/50 text-[10px] uppercase font-bold block">Drawdown Limits</span>
          <div>Max Daily Loss: <strong class="text-error">${{ (gftRules?.daily_drawdown_limit_3pct ?? (effectiveInitialBalance * 0.03)).toFixed(2) }} (3%)</strong></div>
          <div>Max Trailing Loss: <strong class="text-error">${{ (gftRules?.max_drawdown_limit_6pct ?? (effectiveInitialBalance * 0.06)).toFixed(2) }} (6%)</strong></div>
        </div>

        <div class="p-3 rounded-xl bg-base-300/50 border border-base-content/5 space-y-1">
          <span class="text-base-content/50 text-[10px] uppercase font-bold block">Trade Durations</span>
          <div>Min Holding Time: <strong class="text-base-content">{{ gftRules?.min_holding_seconds || 120 }}s (2m)</strong></div>
          <div>Max Holding Time: <strong class="text-base-content">{{ gftRules?.max_holding_seconds || 900 }}s (15m)</strong></div>
        </div>

        <div class="p-3 rounded-xl bg-base-300/50 border border-base-content/5 space-y-1">
          <span class="text-base-content/50 text-[10px] uppercase font-bold block">Trading Sessions</span>
          <div v-for="sess in gftRules?.trading_sessions || []" :key="sess.session">
            <span class="font-bold text-primary">{{ sess.session }}:</span> {{ sess.window_local }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue';
import { ShieldCheck, DollarSign, Activity, Layers, Terminal, RefreshCw, Clock } from 'lucide-vue-next';
import StatTile from '../common/StatTile.vue';
import StatusBadge from '../common/StatusBadge.vue';
import EmptyState from '../common/EmptyState.vue';
import { useRiskStatus } from '../../composables/useRiskStatus';

const {
  drawdownStatus,
  gftRules,
  brokerAccounts,
  isSafe,
  remainingBudget,
  totalBalance,
  fetchRiskData,
} = useRiskStatus();

const effectiveInitialBalance = computed(() => {
  return brokerAccounts.value[0]?.initial_balance || drawdownStatus.value?.initial_balance || gftRules.value?.account_size || 5000;
});

onMounted(() => {
  fetchRiskData();
});
</script>
