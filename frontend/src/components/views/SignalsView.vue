<template>
  <div class="w-full h-full overflow-y-auto px-3 md:px-6 py-4 space-y-4 font-mono select-none bg-base-100 text-base-content">
    <!-- Top Stats Ribbon -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-2.5 md:gap-4">
      <StatTile
        label="Open Positions"
        :value="stats.open"
        :variant="stats.open > 0 ? 'primary' : 'default'"
        :icon="Activity"
        subtext="Live market exposure"
      />
      <StatTile
        label="Closed Trades"
        :value="stats.closed"
        :icon="Layers"
        :subtext="`${stats.wins}W / ${stats.losses}L`"
      />
      <StatTile
        label="Win Rate"
        :value="`${stats.winRate.toFixed(1)}%`"
        :variant="stats.winRate >= 50 ? 'success' : 'warning'"
        :icon="Zap"
        :trend="stats.winRate >= 50 ? 'up' : 'down'"
      />
      <StatTile
        label="Net Realized PnL"
        :value="`${stats.totalPnlUsd >= 0 ? '+' : ''}$${stats.totalPnlUsd.toFixed(2)}`"
        :variant="stats.totalPnlUsd >= 0 ? 'success' : 'error'"
        :icon="DollarSign"
      />
    </div>

    <!-- Active Open Positions Section -->
    <div class="card bg-base-200/60 border border-base-content/10 p-3 md:p-4 rounded-xl space-y-3">
      <div class="flex items-center justify-between border-b border-base-content/10 pb-2">
        <div class="flex items-center gap-2">
          <Radio class="w-4 h-4 text-primary animate-pulse" />
          <h3 class="font-bold text-xs uppercase tracking-wider text-base-content">Active Live Positions</h3>
          <span class="badge badge-xs badge-primary font-mono">{{ activePositions.length }}</span>
        </div>
      </div>

      <!-- Positions Cards -->
      <div v-if="activePositions.length > 0" class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        <div 
          v-for="pos in activePositions" 
          :key="pos.id"
          class="card bg-base-300/80 border border-base-content/10 p-3 rounded-xl flex flex-col justify-between gap-3 shadow-xs"
        >
          <div class="flex items-start justify-between gap-2">
            <div>
              <div class="flex items-center gap-1.5">
                <span 
                  class="badge badge-sm font-bold font-mono"
                  :class="pos.action === 'BUY' || pos.action === 'LONG' ? 'badge-success bg-success/15 text-success' : 'badge-error bg-error/15 text-error'"
                >
                  {{ pos.action || pos.side }}
                </span>
                <span class="font-bold text-xs text-base-content">{{ pos.pair || '—' }}</span>
              </div>
              <div class="text-[11px] text-base-content/60 font-mono mt-0.5 truncate max-w-[200px]">
                {{ (pos.strategy || '').replace('Strategy', '') }}
              </div>
            </div>

            <!-- Inspect on Chart Button -->
            <button
              @click="handleInspect(pos)"
              class="btn btn-xs btn-ghost border border-base-content/10 text-[10px]"
              title="Inspect on Chart"
            >
              Chart (F1)
            </button>
          </div>

          <!-- Position Coordinates Grid -->
          <div class="grid grid-cols-3 gap-2 bg-base-200/70 p-2 rounded-lg text-[11px] font-mono">
            <div>
              <span class="text-base-content/50 block text-[9px] uppercase">Entry</span>
              <strong class="text-base-content">${{ formatPrice(pos.price || pos.entry_price) }}</strong>
            </div>
            <div>
              <span class="text-base-content/50 block text-[9px] uppercase">Stop Loss</span>
              <strong class="text-error">${{ formatPrice(pos.stop_loss) }}</strong>
            </div>
            <div>
              <span class="text-base-content/50 block text-[9px] uppercase">Take Profit</span>
              <strong class="text-success">${{ formatPrice(pos.take_profit) }}</strong>
            </div>
          </div>

          <!-- Actions & Close Button -->
          <div class="flex items-center justify-between gap-2 pt-1">
            <span class="text-[10px] text-base-content/50 font-mono">
              Lot: {{ (pos as any).lots || (pos as any).lot_size || '—' }}
            </span>
            <button
              @click="handleClose(pos)"
              class="btn btn-xs btn-error btn-outline font-bold font-mono"
            >
              Close Position
            </button>
          </div>
        </div>
      </div>

      <EmptyState
        v-else
        title="No Open Positions"
        description="Strategy runners are actively scanning for alpha setups."
        :icon="Radio"
      />
    </div>

    <!-- Trade History & Signal Log Section -->
    <div class="card bg-base-200/60 border border-base-content/10 p-3 md:p-4 rounded-xl space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-2 border-b border-base-content/10 pb-2">
        <div class="flex items-center gap-2">
          <Layers class="w-4 h-4 text-secondary" />
          <h3 class="font-bold text-xs uppercase tracking-wider text-base-content">Execution Log & Signals</h3>
          <span class="badge badge-xs badge-neutral font-mono">{{ signals.length }} total</span>
        </div>

        <div class="flex items-center gap-2">
          <input
            v-model="searchQuery"
            type="text"
            placeholder="Filter strategy / symbol..."
            class="input input-xs input-bordered bg-base-300 font-mono text-[11px] w-40 md:w-56"
          />
          <button
            v-if="signals.length > 0"
            @click="handleClearSignals"
            class="btn btn-xs btn-ghost border border-base-content/10 text-base-content/60 hover:text-error text-[10px]"
            title="Clear Signal Stream"
          >
            Clear Log
          </button>
        </div>
      </div>

      <!-- Responsive List / Table -->
      <div v-if="filteredSignals.length > 0" class="overflow-x-auto">
        <table class="table table-xs font-mono w-full">
          <thead>
            <tr class="border-b border-base-content/10 text-base-content/60 text-[10px]">
              <th>Time</th>
              <th>Strategy</th>
              <th>Action</th>
              <th>Entry</th>
              <th>Exit</th>
              <th>Reason</th>
              <th>PnL</th>
              <th>Broker Order</th>
              <th class="text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            <tr 
              v-for="sig in filteredSignals" 
              :key="sig.id"
              class="hover:bg-base-300/40 border-b border-base-content/5 transition-colors"
            >
              <td class="text-base-content/60 text-[11px] whitespace-nowrap">
                {{ formatTime(sig.time || (sig as any).timestamp) }}
              </td>
              <td class="font-bold text-base-content text-[11px] truncate max-w-[150px]">
                {{ (sig.strategy || '').replace('Strategy', '') }}
              </td>
              <td>
                <span 
                  class="badge badge-xs font-bold font-mono"
                  :class="sig.action === 'BUY' || sig.action === 'LONG' ? 'badge-success bg-success/15 text-success' : 'badge-error bg-error/15 text-error'"
                >
                  {{ sig.action || sig.side }}
                </span>
              </td>
              <td class="text-base-content font-bold text-[11px]">
                ${{ formatPrice(sig.price || sig.entry_price) }}
              </td>
              <td class="text-base-content/70 text-[11px]">
                {{ sig.exit_price ? `$${formatPrice(sig.exit_price)}` : '—' }}
              </td>
              <td>
                <span v-if="sig.exit_reason" class="badge badge-xs badge-neutral text-[9px]">
                  {{ sig.exit_reason }}
                </span>
                <span v-else class="text-base-content/40 text-[10px]">RUNNING</span>
              </td>
              <td>
                <span 
                  v-if="sig.pnl_pct != null || (sig as any).pnl_usd != null"
                  class="font-bold text-[11px]"
                  :class="((sig as any).pnl_usd || sig.pnl_pct || 0) >= 0 ? 'text-success' : 'text-error'"
                >
                  {{ ((sig as any).pnl_usd || 0) >= 0 ? '+' : '' }}${{ ((sig as any).pnl_usd || 0).toFixed(2) }}
                  <span class="text-[9px] opacity-75">({{ sig.pnl_pct ? (sig.pnl_pct > 0 ? '+' : '') + sig.pnl_pct.toFixed(2) + '%' : '' }})</span>
                </span>
                <span v-else class="text-base-content/40">—</span>
              </td>
              <td class="text-[10px] text-base-content/60 truncate max-w-[120px]">
                {{ (sig as any).broker_order?.order_id || (sig as any).broker_order?.status || '—' }}
              </td>
              <td class="text-right">
                <button
                  @click="handleInspect(sig)"
                  class="btn btn-xs btn-ghost text-primary text-[10px] px-1.5"
                >
                  Inspect
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <EmptyState
        v-else
        title="No Signals Found"
        description="No signal records match the active filter criteria."
        :icon="Layers"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';
import { Activity, Layers, Zap, DollarSign, Radio } from 'lucide-vue-next';
import StatTile from '../common/StatTile.vue';
import EmptyState from '../common/EmptyState.vue';
import { useSignals } from '../../composables/useSignals';
import type { SignalData } from '../../types';

const emit = defineEmits<{
  (e: 'inspectSignal', sig: SignalData): void;
}>();

const { signals, activePositions, stats, closePosition, clearSignals, inspectSignal } = useSignals();

const searchQuery = ref('');

const filteredSignals = computed(() => {
  if (!searchQuery.value) return signals.value;
  const q = searchQuery.value.toLowerCase();
  return signals.value.filter((s) => {
    const strat = (s.strategy || '').toLowerCase();
    const pair = (s.pair || '').toLowerCase();
    const action = (s.action || s.side || '').toLowerCase();
    return strat.includes(q) || pair.includes(q) || action.includes(q);
  });
});

const handleClose = async (pos: SignalData) => {
  if (confirm(`Confirm emergency manual close for ${pos.strategy} (${pos.action})?`)) {
    await closePosition(pos);
  }
};

const handleInspect = (sig: SignalData) => {
  inspectSignal(sig);
  emit('inspectSignal', sig);
};

const handleClearSignals = async () => {
  if (confirm('Clear all signal history logs?')) {
    await clearSignals();
  }
};

const formatPrice = (p?: number) => {
  if (p == null || isNaN(p)) return '—';
  return p.toFixed(2);
};

const formatTime = (ts?: number) => {
  if (!ts) return '—';
  const sec = ts > 1e11 ? Math.floor(ts / 1000) : ts;
  const d = new Date(sec * 1000);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', month: 'short', day: '2-digit' });
};
</script>
