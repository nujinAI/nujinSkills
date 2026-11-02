import { ref, computed, watch } from 'vue';
import { useWebSocket } from './useWebSocket';
import type { ManagedStrategy, PortfolioSummary, DistributionAnalytics } from '../types';

const selectedStrategy = ref<string>('');
const selectedBacktestData = ref<any>(null);
const loadingBacktest = ref(false);
const nativeActiveRunners = ref<string[]>([]);

export const deduplicateStrategies = (list: ManagedStrategy[]): ManagedStrategy[] => {
  if (!Array.isArray(list)) return [];
  const seen = new Set<string>();
  const out: ManagedStrategy[] = [];
  for (const s of list) {
    const raw = s.name || s.file || s.id || '';
    const key = raw.replace('.py', '').trim().toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(s);
  }
  return out;
};

export const formatStrategyTitle = (strat: ManagedStrategy | any): string => {
  let name = strat.display_name || strat.name || '';
  if (name.includes('/')) {
    name = name.split('/').pop() || name;
  }
  name = name.replace('.py', '').trim();
  for (const sep of [' — ', ' -- ', ' - ']) {
    if (name.includes(sep)) {
      name = name.split(sep)[0].trim();
      break;
    }
  }
  if (!name.includes(' ') && /^[a-z0-9]+[A-Z]/.test(name)) {
    name = name.replace(/([a-z0-9])([A-Z])/g, '$1 $2');
  }
  return name || strat.name || '';
};

export function useStrategies() {
  const { managedStrategies, portfolioSummary, distributionAnalytics, liveSystemState } = useWebSocket();

  // Fetch native bot runners to ensure in-memory execution truth
  const checkBotStatus = async () => {
    try {
      const res = await fetch('/api/bot/status');
      if (res.ok) {
        const data = await res.json();
        const active: string[] = [];
        if (data.runners) {
          for (const [name, info] of Object.entries<any>(data.runners)) {
            if (info.native_active) {
              active.push(name.replace('.py', ''));
            }
          }
        }
        if (active.length > 0) {
          nativeActiveRunners.value = active;
        } else if (data.active_strategies) {
          nativeActiveRunners.value = data.active_strategies.map((s: string) => s.replace('.py', ''));
        }
      }
    } catch (e) {
      console.warn('[useStrategies] Could not fetch bot status:', e);
    }
  };

  const activeBots = computed<string[]>(() => {
    if (nativeActiveRunners.value.length > 0) {
      return nativeActiveRunners.value;
    }
    const fromManaged = managedStrategies.value
      .filter((s) => s.status === 'ACTIVE_LIVE')
      .map((s) => s.name.replace('.py', ''));
    if (fromManaged.length > 0) return fromManaged;

    if (liveSystemState.value?.active_strategies && liveSystemState.value.active_strategies.length > 0) {
      return liveSystemState.value.active_strategies.map((s: string) => s.replace('.py', ''));
    }
    return [];
  });

  const pollStrategies = async () => {
    try {
      const res = await fetch('/api/strategies/manage');
      if (res.ok) {
        const data = await res.json();
        if (data?.strategies && Array.isArray(data.strategies)) {
          managedStrategies.value = deduplicateStrategies(data.strategies);
        }
        if (data?.portfolio_summary) {
          portfolioSummary.value = data.portfolio_summary;
        }
        if (data?.distribution_analytics) {
          distributionAnalytics.value = data.distribution_analytics;
        }
      }
    } catch {
      // silent fallback
    }
    await checkBotStatus();
  };

  const selectStrategy = async (stratName: string) => {
    if (!stratName) return;
    const clean = stratName.endsWith('.py') ? stratName : `${stratName}.py`;
    selectedStrategy.value = clean;
    loadingBacktest.value = true;
    try {
      const res = await fetch('/api/strategies/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strategy: clean }),
      });
      if (res.ok) {
        const data = await res.json();
        if (selectedStrategy.value === clean) {
          selectedBacktestData.value = data;
        }
      }
    } catch (e) {
      console.error('[useStrategies] Failed to select strategy backtest:', e);
    } finally {
      if (selectedStrategy.value === clean) {
        loadingBacktest.value = false;
      }
    }
  };

  const deployStrategy = async (stratName: string, mode: 'dry-run' | 'live' = 'dry-run') => {
    try {
      const res = await fetch('/api/bot/deploy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strategy: stratName, mode }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.state) {
          selectedBacktestData.value = data;
        }
        await pollStrategies();
      }
    } catch (e) {
      console.error('[useStrategies] Failed to deploy strategy:', e);
    }
  };

  const updateStrategyStatus = async (stratName: string, newStatus: string) => {
    try {
      const res = await fetch('/api/strategies/manage/status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strategy: stratName, status: newStatus }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.strategies) {
          managedStrategies.value = data.strategies;
        }
        await pollStrategies();
      }
    } catch (e) {
      console.error('[useStrategies] Failed to update strategy status:', e);
    }
  };

  const runBacktest = async (stratName: string, days: number = 30, timeframe?: string, accountSize?: number) => {
    loadingBacktest.value = true;
    try {
      const payload: any = { strategy: stratName, days: days || 30 };
      if (timeframe) payload.timeframe = timeframe;
      if (accountSize) payload.account_size = accountSize;
      const res = await fetch('/api/strategies/manage/run-backtest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.strategies) {
          managedStrategies.value = deduplicateStrategies(data.strategies);
        }
        if (data.result) {
          selectedBacktestData.value = data.result;
        }
      }
    } catch (e) {
      console.error('[useStrategies] Failed to run backtest:', e);
    } finally {
      loadingBacktest.value = false;
    }
  };

  // Watch managedStrategies to select the first one if none selected
  watch(
    managedStrategies,
    (strats) => {
      if (strats && strats.length > 0 && !selectedStrategy.value) {
        const top = strats[0];
        const file = top.file || (top.name.endsWith('.py') ? top.name : `${top.name}.py`);
        selectStrategy(file);
      }
    },
    { immediate: true }
  );

  return {
    managedStrategies,
    portfolioSummary,
    distributionAnalytics,
    selectedStrategy,
    selectedBacktestData,
    loadingBacktest,
    activeBots,
    pollStrategies,
    selectStrategy,
    deployStrategy,
    updateStrategyStatus,
    runBacktest,
    checkBotStatus,
  };
}
