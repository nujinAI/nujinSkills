#!/usr/bin/env python3
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.backtest_engine import run_real_backtest
from server.cynic_gates import format_matrix, MAX_MDD_99

def audit(strategy: str, save_state: bool, output_path: str, days: int = 30,
          account_size: float = None, max_mdd: float = None, run_dir: str = None):
    if run_dir:
        os.makedirs(run_dir, exist_ok=True)
        if output_path == "data/audit_report.json":
            output_path = os.path.join(run_dir, "audit_report.json")

    effective_mdd = float(max_mdd) if max_mdd is not None else MAX_MDD_99
    print(f"[BacktestAudit] Running quantitative audit for strategy: {strategy} (days={days}, max_mdd={effective_mdd*100:.1f}%)")
    print(f"[BacktestAudit] save_state={save_state} | output={output_path}")

    try:
        import inspect
        sig = inspect.signature(run_real_backtest)
        kwargs = dict(save_as_active=save_state, days=days, account_size=account_size)
        if "max_mdd" in sig.parameters:
            kwargs["max_mdd"] = effective_mdd
        if "run_dir" in sig.parameters:
            kwargs["run_dir"] = run_dir
        results = run_real_backtest(strategy, **kwargs)
    except Exception as e:
        print(f"[BacktestAudit] ERROR — backtest failed: {e}")
        sys.exit(1)

    summary = results.get("summary", {})
    gates   = results.get("falsification_gates", {})
    regimes = results.get("regime_breakdown", {})
    trades  = results.get("trades_detail", [])

    acct_s = summary.get("account_size")
    pnl_d = summary.get("net_pnl_dollars", 0.0)
    pnl_p = summary.get("net_pnl_pct", 0.0)

    from core.analytics import compute_institutional_tier
    strat_meta = compute_institutional_tier(summary, gates, max_mdd_limit=effective_mdd)
    rank_tier = strat_meta.get("tier", "N/A")
    rank_score = strat_meta.get("ranking_score", 0.0)
    tier_reason = strat_meta.get("tier_reason", "")

    print("\n" + "=" * 70)
    print(f"[BacktestAudit] STRATEGY AUDIT REPORT: {results.get('strategy')}")
    print("=" * 70)
    print(f"  Institutional Tier:    {rank_tier}")
    print(f"  Ranking Score:         {rank_score}/100 ({tier_reason})")
    print(f"  Target Profile:        {results.get('thesis_props', {}).get('target_profile')}")
    if account_size is not None and acct_s is not None:
        print(f"  Account Benchmark:     ${acct_s:,.2f}")
        print(f"  Net Realized PnL:      ${pnl_d:+,.2f} ({pnl_p:+.2f}%)")
    else:
        print(f"  Return Basis:          Normalized (% returns)")
        print(f"  Net Realized PnL:      {pnl_p:+.2f}%")
    print(f"  Net Sharpe Ratio:      {summary.get('sharpe')} (A-Tier floor >= 1.8)")
    print(f"  Win Rate:              {summary.get('win_rate', 0) * 100:.1f}%")
    print(f"  Profit Factor:         {summary.get('profit_factor')}")
    print(f"  Max Drawdown (Full):   {summary.get('max_drawdown', 0) * 100:.2f}%")
    print(f"  Monte Carlo MDD99:     {summary.get('mdd_99', 0) * 100:.2f}% (gate: <= {effective_mdd * 100:.1f}%)")
    print(f"  Deflated Sharpe (DSR): {summary.get('dsr')} (>= 0.95) -> {gates.get('gate_1_dsr', {}).get('status')}")
    print(f"  Expectancy:            {summary.get('expectancy_bps')} bps")
    print(f"  Total Trades:          {len(trades)}")
    print("-" * 70)
    # Rendered from the canonical registry, so the report can no longer
    # mislabel the gate count or read a key that is never produced.
    print(format_matrix(gates))
    print("-" * 70)
    print("  MARKET REGIME SURVIVAL:")
    for reg, data in regimes.items():
        label = reg.replace("_", " ").title()
        print(f"    {label:<16}: {data.get('trade_count')} trades | WR: {data.get('win_rate', 0) * 100:.1f}% | PF: {data.get('profit_factor')} | PnL: {data.get('net_pnl_pct', 0):+.2f}%")
    print("=" * 70 + "\n")

    def json_converter(o):
        import numpy as np
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, (np.integer, np.floating)):
            return o.item()
        return str(o)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    tmp_output = f"{output_path}.{os.getpid()}.tmp"
    with open(tmp_output, "w") as f:
        json.dump(results, f, indent=2, default=json_converter)
    os.replace(tmp_output, output_path)
    print(f"[BacktestAudit] Audit report saved to {output_path}")
    if save_state:
        print(f"[BacktestAudit] Strategy state written to data/state.json via StateManager")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Strategy Backtest & Cynic Audit")
    parser.add_argument("--strategy",     type=str, required=True,                       help="Strategy filename in strategies/ (required, no hardcoded defaults)")
    parser.add_argument("--days",         type=int, default=30,                          help="Lookback period in days (e.g. 14, 30, 60, 90)")
    parser.add_argument("--account-size", type=float, default=None,                      help="Optional account size override in $ (omit for normalized %% returns)")
    parser.add_argument("--max-mdd",      type=float, default=None,                      help="Max Monte Carlo MDD99 threshold as decimal (e.g. 0.05 for 5%%; default 0.03)")
    parser.add_argument("--run-dir",      type=str, default=None,                        help="Isolated per-run output directory to prevent concurrent audit collisions")
    parser.add_argument("--save-state",   action="store_true", default=False,            help="Deploy as active strategy (writes data/state.json)")
    parser.add_argument("--json-output",  default="data/audit_report.json",              help="Output JSON report path")
    args = parser.parse_args()

    audit(args.strategy, args.save_state, args.json_output, days=args.days,
          account_size=args.account_size, max_mdd=args.max_mdd, run_dir=args.run_dir)
