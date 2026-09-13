"""Deprecated. Use src/brain/store.py (AstraStore) instead."""
from __future__ import annotations

import sys
from pathlib import Path

_BRAIN = Path(__file__).resolve().parent.parent / "brain"
if str(_BRAIN) not in sys.path:
    sys.path.insert(0, str(_BRAIN))

from store import AstraStore, get_store  # noqa: E402

# Back-compat alias
Memory = AstraStore
__all__ = ["Memory", "AstraStore", "get_store"]
