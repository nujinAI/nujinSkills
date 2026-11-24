import { ref, computed } from 'vue';
import { useWebSocket } from './useWebSocket';
import type { SignalData } from '../types';

const targetedSignal = ref<SignalData | null>(null);

export function useSignals() {
  const { signals, latestSignal } = useWebSocket();

  const fetchSignals = async () => {
    try {
      const res = await fetch('/api/signals');
      if (res.ok) {
        const data = await res.json();
        if (data?.signals && Array.isArray(data.signals)) {
          signals.value = data.signals;
        }
      }
    } catch (e) {
      console.warn('[useSignals] Failed to fetch signals:', e);
    }
  };

  const activePositions = computed<SignalData[]>(() => {
    return signals.value.filter(
      (s) => s.status === 'ACTIVE_IN_POSITION' || s.status === 'PENDING_LIMIT' || s.status === 'OPEN' || s.status === 'PENDING'
    );
  });

  const closedTrades = computed<SignalData[]>(() => {
    return signals.value.filter((s) => s.status === 'CLOSED');
  });

  const stats = computed(() => {
    const closed = closedTrades.value;
    const wins = closed.filter((t) => (t.pnl_pct != null && t.pnl_pct > 0) || ((t as any).pnl_usd != null && (t as any).pnl_usd > 0));
    const losses = closed.filter((t) => (t.pnl_pct != null && t.pnl_pct < 0) || ((t as any).pnl_usd != null && (t as any).pnl_usd < 0));
    const totalPnlUsd = closed.reduce((acc, t) => acc + ((t as any).pnl_usd || 0), 0);
    const winRate = closed.length > 0 ? (wins.length / closed.length) * 100 : 0;

    return {
      total: signals.value.length,
      open: activePositions.value.length,
      closed: closed.length,
      wins: wins.length,
      losses: losses.length,
      winRate,
      totalPnlUsd,
    };
  });

  const inspectSignal = (signal: SignalData | null) => {
    targetedSignal.value = signal;
  };

  const closePosition = async (signal: SignalData, exitPrice?: number) => {
    try {
      const res = await fetch('/api/signals/close', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: signal.id,
          strategy: signal.strategy,
          exit_price: exitPrice ?? 0,
          exit_reason: 'MANUAL_UI_CLOSE',
        }),
      });
      if (res.ok) {
        await fetchSignals();
        if (targetedSignal.value?.id === signal.id) {
          targetedSignal.value = null;
        }
      }
    } catch (e) {
      console.error('[useSignals] Failed to close position:', e);
    }
  };

  const clearSignals = async (strategyName?: string) => {
    try {
      const res = await fetch('/api/signals/clear', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strategy: strategyName }),
      });
      if (res.ok) {
        await fetchSignals();
        targetedSignal.value = null;
      }
    } catch (e) {
      console.error('[useSignals] Failed to clear signals:', e);
    }
  };

  return {
    signals,
    latestSignal,
    activePositions,
    closedTrades,
    targetedSignal,
    stats,
    fetchSignals,
    inspectSignal,
    closePosition,
    clearSignals,
  };
}
