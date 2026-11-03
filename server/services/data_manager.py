"""
server.services.data_manager
─────────────────────────────────────────────────────────────
Transparent backward-compatible delegator to core.data (SSOT).
Eliminates code duplication across the system while preserving test seams.
"""
from __future__ import annotations

import sys
from core.data import *
import core.data as _core_data

# Re-export all public and internal helpers from core.data
for _attr in dir(_core_data):
    if not _attr.startswith("__"):
        globals()[_attr] = getattr(_core_data, _attr)

__all__ = [name for name in dir(_core_data) if not name.startswith("__")]
