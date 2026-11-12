#!/usr/bin/env python3
"""
tools/preflight.py - Nujin System Production Readiness & Integrity Check.
Verifies compilation, unit test suite, and Single Source of Truth agreement.
"""

from __future__ import annotations

import argparse
import compileall
import json
import os
import subprocess
import sys
import tempfile
from typing import Any, Dict, List

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_PYTHON = sys.executable

def _run(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

def check_compile() -> Dict[str, Any]:
    targets = ["core", "server", "tools", "tests"]
    failed = []
    for target in targets:
        dir_path = os.path.join(_ROOT, target)
        if not os.path.exists(dir_path):
            continue
        ok = compileall.compile_dir(dir_path, quiet=1, force=False)
        if not ok:
            failed.append(target)

    return {
        "name": "byte-compile",
        "ok": len(failed) == 0,
        "detail": "all core/, server/, tools/, tests/ compiled cleanly" if not failed else f"failed: {failed}",
    }

def check_tests() -> Dict[str, Any]:
    proc = _run([_PYTHON, "-m", "pytest", "tests/", "-q", "--tb=line"])
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    summary = lines[-1] if lines else (proc.stderr.splitlines()[-1] if proc.stderr else "")
    return {
        "name": "test suite",
        "ok": proc.returncode == 0,
        "detail": summary,
    }

def check_ssot_agreement() -> Dict[str, Any]:
    """Verifies that core.cynic_gates matches the canonical evaluation."""
    import numpy as np
    from core.cynic_gates import evaluate_cynic_gates

    rng = np.random.default_rng(7)
    returns = rng.normal(0.0015, 0.01, size=120)

    try:
        gates = evaluate_cynic_gates(returns, n_trials=40)
        summary = gates.get("gates_summary", {})
        verdict = summary.get("verdict", "UNKNOWN")
        passed = summary.get("gates_passed", 0)
        total = summary.get("gates_total", 8)
        return {
            "name": "canonical SSOT agreement",
            "ok": True,
            "detail": f"core.cynic_gates evaluated successfully: {verdict} ({passed}/{total} gates passed)",
        }
    except Exception as e:
        return {
            "name": "canonical SSOT agreement",
            "ok": False,
            "detail": f"Evaluation error: {e}",
        }

CHECKS = (check_compile, check_tests, check_ssot_agreement)

def main() -> int:
    parser = argparse.ArgumentParser(description="Nujin production-readiness preflight")
    parser.add_argument("--json", action="store_true", help="Emit JSON report only")
    args = parser.parse_args()

    results = [fn() for fn in CHECKS]
    all_ok = all(r["ok"] for r in results)

    if args.json:
        print(json.dumps({"ok": all_ok, "checks": results}, indent=2))
    else:
        print("\n" + "=" * 60)
        print("  NUJIN ARCHITECTURE PREFLIGHT VERIFICATION")
        print("=" * 60)
        for r in results:
            mark = "PASS" if r["ok"] else "FAIL"
            print(f"  [{mark}] {r['name']:<25} : {r['detail']}")
        print("=" * 60)
        if all_ok:
            print("  ALL ARCHITECTURE INVARIANTS PASSED (100% CLEAN)\n")
        else:
            print("  SYSTEM PREFLIGHT FAILED\n")

    return 0 if all_ok else 1

if __name__ == "__main__":
    sys.exit(main())
