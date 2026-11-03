"""
core/analytics.py - Canonical Quantitative Analytics & Post-Trade Metrics.
Single Source of Truth for computing equity curves, adaptive return distribution
histograms, multi-tier account growth models ($5k - $100k), and summary statistics.
"""
from typing import Dict, List, Any, Optional
import numpy as np
from server.constants import trade_annualization_factor


def compute_trade_records_summary(trades: List[Any], account_size: float = 5000.0) -> Dict[str, Any]:
    """
    Computes summary metrics directly from TradeRecord dataclass instances.
    Used by core.simulation to avoid duplicating metric, drawdown, and win-rate formulas.
    """
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "net_pnl_dollars": 0.0,
            "net_pnl_r": 0.0,
            "trades": []
        }

    r_multiples = np.array([t.pnl_r for t in trades])
    dollar_pnls = np.array([t.pnl_dollars for t in trades])
    wins = dollar_pnls[dollar_pnls > 0]
    losses = dollar_pnls[dollar_pnls < 0]

    win_rate = len(wins) / len(dollar_pnls)
    gross_win = wins.sum() if len(wins) > 0 else 0.0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 1e-9
    profit_factor = gross_win / gross_loss

    equity_curve = np.cumsum(dollar_pnls) + account_size
    peak = np.maximum.accumulate(equity_curve)
    drawdowns = (peak - equity_curve) / peak
    max_dd_pct = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

    return {
        "total_trades": len(trades),
        "win_rate": round(float(win_rate), 4),
        "profit_factor": round(float(profit_factor), 2),
        "net_pnl_dollars": round(float(dollar_pnls.sum()), 2),
        "net_pnl_r": round(float(r_multiples.sum()), 2),
        "expectancy_r": round(float(np.mean(r_multiples)), 3),
        "max_drawdown_pct": round(max_dd_pct, 4),
        "trades": trades
    }


def compute_summary_metrics(
    trades_detail: List[Dict[str, Any]],
    account_size: float = 5000.0,
    time_info: Optional[Dict[str, Any]] = None,
    dsr: float = 0.0,
    mdd_99: float = 0.0
) -> Dict[str, Any]:
    """
    Computes canonical summary statistics from a list of simulated trade details.
    """
    if not trades_detail:
        return {
            "sharpe": 0.0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
            "mdd_99": 0.0,
            "dsr": 0.0,
            "trades": 0,
            "profit_factor": 0.0,
            "expectancy_bps": 0.0,
            "account_size": account_size,
            "net_pnl_dollars": 0.0,
            "net_pnl": 0.0,
            "net_pnl_pct": 0.0,
        }

    returns_arr = np.array([tr.get("pnl_pct", 0.0) / 100.0 for tr in trades_detail], dtype=float)
    trade_count = len(returns_arr)
    win_rate = float(np.mean(returns_arr > 0))
    gross_profit = float(np.sum(returns_arr[returns_arr > 0])) if np.any(returns_arr > 0) else 0.0
    gross_loss = float(np.abs(np.sum(returns_arr[returns_arr < 0]))) if np.any(returns_arr < 0) else 0.0
    profit_factor = round(min(gross_profit / gross_loss, 99.9), 2) if gross_loss > 1e-4 else (99.9 if gross_profit > 0 else 0.0)

    cum_ret = np.cumsum(returns_arr)
    peak = np.maximum.accumulate(cum_ret)
    dd = peak - cum_ret
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0.015

    mean_ret = float(np.mean(returns_arr))
    std_ret = float(np.std(returns_arr))
    sharpe = float((mean_ret / max(std_ret, 1e-6)) * trade_annualization_factor())
    expectancy_bps = float(mean_ret * 10000.0)

    net_pnl_dollars = round(float(sum(tr.get("pnl_dollars", 0.0) for tr in trades_detail)), 2)
    net_pnl_pct = round(float(sum(tr.get("pnl_pct", 0.0) for tr in trades_detail)), 4)

    summary = {
        "sharpe": round(sharpe, 2),
        "win_rate": round(win_rate, 3),
        "max_drawdown": round(max_dd, 4),
        "mdd_99": mdd_99,
        "dsr": dsr,
        "trades": trade_count,
        "profit_factor": profit_factor,
        "expectancy_bps": round(expectancy_bps, 2),
        "account_size": account_size,
        "net_pnl_dollars": net_pnl_dollars,
        "net_pnl": net_pnl_dollars,
        "net_pnl_pct": net_pnl_pct,
    }

    if time_info:
        summary.update({
            "start_time": time_info.get("start_time"),
            "end_time": time_info.get("end_time"),
            "start_date": time_info.get("start_date"),
            "end_date": time_info.get("end_date"),
            "duration_days": time_info.get("duration_days"),
            "period_label": time_info.get("period_label"),
            "candles_count": time_info.get("candles_count"),
            "provider_max_reached": time_info.get("provider_max_reached", False),
        })

    return summary


def compute_equity_curve(trades_detail: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Computes a progressive percentage equity curve and drawdown series.
    """
    if not trades_detail:
        return []

    curr_equity = 100.0
    peak_equity = 100.0
    equity_curve = [{
        "time": trades_detail[0].get("entry_time", 0),
        "equity_pct": 100.0,
        "drawdown_pct": 0.0
    }]

    for tr in trades_detail:
        curr_equity += tr.get("pnl_pct", 0.0)
        peak_equity = max(peak_equity, curr_equity)
        dd_pct = round(((peak_equity - curr_equity) / peak_equity) * 100.0, 2)
        equity_curve.append({
            "time": tr.get("exit_time", 0),
            "equity_pct": round(curr_equity, 4),
            "drawdown_pct": dd_pct
        })

    return equity_curve


def compute_return_distribution(pnl_pcts: List[float]) -> List[Dict[str, Any]]:
    """
    Computes adaptive histogram bins for trade return percentage distribution
    scaled dynamically by sample standard deviation.
    """
    if not pnl_pcts:
        return []

    std_pnl = float(np.std(pnl_pcts)) if len(pnl_pcts) > 1 else 1.0
    step = round(max(0.05, std_pnl * 0.75), 2)
    bins_def = [
        {"bin_label": f"<-{2*step:.2f}%", "min": -999.0, "max": -2*step, "win": False},
        {"bin_label": f"-{2*step:.2f}% to -{step:.2f}%", "min": -2*step, "max": -step, "win": False},
        {"bin_label": f"-{step:.2f}% to 0%", "min": -step, "max": 0.0, "win": False},
        {"bin_label": f"0% to +{step:.2f}%", "min": 0.0, "max": step, "win": True},
        {"bin_label": f"+{step:.2f}% to +{2*step:.2f}%", "min": step, "max": 2*step, "win": True},
        {"bin_label": f">+{2*step:.2f}%", "min": 2*step, "max": 999.0, "win": True}
    ]

    return_distribution = []
    for b in bins_def:
        cnt = sum(1 for p in pnl_pcts if b["min"] <= p < b["max"])
        return_distribution.append({
            "bin_label": b["bin_label"],
            "count": cnt,
            "win": b["win"]
        })

    return return_distribution


def compute_account_growth_models(
    trades_detail: List[Dict[str, Any]],
    account_size: float = 5000.0,
    account_tiers: Optional[List[int]] = None,
    account_mult: float = 1.0
) -> Dict[str, Any]:
    """
    Projects cumulative account growth and drawdown across standard prop firm / institutional
    balance tiers ($5k, $10k, $25k, $50k, $100k).
    """
    if account_tiers is None:
        account_tiers = [5000, 10000, 25000, 50000, 100000]

    account_growth_models: Dict[str, Any] = {}
    if not trades_detail:
        return {"account_tiers": {}, "benchmark_tier": int(account_size)}

    for tier in account_tiers:
        tier_bal = float(tier)
        peak_b = tier_bal
        tier_curve = [{
            "time": trades_detail[0].get("entry_time", 0),
            "equity_pct": 100.0,
            "drawdown_pct": 0.0,
            "balance": tier_bal
        }]
        max_dd_tier = 0.0

        for tr in trades_detail:
            scaled_trade_pct = tr.get("pnl_pct", 0.0) * account_mult
            trade_dollar = float(tier) * (scaled_trade_pct / 100.0)
            tier_bal += trade_dollar
            peak_b = max(peak_b, tier_bal)
            dd_val = round(((peak_b - tier_bal) / peak_b) * 100.0, 2)
            max_dd_tier = max(max_dd_tier, dd_val)
            tier_curve.append({
                "time": tr.get("exit_time", 0),
                "equity_pct": round((tier_bal / float(tier)) * 100.0, 4),
                "drawdown_pct": dd_val,
                "balance": round(tier_bal, 2),
                "profit_dollars": round(tier_bal - float(tier), 2)
            })

        account_growth_models[str(tier)] = {
            "account_size": tier,
            "final_balance": round(tier_bal, 2),
            "net_growth_pct": round(((tier_bal - float(tier)) / float(tier)) * 100.0, 2),
            "net_profit_dollars": round(tier_bal - float(tier), 2),
            "max_drawdown_pct": round(max_dd_tier, 2),
            "equity_curve": tier_curve
        }

    bench_tier_str = str(int(account_size)) if str(int(account_size)) in account_growth_models else "5000"
    benchmark_model = account_growth_models.get(bench_tier_str, account_growth_models.get("5000", {}))
    net_pnl_dollars = round(float(sum(tr.get("pnl_dollars", 0.0) for tr in trades_detail)), 2)
    net_pnl_pct = round(float(sum(tr.get("pnl_pct", 0.0) for tr in trades_detail)), 4)

    return {
        "benchmark_tier": int(account_size),
        "net_growth_pct": benchmark_model.get("net_growth_pct", net_pnl_pct),
        "net_profit_dollars": benchmark_model.get("net_profit_dollars", net_pnl_dollars),
        "max_drawdown_pct": benchmark_model.get("max_drawdown_pct", 0.0),
        "account_tiers": account_growth_models
    }
