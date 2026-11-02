import { ref, computed } from 'vue';
import { playSignalTone } from '../utils/audio';
import type {
  WidgetData,
  SignalData,
  ManagedStrategy,
  PortfolioSummary,
  DistributionAnalytics,
} from '../types';

export interface SystemState {
  active_strategy?: string;
  target_profile?: string;
  status?: string;
  backtest_summary?: Record<string, any>;
  signals_count?: number;
  last_updated?: string;
  equity_curve?: any[];
  return_distribution?: any[];
  regime_breakdown?: Record<string, any>;
  falsification_gates?: Record<string, any>;
  trades_detail?: any[];
  trade_markers?: any[];
  thesis_props?: Record<string, any>;
  active_strategies?: string[];
}

export interface DiscoveredStrategyPayload {
  strategy: string;
  file: string;
  display_name: string;
  target_profile?: string;
  thesis?: string;
  symbol?: string;
  timeframe?: string;
  timestamp?: number;
}

export interface MarketTickPayload {
  symbol: string;
  timeframe?: string;
  price?: number;
  quote?: any;
  candle?: {
    time: number;
    open: number;
    high: number;
    low: number;
    close: number;
    volume?: number;
  };
  is_bar_closed?: boolean;
}

// Global Singleton State
const isConnected = ref(false);
const widgetsMap = ref<Record<string, WidgetData>>({});
const latestSignal = ref<SignalData | null>(null);
const signals = ref<SignalData[]>([]);
const liveSystemState = ref<SystemState | null>(null);
const managedStrategies = ref<ManagedStrategy[]>([]);
const portfolioSummary = ref<PortfolioSummary | null>(null);
const distributionAnalytics = ref<DistributionAnalytics | null>(null);
const latestDiscoveredStrategy = ref<DiscoveredStrategyPayload | null>(null);
const latestMarketTick = ref<MarketTickPayload | null>(null);
const copilotMarkup = ref<any | null>(null);

let socket: WebSocket | null = null;
let reconnectTimer: any = null;
let isStarted = false;

const connect = () => {
  if (typeof window === 'undefined') return;

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.hostname || 'localhost';
  // Use Vite proxy (/ws) or direct port 8000
  const wsUrl = `${protocol}//${host}:8000/ws`;

  try {
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
      console.log('[WS] Connected to Nujin Telemetry Bus');
      isConnected.value = true;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    socket.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        const { event_type, payload } = msg;
        if (!event_type || !payload) return;

        switch (event_type) {
          case 'UPSERT_WIDGET': {
            const widgetId = payload.id || payload.title || 'default_id';
            widgetsMap.value = { ...widgetsMap.value, [widgetId]: payload };
            break;
          }
          case 'CHART_MARKER':
          case 'TELEGRAM_ALERT':
          case 'SIGNAL_TRIGGERED': {
            latestSignal.value = payload;
            const exists = signals.value.some(
              (s) => s.id === payload.id || (s.time === payload.time && s.action === payload.action)
            );
            if (!exists) {
              signals.value = [payload, ...signals.value];
            }
            const action = payload.action || payload.side;
            if (action) {
              playSignalTone(action);
            }
            break;
          }
          case 'STATE_UPDATED': {
            liveSystemState.value = payload;
            break;
          }
          case 'SIGNAL_CLOSED': {
            signals.value = signals.value.map((s) =>
              s.id === payload.id ? { ...s, ...payload } : s
            );
            if (
              latestSignal.value &&
              (latestSignal.value.id === payload.id ||
                (payload.time && Math.abs(Number(latestSignal.value.time || 0) - Number(payload.time)) < 2))
            ) {
              latestSignal.value = {
                ...latestSignal.value,
                ...payload,
                status: 'CLOSED',
              };
            }
            break;
          }
          case 'SIGNALS_CLEARED': {
            if (payload?.strategy) {
              signals.value = signals.value.filter((s) => s.strategy !== payload.strategy);
            } else {
              signals.value = [];
            }
            break;
          }
          case 'SIGNAL_DELETED': {
            signals.value = signals.value.filter((s) => s.id !== payload.id);
            if (latestSignal.value && latestSignal.value.id === payload.id) {
              latestSignal.value = signals.value[0] || null;
            }
            break;
          }
          case 'SIGNALS_UPDATED': {
            if (Array.isArray(payload)) {
              signals.value = payload;
            } else if (payload?.signals && Array.isArray(payload.signals)) {
              signals.value = payload.signals;
            }
            latestSignal.value = signals.value[0] || null;
            break;
          }
          case 'STRATEGIES_UPDATED': {
            const rawList = Array.isArray(payload) ? payload : (payload?.strategies || []);
            const seen = new Set<string>();
            const deduped: ManagedStrategy[] = [];
            for (const s of rawList) {
              const k = (s.name || s.file || '').replace('.py', '').toLowerCase();
              if (!k || seen.has(k)) continue;
              seen.add(k);
              deduped.push(s);
            }
            managedStrategies.value = deduped;
            if (payload?.portfolio_summary) {
              portfolioSummary.value = payload.portfolio_summary;
            }
            if (payload?.distribution_analytics) {
              distributionAnalytics.value = payload.distribution_analytics;
            }
            break;
          }
          case 'MARKET_TICK': {
            latestMarketTick.value = payload;
            break;
          }
          case 'STRATEGY_DISCOVERED': {
            latestDiscoveredStrategy.value = {
              ...payload,
              timestamp: Date.now(),
            };
            break;
          }
          case 'COPILOT_MARKUP': {
            copilotMarkup.value = payload;
            break;
          }
          default:
            break;
        }
      } catch (err) {
        console.error('[WS] Parse error:', err);
      }
    };

    socket.onclose = () => {
      isConnected.value = false;
      if (!reconnectTimer) {
        reconnectTimer = setTimeout(connect, 3000);
      }
    };

    socket.onerror = () => {
      socket?.close();
    };
  } catch (err) {
    console.error('[WS] Init error:', err);
    if (!reconnectTimer) {
      reconnectTimer = setTimeout(connect, 3000);
    }
  }
};

export function useWebSocket() {
  if (!isStarted) {
    isStarted = true;
    connect();
  }

  const widgets = computed(() => Object.values(widgetsMap.value));

  return {
    isConnected,
    widgets,
    latestSignal,
    signals,
    liveSystemState,
    managedStrategies,
    portfolioSummary,
    distributionAnalytics,
    latestDiscoveredStrategy,
    latestMarketTick,
    copilotMarkup,
  };
}
