"""
core/portfolio.py - The Single Source of Truth for Portfolio Correlation, Regime Orthogonality, and Ensemble Metrics.
Part of NujinSkills Quantitative System.
"""
from __future__ import annotations

import os
import sys
import logging
from typing import Dict, List, Any, Optional, Tuple
import numpy as np
import pandas as pd
from scipy.spatial.distance import squareform
from scipy.cluster.hierarchy import linkage, leaves_list

from core.data import fetch_ohlcv

logger = logging.getLogger("CorePortfolio")


def classify_market_regimes(df: pd.DataFrame, window: int = 96) -> pd.Series:
    """
    Classifies each bar into one of three market regimes:
    - 'BULL': Price above 200 EMA with positive 20-bar slope
    - 'BEAR': Price below 200 EMA with negative 20-bar slope
    - 'RANGE': Oscillating around baseline, ADX < 20 or low slope
    """
    close = df["close"]
    ema200 = close.ewm(span=min(200, len(df)), adjust=False).mean()
    slope = (ema200 - ema200.shift(20)) / ema200.shift(20)

    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum(
            abs(df["high"] - close.shift(1)),
            abs(df["low"] - close.shift(1))
        )
    )
    atr14 = tr.rolling(14).mean()
    up_move = df["high"] - df["high"].shift(1)
    down_move = df["low"].shift(1) - df["low"]
    pos_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    neg_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    pos_di = 100 * (pd.Series(pos_dm, index=df.index).rolling(14).mean() / (atr14 + 1e-8))
    neg_di = 100 * (pd.Series(neg_dm, index=df.index).rolling(14).mean() / (atr14 + 1e-8))
    dx = 100 * abs(pos_di - neg_di) / (pos_di + neg_di + 1e-8)
    adx = dx.rolling(14).mean()

    regimes = pd.Series("RANGE", index=df.index)
    regimes[(close > ema200) & (slope > 0.001) & (adx > 20)] = "BULL"
    regimes[(close < ema200) & (slope < -0.001) & (adx > 20)] = "BEAR"
    return regimes.bfill().fillna("RANGE")


def simulate_strategy_bar_returns(strategy_name: str, df: pd.DataFrame) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    """
    Instantiates a strategy and executes a discrete simulation to obtain bar-by-bar fractional returns.
    """
    from server.services.backtest_engine import load_strategy_instance
    from core.simulation import run_discrete_simulation

    strat_inst, symbol, timeframe, err = load_strategy_instance(strategy_name)
    n_bars = len(df)
    returns = np.zeros(n_bars, dtype=float)
    trades: List[Dict[str, Any]] = []

    if strat_inst is None:
        logger.warning(f"[CorePortfolio] Failed to load strategy {strategy_name}: {err}")
        return returns, trades

    try:
        df_eval = df.copy()
        if "timestamp" in df_eval.columns:
            df_eval["dt"] = pd.to_datetime(df_eval["timestamp"], unit="s", utc=True)
            df_eval = df_eval.set_index("dt")

        if hasattr(strat_inst, "compute_indicators"):
            df_eval = strat_inst.compute_indicators(df_eval)

        if hasattr(strat_inst, "generate_signals"):
            sig_df = strat_inst.generate_signals(df_eval)
            sim_res = run_discrete_simulation(
                df=df_eval,
                signals=sig_df,
                symbol=symbol or getattr(strat_inst, "symbol", "UNKNOWN"),
                account_size=5000.0,
                dollar_risk_1r=17.5,
                max_daily_losses=2,
                max_hold_bars=getattr(strat_inst, "max_hold_bars", 24),
                close_eod=True,
            )
            for t in sim_res.get("trades", []):
                trades.append({
                    "entry_time": t.entry_time,
                    "exit_time": t.exit_time,
                    "pnl_dollars": t.pnl_dollars,
                    "pnl_r": t.pnl_r,
                    "exit_reason": t.exit_reason,
                })
                # Map pnl to bar return array
                ret_frac = t.pnl_dollars / 5000.0
                returns[min(t.bars_held, n_bars - 1)] += ret_frac
    except Exception as e:
        logger.error(f"[CorePortfolio] Simulation failed for {strategy_name}: {e}")

    return returns, trades


def calculate_metrics(returns: np.ndarray) -> Dict[str, float]:
    """Computes foundational quantitative metrics from a return series."""
    if len(returns) == 0:
        return {"sharpe": 0.0, "total_return_pct": 0.0, "max_drawdown_pct": 0.0, "equity_r_squared": 0.0}

    mean_r = float(np.mean(returns))
    std_r = float(np.std(returns))
    sharpe = float((mean_r / (std_r + 1e-8)) * np.sqrt(35040)) if std_r > 1e-8 else 0.0

    cum_ret = np.cumsum(returns)
    peak = np.maximum.accumulate(cum_ret)
    dd = peak - cum_ret
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

    # Linearity standard R²
    x = np.arange(len(cum_ret))
    if len(x) > 2 and np.std(cum_ret) > 1e-8:
        corr_val = np.corrcoef(x, cum_ret)[0, 1]
        r_sq = float(corr_val ** 2) if not np.isnan(corr_val) else 0.0
    else:
        r_sq = 0.0

    return {
        "sharpe": round(sharpe, 2),
        "total_return_pct": round(float(np.sum(returns) * 100), 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "equity_r_squared": round(r_sq, 3),
    }


def compute_hrp_weights(ret_df: pd.DataFrame) -> Dict[str, float]:
    """Computes Hierarchical Risk Parity (HRP) weights from strategy return series."""
    cols = list(ret_df.columns)
    if not cols:
        return {}
    if len(cols) == 1:
        return {cols[0]: 1.0}

    cov = ret_df.cov().fillna(0.0).to_numpy(copy=True)
    corr = ret_df.corr().fillna(0.0).to_numpy(copy=True)
    np.fill_diagonal(corr, 1.0)
    dist = np.sqrt(np.clip((1.0 - corr) / 2.0, 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)

    try:
        condensed = squareform(dist, checks=False)
        link = linkage(condensed, method="single")
        sort_ix = list(leaves_list(link))
    except Exception:
        sort_ix = list(range(len(cols)))

    weights = np.ones(len(cols), dtype=float)

    def _cluster_var(c_indices: List[int]) -> float:
        sub_cov = cov[np.ix_(c_indices, c_indices)]
        ivp = 1.0 / np.maximum(np.diag(sub_cov), 1e-10)
        ivp /= ivp.sum()
        return float(np.dot(ivp, np.dot(sub_cov, ivp)))

    clusters = [sort_ix]
    while clusters:
        next_clusters = []
        for cluster in clusters:
            if len(cluster) > 1:
                mid = len(cluster) // 2
                left = cluster[:mid]
                right = cluster[mid:]
                var_l = _cluster_var(left)
                var_r = _cluster_var(right)
                alpha = 1.0 - var_l / max(var_l + var_r, 1e-12)
                weights[left] *= alpha
                weights[right] *= (1.0 - alpha)
                next_clusters.extend([left, right])
        clusters = next_clusters

    weights /= max(weights.sum(), 1e-12)
    return {cols[i]: round(float(weights[i]), 4) for i in range(len(cols))}


def evaluate_portfolio(
    strategy_names: Optional[List[str]] = None,
    data_path: str = "data/candles_15m.csv",
    correlation_threshold: float = 0.50
) -> Dict[str, Any]:
    """
    Evaluates candidate/active strategies against correlation and regime orthogonality.
    """
    if not strategy_names:
        strat_dir = "strategies"
        if os.path.exists(strat_dir):
            strategy_names = [f.replace(".py", "") for f in os.listdir(strat_dir) if f.endswith(".py") and not f.startswith("__")]
        else:
            strategy_names = []

    if not strategy_names:
        return {
            "strategies": [],
            "correlation_matrix": {},
            "spearman_matrix": {},
            "individual_metrics": {},
            "regime_breakdown": {},
            "portfolio_ensemble": {
                "blended_sharpe": 0.0,
                "blended_total_return_pct": 0.0,
                "blended_max_drawdown_pct": 0.0,
                "blended_r_squared": 0.0,
                "diversification_ratio": 1.0,
                "correlation_threshold": correlation_threshold
            },
            "pairwise_analysis": []
        }

    # Dynamic data retrieval
    candles = fetch_ohlcv("OANDA:XAUUSD", timeframe="15m", count=1500)
    if not candles:
        return {
            "strategies": strategy_names,
            "correlation_matrix": {},
            "spearman_matrix": {},
            "individual_metrics": {},
            "regime_breakdown": {},
            "portfolio_ensemble": {
                "blended_sharpe": 0.0,
                "blended_total_return_pct": 0.0,
                "blended_max_drawdown_pct": 0.0,
                "diversification_ratio": 1.0,
                "correlation_threshold": correlation_threshold
            },
            "pairwise_analysis": []
        }

    df = pd.DataFrame(candles)
    regimes = classify_market_regimes(df)

    strategy_returns: Dict[str, np.ndarray] = {}
    strategy_trades: Dict[str, List[Dict[str, Any]]] = {}
    individual_metrics: Dict[str, Any] = {}
    regime_breakdown: Dict[str, Any] = {}

    for s_name in strategy_names:
        ret, trades = simulate_strategy_bar_returns(s_name, df)
        strategy_returns[s_name] = ret
        strategy_trades[s_name] = trades
        individual_metrics[s_name] = calculate_metrics(ret)

        reg_metrics = {}
        for r_name in ["BULL", "BEAR", "RANGE"]:
            mask = (regimes == r_name).values
            r_ret = ret[mask]
            reg_metrics[r_name] = {
                "trades": len(trades),
                "pnl_pct": round(float(np.sum(r_ret) * 100), 2),
                "sharpe": round(float((np.mean(r_ret) / (np.std(r_ret) + 1e-8)) * np.sqrt(35040)), 2) if np.std(r_ret) > 1e-8 else 0.0
            }
        regime_breakdown[s_name] = reg_metrics

    ret_df = pd.DataFrame(strategy_returns)
    valid_cols = [c for c in ret_df.columns if ret_df[c].std() > 1e-8]
    if len(valid_cols) > 1:
        corr_matrix = ret_df[valid_cols].corr(method="pearson").round(3).to_dict()
        spearman_matrix = ret_df[valid_cols].corr(method="spearman").round(3).to_dict()
    else:
        corr_matrix = {c: {c: 1.0} for c in valid_cols}
        spearman_matrix = {c: {c: 1.0} for c in valid_cols}

    redundancy_flags = []
    for i, c1 in enumerate(valid_cols):
        for j, c2 in enumerate(valid_cols):
            if i < j:
                rho = corr_matrix.get(c1, {}).get(c2, 0.0)
                if rho > correlation_threshold:
                    redundancy_flags.append({
                        "pair": f"{c1} <-> {c2}",
                        "correlation": rho,
                        "status": "REDUNDANT",
                        "recommendation": f"High collinearity (rho={rho:.2f} > {correlation_threshold}). Running both doubles leverage during drawdowns without diversification benefits."
                    })
                elif rho < 0.15:
                    redundancy_flags.append({
                        "pair": f"{c1} <-> {c2}",
                        "correlation": rho,
                        "status": "COMPLEMENTARY",
                        "recommendation": f"Excellent regime orthogonality (rho={rho:.2f}). Highly complementary return stream."
                    })

    if valid_cols:
        hrp_weights = compute_hrp_weights(ret_df[valid_cols])
        w_vec = np.array([hrp_weights[c] for c in valid_cols], dtype=float)
        blended_returns = ret_df[valid_cols].values @ w_vec
        blended_metrics = calculate_metrics(blended_returns)

        indiv_vols = [ret_df[c].std() for c in valid_cols]
        blended_vol = float(np.std(blended_returns))
        div_ratio = round(float(np.dot(w_vec, indiv_vols) / (blended_vol + 1e-8)), 2)
    else:
        hrp_weights = {}
        blended_metrics = {"sharpe": 0.0, "total_return_pct": 0.0, "max_drawdown_pct": 0.0, "equity_r_squared": 0.0}
        div_ratio = 1.0

    return {
        "strategies": valid_cols,
        "correlation_matrix": corr_matrix,
        "spearman_matrix": spearman_matrix,
        "individual_metrics": individual_metrics,
        "regime_breakdown": regime_breakdown,
        "hrp_weights": hrp_weights,
        "portfolio_ensemble": {
            "blended_sharpe": blended_metrics["sharpe"],
            "blended_total_return_pct": blended_metrics["total_return_pct"],
            "blended_max_drawdown_pct": blended_metrics["max_drawdown_pct"],
            "blended_r_squared": blended_metrics.get("equity_r_squared", 0.0),
            "diversification_ratio": div_ratio,
            "hrp_weights": hrp_weights,
            "correlation_threshold": correlation_threshold
        },
        "pairwise_analysis": redundancy_flags
    }


def print_ascii_report(report: Dict[str, Any]) -> None:
    """Prints a structured ASCII report of the portfolio correlation & ensemble metrics."""
    strats = report.get("strategies", [])
    print("=" * 72)
    print("📊 PORTFOLIO CYNIC: CORRELATION & REGIME ORTHOGONALITY")
    print("=" * 72)
    if not strats:
        print("No active strategies found to evaluate.")
        print("=" * 72)
        return

    corr = report.get("correlation_matrix", {})
    header = f"{'Strategy':<24}" + "".join(f"{s[:8]:>10}" for s in strats)
    print(header)
    print("-" * len(header))
    for s1 in strats:
        row = f"{s1:<24}"
        for s2 in strats:
            val = corr.get(s1, {}).get(s2, 0.0)
            row += f"{val:>10.2f}"
        print(row)
    print("=" * 72)
