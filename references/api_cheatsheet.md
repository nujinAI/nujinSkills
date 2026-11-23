# NujinSkills API & CLI Cheat Sheet (Read This Instead of `.py` Source Files)

Exact public signatures, return schemas, CLI flags, and black-box engine contracts. **Never read `core/*.py`, `tools/*.py`, or `data/*.json` to look up interfaces.**

---

## 1. Black-Box Engine & Audit Contract (5 Facts)

- **Input `df`:** Columns `open`, `high`, `low`, `close`, `volume` (float); UTC `DatetimeIndex` (normalize in `compute_indicators` if naive/non-datetime).
- **Signal Output:** `generate_signals(df)` returns DataFrame aligned to `df.index` with `entry_signal` (`1`, `-1`, `0`), `stop_loss` (`float`), `target` (`float`). Valid geometry: `0 < SL < close < TP` (long), `0 < TP < close < SL` (short).
- **Execution Simulation:** Enters on signal bar `close`; **Pessimistic Intrabar Resolution** (if both `SL` and `TP` trigger on the same bar, `SL` fills first); opposite signal closes/reverses at bar `close`.
- **Gate 2 (Stability) & Gate 5 (Regimes):** Gate 2 perturbs numeric `__init__` attributes by $\pm 10\%$ (Sharpe drop must stay $< 30\%$); Gate 5 classifies `bull_market` (`close > SMA50 * 1.002`), `bear_market` (`close < SMA50 * 0.998`), and `ranging_market` (within band).
- **Data Split:** First `66.7%` = In-Sample (profiling, scanning, `validate_hypothesis.py`, `autopsy_strategy.py`); final `33.3%` = Blind OOS (touched only by `run_backtest_audit.py`).

---

## 2. `core.indicators` Public API (All Strictly Causal)

```python
from core.indicators import (
    sma, ema, wma, hma, kama, rsi, macd, stochastic, roc, cci, williams_r,
    true_range, atr, adx, bollinger_bands, keltner_channels, donchian_channels,
    supertrend, obv, cmf, zscore, rolling_linreg_slope, hurst_proxy, rolling_vwap,
    compute_talib_token, ensure_dynamic_indicators,
    add_causal_mtf_features, add_cross_asset_context, add_pandas_ta_suite,
)
```
- **Single-Series (`-> Series`):** `sma/ema/wma/hma(s, period=20)`, `kama(s, period=10)`, `rsi(s, period=14)`, `roc(s, period=10)`, `zscore(s, period=20)`, `rolling_linreg_slope(s, period=20)`, `hurst_proxy(close, window=50)`, `true_range(h, l, c)`, `atr(h, l, c, period=14)`, `cci(h, l, c, period=20)`, `williams_r(h, l, c, period=14)`, `obv(c, v)`, `cmf(h, l, c, v, period=20)`.
- **Multi-Output Tuples:**
  - `macd(s, fast=12, slow=26, signal=9)` → `(macd, signal, hist)`
  - `stochastic(h, l, c, k_period=14, d_period=3)` → `(k, d)`
  - `adx(h, l, c, period=14)` → `(adx, plus_di, minus_di)`
  - `bollinger_bands(s, period=20, std_dev=2.0)` → `(mid, upper, lower, bandwidth, pct_b)`
  - `keltner_channels(h, l, c, period=20, atr_mult=1.5)` → `(mid, upper, lower)`
  - `donchian_channels(h, l, period=20, causal=True)` → `(upper, lower, mid)`
  - `supertrend(h, l, c, period=10, multiplier=3.0)` → `(line, direction)` (`+1`/`-1`)
  - `rolling_vwap(c, v, period=50)` → `(vwap, vwap_z, va_high_1_5std, va_low_1_5std)`
- **Dynamic & MTF Enrichers (`-> DataFrame`):**
  - `compute_talib_token(df, token)` → `Series|None` (any of 201 TA-Lib funcs, e.g. `"mfi_14"`, `"natr_14"`, `"er_10"`, `"cmo_14"`, `"tsi_25_13"`, `"cdlengulfing"`). Direct `import talib` is also installed.
  - `ensure_dynamic_indicators(df, expressions=[...])` → computes referenced tokens on-the-fly.
  - `add_causal_mtf_features(df)` → adds shifted completed-bar `htf4x_{ema_21,rsi_14,adx_14,supertrend_dir,trend_dir}`, `htf16x_{...}`, and `mtf_alignment_score` ($\in [-1, 1]$).
  - `add_cross_asset_context(df, benchmark_df=None, window=50)` → adds `cross_asset_beta_50`, `cross_asset_corr_50`, `cross_asset_rs_zscore_20`.
  - `add_pandas_ta_suite(df)` → adds all `ta` library columns.

---

## 3. Other `core` Modules (Exact Signatures)

- **`core.market_structure`:** `detect_swing_points(df, left_bars=5, right_bars=5, causal=True)` → adds `is_swing_high`, `is_swing_low`, `last_swing_high`, `last_swing_low` (zero lookahead when `causal=True`).
- **`core.feature_factory`:** `compute_all_features(df)` / `compute_selected_features(df, feature_names)` → ~103 stationary coordinates across $W \in \{3,5,8,13,21,34,55\}$ (`v1_drift_w{W}`, `v3_body_mean_w{W}`, `v4_asym_mean_w{W}`, `v5_loc_ema_w{W}`, `coord_{iqr,ema,chan,ext}_w{W}`, `path_eff_w{W}`, `abs_eff_w{W}`, `overlap_density_w{W}`, `{disp,hl_vol,span}_ratio_{wf}_{ws}`, `{autocorr_lag1,var_ratio,rs_exp,skew,semidev_bal,disp_cv}_w{8,13,21,34}`, `coupling_{v3_v6,v6_v2}_w{1,3,5,13,21}`, `v6_vol_z_w21`, `v2_span_ratio_w1`, `phase_diurnal_{sin,cos}`).
- **`core.data`:** `fetch_ohlcv(symbol, timeframe='15m', count=1500, period=None, use_cache=True)` · `resolve_market_symbol(symbol) -> str`.
- **`core.friction`:** `resolve_asset_friction(symbol, price) -> (spread, fee_pct, slip)` · `get_roundtrip_friction(symbol, price) -> float` · `check_friction_hurdle(symbol, entry, stop_dist) -> (ok, pct)`.
- **`core.risk`:** `parse_prompt_to_risk(prompt, active_balance=None)` → dict `{account_size, risk_pct_1r, dollar_risk_1r, max_daily_drawdown_pct, max_total_drawdown_pct, max_daily_losses, daily_profit_cap}` · `calculate_position_units(dollar_risk_1r, entry, sl) -> float`.

---

## 4. Canonical CLI Tools & Flags (Run `--help` Only If Needed)

| Tool | Key Flags | Purpose |
|---|---|---|
| `tools/validate_hypothesis.py` | `--profile --symbol SYM --tf TF --days D` \| `--strategy FILE --days D [--json]` | 10-line IS market profile OR IS zero-lookahead + Sub-Era + 4-layer pre-check |
| `tools/scan_edge.py` | `--symbol SYM --tf TF --days D [--style auto\|scalp\|day\|swing\|invest] [--max-mdd F] [--top-k N]` | Optional ML anomaly & plateau scanner (writes `data/latest_edge_scan.json`) |
| `tools/build_strategy.py` | `--name NAME --from-scan-rank K` *(or explicit `--primary-feature`, `--polarity`, `--q-low/high`, `--regime-*`, `--extra-filter-*`, `--sl-mult`, `--tp-mult`, `--risk-pct`)* | Synthesize strategy from `scan_edge.py` rank into `zillionsAlpha/strategies/` |
| `tools/run_backtest_audit.py` | `--strategy FILE --days D [--account-size N] [--save-state]` | Authoritative IS + Blind OOS 8-Gate Cynic Audit (writes `data/audit_report.json`) |
| `tools/autopsy_strategy.py` | `--audit-json data/audit_report.json [--json]` | Strictly IS 4-layer failure + shallow-tree remediation report |
