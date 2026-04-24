"""SHA256-based AST cache for incremental indexing.

Caches serialised :class:`~codegraph.schema.ParseResult` objects keyed by
content hash so ``codegraph index --update`` can skip unchanged files.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from . import __version__
from .schema import ParseResult, parse_result_from_dict, parse_result_to_dict


def file_content_hash(path: Path, repo: Path) -> str:
    """SHA256 of file bytes + null separator + repo-relative path.

    Including the relative path ensures that identical content at different
    paths produces different hashes, making the cache portable across
    checkouts.
    """
    content = path.read_bytes()
    rel = str(path.resolve().relative_to(repo.resolve()))
    h = hashlib.sha256()
    h.update(content)
    h.update(b"\x00")
    h.update(rel.encode())
    return h.hexdigest()


class AstCache:
    """Manages a ``.codegraph-cache/ast/`` directory of cached ParseResults."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.cache_dir = repo / ".codegraph-cache" / "ast"
        self.manifest_path = repo / ".codegraph-cache" / "manifest.json"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load_manifest(self) -> dict[str, str]:
        """Load ``{rel_path: sha256_hash}`` from ``manifest.json``.

        Returns ``{}`` if the file is missing, corrupt, or was written by a
        different codegraph version (parsing logic may have changed).
        """
        try:
            raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if isinstance(raw, dict) and raw.get("version") == __version__:
            return raw.get("files", {})
        # Legacy (flat dict) or version mismatch — treat as empty.
        return {}

    def save_manifest(self, manifest: dict[str, str]) -> None:
        """Atomically write *manifest* to ``manifest.json``."""
        tmp = self.manifest_path.with_suffix(".tmp")
        payload = {"version": __version__, "files": manifest}
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self.manifest_path)

    def get(self, rel_path: str, current_hash: str) -> ParseResult | None:
        """Return cached ParseResult if *current_hash* matches, else ``None``."""
        entry = self.cache_dir / f"{current_hash}.json"
        if not entry.exists():
            return None
        try:
            d = json.loads(entry.read_text(encoding="utf-8"))
            return parse_result_from_dict(d)
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            return None

    def put(self, rel_path: str, content_hash: str, result: ParseResult) -> None:
        """Serialise *result* and atomically write to ``{content_hash}.json``."""
        entry = self.cache_dir / f"{content_hash}.json"
        tmp = entry.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(parse_result_to_dict(result)), encoding="utf-8")
            os.replace(tmp, entry)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    def clear(self) -> None:
        """Delete all cached entries, temp files, and the manifest."""
        for f in self.cache_dir.glob("*.json"):
            f.unlink()
        for f in self.cache_dir.glob("*.tmp"):
            f.unlink()
        if self.manifest_path.exists():
            self.manifest_path.unlink()
