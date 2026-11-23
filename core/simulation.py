"""
core/simulation.py - The Single Source of Truth for Backtesting & Discrete Execution.
Pessimistic Intrabar Resolution: If a bar touches both Stop-Loss and Target,
Stop-Loss is ALWAYS assumed to trigger first. Zero lookahead bias.
"""
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import numpy as np
import pandas as pd
from core.friction import get_roundtrip_friction, compute_carry_cost
from core.analytics import compute_trade_records_summary


def resolve_strategy_close_eod(strat_inst: Any = None, symbol: Optional[str] = None, timeframe: Optional[str] = None) -> bool:
    """
    Universal, unbiased EOD exit resolver:
      - If the strategy explicitly declares `close_eod`, honor it verbatim.
      - Otherwise default to False (never silently force a 21:00 UTC exit on 24/7 crypto,
        swing strategies, or traders who did not opt into intraday EOD flattening).
    """
    if strat_inst is not None and hasattr(strat_inst, "close_eod"):
        val = getattr(strat_inst, "close_eod")
        if val is not None:
            return bool(val)
    return False


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
    symbol: Optional[str] = None,
    account_size: float = 5_000.0,
    dollar_risk_1r: Optional[float] = None,
    max_daily_losses: int = 2,
    daily_profit_cap: Optional[float] = None,
    max_hold_bars: int = 24,
    close_eod: bool = False,
    eod_close_hour_utc: int = 21,
    daily_carry_bps: float = 0.0,
    friction_override: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Simulates trades bar-by-bar against execution geometry with pessimistic resolution.
    signals DataFrame must contain:
    - 'entry_signal': 1 (Long), -1 (Short), 0 (Flat)
    - 'stop_loss': structural invalidation price
    - 'target': structural take profit price
    Optional columns for Limit/Pending Order execution:
    - 'limit_price': execution trigger price for resting limit order
    - 'limit_expiry_bars': maximum bars to wait for fill before auto-canceling (default: 3)
    - 'order_type': 'MARKET' or 'LIMIT' (defaults to 'LIMIT' if limit_price > 0 else 'MARKET')
    """
    if dollar_risk_1r is None or dollar_risk_1r <= 0:
        dollar_risk_1r = round(account_size * 0.0035, 2)

    trades: List[TradeRecord] = []
    current_position = None
    pending_order = None
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
    sig_limit = signals['limit_price'].values if 'limit_price' in signals.columns else np.zeros(len(df))
    sig_expiry = signals['limit_expiry_bars'].values if 'limit_expiry_bars' in signals.columns else np.zeros(len(df))
    sig_type = signals['order_type'].values if 'order_type' in signals.columns else np.array([""] * len(df))

    for i in range(len(df)):
        bar_time = times[i]
        bar_day = bar_time.date() if hasattr(bar_time, 'date') else bar_time

        if bar_day != current_day:
            current_day = bar_day
            daily_losses = 0
            daily_pnl = 0.0

        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        atr = atrs[i]

        # -------------------------------------------------------------
        # 1. Manage Active Position (if any)
        # -------------------------------------------------------------
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
            elif close_eod and hasattr(bar_time, 'hour') and bar_time.hour >= eod_close_hour_utc:
                exit_triggered = True
                exit_price = c
                exit_reason = "EOD"

            if exit_triggered:
                gross_diff = (exit_price - pos['entry_price']) * direction
                friction = get_roundtrip_friction(symbol, exit_price, atr, friction_override=friction_override)
                carry = 0.0
                if daily_carry_bps > 0.0 and hasattr(bar_time, "timestamp") and hasattr(pos['entry_time'], "timestamp"):
                    holding_hours = max(0.0, (bar_time.timestamp() - pos['entry_time'].timestamp()) / 3600.0)
                    carry = compute_carry_cost(exit_price, holding_hours, direction, daily_carry_bps=daily_carry_bps)
                net_price_diff = gross_diff - friction - carry

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

        # -------------------------------------------------------------
        # 2. Check Resting Pending Limit Order (if any and not in position)
        # -------------------------------------------------------------
        if current_position is None and pending_order is not None:
            # Check circuit breakers before filling pending order
            if daily_losses >= max_daily_losses or (daily_profit_cap and daily_pnl >= daily_profit_cap):
                pending_order = None
            else:
                p_dir = pending_order['direction']
                p_limit = pending_order['limit_price']
                p_sl = pending_order['stop_loss']
                p_tp = pending_order['target']
                p_units = pending_order['units']

                # Fill condition check:
                # Long limit fills if market traded down to or below limit price (l <= p_limit)
                # Short limit fills if market traded up to or above limit price (h >= p_limit)
                is_filled = (l <= p_limit) if p_dir == 1 else (h >= p_limit)

                if is_filled:
                    # Deterministic pessimistic limit execution:
                    # If bar opened better than limit (favorable gap), fill at open; otherwise fill at limit price.
                    # For Long: if open < limit, fill at open (favorable gap); else limit_price.
                    # For Short: if open > limit, fill at open (favorable gap); else limit_price.
                    fill_price = min(o, p_limit) if p_dir == 1 else max(o, p_limit)

                    current_position = {
                        'entry_time': bar_time,
                        'direction': p_dir,
                        'entry_price': fill_price,
                        'stop_loss': p_sl,
                        'target': p_tp,
                        'units': p_units,
                        'bars_held': 0
                    }
                    pending_order = None

                    # If filled intrabar, check if SL or TP was reached on the remainder of this fill bar
                    pos = current_position
                    sl_hit = (l <= p_sl) if p_dir == 1 else (h >= p_sl)
                    tp_hit = (h >= p_tp) if p_dir == 1 else (l <= p_tp)

                    exit_triggered = False
                    exit_price = 0.0
                    exit_reason = ""

                    if sl_hit and tp_hit:
                        exit_triggered = True
                        exit_price = p_sl
                        exit_reason = "SL"
                    elif sl_hit:
                        exit_triggered = True
                        exit_price = p_sl
                        exit_reason = "SL"
                    elif tp_hit:
                        exit_triggered = True
                        exit_price = p_tp
                        exit_reason = "TP"

                    if exit_triggered:
                        gross_diff = (exit_price - pos['entry_price']) * p_dir
                        friction = get_roundtrip_friction(symbol, exit_price, atr, friction_override=friction_override)
                        net_price_diff = gross_diff - friction

                        pnl_dollars = net_price_diff * pos['units']
                        pnl_r = pnl_dollars / dollar_risk_1r

                        trades.append(TradeRecord(
                            entry_time=pos['entry_time'],
                            exit_time=bar_time,
                            direction=p_dir,
                            entry_price=pos['entry_price'],
                            exit_price=exit_price,
                            stop_loss=p_sl,
                            target=p_tp,
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
                else:
                    # Pending order was not filled on this bar. Decrement expiration.
                    pending_order['bars_pending'] += 1
                    # Also invalidate pending order if structural SL was breached before fill
                    sl_breached = (l <= p_sl) if p_dir == 1 else (h >= p_sl)
                    if sl_breached or (pending_order['bars_pending'] >= pending_order['max_pending_bars']):
                        pending_order = None

        # -------------------------------------------------------------
        # 3. New Signal Generation (At Bar Close i, targeting bar i+1)
        # -------------------------------------------------------------
        if current_position is None and pending_order is None and i < len(df) - 1:
            if daily_losses >= max_daily_losses:
                continue
            if daily_profit_cap and daily_pnl >= daily_profit_cap:
                continue

            signal = sig_entry[i]
            if signal != 0:
                direction = int(signal)
                sl = float(sig_sl[i])
                tp = float(sig_tp[i])

                lim_p = float(sig_limit[i]) if (len(sig_limit) > i and not np.isnan(sig_limit[i])) else 0.0
                ord_t = str(sig_type[i]).upper() if (len(sig_type) > i and sig_type[i]) else ""
                is_limit = (ord_t == "LIMIT") or (lim_p > 0)

                if is_limit and lim_p > 0:
                    # Limit Order Setup:
                    # Long limit must be below or equal to current bar close; Short limit above or equal
                    stop_dist = abs(lim_p - sl)
                    if stop_dist > 0:
                        units = dollar_risk_1r / stop_dist
                        raw_expiry = int(sig_expiry[i]) if (len(sig_expiry) > i and sig_expiry[i] > 0) else 3
                        max_pending = max(1, min(100, raw_expiry))
                        pending_order = {
                            'order_time': times[i],
                            'direction': direction,
                            'limit_price': lim_p,
                            'stop_loss': sl,
                            'target': tp,
                            'units': units,
                            'bars_pending': 0,
                            'max_pending_bars': max_pending
                        }
                else:
                    # Standard Market Order Setup (Immediate fill at open of bar i+1)
                    entry_price = opens[i + 1]
                    stop_dist = abs(entry_price - sl)

                    if stop_dist > 0:
                        units = dollar_risk_1r / stop_dist
                        current_position = {
                            'entry_time': times[i + 1],
                            'direction': direction,
                            'entry_price': entry_price,
                            'stop_loss': sl,
                            'target': tp,
                            'units': units,
                            'bars_held': 0
                        }

    return compute_trade_records_summary(trades, account_size)
