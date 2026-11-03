"""
server/session_store.py
─────────────────────────────────────────────────────────────────────────────
Dedicated Per-Session & Experiment Isolation Manager for NujinAI.

Guarantees that each user request / research session operates in its own
isolated workspace directory (``.nujin/sessions/<session_id>/``) — just like
an AI conversation has its own chat thread — so a new user request is never
biased, polluted, or penalized by files or trial counts left over from older
requests.

Directory layout inside a session (`.nujin/sessions/<session_id>/`):
  • `session_meta.json`       — Session metadata (symbol, timeframe, intent, created_at)
  • `empirical_briefing.json` — Stage 1 Multi-Paradigm Statistical & Edge Family Briefing
  • `features.csv`            — Stage 1 / 2 Engineered feature matrix
  • `best_rule.json`          — Stage 2 Best discovered/synthesized strategy specification
  • `candidate_returns.json`  — Stage 2 / 3 Per-trade return series & metadata
  • `experiment_log.jsonl`    — Append-only log of iterations in this session
  • `trial_ledger.jsonl`      — Session-scoped trial ledger for Deflated Sharpe Ratio (DSR)

Active session pointer:
  • `.nujin/active_session.json` tracks the currently active session ID when
    CLI tools are invoked sequentially without an explicit `--id` / `--session` flag.
  • Starting a new session (`create_session` or `--new-session`) immediately
    creates a fresh, unpolluted workspace.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
NUJIN_DIR = os.path.join(_ROOT, ".nujin")
SESSIONS_DIR = os.path.join(NUJIN_DIR, "sessions")
LEGACY_EXPERIMENTS_DIR = os.path.join(NUJIN_DIR, "experiments")
ACTIVE_SESSION_FILE = os.path.join(NUJIN_DIR, "active_session.json")


def _slugify(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_-]+", "_", (value or "").strip())
    return re.sub(r"_+", "_", clean).strip("_").lower() or "session"


def generate_session_id(symbol: str = "BTCUSDT", timeframe: str = "15m", tag: str = "") -> str:
    """Generate a unique, human-readable session ID."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    sym_slug = _slugify(symbol)
    tf_slug = _slugify(timeframe)
    if tag:
        return f"{ts}_{sym_slug}_{tf_slug}_{_slugify(tag)}"
    return f"{ts}_{sym_slug}_{tf_slug}"


def get_active_session_id() -> Optional[str]:
    """Return the active session ID from environment or `.nujin/active_session.json`."""
    env_sid = os.environ.get("NUJIN_SESSION_ID", "").strip()
    if env_sid:
        return env_sid
    if os.path.exists(ACTIVE_SESSION_FILE):
        try:
            with open(ACTIVE_SESSION_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            sid = str(data.get("session_id") or "").strip()
            if sid:
                return sid
        except Exception:
            pass
    return None


def set_active_session_id(session_id: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    """Persist `session_id` as the active session pointer."""
    os.makedirs(NUJIN_DIR, exist_ok=True)
    payload: Dict[str, Any] = {
        "session_id": session_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if metadata:
        payload.update(metadata)
    with open(ACTIVE_SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return session_id


def resolve_session_dir(
    session_id: Optional[str] = None,
    create_if_missing: bool = True,
    symbol: str = "BTCUSDT",
    timeframe: str = "15m",
) -> str:
    """
    Resolve the filesystem directory for `session_id`.
    Checks:
      1. Explicit `session_id` (or `NUJIN_SESSION_ID` / active session)
      2. `.nujin/sessions/<session_id>` (canonical)
      3. `.nujin/experiments/<session_id>` (backward-compatible lookup if it already exists)
    If no session exists and `create_if_missing=True`, creates a new isolated session.
    """
    sid = (session_id or "").strip() or get_active_session_id()
    if not sid:
        sid = generate_session_id(symbol=symbol, timeframe=timeframe)
        if create_if_missing:
            set_active_session_id(sid, {"symbol": symbol, "timeframe": timeframe})

    canonical_dir = os.path.join(SESSIONS_DIR, sid)
    legacy_dir = os.path.join(LEGACY_EXPERIMENTS_DIR, sid)

    if os.path.exists(canonical_dir):
        target_dir = canonical_dir
    elif os.path.exists(legacy_dir):
        target_dir = legacy_dir
    else:
        target_dir = canonical_dir
        if create_if_missing:
            os.makedirs(target_dir, exist_ok=True)

    return target_dir


def create_session(
    session_id: Optional[str] = None,
    symbol: str = "BTCUSDT",
    timeframe: str = "15m",
    intent: str = "auto",
    thesis: str = "",
    activate: bool = True,
) -> Dict[str, Any]:
    """
    Create a fresh, isolated research session directory and initialize its metadata.
    Never copies stale rules, returns, or trial ledgers from prior sessions.
    """
    sid = (session_id or "").strip() or generate_session_id(symbol=symbol, timeframe=timeframe)
    sdir = os.path.join(SESSIONS_DIR, sid)
    os.makedirs(sdir, exist_ok=True)

    meta = {
        "session_id": sid,
        "symbol": symbol,
        "timeframe": timeframe,
        "intent": intent,
        "thesis": thesis,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "session_dir": sdir,
    }
    meta_path = os.path.join(sdir, "session_meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    if activate:
        set_active_session_id(sid, {"symbol": symbol, "timeframe": timeframe, "intent": intent})

    return meta


def get_session_paths(
    session_id: Optional[str] = None,
    symbol: str = "BTCUSDT",
    timeframe: str = "15m",
    create_if_missing: bool = True,
) -> Dict[str, str]:
    """
    Return all standard file paths scoped strictly to the resolved session.
    """
    sid = (session_id or "").strip() or get_active_session_id()
    if not sid:
        sid = generate_session_id(symbol=symbol, timeframe=timeframe)
        if create_if_missing:
            set_active_session_id(sid, {"symbol": symbol, "timeframe": timeframe})

    sdir = resolve_session_dir(sid, create_if_missing=create_if_missing, symbol=symbol, timeframe=timeframe)
    return {
        "session_id": sid,
        "session_dir": sdir,
        "meta": os.path.join(sdir, "session_meta.json"),
        "briefing": os.path.join(sdir, "empirical_briefing.json"),
        "features": os.path.join(sdir, "features.csv"),
        "best_rule": os.path.join(sdir, "best_rule.json"),
        "candidate_returns": os.path.join(sdir, "candidate_returns.json"),
        "experiment_log": os.path.join(sdir, "experiment_log.jsonl"),
        "trial_ledger": os.path.join(sdir, "trial_ledger.jsonl"),
    }


def list_sessions(limit: int = 25) -> List[Dict[str, Any]]:
    """List existing isolated sessions sorted newest first."""
    results: List[Dict[str, Any]] = []
    for base in (SESSIONS_DIR, LEGACY_EXPERIMENTS_DIR):
        if not os.path.exists(base):
            continue
        for entry in os.listdir(base):
            full = os.path.join(base, entry)
            if not os.path.isdir(full):
                continue
            meta_file = os.path.join(full, "session_meta.json")
            meta: Dict[str, Any] = {"session_id": entry, "session_dir": full}
            if os.path.exists(meta_file):
                try:
                    with open(meta_file, "r", encoding="utf-8") as f:
                        meta.update(json.load(f))
                except Exception:
                    pass
            meta["mtime"] = os.path.getmtime(full)
            meta["has_briefing"] = os.path.exists(os.path.join(full, "empirical_briefing.json"))
            meta["has_features"] = os.path.exists(os.path.join(full, "features.csv"))
            meta["has_best_rule"] = os.path.exists(os.path.join(full, "best_rule.json"))
            results.append(meta)

    results.sort(key=lambda r: float(r.get("mtime", 0.0)), reverse=True)
    return results[:limit]
