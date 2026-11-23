"""
server/trial_ledger.py — append-only record of every strategy variant evaluated.

The Deflated Sharpe Ratio exists to penalise *how many hypotheses were searched*.
Its central input, $N_{trials}$, was previously derived from the number of trades
in a backtest — a quantity with no relationship to the search effort — which made
the penalty arbitrary and the gate weaker than it appeared.

This ledger makes the search history explicit and auditable, and supports
per-session isolation so a new user request's search effort is tracked in its own
session ledger (`.nujin/sessions/<session_id>/trial_ledger.jsonl`) without being
penalised by unrelated older user sessions.

Storage:
  • Session-scoped: ``.nujin/sessions/<session_id>/trial_ledger.jsonl``
  • Default / global fallback: ``.nujin/trial_ledger.jsonl``
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from server.session_store import get_active_session_id, get_session_paths

_LEDGER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".nujin"))
LEDGER_PATH = os.path.join(_LEDGER_DIR, "trial_ledger.jsonl")

# log(1) == 0 makes the expected-maximum-Sharpe term degenerate, so never report
# fewer than 2 trials.
MIN_TRIALS = 2


def resolve_ledger_path(path: Optional[str] = None, session_id: Optional[str] = None) -> str:
    """
    Resolve the trial ledger path.
    - If a custom `path` (different from the global default `LEDGER_PATH`) is explicitly provided, use it.
    - If `session_id` is provided, use that session's isolated `trial_ledger.jsonl`.
    - Otherwise, if an active session exists, use that session's `trial_ledger.jsonl`.
    - Otherwise default to `LEDGER_PATH`.
    """
    if path is not None and path != LEDGER_PATH:
        return path
    if session_id:
        return get_session_paths(session_id=session_id, create_if_missing=True)["trial_ledger"]
    active_sid = get_active_session_id()
    if active_sid:
        return get_session_paths(session_id=active_sid, create_if_missing=True)["trial_ledger"]
    return LEDGER_PATH


def fingerprint(obj: Any) -> str:
    """Stable short hash identifying a distinct hypothesis."""
    payload = json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def record_trial(
    kind: str,
    fingerprint: Optional[str] = None,
    metrics: Optional[dict] = None,
    source: Optional[str] = None,
    path: str = LEDGER_PATH,
    session_id: Optional[str] = None,
) -> dict:
    """Append one evaluated hypothesis atomically under a file lock. Returns the recorded entry."""
    target_path = resolve_ledger_path(path=path, session_id=session_id)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "fingerprint": fingerprint,
        "source": source,
        "session_id": session_id or get_active_session_id(),
        "metrics": metrics or {},
    }
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    line = json.dumps(entry, default=str) + "\n"
    try:
        import fcntl
    except ImportError:
        fcntl = None
    with open(target_path, "a", encoding="utf-8") as f:
        if fcntl is not None:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(line)
            f.flush()
        finally:
            if fcntl is not None:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return entry


def read_trials(
    kind: Optional[str] = None,
    path: str = LEDGER_PATH,
    session_id: Optional[str] = None,
) -> list[dict]:
    """Read recorded trials, optionally filtered by kind and/or session."""
    target_path = resolve_ledger_path(path=path, session_id=session_id)
    if not os.path.exists(target_path):
        return []
    out: list[dict] = []
    with open(target_path, "r", encoding="utf-8") as f:
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


def count_trials(
    kind: Optional[str] = None,
    path: str = LEDGER_PATH,
    session_id: Optional[str] = None,
) -> int:
    """
    Count *distinct* hypotheses searched.

    Entries carrying the same fingerprint (e.g. the same strategy re-audited)
    count once; entries without a fingerprint count individually.
    """
    seen: set[str] = set()
    anonymous = 0
    for entry in read_trials(kind=kind, path=path, session_id=session_id):
        fp = entry.get("fingerprint")
        if fp:
            seen.add(str(fp))
        else:
            anonymous += 1
    return len(seen) + anonymous


def n_trials_for_dsr(
    kind: Optional[str] = None,
    path: str = LEDGER_PATH,
    session_id: Optional[str] = None,
) -> int:
    """Trial count suitable for DSR, floored at MIN_TRIALS."""
    return max(MIN_TRIALS, count_trials(kind=kind, path=path, session_id=session_id))
