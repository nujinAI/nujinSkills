#!/usr/bin/env python3
"""
tools/preflight.py
─────────────────────────────────────────────────────────────
One command that answers "is this checkout safe to run?".

There is no CI pipeline for this repository by design, so production readiness has to be
verifiable locally. This runs the checks that matter, in order, and prints a summary:

  1. Byte-compile           — every source file in server/, tools/, tests/ parses
  2. Test suite             — the full pytest run, which itself includes:
                                * offline import safety for server/, tools/ and plugins/
                                * no undefined globals read by any function
                                * one interception seam for live market-data fetches
                                * live-state isolation and a hard network guard
  3. Audit CLI agreement    — validation_cynic and cynic_auditor must reach the same verdict
                              on the same deterministic return series

Usage:
    python -m tools.preflight
    python -m tools.preflight --json      # machine-readable result

Exit code is 0 only when every step passes.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from typing import Any, Dict, List

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PYTHON = sys.executable


def _run(argv: List[str], cwd: str = _ROOT, timeout: int = 900) -> subprocess.CompletedProcess:
    """Runs a command and returns the completed process, preserving its exit status."""
    return subprocess.run(
        argv, cwd=cwd, capture_output=True, text=True, timeout=timeout,
        env={**os.environ, "PYTHONPATH": _ROOT + os.pathsep + os.environ.get("PYTHONPATH", "")},
    )


def check_compile() -> Dict[str, Any]:
    proc = _run([_PYTHON, "-m", "compileall", "-q", "server", "tools", "tests"])
    return {
        "name": "byte-compile",
        "ok": proc.returncode == 0,
        "detail": "server/, tools/, tests/ compile" if proc.returncode == 0
                  else (proc.stdout + proc.stderr).strip()[-800:],
    }


def check_tests() -> Dict[str, Any]:
    proc = _run([_PYTHON, "-m", "pytest", "-q", "-rs"])
    tail = "\n".join(line for line in proc.stdout.strip().splitlines()[-6:])
    return {
        "name": "test suite",
        "ok": proc.returncode == 0,
        "detail": tail or (proc.stdout + proc.stderr).strip()[-800:],
    }


def check_cli_agreement() -> Dict[str, Any]:
    """
    The auditor and the backtester must not disagree about the same candidate.

    The two CLIs are separate entry points onto the same gate mathematics; this is the
    end-to-end proof that the single-source-of-truth contract holds at the CLI level.
    """
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - environment problem, reported below
        return {"name": "audit CLI agreement", "ok": False, "detail": f"numpy unavailable: {exc}"}

    rng = np.random.default_rng(7)
    returns = [float(x) for x in rng.normal(0.0015, 0.01, size=120)]

    with tempfile.TemporaryDirectory(prefix="nujin-preflight-") as tmp:
        fixture = os.path.join(tmp, "returns.json")
        with open(fixture, "w", encoding="utf-8") as f:
            json.dump(returns, f)

        results = {}
        for label, module in (("validation_cynic", "tools.validation_cynic"),
                              ("cynic_auditor", "tools.cynic_auditor")):
            proc = _run([_PYTHON, "-m", module, "--returns", fixture, "--trials", "40", "--json"])
            if proc.returncode != 0:
                return {
                    "name": "audit CLI agreement", "ok": False,
                    "detail": f"{label} exited {proc.returncode}: {(proc.stdout + proc.stderr).strip()[-500:]}",
                }
            try:
                # The CLIs emit pretty-printed JSON, so parse the whole stream.
                payload = json.loads(proc.stdout.strip())
            except (ValueError, IndexError) as exc:
                return {"name": "audit CLI agreement", "ok": False,
                        "detail": f"{label} produced unparseable JSON: {exc}"}

            verdict = payload.get("overall_status")
            if isinstance(verdict, dict):
                verdict = verdict.get("verdict")
            results[label] = {
                "verdict": verdict or payload.get("gates_summary", {}).get("verdict"),
                "gates": payload.get("gates_summary", {}),
            }

        agree = results["validation_cynic"]["verdict"] == results["cynic_auditor"]["verdict"]
        gates = results["validation_cynic"]["gates"]
        summary = (
            f"both report {results['validation_cynic']['verdict']} "
            f"({gates.get('gates_passed', '?')}/{gates.get('gates_total', '?')} gates passed)"
        )
        return {
            "name": "audit CLI agreement",
            "ok": agree,
            "detail": summary if agree else f"DISAGREE: {results}",
        }


CHECKS = (check_compile, check_tests, check_cli_agreement)


def main() -> int:
    parser = argparse.ArgumentParser(description="Nujin production-readiness preflight")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON only")
    args = parser.parse_args()

    reports = []
    for check in CHECKS:
        reports.append(check())

    if args.json:
        print(json.dumps({"checks": reports, "ok": all(r["ok"] for r in reports)}, indent=2))
    else:
        print("Nujin preflight")
        print("=" * 64)
        for report in reports:
            mark = "PASS" if report["ok"] else "FAIL"
            print(f"[{mark}] {report['name']}")
            for line in (report["detail"] or "").splitlines():
                print(f"        {line}")
        print("=" * 64)
        failed = [r["name"] for r in reports if not r["ok"]]
        print("All checks passed." if not failed else "FAILED: " + ", ".join(failed))

    return 0 if all(report["ok"] for report in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
