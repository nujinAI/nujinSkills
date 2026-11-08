# Strategy Interface & Fast-Path Deployment

This document provides the canonical code contract for authoring strategies and deploying them into the NujinSkills engine.

---

## 1. Strategy Interface Contract

A strategy file must define a single class whose name matches its filename (e.g. `class GoldAsiaLiquiditySweep` in `GoldAsiaLiquiditySweep.py`).

### Rules:
- **Zero Hardcoded Capital:** Never hardcode dollar balances ($) or static lot quantities.
- **Risk Percentage Only:** Define `risk_pct_1r` as a fraction (e.g., `0.0035` for 0.35%, `0.01` for 1.0%).
- **Metadata Required:** Must declare `symbol` and `timeframe` as class attributes.

### Sizing Mechanism:
$$\text{Dollar Risk} = \text{Balance} \times \text{Strategy Risk\%}$$
$$\text{Lots} = \frac{\text{Dollar Risk}}{|\text{Entry} - \text{Stop Loss}| \times 100}$$

---

## 2. Canonical Strategy Skeleton

```python
from typing import Any
import pandas as pd


class NewStrategyName:
    """
    [Strategy Display Name]
    [Summary of core structural edge, execution windows, and invalidation criteria].
    """

    symbol: str = "OANDA:XAUUSD"
    timeframe: str = "5m"

    def __init__(
        self,
        risk_pct_1r: float = 0.0035,        # 0.35% prop-firm or 1.0% growth mode
        sl_atr_mult: float = 1.5,
        tp_atr_mult: float = 3.5,
        **kwargs: Any
    ):
        self.risk_pct_1r = risk_pct_1r
        self.sl_atr_mult = sl_atr_mult
        self.tp_atr_mult = tp_atr_mult

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculates indicators and structural levels."""
        data = df.copy()
        if not isinstance(data.index, pd.DatetimeIndex):
            data.index = pd.to_datetime(data.index, utc=True)
        elif data.index.tz is None:
            data.index = data.index.tz_localize("UTC")
        else:
            data.index = data.index.tz_convert("UTC")

        # Vectorized calculations (ATR, session highs/lows, VWAP, etc.)
        return data

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Returns DataFrame with strictly 3 columns:
        - entry_signal: 1 (Long), -1 (Short), 0 (Neutral)
        - stop_loss: Float level (must be non-zero when entry_signal != 0)
        - target: Float level (must be non-zero when entry_signal != 0)
        """
        data = self.compute_indicators(df)
        signals = pd.DataFrame(index=data.index)
        signals["entry_signal"] = 0
        signals["stop_loss"] = 0.0
        signals["target"] = 0.0

        long_cond = pd.Series(False, index=data.index)
        short_cond = pd.Series(False, index=data.index)

        # Long assignment
        signals.loc[long_cond, "entry_signal"] = 1
        signals.loc[long_cond, "stop_loss"] = ...
        signals.loc[long_cond, "target"] = ...

        # Short assignment
        signals.loc[short_cond, "entry_signal"] = -1
        signals.loc[short_cond, "stop_loss"] = ...
        signals.loc[short_cond, "target"] = ...

        return signals
```

---

## 3. Fast-Path Deployment Workflow

1. **Write Strategy:**
   - Personal alpha: `../zillionsAlpha/strategies/<StrategyName>.py`
   - Commercial/Prop: `../nujinPro/strategies/<StrategyName>.py`
2. **Symlink to Engine:**
   ```bash
   ln -s ../../zillionsAlpha/strategies/<StrategyName>.py strategies/<StrategyName>.py
   ```
3. **Audit Strategy:**
   ```bash
   python tools/run_backtest_audit.py --strategy <StrategyName>.py --days 30
   ```
