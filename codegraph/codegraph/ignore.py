"""`.codegraphignore` — user-controlled exclusion of files, routes, and components.

Drop a ``.codegraphignore`` at the repo root (or point at any other file with
``--ignore-file``). Patterns use gitignore-style globs plus two codegraph
extensions:

- ``@route:/admin/*`` — matches against :class:`~.schema.RouteNode.path`
- ``@component:*Admin*`` — matches against function / class component names
- ``!pattern`` negation works for all three

codegraph's built-in :data:`~.config.BASE_EXCLUDE_DIRS` still prunes the walk
first (fast ``set`` check on path components). :class:`IgnoreFilter` only runs
on the survivors, so it never competes with the cheap fast-path.
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class IgnoreConfigError(Exception):
    """Raised when a ``.codegraphignore`` file cannot be read or parsed."""


@dataclass
class IgnorePattern:
    pattern: str
    pattern_type: str  # "file" | "route" | "component"
    is_negation: bool = False
    regex: Optional[re.Pattern] = None


@dataclass
class IgnoreConfig:
    file_patterns: list[IgnorePattern] = field(default_factory=list)
    route_patterns: list[IgnorePattern] = field(default_factory=list)
    component_patterns: list[IgnorePattern] = field(default_factory=list)
    raw_patterns: list[str] = field(default_factory=list)


class IgnoreFilter:
    """Filters files, routes, and components against a ``.codegraphignore`` file.

    Unlike the upstream agent-onboarding version, this class ships **no default
    patterns** — codegraph's :data:`~.config.BASE_EXCLUDE_DIRS` already handles
    build artefacts, and opinionated admin-route defaults don't belong in a
    generic indexer. Users opt in by writing patterns themselves.
    """

    def __init__(self, ignore_path: Path) -> None:
        self.ignore_path = Path(ignore_path).resolve()
        self.config = IgnoreConfig()
        if not self.ignore_path.exists():
            raise IgnoreConfigError(f"{self.ignore_path} not found")
        try:
            with open(self.ignore_path, encoding="utf-8", newline="") as fh:
                content = fh.read()
        except OSError as e:
            raise IgnoreConfigError(f"Cannot read {self.ignore_path}: {e}") from e
        self._parse_patterns(content)

    # ── parsing ─────────────────────────────────────────────────────────

    def _parse_patterns(self, content: str) -> None:
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            self.config.raw_patterns.append(line)

            is_negation = line.startswith("!")
            if is_negation:
                line = line[1:]

            if line.startswith("@route:"):
                pattern = line[len("@route:"):]
                self.config.route_patterns.append(IgnorePattern(
                    pattern=pattern,
                    pattern_type="route",
                    is_negation=is_negation,
                    regex=self._glob_to_regex(pattern),
                ))
            elif line.startswith("@component:"):
                pattern = line[len("@component:"):]
                self.config.component_patterns.append(IgnorePattern(
                    pattern=pattern,
                    pattern_type="component",
                    is_negation=is_negation,
                    regex=self._glob_to_regex(pattern),
                ))
            else:
                self.config.file_patterns.append(IgnorePattern(
                    pattern=line,
                    pattern_type="file",
                    is_negation=is_negation,
                    regex=self._gitignore_to_regex(line),
                ))

    @staticmethod
    def _glob_to_regex(pattern: str) -> re.Pattern:
        """Convert a simple ``*``/``**``/``?`` glob into a regex.

        Used for ``@route:`` and ``@component:`` patterns where we want
        substring-style matching (no leading-slash semantics).
        """
        escaped = re.escape(pattern)
        escaped = escaped.replace(r"\*\*", ".*")
        escaped = escaped.replace(r"\*", "[^/]*")
        escaped = escaped.replace(r"\?", ".")
        return re.compile(f"^{escaped}$", re.IGNORECASE)

    @staticmethod
    def _gitignore_to_regex(pattern: str) -> re.Pattern:
        """Convert a gitignore-style glob into a regex.

        Handles leading slash (root anchor), trailing slash (directory only),
        ``**`` (any number of path components), ``*`` (within one component),
        and ``?`` (single non-slash character).
        """
        if pattern.startswith("/"):
            pattern = pattern[1:]
            anchored = True
        else:
            anchored = False

        escaped = re.escape(pattern)
        escaped = escaped.replace(r"\*\*/", "(?:.*/)?")
        escaped = escaped.replace(r"/\*\*", "(?:/.*)?")
        escaped = escaped.replace(r"\*\*", ".*")
        escaped = escaped.replace(r"\*", "[^/]*")
        escaped = escaped.replace(r"\?", "[^/]")

        if escaped.endswith("/"):
            escaped = escaped[:-1] + "(?:/.*)?"

        if anchored:
            regex_pattern = f"^{escaped}(?:/.*)?$"
        else:
            regex_pattern = f"(?:^|/){escaped}(?:/.*)?$"

        return re.compile(regex_pattern, re.IGNORECASE)

    # ── predicates ──────────────────────────────────────────────────────

    def should_ignore_file(self, file_path: str) -> bool:
        path = file_path.replace("\\", "/")
        if path.startswith("./"):
            path = path[2:]
        decision = False
        for pattern in self.config.file_patterns:
            if pattern.regex and pattern.regex.search(path):
                decision = not pattern.is_negation
        return decision

    def should_ignore_route(self, route_path: str) -> bool:
        if not route_path.startswith("/"):
            route_path = "/" + route_path
        decision = False
        for pattern in self.config.route_patterns:
            if pattern.regex and pattern.regex.search(route_path):
                decision = not pattern.is_negation
            elif fnmatch.fnmatch(route_path, pattern.pattern):
                decision = not pattern.is_negation
        return decision

    def should_ignore_component(self, component_name: str) -> bool:
        decision = False
        for pattern in self.config.component_patterns:
            if pattern.regex and pattern.regex.search(component_name):
                decision = not pattern.is_negation
            elif fnmatch.fnmatch(component_name, pattern.pattern):
                decision = not pattern.is_negation
        return decision

    # ── helpers ─────────────────────────────────────────────────────────

    def counts(self) -> tuple[int, int, int]:
        """Return ``(files, routes, components)`` pattern counts."""
        return (
            len(self.config.file_patterns),
            len(self.config.route_patterns),
            len(self.config.component_patterns),
        )
