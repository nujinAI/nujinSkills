import { ref, computed } from 'vue';

export interface DrawdownStatus {
  status: string;
  reason: string;
  is_safe: boolean;
  strategy?: string;
  day_key?: string;
  initial_balance?: number;
  current_equity?: number;
  today_loss_usd?: number;
  today_realized_pnl_usd?: number;
  today_losses_count?: number;
  max_daily_loss_usd?: number;
  max_daily_dd_pct?: number;
  remaining_budget_usd?: number;
  single_trade_risk_usd?: number;
  message?: string;
}

export interface BrokerAccount {
  id: string;
  broker_id: string;
  label: string;
  environment: string;
  balance: number;
  initial_balance: number;
  is_active: boolean;
  login_masked: string;
}

const drawdownStatus = ref<DrawdownStatus | null>(null);
const brokerAccounts = ref<BrokerAccount[]>([]);
const loadingRisk = ref(false);

export function useRiskStatus() {
  const fetchRiskData = async () => {
    loadingRisk.value = true;
    try {
      const [ddRes, accRes] = await Promise.all([
        fetch('/api/risk/drawdown-status').catch(() => null),
        fetch('/api/brokers/accounts').catch(() => null),
      ]);

      if (ddRes && ddRes.ok) {
        drawdownStatus.value = await ddRes.json();
      }
      if (accRes && accRes.ok) {
        const data = await accRes.json();
        brokerAccounts.value = data.accounts || [];
      }
    } catch (e) {
      console.warn('[useRiskStatus] Error fetching risk data:', e);
    } finally {
      loadingRisk.value = false;
    }
  };

  const isSafe = computed(() => drawdownStatus.value?.is_safe ?? true);
  const remainingBudget = computed(() => drawdownStatus.value?.remaining_budget_usd ?? 0);
  const totalBalance = computed(() => {
    if (brokerAccounts.value.length > 0) {
      return brokerAccounts.value.reduce((sum, a) => sum + (a.balance || 0), 0);
    }
    return drawdownStatus.value?.current_equity ?? 0;
  });

  return {
    drawdownStatus,
    brokerAccounts,
    loadingRisk,
    isSafe,
    remainingBudget,
    totalBalance,
    fetchRiskData,
  };
}
