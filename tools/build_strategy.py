#!/usr/bin/env python3
"""
tools/build_strategy.py - Deterministic Quantitative Strategy Synthesizer.

Automates the translation of a verified statistical edge (from scan_edge.py)
into a production-grade strategy file with strict 1R risk geometry,
<= 3 structural parameters, and objective invalidation.

Prevents the AI from hallucinating boilerplate or cloning old strategies.

Usage:
    python tools/build_strategy.py \
        --name TrendMomentumAlpha \
        --symbol OANDA:XAUUSD \
        --tf 5m \
        --feature momentum_roc_20 \
        --archetype momentum \
        --sl-mult 1.5 \
        --tp-mult 2.5 \
        --risk-pct 0.0035
"""
import os
import sys
import argparse

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
WORKSPACE_ROOT = os.path.abspath(os.path.join(PROJECT_ROOT, ".."))

STRATEGY_TEMPLATE = '''"""
{name}.py - Synthesized Quantitative Alpha Model.
Generated automatically by tools/build_strategy.py from verified empirical edge: {feature}.
Asset: {symbol} | Timeframe: {tf} | Archetype: {archetype}
"""
from typing import Any
import numpy as np
import pandas as pd


class {name}:
    symbol: str = "{symbol}"
    timeframe: str = "{tf}"

    def __init__(
        self,
        risk_pct_1r: float = {risk_pct},
        sl_atr_mult: float = {sl_mult},
        tp_atr_mult: float = {tp_mult},
        lookback: int = {lookback},
        **kwargs: Any
    ):
        self.risk_pct_1r = float(risk_pct_1r)
        self.sl_atr_mult = float(sl_atr_mult)
        self.tp_atr_mult = float(tp_atr_mult)
        self.lookback = int(lookback)

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        data = df.copy()
        if not isinstance(data.index, pd.DatetimeIndex):
            data.index = pd.to_datetime(data.index, utc=True)
        elif data.index.tz is None:
            data.index = data.index.tz_localize("UTC")
        else:
            data.index = data.index.tz_convert("UTC")

        # True Range & ATR for objective volatility stop
        high = data["high"].astype(float)
        low = data["low"].astype(float)
        close = data["close"].astype(float)
        tr = np.maximum(
            high - low,
            np.maximum((high - close.shift(1)).abs(), (low - close.shift(1)).abs())
        )
        data["atr"] = tr.rolling(14).mean().bfill()

        # Feature calculation based on archetype
        {indicator_calculation}

        return data

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        data = self.compute_indicators(df)
        signals = pd.DataFrame(index=data.index)
        signals["entry_signal"] = 0
        signals["stop_loss"] = 0.0
        signals["target"] = 0.0

        close = data["close"].astype(float)
        atr = data["atr"].astype(float)

        {signal_logic}

        # Long assignments
        signals.loc[long_cond, "entry_signal"] = 1
        signals.loc[long_cond, "stop_loss"] = close[long_cond] - (self.sl_atr_mult * atr[long_cond])
        signals.loc[long_cond, "target"] = close[long_cond] + (self.tp_atr_mult * atr[long_cond])

        # Short assignments
        signals.loc[short_cond, "entry_signal"] = -1
        signals.loc[short_cond, "stop_loss"] = close[short_cond] + (self.sl_atr_mult * atr[short_cond])
        signals.loc[short_cond, "target"] = close[short_cond] - (self.tp_atr_mult * atr[short_cond])

        return signals
'''


def parse_args():
    parser = argparse.ArgumentParser(description="Synthesize Quantitative Alpha Strategy")
    parser.add_argument("--name", type=str, required=True, help="Strategy class name (e.g. TrendMomentumAlpha)")
    parser.add_argument("--symbol", type=str, default="OANDA:XAUUSD", help="Asset ticker")
    parser.add_argument("--tf", type=str, default="5m", help="Timeframe")
    parser.add_argument("--feature", type=str, default="momentum_roc_20", help="Feature name from scan_edge.py")
    parser.add_argument("--archetype", type=str, choices=["momentum", "mean_reversion", "range_breakout"], default="momentum")
    parser.add_argument("--lookback", type=int, default=20, help="Feature lookback window")
    parser.add_argument("--sl-mult", type=float, default=1.5, help="Stop loss ATR multiplier")
    parser.add_argument("--tp-mult", type=float, default=2.5, help="Take profit ATR multiplier")
    parser.add_argument("--risk-pct", type=float, default=0.0035, help="Risk percentage per trade (e.g. 0.0035 for 0.35%%)")
    return parser.parse_args()


def main():
    args = parse_args()

    # Determine code blocks based on archetype
    if args.archetype == "momentum":
        ind_code = f"""data["feat"] = (close - close.shift(self.lookback)) / (close.shift(self.lookback) + 1e-8)
        data["feat_ma"] = data["feat"].rolling(self.lookback * 2).mean()
        data["feat_std"] = data["feat"].rolling(self.lookback * 2).std()"""
        sig_code = """z_score = (data["feat"] - data["feat_ma"]) / (data["feat_std"] + 1e-8)
        long_cond = (z_score > 1.2) & (z_score.shift(1) <= 1.2)
        short_cond = (z_score < -1.2) & (z_score.shift(1) >= -1.2)"""

    elif args.archetype == "mean_reversion":
        ind_code = f"""sma = close.rolling(self.lookback).mean()
        std = close.rolling(self.lookback).std()
        data["feat"] = (close - sma) / (std + 1e-8)"""
        sig_code = """feat = data["feat"]
        long_cond = (feat < -2.0) & (feat.shift(1) >= -2.0)
        short_cond = (feat > 2.0) & (feat.shift(1) <= 2.0)"""

    else:  # range_breakout
        ind_code = f"""data["hh"] = high.rolling(self.lookback).max().shift(1)
        data["ll"] = low.rolling(self.lookback).min().shift(1)"""
        sig_code = """long_cond = (close > data["hh"]) & (close.shift(1) <= data["hh"].shift(1))
        short_cond = (close < data["ll"]) & (close.shift(1) >= data["ll"].shift(1))"""

    content = STRATEGY_TEMPLATE.format(
        name=args.name,
        symbol=args.symbol,
        tf=args.tf,
        feature=args.feature,
        archetype=args.archetype,
        risk_pct=args.risk_pct,
        sl_mult=args.sl_mult,
        tp_mult=args.tp_mult,
        lookback=args.lookback,
        indicator_calculation=ind_code,
        signal_logic=sig_code
    )

    # Destination paths
    alpha_dir = os.path.join(WORKSPACE_ROOT, "zillionsAlpha", "strategies")
    os.makedirs(alpha_dir, exist_ok=True)
    strategy_path = os.path.join(alpha_dir, f"{args.name}.py")

    with open(strategy_path, "w") as f:
        f.write(content)
    print(f"[+] Created strategy source: {strategy_path}")

    # Symlink to nujinSkills/strategies
    skills_strat_dir = os.path.join(PROJECT_ROOT, "strategies")
    os.makedirs(skills_strat_dir, exist_ok=True)
    symlink_path = os.path.join(skills_strat_dir, f"{args.name}.py")
    if os.path.exists(symlink_path) or os.path.islink(symlink_path):
        os.remove(symlink_path)

    rel_source = os.path.relpath(strategy_path, skills_strat_dir)
    os.symlink(rel_source, symlink_path)
    print(f"[+] Symlinked to engine: {symlink_path}")
    print(f"[+] Ready to audit: python tools/run_backtest_audit.py --strategy {args.name}.py --days 30")


if __name__ == "__main__":
    main()
