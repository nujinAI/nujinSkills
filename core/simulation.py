"""
core/simulation.py - The Single Source of Truth for Backtesting & Discrete Execution.
Pessimistic Intrabar Resolution: If a bar touches both Stop-Loss and Target,
Stop-Loss is ALWAYS assumed to trigger first. Zero lookahead bias.
"""
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd
from core.friction import get_roundtrip_friction

@dataclass
class TradeRecord:
    entry_time: Any
    exit_time: Any
    direction: int
    entry_price: float
    exit_price: float
    stop_loss: float
    target: float
    units: float
    dollar_risk_1r: float
    pnl_dollars: float
    pnl_r: float
    exit_reason: str
    bars_held: int

def run_discrete_simulation(
    df: pd.DataFrame,
    signals: pd.DataFrame,
    symbol: str = "OANDA:XAUUSD",
    account_size: float = 5_000.0,
    dollar_risk_1r: Optional[float] = None,
    max_daily_losses: int = 2,
    daily_profit_cap: Optional[float] = None,
    max_hold_bars: int = 24,
    close_eod: bool = True
) -> Dict[str, Any]:
    """
    Simulates trades bar-by-bar against execution geometry with pessimistic resolution.
    signals DataFrame must contain:
    - 'entry_signal': 1 (Long), -1 (Short), 0 (Flat)
    - 'stop_loss': structural invalidation price
    - 'target': structural take profit price
    """
    if dollar_risk_1r is None or dollar_risk_1r <= 0:
        dollar_risk_1r = round(account_size * 0.0035, 2)

    trades: List[TradeRecord] = []
    current_position = None
    daily_losses = 0
    daily_pnl = 0.0
    current_day = None

    times = df.index
    opens = df['open'].values
    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values
    atrs = df['atr'].values if 'atr' in df.columns else np.zeros(len(df))

    sig_entry = signals['entry_signal'].values if 'entry_signal' in signals.columns else np.zeros(len(df))
    sig_sl = signals['stop_loss'].values if 'stop_loss' in signals.columns else np.zeros(len(df))
    sig_tp = signals['target'].values if 'target' in signals.columns else np.zeros(len(df))

    for i in range(len(df)):
        bar_time = times[i]
        bar_day = bar_time.date() if hasattr(bar_time, 'date') else bar_time

        if bar_day != current_day:
            current_day = bar_day
            daily_losses = 0
            daily_pnl = 0.0

        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        atr = atrs[i]

        if current_position is not None:
            pos = current_position
            pos['bars_held'] += 1
            direction = pos['direction']
            sl = pos['stop_loss']
            tp = pos['target']

            sl_hit = (l <= sl) if direction == 1 else (h >= sl)
            tp_hit = (h >= tp) if direction == 1 else (l <= tp)

            exit_triggered = False
            exit_price = 0.0
            exit_reason = ""

            # Pessimistic Resolution: SL always triggers first on same-bar collision
            if sl_hit and tp_hit:
                exit_triggered = True
                exit_price = sl
                exit_reason = "SL"
            elif sl_hit:
                exit_triggered = True
                exit_price = sl
                exit_reason = "SL"
            elif tp_hit:
                exit_triggered = True
                exit_price = tp
                exit_reason = "TP"
            elif pos['bars_held'] >= max_hold_bars:
                exit_triggered = True
                exit_price = c
                exit_reason = "TIME_STOP"
            elif close_eod and hasattr(bar_time, 'hour') and bar_time.hour >= 21:
                exit_triggered = True
                exit_price = c
                exit_reason = "EOD"

            if exit_triggered:
                gross_diff = (exit_price - pos['entry_price']) * direction
                friction = get_roundtrip_friction(symbol, exit_price, atr)
                net_price_diff = gross_diff - friction

                pnl_dollars = net_price_diff * pos['units']
                pnl_r = pnl_dollars / dollar_risk_1r

                trades.append(TradeRecord(
                    entry_time=pos['entry_time'],
                    exit_time=bar_time,
                    direction=direction,
                    entry_price=pos['entry_price'],
                    exit_price=exit_price,
                    stop_loss=sl,
                    target=tp,
                    units=pos['units'],
                    dollar_risk_1r=dollar_risk_1r,
                    pnl_dollars=pnl_dollars,
                    pnl_r=pnl_r,
                    exit_reason=exit_reason,
                    bars_held=pos['bars_held']
                ))

                daily_pnl += pnl_dollars
                if pnl_dollars < 0:
                    daily_losses += 1

                current_position = None

        if current_position is None and i < len(df) - 1:
            if daily_losses >= max_daily_losses:
                continue
            if daily_profit_cap and daily_pnl >= daily_profit_cap:
                continue

            signal = sig_entry[i]
            if signal != 0:
                entry_price = opens[i + 1]
                sl = sig_sl[i]
                tp = sig_tp[i]
                stop_dist = abs(entry_price - sl)

                if stop_dist > 0:
                    units = dollar_risk_1r / stop_dist
                    current_position = {
                        'entry_time': times[i + 1],
                        'direction': int(signal),
                        'entry_price': entry_price,
                        'stop_loss': sl,
                        'target': tp,
                        'units': units,
                        'bars_held': 0
                    }

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
