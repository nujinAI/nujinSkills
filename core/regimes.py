"""
core/regimes.py - Canonical Market Regime Classification and Trade Breakdown.
Single Source of Truth for identifying market regimes (bull, bear, ranging)
and computing per-regime performance breakdown across backtests and live telemetry.
"""
from typing import Dict, List, Any
import numpy as np
import pandas as pd


def classify_market_regimes(df: pd.DataFrame, window: int = 50, band_pct: float = 0.002) -> Dict[int, str]:
    """
    Classifies each timestamp in an OHLCV dataframe into a market regime:
    - 'bull_market': close > SMA(window) * (1 + band_pct)
    - 'bear_market': close < SMA(window) * (1 - band_pct)
    - 'ranging_market': within band
    Returns a mapping of int timestamp -> regime string.
    """
    if df.empty or 'close' not in df.columns:
        return {}

    sma = df['close'].rolling(window).mean()
    regime_map: Dict[int, str] = {}

    for i, (idx, r) in enumerate(df.iterrows()):
        ts = int(r['timestamp']) if 'timestamp' in r else int(r.get('time', idx))
        c_val = float(r['close'])
        s_val = float(sma.iloc[i]) if not np.isnan(sma.iloc[i]) else c_val

        if c_val > s_val * (1.0 + band_pct):
            regime = "bull_market"
        elif c_val < s_val * (1.0 - band_pct):
            regime = "bear_market"
        else:
            regime = "ranging_market"
        regime_map[ts] = regime

    return regime_map


def compute_regime_breakdown(
    trades_detail: List[Dict[str, Any]],
    regime_map: Dict[int, str]
) -> Dict[str, Any]:
    """
    Assigns each trade to its entry market regime and generates equity curves,
    win rates, profit factors, and drawdowns partitioned by regime.
    """
    regime_trades: Dict[str, List[Dict[str, Any]]] = {
        "bull_market": [],
        "bear_market": [],
        "ranging_market": []
    }

    for tr in trades_detail:
        entry_time = tr.get("entry_time", 0)
        reg = regime_map.get(entry_time, "ranging_market")
        tr["regime"] = reg
        if reg in regime_trades:
            regime_trades[reg].append(tr)
        else:
            regime_trades.setdefault(reg, []).append(tr)

    regime_breakdown: Dict[str, Any] = {}
    for reg, tr_list in regime_trades.items():
        t_cnt = len(tr_list)
        if t_cnt > 0:
            arr_pnl = np.array([t.get("pnl_pct", 0.0) for t in tr_list], dtype=float)
            w_rate = float(np.mean(arr_pnl > 0))
            g_prof = float(np.sum(arr_pnl[arr_pnl > 0])) if np.any(arr_pnl > 0) else 0.0
            g_loss = float(np.abs(np.sum(arr_pnl[arr_pnl < 0]))) if np.any(arr_pnl < 0) else 0.0
            pf = round(min(g_prof / g_loss, 99.9), 2) if g_loss > 1e-4 else (99.9 if g_prof > 0 else 0.0)
            net_pnl = round(float(np.sum(arr_pnl)), 2)

            reg_eq = 100.0
            peak_reg_eq = 100.0
            max_reg_dd = 0.0
            reg_curve = [{
                "time": tr_list[0].get("entry_time", 0),
                "equity_pct": 100.0,
                "drawdown_pct": 0.0,
                "trade_num": 0
            }]

            for idx_t, tr in enumerate(tr_list, start=1):
                reg_eq += tr.get("pnl_pct", 0.0)
                peak_reg_eq = max(peak_reg_eq, reg_eq)
                dd_val = round(((peak_reg_eq - reg_eq) / peak_reg_eq) * 100.0, 2)
                max_reg_dd = max(max_reg_dd, dd_val)
                reg_curve.append({
                    "time": tr.get("exit_time", 0),
                    "equity_pct": round(reg_eq, 4),
                    "drawdown_pct": dd_val,
                    "pnl_pct": tr.get("pnl_pct", 0.0),
                    "trade_num": idx_t
                })

            regime_breakdown[reg] = {
                "trade_count": t_cnt,
                "win_rate": round(w_rate, 3),
                "profit_factor": pf,
                "net_pnl_pct": net_pnl,
                "peak_equity_pct": round(peak_reg_eq, 2),
                "max_drawdown_pct": round(max_reg_dd, 2),
                "equity_curve": reg_curve
            }
        else:
            regime_breakdown[reg] = {
                "trade_count": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "net_pnl_pct": 0.0,
                "peak_equity_pct": 100.0,
                "max_drawdown_pct": 0.0,
                "equity_curve": []
            }

    return regime_breakdown
