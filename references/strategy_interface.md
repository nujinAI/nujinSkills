# Strategy Interface & Fast-Path Deployment

Canonical code contract for authoring any NujinSkills strategy (creative 4-layer models, indicator-augmented systems, or scan-synthesized strategies).

---

## 1. Strategy Interface Contract

A strategy file defines a single class whose name matches its filename (e.g. `class StructuralAlphaEngine` in `StructuralAlphaEngine.py`).

### Rules:
- **Zero Hardcoded Capital:** Never hardcode dollar balances ($) or static lot quantities.
- **Risk Percentage Only:** Define `risk_pct_1r` as a fraction (e.g., `0.0035` for 0.35%, `0.01` for 1.0%).
- **Metadata Required:** Declare `symbol` and `timeframe` as class attributes.
- **Parsimony & Stability Plateau Discipline:** Keep tunable `__init__` parameters minimal, canonical, and justified by the thesis—never stack redundant indicators or curve-fit arbitrary decimals. Anti-overfitting is enforced empirically by Gate 1 (DSR), Gate 2 ($\pm 10\%$ parameter stability plateau), and 5-Slice Sub-Era Invariance rather than arbitrary artificial rules.
- **100% Causal Execution:** Zero future leakage (`shift(-k)`, full-sample quantiles/scaling, unshifted HTF bars, or non-causal swings). Use `core.indicators`, `core.market_structure.detect_swing_points(..., causal=True)`, `core.feature_factory`, or clean backward-looking vectorized math—see [`references/api_cheatsheet.md`](api_cheatsheet.md) for exact signatures instead of reading `.py` source files.
- **Objective Invalidation:** `stop_loss` must anchor to a structural or volatility-normalized invalidation boundary clearing the friction floor ($\le 10\%$ of SL distance).
- **Optional Diagnostics Hook:** A strategy may optionally expose `get_diagnostic_features(df)` returning a DataFrame of its core indicators/features so `validate_hypothesis.py` can run an automated anti-collinearity check ($|\rho| < 0.85$). Not required—zero mandatory boilerplate.

### Sizing Mechanism:
$$\text{Dollar Risk} = \text{Balance} \times \text{risk\_pct\_1r}, \qquad \text{Units} = \frac{\text{Dollar Risk}}{|\text{Entry} - \text{Stop Loss}| \times \text{Contract Multiplier}}$$

---

## 2. Canonical Strategy Skeleton

```python
import os
import sys
from typing import Any
import pandas as pd

_SKILLS_ROOT = "/home/christonomous/NujinAI/nujinSkills"
if _SKILLS_ROOT not in sys.path:
    sys.path.insert(0, _SKILLS_ROOT)


class NewStrategyName:
    """
    [Strategy Display Name]
    Context:      [Regime / environmental permission]
    Location:     [Structural zone / area of value]
    Confirmation: [Participation / shift trigger]
    Invalidation: [Objective structural stop & exit geometry]
    """

    symbol: str = "OANDA:XAUUSD"
    timeframe: str = "15m"

    def __init__(
        self,
        risk_pct_1r: float = 0.0035,
        sl_atr_mult: float = 1.5,
        tp_atr_mult: float = 3.0,
        **kwargs: Any,
    ):
        self.risk_pct_1r = float(risk_pct_1r)
        self.sl_atr_mult = float(sl_atr_mult)
        self.tp_atr_mult = float(tp_atr_mult)

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Strictly causal vectorized features (Context, Location, Confirmation)."""
        data = df.copy()
        if not isinstance(data.index, pd.DatetimeIndex):
            data.index = pd.to_datetime(data.index, utc=True)
        elif data.index.tz is None:
            data.index = data.index.tz_localize("UTC")
        else:
            data.index = data.index.tz_convert("UTC")

        # Use core.indicators, core.market_structure(..., causal=True),
        # core.feature_factory, or custom causal vectorized math.
        return data

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Returns DataFrame with strictly 3 columns:
        - entry_signal: 1 (Long), -1 (Short), 0 (Neutral)
        - stop_loss: Float level (must satisfy SL < close for longs, SL > close for shorts)
        - target: Float level (must satisfy TP > close for longs, TP < close for shorts)
        """
        data = self.compute_indicators(df)
        signals = pd.DataFrame(index=data.index)
        signals["entry_signal"] = 0
        signals["stop_loss"] = 0.0
        signals["target"] = 0.0

        long_cond = pd.Series(False, index=data.index)
        short_cond = pd.Series(False, index=data.index)

        signals.loc[long_cond, "entry_signal"] = 1
        signals.loc[long_cond, "stop_loss"] = ...
        signals.loc[long_cond, "target"] = ...

        signals.loc[short_cond, "entry_signal"] = -1
        signals.loc[short_cond, "stop_loss"] = ...
        signals.loc[short_cond, "target"] = ...

        return signals
```

---

## 3. Fast-Path Validation & Deployment Workflow

1. **Write Strategy:** `../zillionsAlpha/strategies/<StrategyName>.py` (or `../nujinPro/strategies/<StrategyName>.py`).
2. **Symlink to Engine:**
   ```bash
   ln -sf ../../zillionsAlpha/strategies/<StrategyName>.py strategies/<StrategyName>.py
   ```
3. **Pre-Validate In-Sample (Zero Lookahead + Sub-Era + 4-Layer Telemetry):**
   ```bash
   python tools/validate_hypothesis.py --strategy <StrategyName>.py --days 60
   ```
4. **Full 8-Gate Cynic & Blind OOS Audit:**
   ```bash
   python tools/run_backtest_audit.py --strategy <StrategyName>.py --days 60
   ```
