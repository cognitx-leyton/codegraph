"""Phase 7: git log + CODEOWNERS ingestion."""
from __future__ import annotations

import fnmatch
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Optional


def collect_ownership(repo_root: Path, indexed_files: set[str]) -> dict:
    """Build authors/teams/last_modified/contributors/owned_by from git + CODEOWNERS."""
    authors: dict[str, dict] = {}
    last_modified: list[dict] = []
    contributors: list[dict] = []

    # Single git log call: name + email + timestamp + file list per commit
    try:
        proc = subprocess.run(
            ["git", "log", "--name-only", "--pretty=format:__COMMIT__%H|%ae|%an|%at"],
            cwd=str(repo_root), capture_output=True, text=True, check=False, timeout=120,
        )
        log_text = proc.stdout
    except (OSError, subprocess.SubprocessError):
        return {}

    file_last: dict[str, tuple[str, int]] = {}    # file -> (email, ts)
    file_counts: dict[str, Counter] = {}          # file -> Counter[email]
    current_email: Optional[str] = None
    current_name: Optional[str] = None
    current_ts: int = 0

    for line in log_text.splitlines():
        if line.startswith("__COMMIT__"):
            try:
                _, payload = line.split("__COMMIT__", 1)
                _h, email, name, ts = payload.split("|", 3)
                current_email = email
                current_name = name
                current_ts = int(ts)
                if email not in authors:
                    authors[email] = {"email": email, "name": name}
            except ValueError:
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
        for email, count in counter.most_common(10):
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
    for line in p.read_text(errors="replace").splitlines():
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
        pat = pat[1:]
        return fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(path, pat + "*")
    # **/ pattern
    if "/" not in pat.rstrip("*/"):
        return any(fnmatch.fnmatch(seg, pat.rstrip("/")) for seg in path.split("/"))
    return fnmatch.fnmatch(path, "*" + pat) or fnmatch.fnmatch(path, pat)
