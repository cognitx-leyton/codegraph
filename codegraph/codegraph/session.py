"""Persistent REPL session state.

The REPL remembers the "current repo" and "current Neo4j connection" between
invocations so an agent (or a human) does not have to re-specify them on every
command. State lives at ``~/.codegraph/session.json`` by default — override with
the ``CODEGRAPH_SESSION_FILE`` environment variable.

This is intentionally a tiny, line-count-minimal module. Anything fancier
(history, saved queries, multi-project juggling) should live in its own file.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional


def _default_session_path() -> Path:
    override = os.environ.get("CODEGRAPH_SESSION_FILE")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".codegraph" / "session.json"


@dataclass
class Session:
    """In-memory session state. Serialisable to / from JSON."""

    repo: Optional[str] = None
    """Absolute path to the currently-open repository, or ``None``."""

    uri: Optional[str] = None
    """Bolt URI of the active Neo4j connection."""

    user: Optional[str] = None
    password: Optional[str] = None
    """Neo4j credentials. Stored in plaintext — this is a dev tool against a
    local database; do not put production secrets in the session file."""

    last_query: Optional[str] = None
    """Last Cypher query run via ``query``. Useful for ``!!`` replays and for
    agents that want to know what the previous operation was."""

    last_index_stats: dict[str, Any] = field(default_factory=dict)
    """Counts from the most recent ``index`` run (files, classes, edges, …)."""

    # ── Persistence ──────────────────────────────────────────────

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Session":
        path = path or _default_session_path()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return cls()
        # Ignore unknown keys — forward-compatible with future additions.
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: Optional[Path] = None) -> None:
        path = path or _default_session_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))

    # ── Convenience ──────────────────────────────────────────────

    def set_repo(self, repo: str) -> None:
        self.repo = str(Path(repo).expanduser().resolve())

    def set_connection(self, uri: str, user: str, password: str) -> None:
        self.uri = uri
        self.user = user
        self.password = password

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> dict[str, str]:
        """Short key-value summary for the REPL's status block."""
        return {
            "repo": self.repo or "(none)",
            "neo4j": self.uri or "(not connected)",
            "user": self.user or "(unset)",
        }
