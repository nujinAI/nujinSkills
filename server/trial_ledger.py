"""
server/trial_ledger.py — append-only record of every strategy variant evaluated.

The Deflated Sharpe Ratio exists to penalise *how many hypotheses were searched*.
Its central input, $N_{trials}$, was previously derived from the number of trades
in a backtest — a quantity with no relationship to the search effort — which made
the penalty arbitrary and the gate weaker than it appeared.

This ledger makes the search history explicit and auditable, which also lays the
groundwork for a future Probability-of-Backtest-Overfitting (PBO/CSCV) check.

Storage: ``.nujin/trial_ledger.jsonl`` — one JSON object per line, append-only.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

_LEDGER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".nujin"))
LEDGER_PATH = os.path.join(_LEDGER_DIR, "trial_ledger.jsonl")

# log(1) == 0 makes the expected-maximum-Sharpe term degenerate, so never report
# fewer than 2 trials.
MIN_TRIALS = 2


def fingerprint(obj: Any) -> str:
    """Stable short hash identifying a distinct hypothesis."""
    payload = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def record_trial(kind: str, fingerprint: Optional[str] = None,
                 metrics: Optional[dict] = None, source: Optional[str] = None,
                 path: str = LEDGER_PATH) -> dict:
    """Append one evaluated hypothesis. Returns the recorded entry."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "fingerprint": fingerprint,
        "source": source,
        "metrics": metrics or {},
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    return entry


def read_trials(kind: Optional[str] = None, path: str = LEDGER_PATH) -> list[dict]:
    """Read recorded trials, optionally filtered by kind."""
    if not os.path.exists(path):
        return []
    out: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if kind and entry.get("kind") != kind:
                continue
            out.append(entry)
    return out


def count_trials(kind: Optional[str] = None, path: str = LEDGER_PATH) -> int:
    """
    Count *distinct* hypotheses searched.

    Entries carrying the same fingerprint (e.g. the same strategy re-audited)
    count once; entries without a fingerprint count individually.
    """
    seen: set[str] = set()
    anonymous = 0
    for entry in read_trials(kind=kind, path=path):
        fp = entry.get("fingerprint")
        if fp:
            seen.add(str(fp))
        else:
            anonymous += 1
    return len(seen) + anonymous


def n_trials_for_dsr(kind: Optional[str] = None, path: str = LEDGER_PATH) -> int:
    """Trial count suitable for DSR, floored at MIN_TRIALS."""
    return max(MIN_TRIALS, count_trials(kind=kind, path=path))
