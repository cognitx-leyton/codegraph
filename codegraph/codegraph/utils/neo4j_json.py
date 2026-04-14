"""JSON-serialisation helpers for Neo4j result rows."""
from __future__ import annotations

import json
from typing import Any, Mapping


def clean_row(row: Mapping[str, Any] | Any) -> dict:
    """Best-effort JSON-clean of a neo4j ``Record`` / row mapping.

    Values that are already JSON-serialisable are returned as-is. Neo4j
    :class:`Node` / :class:`Relationship` objects are unwrapped via their
    ``_properties`` dict. Anything else (``Path``, unknown types, etc.) falls
    back to ``str(v)`` so the result is always JSON-safe.
    """
    items = row.items() if hasattr(row, "items") else dict(row).items()
    out: dict = {}
    for k, v in items:
        try:
            json.dumps(v)
            out[k] = v
        except TypeError:
            if hasattr(v, "_properties"):
                out[k] = dict(v._properties)
            else:
                out[k] = str(v)
    return out
