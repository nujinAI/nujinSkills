<template>
  <div class="w-full h-full overflow-y-auto px-3 md:px-6 py-4 space-y-4 font-mono select-none bg-base-100 text-base-content">
    <!-- Top Portfolio Summary Ribbon -->
    <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5 md:gap-4">
      <StatTile
        label="Active Runners"
        :value="activeBots.length"
        :variant="activeBots.length > 0 ? 'success' : 'default'"
        :icon="Cpu"
        subtext="Live bot processes"
      />
      <StatTile
        label="Blended Sharpe"
        :value="formatMetric(portfolioSummary?.blended_sharpe)"
        :variant="(portfolioSummary?.blended_sharpe || 0) >= 1.5 ? 'success' : 'default'"
        :icon="Zap"
        subtext="Portfolio risk-adjusted"
      />
      <StatTile
        label="Blended Win Rate"
        :value="`${formatMetric(portfolioSummary?.blended_win_rate)}%`"
        :variant="(portfolioSummary?.blended_win_rate || 0) >= 50 ? 'success' : 'warning'"
        :icon="TrendingUp"
        subtext="Across active universe"
      />
      <StatTile
        label="Profit Factor"
        :value="formatMetric(portfolioSummary?.combined_profit_factor)"
        :variant="(portfolioSummary?.combined_profit_factor || 0) >= 1.3 ? 'success' : 'default'"
        :icon="DollarSign"
        subtext="Aggregated PnL ratio"
      />
      <StatTile
        label="Universe Size"
        :value="managedStrategies.length"
        :icon="Layers"
        subtext="Discovered alphas"
      />
    </div>

    <!-- Filter & Search Toolbar -->
    <div class="card bg-base-200/80 border border-base-content/10 p-3 rounded-xl flex flex-wrap items-center justify-between gap-3 shadow-xs">
      <div class="flex items-center gap-1.5 flex-wrap">
        <span class="text-xs text-base-content/60 font-semibold uppercase mr-1">Filter:</span>
        <button
          v-for="filter in ['ALL', 'ACTIVE', 'S-TIER', 'A-TIER', 'B-TIER']"
          :key="filter"
          @click="activeTierFilter = filter"
          class="btn btn-xs font-mono text-[11px]"
          :class="activeTierFilter === filter ? 'btn-primary text-primary-content font-bold' : 'btn-ghost text-base-content/70 hover:text-base-content'"
        >
          {{ filter }}
        </button>
      </div>

      <div class="flex items-center gap-2">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="Search strategy..."
          class="input input-xs input-bordered bg-base-300 font-mono text-[11px] w-48 md:w-60"
        />
        <button
          @click="pollStrategies"
          class="btn btn-xs btn-ghost border border-base-content/10 text-[10px]"
          title="Refresh Alphas"
        >
          <RefreshCw class="w-3 h-3" />
        </button>
      </div>
    </div>

    <!-- Strategies Table / Grid -->
    <div class="card bg-base-200/60 border border-base-content/10 p-3 md:p-4 rounded-xl space-y-3">
      <div class="flex items-center justify-between border-b border-base-content/10 pb-2">
        <div class="flex items-center gap-2">
          <Layers class="w-4 h-4 text-primary" />
          <h3 class="font-bold text-xs uppercase tracking-wider text-base-content">Quantitative Alpha Universe</h3>
          <span class="badge badge-xs badge-neutral font-mono">{{ filteredStrategies.length }} displayed</span>
        </div>
      </div>

      <div v-if="filteredStrategies.length > 0" class="overflow-x-auto">
        <table class="table table-xs font-mono w-full">
          <thead>
            <tr class="border-b border-base-content/10 text-base-content/60 text-[10px]">
              <th class="w-12">Rank</th>
              <th>Strategy</th>
              <th>Tier</th>
              <th>Status</th>
              <th>Asset</th>
              <th>Sharpe</th>
              <th>Win Rate</th>
              <th>Max DD</th>
              <th>Profit Factor</th>
              <th class="text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(strat, idx) in filteredStrategies"
              :key="strat.id || strat.name"
              class="hover:bg-base-300/40 border-b border-base-content/5 transition-colors"
            >
              <td class="font-bold text-primary text-xs">
                #{{ idx + 1 }}
              </td>
              <td>
                <div class="font-bold text-base-content text-[11px] truncate max-w-[240px]" :title="formatStrategyTitle(strat)">
                  {{ formatStrategyTitle(strat) }}
                </div>
                <div class="text-[10px] text-base-content/50 truncate max-w-[240px] font-mono">
                  {{ strat.file || `${strat.name}.py` }}
                </div>
              </td>
              <td>
                <span 
                  class="badge badge-xs font-bold font-mono"
                  :class="getTierClass(strat.tier)"
                >
                  {{ strat.tier || 'Unranked' }}
                </span>
              </td>
              <td>
                <StatusBadge :status="strat.status" size="xs" />
              </td>
              <td class="text-base-content/70 text-[11px]">
                {{ strat.symbol || '—' }} <span v-if="strat.timeframe" class="opacity-60 text-[10px]">({{ strat.timeframe }})</span>
              </td>
              <td class="font-bold text-[11px]" :class="(strat.latest_backtest?.sharpe || 0) >= 1.5 ? 'text-success' : 'text-base-content'">
                {{ formatMetric(strat.latest_backtest?.sharpe) }}
              </td>
              <td class="font-bold text-[11px]">
                {{ formatPercent(strat.latest_backtest?.win_rate) }}
              </td>
              <td class="text-error font-bold text-[11px]">
                -{{ formatPercent(strat.latest_backtest?.max_drawdown) }}
              </td>
              <td class="text-base-content font-bold text-[11px]">
                {{ formatMetric(strat.latest_backtest?.profit_factor) }}
              </td>
              <td class="text-right">
                <div class="flex items-center justify-end gap-1.5">
                  <!-- Quick Chart Jump -->
                  <button
                    @click="$emit('navigateToChart', strat.file || `${strat.name}.py`)"
                    class="btn btn-xs btn-ghost text-primary text-[10px] px-1.5"
                    title="View on Chart (F1)"
                  >
                    Chart
                  </button>

                  <!-- Quick Backtest Jump -->
                  <button
                    @click="$emit('navigateToBacktest', strat.file || `${strat.name}.py`)"
                    class="btn btn-xs btn-ghost text-secondary text-[10px] px-1.5"
                    title="Audit Backtest (F3)"
                  >
                    Audit
                  </button>

                  <!-- Status Toggle Dropdown -->
                  <div class="dropdown dropdown-end">
                    <div tabindex="0" role="button" class="btn btn-xs btn-neutral text-[10px] px-1.5">
                      Status
                    </div>
                    <ul tabindex="0" class="dropdown-content menu p-1 shadow-xl bg-base-300 rounded-box w-36 border border-base-content/10 z-50 text-xs">
                      <li>
                        <button
                          @click="handleStatusChange(strat, 'ACTIVE_LIVE')"
                          :class="{ 'font-bold text-success': strat.status === 'ACTIVE_LIVE' }"
                        >
                          <Zap class="w-3 h-3 text-success" /> Active Live
                        </button>
                      </li>
                      <li>
                        <button
                          @click="handleStatusChange(strat, 'CRON_BACKTEST')"
                          :class="{ 'font-bold text-warning': strat.status === 'CRON_BACKTEST' }"
                        >
                          <Clock class="w-3 h-3 text-warning" /> Cron Backtest
                        </button>
                      </li>
                      <li>
                        <button
                          @click="handleStatusChange(strat, 'DEACTIVATED')"
                          :class="{ 'font-bold text-base-content/60': strat.status === 'DEACTIVATED' }"
                        >
                          <Pause class="w-3 h-3 text-base-content/40" /> Pause / Off
                        </button>
                      </li>
                    </ul>
                  </div>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <EmptyState
        v-else
        title="No Strategies Found"
        description="Try adjusting your filter or search query."
        :icon="Layers"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import {
  Cpu,
  Zap,
  TrendingUp,
  DollarSign,
  Layers,
  RefreshCw,
  Clock,
  Pause,
} from 'lucide-vue-next';
import StatTile from '../common/StatTile.vue';
import StatusBadge from '../common/StatusBadge.vue';
import EmptyState from '../common/EmptyState.vue';
import { useStrategies, deduplicateStrategies, formatStrategyTitle } from '../../composables/useStrategies';
import type { ManagedStrategy } from '../../types';

defineEmits<{
  (e: 'navigateToChart', strat: string): void;
  (e: 'navigateToBacktest', strat: string): void;
}>();

const {
  managedStrategies,
  portfolioSummary,
  activeBots,
  pollStrategies,
  updateStrategyStatus,
  deployStrategy,
} = useStrategies();

const activeTierFilter = ref<string>('ALL');
const searchQuery = ref<string>('');

const filteredStrategies = computed(() => {
  const deduped = deduplicateStrategies(managedStrategies.value);
  let list = deduped;

  if (activeTierFilter.value === 'ACTIVE') {
    list = list.filter((s) => s.status === 'ACTIVE_LIVE' || activeBots.value.includes(s.name.replace('.py', '')));
  } else if (activeTierFilter.value !== 'ALL') {
    list = list.filter((s) => (s.tier || '').toUpperCase().includes(activeTierFilter.value));
  }

  if (searchQuery.value) {
    const q = searchQuery.value.toLowerCase();
    list = list.filter(
      (s) =>
        s.name.toLowerCase().includes(q) ||
        formatStrategyTitle(s).toLowerCase().includes(q) ||
        (s.symbol && s.symbol.toLowerCase().includes(q))
    );
  }

  return list;
});

const handleStatusChange = async (strat: ManagedStrategy, status: string) => {
  if (status === 'ACTIVE_LIVE') {
    await deployStrategy(strat.file || `${strat.name}.py`, 'dry-run');
  }
  await updateStrategyStatus(strat.file || `${strat.name}.py`, status);
};

const getTierClass = (tier?: string) => {
  if (!tier) return 'badge-neutral';
  if (tier.includes('S-Tier')) return 'badge-warning bg-warning/15 text-warning border-warning/30';
  if (tier.includes('A-Tier')) return 'badge-primary bg-primary/15 text-primary border-primary/30';
  if (tier.includes('B-Tier')) return 'badge-info bg-info/15 text-info border-info/30';
  return 'badge-neutral bg-base-300 text-base-content/60';
};

const formatMetric = (val?: number | null) => {
  if (val == null || isNaN(val)) return '—';
  return val.toFixed(2);
};

const formatPercent = (val?: number | null) => {
  if (val == null || isNaN(val)) return '—';
  const norm = val <= 1 ? val * 100 : val;
  return `${norm.toFixed(1)}%`;
};
</script>
