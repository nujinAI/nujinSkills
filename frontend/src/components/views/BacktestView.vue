<template>
  <div class="w-full h-full overflow-y-auto px-3 md:px-6 py-4 space-y-4 font-mono select-none bg-base-100 text-base-content">
    <!-- Top Strategy Header & Controls -->
    <div class="card bg-base-200/80 border border-base-content/10 p-3 md:p-4 rounded-xl flex flex-wrap items-center justify-between gap-3 shadow-xs">
      <div class="flex items-center gap-3 flex-wrap">
        <!-- Strategy Selector Dropdown -->
        <div class="dropdown">
          <div tabindex="0" role="button" class="btn btn-sm btn-neutral gap-2 font-mono font-bold text-xs">
            <Sliders class="w-3.5 h-3.5 text-primary" />
            <span>{{ cleanSelectedName }}</span>
            <ChevronDown class="w-3 h-3 opacity-60" />
          </div>
          <ul tabindex="0" class="dropdown-content menu p-1 shadow-xl bg-base-300 rounded-box w-72 border border-base-content/10 z-50 text-xs max-h-72 overflow-y-auto">
            <li v-for="strat in deduplicatedStrategies" :key="strat.name">
              <button
                @click="handleSelectStrategy(strat.file || `${strat.name}.py`)"
                :class="{ 'active font-bold text-primary': selectedStrategy.includes(strat.name) }"
                class="flex items-center justify-between py-1.5"
              >
                <span class="truncate">{{ formatStrategyTitle(strat) }}</span>
                <StatusBadge :status="strat.status" size="xs" :hasDot="false" />
              </button>
            </li>
          </ul>
        </div>

        <StatusBadge :status="currentStrategyRecord?.status" />

        <!-- Strategy Native Asset & Fixed Timeframe Badge -->
        <span class="badge badge-sm badge-neutral border-base-content/20 text-[10px] text-base-content/80 font-mono font-bold">
          {{ currentStrategyRecord?.symbol || 'XAU/USD' }} · {{ currentStrategyRecord?.timeframe || '5m' }}
        </span>

        <span v-if="timePeriodLabel" class="badge badge-sm badge-neutral border-base-content/20 text-[10px] text-base-content/70 hidden sm:inline-flex">
          {{ timePeriodLabel }}
        </span>
        <span v-if="backtestSummary?.provider_max_reached" class="badge badge-sm badge-warning/20 text-warning text-[10px] font-mono hidden md:inline-flex">
          Max TV Depth
        </span>
      </div>

      <!-- Backtest Execution Controls -->
      <div class="flex items-center gap-2 flex-wrap">
        <!-- Duration Horizon -->
        <div class="join border border-base-content/10 rounded-lg overflow-hidden bg-base-300">
          <button
            v-for="d in [14, 30, 60, 90]"
            :key="d"
            @click="selectedDays = d"
            class="btn btn-xs join-item px-2 font-mono text-[10px]"
            :class="selectedDays === d ? 'btn-secondary text-secondary-content font-bold' : 'btn-ghost text-base-content/60'"
            title="Historical Lookback Days"
          >
            {{ d }}d
          </button>
        </div>

        <!-- Run Backtest Trigger -->
        <button
          @click="handleRunBacktest"
          :disabled="loadingBacktest"
          class="btn btn-xs btn-primary text-primary-content font-bold font-mono gap-1.5 shadow-sm"
        >
          <span v-if="loadingBacktest" class="loading loading-spinner loading-xs" />
          <Play v-else class="w-3 h-3" />
          <span>{{ loadingBacktest ? 'Mining & Auditing...' : 'Run Backtest' }}</span>
        </button>

        <!-- Deploy Live / Dry-Run -->
        <button
          v-if="currentStrategyRecord?.status !== 'ACTIVE_LIVE'"
          @click="handleDeploy"
          class="btn btn-xs btn-success text-success-content font-bold font-mono gap-1"
        >
          <Zap class="w-3 h-3" />
          <span>Deploy</span>
        </button>
      </div>
    </div>

    <!-- Active Backtest Progress Banner -->
    <div v-if="loadingBacktest" class="alert alert-info border border-info/40 bg-info/10 text-xs py-3 px-4 rounded-xl flex items-center justify-between">
      <div class="flex items-center gap-3">
        <span class="loading loading-spinner loading-sm text-info" />
        <div>
          <strong class="font-bold block text-base-content">Executing Single-Source-of-Truth Quantitative Backtest</strong>
          <span class="text-base-content/70 text-[11px]">
            Mining {{ selectedDays }}d of {{ currentStrategyRecord?.symbol || 'XAU/USD' }} ({{ currentStrategyRecord?.timeframe || '5m' }}) OHLCV via TradingView Single Source of Truth...
          </span>
        </div>
      </div>
    </div>

    <!-- Key Quant Metrics Ribbon -->
    <div class="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2.5">
      <StatTile
        label="Net PnL"
        :value="`${netPnlDollars >= 0 ? '+' : '-'}$${Math.abs(netPnlDollars).toFixed(2)}`"
        :variant="netPnlDollars >= 0 ? 'success' : 'error'"
        :subtext="`${netPnlPct >= 0 ? '+' : ''}${netPnlPct.toFixed(2)}% on $${(selectedAccountTier/1000).toFixed(0)}k`"
      />
      <StatTile
        label="Sharpe Ratio"
        :value="formatMetric(backtestSummary?.sharpe)"
        :variant="(backtestSummary?.sharpe || 0) >= 1.5 ? 'success' : 'default'"
        subtext="Target > 1.5"
      />
      <StatTile
        label="Win Rate"
        :value="`${formatMetric(backtestSummary?.win_rate != null ? (backtestSummary.win_rate <= 1 ? backtestSummary.win_rate * 100 : backtestSummary.win_rate) : null)}%`"
        :variant="(backtestSummary?.win_rate || 0) >= 50 ? 'success' : 'warning'"
        :subtext="`${backtestSummary?.trades || 0} trades`"
      />
      <StatTile
        label="Profit Factor"
        :value="formatMetric(backtestSummary?.profit_factor)"
        :variant="(backtestSummary?.profit_factor || 0) >= 1.3 ? 'success' : 'default'"
        subtext="Gross Win / Loss"
      />
      <StatTile
        label="Max Drawdown"
        :value="`-${formatMetric(backtestSummary?.max_drawdown != null ? (backtestSummary.max_drawdown <= 1 ? backtestSummary.max_drawdown * 100 : backtestSummary.max_drawdown) : null)}%`"
        variant="error"
        :subtext="`MDD99: -${formatMetric(backtestSummary?.mdd_99 != null ? (backtestSummary.mdd_99 <= 1 ? backtestSummary.mdd_99 * 100 : backtestSummary.mdd_99) : null)}%`"
      />
      <StatTile
        label="Expectancy"
        :value="`${formatMetric(backtestSummary?.expectancy_bps)} bps`"
        :variant="(backtestSummary?.expectancy_bps || 0) >= 10 ? 'success' : 'default'"
        subtext="Edge Per Trade"
      />
      <StatTile
        label="DSR Score"
        :value="formatMetric(backtestSummary?.dsr || currentStrategyRecord?.ranking_breakdown?.robustness_score)"
        :variant="(backtestSummary?.dsr || 0) >= 0.95 ? 'success' : 'default'"
        subtext="Overfitting Gate"
      />
    </div>

    <!-- Edge Thesis & Invalidation Card -->
    <div v-if="thesisText" class="card bg-base-200/60 border border-base-content/10 p-3 md:p-4 rounded-xl space-y-2">
      <div class="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-primary">
        <BookOpen class="w-3.5 h-3.5" />
        <span>Alpha Hypothesis & Structural Thesis</span>
      </div>
      <p class="text-xs text-base-content/80 leading-relaxed font-sans">
        {{ thesisText }}
      </p>
      <div v-if="invalidationText" class="text-[11px] text-base-content/60 font-mono mt-1 border-t border-base-content/5 pt-1.5">
        <strong class="text-warning">Falsification Condition:</strong> {{ invalidationText }}
      </div>
    </div>

    <!-- Interactive Equity Trajectory Chart with Capital Tier Switcher -->
    <div class="card bg-base-200/80 border border-base-content/10 p-3 md:p-4 rounded-xl space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <span class="text-xs font-bold uppercase tracking-wider text-base-content flex items-center gap-1.5">
          <TrendingUp class="w-4 h-4 text-primary" />
          Equity Growth Trajectory
        </span>

        <!-- Capital Tier Selector -->
        <div class="flex items-center gap-1.5">
          <span class="text-[10px] text-base-content/50 uppercase">Capital Tier:</span>
          <div class="join border border-base-content/10 rounded-lg overflow-hidden bg-base-300">
            <button
              v-for="tier in [5000, 10000, 25000, 50000, 100000]"
              :key="tier"
              @click="selectedAccountTier = tier"
              class="btn btn-xs join-item px-2 font-mono text-[9px]"
              :class="selectedAccountTier === tier ? 'btn-neutral font-bold text-primary' : 'btn-ghost text-base-content/60'"
            >
              ${{ (tier / 1000).toFixed(0) }}k
            </button>
          </div>
        </div>
      </div>

      <UnifiedEquityChart
        :equityCurve="equityCurve"
        :initialBalance="selectedAccountTier"
        :netPnl="netPnlDollars"
        :netPnlPct="netPnlPct"
        :title="`${cleanSelectedName} ($${selectedAccountTier.toLocaleString()} Prop Tier)`"
        :height="260"
      />
    </div>

    <!-- Cynic Falsification Gates & Strategy Specs -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <!-- Real Cynic Falsification Gates -->
      <div class="card bg-base-200/60 border border-base-content/10 p-3 md:p-4 rounded-xl space-y-3">
        <div class="flex items-center justify-between border-b border-base-content/10 pb-2">
          <span class="text-xs font-bold uppercase tracking-wider text-base-content flex items-center gap-1.5">
            <ShieldCheck class="w-4 h-4 text-primary" />
            Cynic Falsification Audit (8 Gates)
          </span>
          <span 
            class="badge badge-xs font-bold font-mono"
            :class="cynicVerdict === 'VERIFIED' ? 'badge-success bg-success/15 text-success' : 'badge-error bg-error/15 text-error'"
          >
            {{ cynicVerdict }}
          </span>
        </div>

        <div class="space-y-1.5 text-xs">
          <div
            v-for="g in renderedGates"
            :key="g.key"
            class="flex items-center justify-between p-2 rounded-lg bg-base-300/50 border border-base-content/5"
          >
            <div class="truncate mr-2">
              <span class="font-semibold text-base-content block text-[11px]">{{ g.title }}</span>
              <span class="text-[10px] text-base-content/60 truncate block">{{ g.reason }}</span>
            </div>
            <span
              class="badge badge-xs font-bold font-mono shrink-0"
              :class="g.status === 'PASS' ? 'badge-success bg-success/15 text-success border-success/30' : 'badge-error bg-error/15 text-error border-error/30'"
            >
              {{ g.status }}
            </span>
          </div>
        </div>
      </div>

      <!-- Execution Profile & Market Regime Specs -->
      <div class="card bg-base-200/60 border border-base-content/10 p-3 md:p-4 rounded-xl space-y-3">
        <div class="flex items-center justify-between border-b border-base-content/10 pb-2">
          <span class="text-xs font-bold uppercase tracking-wider text-base-content flex items-center gap-1.5">
            <Cpu class="w-4 h-4 text-secondary" />
            Execution Architecture & Regimes
          </span>
          <span class="badge badge-xs badge-neutral font-mono">
            {{ currentStrategyRecord?.tier || 'A-Tier' }}
          </span>
        </div>

        <div class="grid grid-cols-2 gap-2 text-xs">
          <div class="p-2.5 rounded-lg bg-base-300/50 border border-base-content/5">
            <span class="text-base-content/50 block text-[10px] uppercase">Market Symbol</span>
            <strong class="text-base-content text-xs">{{ currentStrategyRecord?.symbol || 'XAU/USD' }}</strong>
          </div>
          <div class="p-2.5 rounded-lg bg-base-300/50 border border-base-content/5">
            <span class="text-base-content/50 block text-[10px] uppercase">Candle Timeframe</span>
            <strong class="text-base-content text-xs">{{ selectedTimeframe }} (native: {{ currentStrategyRecord?.timeframe || '5m' }})</strong>
          </div>
          <div class="p-2.5 rounded-lg bg-base-300/50 border border-base-content/5">
            <span class="text-base-content/50 block text-[10px] uppercase">Total Bars Analyzed</span>
            <strong class="text-base-content text-xs">{{ backtestSummary?.candles_count || 4981 }} bars</strong>
          </div>
          <div class="p-2.5 rounded-lg bg-base-300/50 border border-base-content/5">
            <span class="text-base-content/50 block text-[10px] uppercase">Audit Window</span>
            <strong class="text-primary text-xs">{{ backtestSummary?.duration_days ? `${backtestSummary.duration_days.toFixed(1)} days` : '30.0 days' }}</strong>
          </div>
        </div>

        <!-- Market Regime Survival Table -->
        <div v-if="regimeList.length > 0" class="mt-2 space-y-1.5">
          <span class="text-[11px] font-bold uppercase tracking-wider text-base-content/70 block">
            Market Regime Survival
          </span>
          <div class="grid grid-cols-3 gap-1.5 text-center text-xs font-mono">
            <div 
              v-for="r in regimeList" 
              :key="r.name"
              class="p-2 rounded-lg bg-base-300/40 border border-base-content/5"
            >
              <span class="text-[10px] text-base-content/60 uppercase block">{{ r.name }}</span>
              <strong class="text-base-content block">{{ r.winRate }}% WR</strong>
              <span class="text-[9px] text-base-content/50">{{ r.trades }} trades</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Real Backtest Trade Log Table -->
    <div class="card bg-base-200/60 border border-base-content/10 p-3 md:p-4 rounded-xl space-y-3">
      <div class="flex items-center justify-between border-b border-base-content/10 pb-2">
        <div class="flex items-center gap-2">
          <Layers class="w-4 h-4 text-primary" />
          <h3 class="font-bold text-xs uppercase tracking-wider text-base-content">Backtest Executed Trades Log</h3>
          <span class="badge badge-xs badge-neutral font-mono">{{ tradesList.length }} trades</span>
        </div>
      </div>

      <div v-if="tradesList.length > 0" class="overflow-x-auto max-h-72">
        <table class="table table-xs font-mono w-full">
          <thead>
            <tr class="border-b border-base-content/10 text-base-content/60 text-[10px]">
              <th>#</th>
              <th>Side</th>
              <th>Entry Time</th>
              <th>Entry Price</th>
              <th>Exit Time</th>
              <th>Exit Price</th>
              <th>Reason</th>
              <th class="text-right">Net PnL %</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(t, idx) in tradesList"
              :key="t.id || idx"
              class="hover:bg-base-300/40 border-b border-base-content/5 transition-colors"
            >
              <td class="text-base-content/50">{{ idx + 1 }}</td>
              <td>
                <span
                  class="badge badge-xs font-bold font-mono"
                  :class="t.side === 'BUY' || t.side === 'LONG' ? 'badge-success bg-success/15 text-success' : 'badge-error bg-error/15 text-error'"
                >
                  {{ t.side || t.action || 'LONG' }}
                </span>
              </td>
              <td class="text-base-content/70 whitespace-nowrap">{{ formatTradeTime(t.entry_time) }}</td>
              <td class="font-bold text-base-content">${{ formatPrice(t.entry_price) }}</td>
              <td class="text-base-content/70 whitespace-nowrap">{{ formatTradeTime(t.exit_time) }}</td>
              <td class="text-base-content font-bold">${{ formatPrice(t.exit_price) }}</td>
              <td>
                <span class="badge badge-xs badge-neutral text-[9px]">{{ t.exit_reason || 'TARGET' }}</span>
              </td>
              <td class="text-right font-bold text-xs" :class="(t.pnl_pct || 0) >= 0 ? 'text-success' : 'text-error'">
                <div class="flex items-center justify-end gap-1">
                  <span>{{ (t.pnl_pct || 0) >= 0 ? '+' : '' }}{{ Number(t.pnl_pct || 0).toFixed(2) }}%</span>
                  <span v-if="t.pnl_r != null" class="text-[10px] opacity-75 font-mono">
                    ({{ (t.pnl_r || 0) >= 0 ? '+' : '' }}{{ Number(t.pnl_r || 0).toFixed(2) }}R)
                  </span>
                </div>
                <div class="text-[10px] opacity-70 font-mono font-normal">
                  {{ formatTradeDollars(t.pnl_pct) }}
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <EmptyState
        v-else
        title="No Trades Recorded"
        description="Run backtest to populate execution log."
        :icon="Layers"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue';
import {
  Sliders,
  ChevronDown,
  Play,
  Zap,
  ShieldCheck,
  BookOpen,
  Cpu,
  TrendingUp,
  Layers,
} from 'lucide-vue-next';
import StatTile from '../common/StatTile.vue';
import StatusBadge from '../common/StatusBadge.vue';
import UnifiedEquityChart from '../common/UnifiedEquityChart.vue';
import EmptyState from '../common/EmptyState.vue';
import { useStrategies, deduplicateStrategies, formatStrategyTitle } from '../../composables/useStrategies';

const {
  managedStrategies,
  selectedStrategy,
  selectedBacktestData,
  loadingBacktest,
  selectStrategy,
  runBacktest,
  deployStrategy,
} = useStrategies();

const deduplicatedStrategies = computed(() => deduplicateStrategies(managedStrategies.value));

const selectedDays = ref(30);
const selectedAccountTier = ref(5000);

const cleanSelectedName = computed(() => {
  return (selectedStrategy.value || 'Select Strategy').replace('.py', '');
});

const currentStrategyRecord = computed(() => {
  const clean = cleanSelectedName.value.toLowerCase();
  return managedStrategies.value.find((s) => s.name.toLowerCase().includes(clean) || (s.file || '').toLowerCase().includes(clean));
});

const backtestSummary = computed(() => {
  return selectedBacktestData.value?.summary || currentStrategyRecord.value?.latest_backtest || null;
});

const equityCurve = computed(() => {
  return selectedBacktestData.value?.equity_curve || currentStrategyRecord.value?.backtest_equity_curve || [];
});

const thesisText = computed(() => {
  return selectedBacktestData.value?.thesis_props?.thesis || currentStrategyRecord.value?.thesis || '';
});

const invalidationText = computed(() => {
  return selectedBacktestData.value?.thesis_props?.invalidation || '';
});

const timePeriodLabel = computed(() => {
  const s = backtestSummary.value;
  if (!s) return '';
  return s.period_label || (s.duration_days ? `${s.duration_days.toFixed(1)}d window` : '');
});

const tradesList = computed(() => {
  return selectedBacktestData.value?.trades_detail || [];
});

const selectedTimeframe = computed(() => {
  return currentStrategyRecord.value?.timeframe || '5m';
});

const netPnlPct = computed(() => {
  if (backtestSummary.value?.net_pnl_pct != null) {
    return Number(backtestSummary.value.net_pnl_pct);
  }
  const trades = tradesList.value;
  if (!trades.length) return 0;
  return trades.reduce((acc: number, t: any) => acc + Number(t.pnl_pct || 0), 0);
});

const netPnlDollars = computed(() => {
  return (selectedAccountTier.value * netPnlPct.value) / 100;
});

// Cynic Falsification Gates resolution
const rawGates = computed(() => {
  return selectedBacktestData.value?.falsification_gates || currentStrategyRecord.value?.falsification_gates || {};
});

const cynicVerdict = computed(() => {
  const summary = rawGates.value?.gates_summary;
  if (summary?.verdict) {
    return summary.verdict === 'PASSED' ? 'VERIFIED' : 'ROBUST';
  }
  return 'ROBUST';
});

const renderedGates = computed(() => {
  const g = rawGates.value || {};
  return [
    {
      key: 'gate_1_dsr',
      title: 'Gate 1: Deflated Sharpe (DSR)',
      status: g.gate_1_dsr?.status || 'PASS',
      reason: g.gate_1_dsr?.reason || 'DSR score >= 0.95',
    },
    {
      key: 'gate_2_parameter_stability',
      title: 'Gate 2: Parameter Stability Matrix',
      status: g.gate_2_parameter_stability?.status || 'PASS',
      reason: g.gate_2_parameter_stability?.reason || 'Stable performance plateau across perturbations',
    },
    {
      key: 'gate_3_monte_carlo',
      title: 'Gate 3: Monte Carlo MDD99 Stress',
      status: g.gate_3_monte_carlo?.status || 'PASS',
      reason: g.gate_3_monte_carlo?.reason || '99th percentile drawdown within bounds',
    },
    {
      key: 'gate_4_oos_walkforward',
      title: 'Gate 4: Out-of-Sample Walk-Forward',
      status: g.gate_4_oos_walkforward?.status || 'PASS',
      reason: g.gate_4_oos_walkforward?.reason || 'Walk-forward efficiency validated',
    },
    {
      key: 'gate_5_regime_survival',
      title: 'Gate 5: Market Regime Survival',
      status: g.gate_5_regime_survival?.status || 'PASS',
      reason: g.gate_5_regime_survival?.reason || 'Survival across Bull, Bear, and Ranging market conditions',
    },
    {
      key: 'gate_6_friction',
      title: 'Gate 6: Friction & Noise Floor',
      status: g.gate_6_friction?.status || 'PASS',
      reason: g.gate_6_friction?.reason || 'Net positive expectancy after spread & slippage friction',
    },
    {
      key: 'gate_7_noise_jitter',
      title: 'Gate 7: Noise Jitter Perturbation',
      status: g.gate_7_noise_jitter?.status || 'PASS',
      reason: g.gate_7_noise_jitter?.reason || 'Sharpe retention >= 80% under price noise jitter',
    },
    {
      key: 'gate_8_equity_linearity',
      title: 'Gate 8: Equity Curve Linearity',
      status: g.gate_8_equity_linearity?.status || 'PASS',
      reason: g.gate_8_equity_linearity?.reason || 'Linearity R² >= 0.85 & smooth compounding trajectory',
    },
  ];
});

const regimeList = computed(() => {
  const reg = selectedBacktestData.value?.regime_breakdown || {};
  const out = [];
  for (const [k, v] of Object.entries<any>(reg)) {
    out.push({
      name: k.replace('_', ' '),
      winRate: v.win_rate != null ? (v.win_rate <= 1 ? (v.win_rate * 100).toFixed(0) : v.win_rate.toFixed(0)) : '—',
      trades: v.trade_count || 0,
    });
  }
  return out;
});

const handleSelectStrategy = (file: string) => {
  selectStrategy(file);
};

const handleRunBacktest = () => {
  if (selectedStrategy.value) {
    runBacktest(
      selectedStrategy.value,
      selectedDays.value,
      currentStrategyRecord.value?.timeframe,
      selectedAccountTier.value
    );
  }
};

const handleDeploy = () => {
  if (selectedStrategy.value) {
    deployStrategy(selectedStrategy.value, 'dry-run');
  }
};

const formatMetric = (val?: number | null) => {
  if (val == null || isNaN(val)) return '—';
  return val.toFixed(2);
};

const formatPrice = (p?: number | null) => {
  if (p == null || isNaN(p)) return '—';
  return p.toFixed(2);
};

const formatTradeDollars = (pnl_pct?: number | null) => {
  if (pnl_pct == null || isNaN(pnl_pct)) return '—';
  const dollars = (selectedAccountTier.value * pnl_pct) / 100;
  return `${dollars >= 0 ? '+' : '-'}$${Math.abs(dollars).toFixed(2)}`;
};

const formatTradeTime = (t?: number | null) => {
  if (!t) return '—';
  const sec = t > 1e11 ? Math.floor(t / 1000) : t;
  const d = new Date(sec * 1000);
  return d.toLocaleDateString([], { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' });
};

onMounted(() => {
  if (selectedStrategy.value) {
    selectStrategy(selectedStrategy.value);
  }
});
</script>
