# Market Research, Pure Mathematical Basis & Optional ML Edge Scanner

This guide covers NujinSkills' quantitative research instruments for uncovering empirical market behavior strictly on the **66.7% In-Sample** slice before touching Blind Out-of-Sample data.

---

## 1. The Core Scientific Law of Edge

An edge exists if and only if a causal, stationary mechanism has a **non-random, sub-era invariant predictive relationship** with future barrier outcomes that **comfortably exceeds transaction friction**:

$$\text{Net Edge} = |\mathbb{E}[R_{t+h} \mid S_t]| - \text{Roundtrip Friction} > 0$$

---

## 2. Primary Research Microscope: In-Sample Microstructure Profiling

Before committing to any paradigm, indicator family, or scanner, profile the target market strictly In-Sample:

```bash
python tools/validate_hypothesis.py --profile --symbol <TICKER> --tf <TIMEFRAME> --days 60
```

This reveals in one compact pass (with Blind OOS locked):
- **Volatility & Friction Feasibility:** `ATR14`, `ATR%`, roundtrip friction as % of `1x ATR`, and minimum stop distance required to clear the 10% friction floor.
- **Return Dynamics:** Lag-1 autocorrelation, 5-bar variance ratio, 20-bar path efficiency, and range volatility clustering (informing whether momentum/breakout, mean-reversion, or mixed-regime approaches fit best).
- **Regime Mix & Diurnal Profile:** In-Sample Bull/Bear/Ranging split and peak vs. quiet UTC hours.

---

## 3. Optional ML Anomaly Scanner (`tools/scan_edge.py` & `core/feature_factory.py`)

When you want an unbiased statistical radar across raw bar physics (either as a standalone discovery source or as research inspiration for a 4-layer thesis), run `tools/scan_edge.py`:

```bash
python tools/scan_edge.py --symbol <TICKER> --tf <TIMEFRAME> --days 60 --style <auto|scalp|day|swing|invest>
```

### The ~103-Coordinate Multi-Scale Mathematical Basis (`core/feature_factory.py`)
Decomposes OHLCV into 6 dimensionless physical bar vectors (`V1` return velocity, `V2` span energy, `V3` body displacement, `V4` wick/boundary asymmetry, `V5` close location, `V6` log-volume z-score) across Fibonacci scales $W \in \{2, 3, 5, 8, 13, 21, 34, 55\}$ using rolling moments, IQR/EMA/channel coordinates, dispersion ratios, autocorrelation, variance ratios, path efficiency, and volume-displacement coupling.

### Scanner Hurdles (In-Sample Only):
1. **ExtraTrees + Shallow Surrogate Trees:** Surfaces top directional coordinates and conditioning regime gates.
2. **5-Slice Chronological Sub-Era Invariance:** Requires consistent positive sub-eras across time.
3. **Permutation Noise Test & $t$-stat Hurdle:** Rejects random timing coincidences ($p \le 0.05$).
4. **2D MFE/MAE Stability Plateau (`core/geometry_optimizer.py`):** Simulates pessimistic intrabar resolution + neighborhood smoothing for robust SL/TP plateaus.

---

## 4. Validating Creative Hypotheses (`tools/validate_hypothesis.py`)

For any custom/creative strategy (using indicators, structural zones, MTF, cross-asset context, or upgraded scan discoveries), verify it strictly In-Sample before touching Blind OOS:

```bash
python tools/validate_hypothesis.py --strategy <StrategyName>.py --days 60
```

This proves **Zero Lookahead (prefix-invariance)**, **5-Slice Sub-Era Invariance**, **Permutation $p$-value**, **Actual Structural Friction Floor**, and **4-Layer Diagnostic Telemetry** (Context regime split, Location/Geometry MAE-MFE & winner giveback, Confirmation 1–2 bar stop-out rate).
