"""Phase 7: git log + CODEOWNERS ingestion."""
from __future__ import annotations

import fnmatch
import logging
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_EMPTY_OWNERSHIP: dict = {
    "authors": [],
    "teams": [],
    "last_modified": [],
    "contributors": [],
    "owned_by": [],
}


def collect_ownership(repo_root: Path, indexed_files: set[str]) -> dict:
    """Build authors/teams/last_modified/contributors/owned_by from git + CODEOWNERS.

    Returns a dict with keys ``authors``, ``teams``, ``last_modified``,
    ``contributors``, and ``owned_by``.  On error (git not found, non-zero
    exit, timeout) every value is an empty list -- but the dict itself is
    **always truthy**.  Callers must not use ``if not ownership:`` as a
    failure check; test individual lists or handle the logged warning
    instead.
    """
    authors: dict[str, dict] = {}
    last_modified: list[dict] = []
    contributors: list[dict] = []

    # Single git log call: name + email + timestamp + file list per commit
    try:
        proc = subprocess.run(
            ["git", "log", "--name-only", "--pretty=format:__COMMIT__%H\x1f%ae\x1f%an\x1f%at"],
            cwd=str(repo_root), capture_output=True, text=True, check=False, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("collect_ownership: git log failed: %s", exc)
        return {k: [] for k in _EMPTY_OWNERSHIP}

    if proc.returncode != 0:
        logger.warning(
            "collect_ownership: git log failed (exit %d): %s",
            proc.returncode,
            proc.stderr.strip(),
        )
        return {k: [] for k in _EMPTY_OWNERSHIP}

    log_text = proc.stdout

    file_last: dict[str, tuple[str, int]] = {}    # file -> (email, ts)
    file_counts: dict[str, Counter] = {}          # file -> Counter[email]
    current_email: Optional[str] = None
    current_name: Optional[str] = None
    current_ts: int = 0

    for line in log_text.splitlines():
        if line.startswith("__COMMIT__"):
            try:
                _, payload = line.split("__COMMIT__", 1)
                _h, email, name, ts = payload.split("\x1f", 3)
                current_email = email
                current_name = name
                current_ts = int(ts)
                if email not in authors:
                    authors[email] = {"email": email, "name": name}
            except ValueError:
                logger.warning("collect_ownership: malformed git log line: %r", line)
                current_email = None
            continue
        if not line.strip():
            continue
        if current_email is None:
            continue
        # File touched in this commit
        f = line.strip()
        if f not in indexed_files:
            continue
        # Last modified = first time we encounter a file (git log is newest-first)
        if f not in file_last:
            file_last[f] = (current_email, current_ts)
        file_counts.setdefault(f, Counter())[current_email] += 1

    for f, (email, ts) in file_last.items():
        last_modified.append({"path": f, "email": email, "at": ts})
    for f, counter in file_counts.items():
        for email, count in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:10]:
            contributors.append({"path": f, "email": email, "commits": count})

    # CODEOWNERS
    teams: set[str] = set()
    owned_by: list[dict] = []
    co_paths = [
        repo_root / "CODEOWNERS",
        repo_root / ".github" / "CODEOWNERS",
        repo_root / "docs" / "CODEOWNERS",
    ]
    co_file = next((p for p in co_paths if p.exists()), None)
    if co_file is not None:
        rules = _parse_codeowners(co_file)
        for f in indexed_files:
            owners = _match_codeowners(f, rules)
            for o in owners:
                teams.add(o)
                owned_by.append({"path": f, "team": o})

    return {
        "authors": list(authors.values()),
        "teams": sorted(teams),
        "last_modified": last_modified,
        "contributors": contributors,
        "owned_by": owned_by,
    }


_CO_LINE_RE = re.compile(r"^\s*([^\s#]+)\s+(.+)$")


def _parse_codeowners(p: Path) -> list[tuple[str, list[str]]]:
    rules: list[tuple[str, list[str]]] = []
    try:
        with open(p, encoding="utf-8", newline="") as fh:
            _text = fh.read()
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("CODEOWNERS: cannot decode %s: %s", p, exc)
        return []
    for line in _text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = _CO_LINE_RE.match(line)
        if not m:
            continue
        pat = m.group(1)
        owners = [t for t in m.group(2).split() if t.startswith("@")]
        rules.append((pat, owners))
    return rules


def _match_codeowners(path: str, rules: list[tuple[str, list[str]]]) -> list[str]:
    """Last matching rule wins (CODEOWNERS semantics)."""
    matched: list[str] = []
    for pat, owners in rules:
        if _co_pattern_match(pat, path):
            matched = owners
    return matched


def _co_pattern_match(pat: str, path: str) -> bool:
    # /foo means rooted at repo root
    if pat.startswith("/"):
        stripped = pat[1:]
        base = stripped.rstrip("/")
        return fnmatch.fnmatch(path, stripped) or fnmatch.fnmatch(path, base + "/*")
    # **/ pattern
    if "/" not in pat.rstrip("*/"):
        return any(fnmatch.fnmatch(seg, pat.rstrip("/")) for seg in path.split("/"))
    return fnmatch.fnmatch(path, "*" + pat) or fnmatch.fnmatch(path, pat)
