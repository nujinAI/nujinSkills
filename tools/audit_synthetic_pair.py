#!/usr/bin/env python3
"""
Institutional Cynic Auditor for Synthetic Pair Trading Engine
Tests IceRatioMeanReversionEngine against Goat Funded Trader prop-firm parameters:
- 5% Max Trailing Drawdown
- 3% Max Daily Drawdown
- 1% Max Floating Loss
- 15% Consistency Rule
"""
import sys
import os
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath("nujinSkills"))
from core.data import fetch_candles_via_tv

def run_prop_audit():
    curr_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.abspath(os.path.join(curr_dir, "..", "..", "zillionsAlpha", "strategies")),
        os.path.abspath(os.path.join(curr_dir, "..", "strategies")),
    ]
    for cand in candidates:
        if os.path.exists(cand) and cand not in sys.path:
            sys.path.insert(0, cand)
    try:
        from IceRatioMeanReversionEngine import IceRatioMeanReversionEngine
    except ImportError as e:
        print(f"Failed to import IceRatioMeanReversionEngine: {e}")
        return
    candles = fetch_candles_via_tv(symbol="TVC:BTCXAU", timeframe="1h", count=1800)
    if not candles:
        print("Failed to fetch ICE data.")
        return

    df = pd.DataFrame(candles)
    df["dt"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df.set_index("dt", inplace=True)

    strat = IceRatioMeanReversionEngine(risk_pct_1r=0.0025, lookback=20, z_threshold=1.75)
    signals = strat.generate_signals(df)
    df = df.join(signals)

    # Simulate Pessimistic Intrabar Execution
    account_size = 100000.0  # $100k Goat Funded Account
    equity = account_size
    peak_equity = account_size
    daily_equity_start = account_size
    current_day = None

    trades = []
    daily_pnl = {}
    in_pos = False
    pos_dir = 0
    pos_entry = 0.0
    pos_sl = 0.0
    pos_tp = 0.0
    pos_entry_time = None
    pos_dollar_risk = 0.0

    max_dd = 0.0
    max_daily_dd = 0.0
    max_floating_loss = 0.0

    friction_bps = 0.0006  # 6 bps total roundtrip synthetic friction

    for i in range(len(df)):
        bar = df.iloc[i]
        bar_date = bar.name.date()

        # Daily tracking
        if current_day != bar_date:
            current_day = bar_date
            daily_equity_start = equity
            daily_pnl[str(bar_date)] = 0.0

        # Intrabar position tracking
        if in_pos:
            # Pessimistic intrabar evaluation: Check SL first!
            if pos_dir == 1:
                floating_pnl_low = (bar["low"] - pos_entry) / pos_entry
                floating_dollar_loss = floating_pnl_low * (pos_dollar_risk / (abs(pos_entry - pos_sl) / pos_entry))
                floating_loss_pct = abs(min(0.0, floating_dollar_loss)) / equity
                max_floating_loss = max(max_floating_loss, floating_loss_pct)

                if bar["low"] <= pos_sl:
                    # SL Hit
                    loss_dollar = -pos_dollar_risk - (pos_dollar_risk * friction_bps)
                    equity += loss_dollar
                    daily_pnl[str(bar_date)] += loss_dollar
                    trades.append({"type": "SL", "pnl": loss_dollar, "r": -1.0, "time": bar.name})
                    in_pos = False
                elif bar["high"] >= pos_tp:
                    # TP Hit
                    reward_mult = abs(pos_tp - pos_entry) / abs(pos_entry - pos_sl)
                    win_dollar = (pos_dollar_risk * reward_mult) - (pos_dollar_risk * friction_bps)
                    equity += win_dollar
                    daily_pnl[str(bar_date)] += win_dollar
                    trades.append({"type": "TP", "pnl": win_dollar, "r": reward_mult, "time": bar.name})
                    in_pos = False
                elif bar.name.hour >= 20: # Daily session close (force flatten)
                    pnl_dollar = ((bar["close"] - pos_entry) / abs(pos_entry - pos_sl)) * pos_dollar_risk - (pos_dollar_risk * friction_bps)
                    equity += pnl_dollar
                    daily_pnl[str(bar_date)] += pnl_dollar
                    trades.append({"type": "EOD", "pnl": pnl_dollar, "r": pnl_dollar / pos_dollar_risk, "time": bar.name})
                    in_pos = False

            elif pos_dir == -1:
                floating_pnl_high = (pos_entry - bar["high"]) / pos_entry
                floating_dollar_loss = floating_pnl_high * (pos_dollar_risk / (abs(pos_sl - pos_entry) / pos_entry))
                floating_loss_pct = abs(min(0.0, floating_dollar_loss)) / equity
                max_floating_loss = max(max_floating_loss, floating_loss_pct)

                if bar["high"] >= pos_sl:
                    # SL Hit
                    loss_dollar = -pos_dollar_risk - (pos_dollar_risk * friction_bps)
                    equity += loss_dollar
                    daily_pnl[str(bar_date)] += loss_dollar
                    trades.append({"type": "SL", "pnl": loss_dollar, "r": -1.0, "time": bar.name})
                    in_pos = False
                elif bar["low"] <= pos_tp:
                    # TP Hit
                    reward_mult = abs(pos_entry - pos_tp) / abs(pos_sl - pos_entry)
                    win_dollar = (pos_dollar_risk * reward_mult) - (pos_dollar_risk * friction_bps)
                    equity += win_dollar
                    daily_pnl[str(bar_date)] += win_dollar
                    trades.append({"type": "TP", "pnl": win_dollar, "r": reward_mult, "time": bar.name})
                    in_pos = False
                elif bar.name.hour >= 20: # Daily session close
                    pnl_dollar = ((pos_entry - bar["close"]) / abs(pos_sl - pos_entry)) * pos_dollar_risk - (pos_dollar_risk * friction_bps)
                    equity += pnl_dollar
                    daily_pnl[str(bar_date)] += pnl_dollar
                    trades.append({"type": "EOD", "pnl": pnl_dollar, "r": pnl_dollar / pos_dollar_risk, "time": bar.name})
                    in_pos = False

        # Peak & Drawdown
        peak_equity = max(peak_equity, equity)
        dd = (peak_equity - equity) / peak_equity
        max_dd = max(max_dd, dd)

        daily_dd = max(0.0, (daily_equity_start - equity) / daily_equity_start)
        max_daily_dd = max(max_daily_dd, daily_dd)

        # New Entry Signal
        if not in_pos and bar["entry_signal"] != 0 and bar.name.hour < 18:
            in_pos = True
            pos_dir = int(bar["entry_signal"])
            pos_entry = float(bar["close"])
            pos_sl = float(bar["stop_loss"])
            pos_tp = float(bar["target"])
            pos_entry_time = bar.name
            pos_dollar_risk = equity * strat.risk_pct_1r

    trades_df = pd.DataFrame(trades)
    total_trades = len(trades_df)
    win_trades = len(trades_df[trades_df["pnl"] > 0]) if total_trades > 0 else 0
    win_rate = (win_trades / total_trades) * 100 if total_trades > 0 else 0.0
    net_pnl = equity - account_size
    profit_pct = (net_pnl / account_size) * 100

    daily_s = pd.Series(daily_pnl)
    profitable_days_05 = len(daily_s[daily_s >= (account_size * 0.005)])
    max_day_profit = daily_s.max() if len(daily_s) > 0 else 0.0
    consistency_pct = (max_day_profit / max(1.0, net_pnl)) * 100 if net_pnl > 0 else 0.0

    print("=" * 60)
    print("GOAT FUNDED TRADER INSTITUTIONAL CYNIC AUDIT REPORT")
    print("Strategy: IceRatioMeanReversionEngine | TVC:BTCXAU (1H)")
    print("=" * 60)
    print(f"Total Completed Trades:      {total_trades}")
    print(f"Win Rate:                    {win_rate:.1f}%")
    print(f"Net Profit:                  ${net_pnl:,.2f} ({profit_pct:.2f}%)")
    print(f"Max Overall Drawdown:        {max_dd*100:.2f}% (Limit: 5.00%) -> {'PASS' if max_dd <= 0.05 else 'FAIL'}")
    print(f"Max Daily Drawdown:          {max_daily_dd*100:.2f}% (Limit: 3.00%) -> {'PASS' if max_daily_dd <= 0.03 else 'FAIL'}")
    print(f"Max Floating Loss:           {max_floating_loss*100:.2f}% (Limit: 1.00%) -> {'PASS' if max_floating_loss <= 0.01 else 'FAIL'}")
    print(f"Profitable Days (>= 0.5%):   {profitable_days_05} days (Req: 6 days) -> {'PASS' if profitable_days_05 >= 6 else 'ONGOING'}")
    print(f"Consistency Score:           {consistency_pct:.1f}% (Rule: < 15.00% single day) -> {'PASS' if consistency_pct <= 15.0 else 'NEEDS_SMOOTHING'}")
    print("=" * 60)

if __name__ == "__main__":
    run_prop_audit()
