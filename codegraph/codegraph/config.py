"""codegraph configuration loader.

Looks for project-level configuration in this order and merges the first match:

1. ``codegraph.toml`` at the repo root — dedicated file, top-level keys.
2. ``pyproject.toml`` at the repo root — under ``[tool.codegraph]``.

The CLI accepts the same keys as flags and **flags always win** over config-file
values. If neither file exists and no ``--package`` flag is given, indexing
stops with a clear error — there are no hardcoded defaults.

Schema::

    packages = ["packages/server", "packages/web"]   # required
    exclude_dirs = ["custom-build"]                  # extends defaults
    exclude_suffixes = [".gen.ts"]                   # extends defaults
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


# Hardcoded base sets — intentionally generic, not Twenty-specific.
# Users extend these via `exclude_dirs` / `exclude_suffixes` in their config.
BASE_EXCLUDE_DIRS: frozenset[str] = frozenset({
    "node_modules", "dist", "build", ".next", ".turbo", "coverage",
    ".git", "generated", "__generated__", ".cache", ".svelte-kit",
    ".nuxt", ".output", ".parcel-cache", ".vercel",
})

BASE_EXCLUDE_SUFFIXES: tuple[str, ...] = (
    ".stories.tsx", ".stories.ts", ".d.ts",
)


@dataclass
class CodegraphConfig:
    """Resolved configuration for an indexing run."""

    packages: list[str] = field(default_factory=list)
    """Repo-relative paths to TypeScript packages to index.

    Each entry is a directory (e.g. ``"packages/server"``, ``"apps/web"``).
    The directory should contain a ``package.json`` / ``tsconfig.json`` so
    TypeScript path aliases can be resolved.
    """

    exclude_dirs: set[str] = field(default_factory=set)
    """Directory names to skip during the file walk, **in addition** to
    :data:`BASE_EXCLUDE_DIRS`. Matched against any path component."""

    exclude_suffixes: tuple[str, ...] = field(default_factory=tuple)
    """Filename suffixes to skip, **in addition** to
    :data:`BASE_EXCLUDE_SUFFIXES`."""

    source: Optional[str] = None
    """Where the config came from (``"codegraph.toml"``,
    ``"pyproject.toml"``, or ``None`` for CLI-only)."""

    def effective_exclude_dirs(self) -> set[str]:
        return set(BASE_EXCLUDE_DIRS) | set(self.exclude_dirs)

    def effective_exclude_suffixes(self) -> tuple[str, ...]:
        return BASE_EXCLUDE_SUFFIXES + tuple(self.exclude_suffixes)


class ConfigError(Exception):
    """Raised when the configuration is invalid or missing required keys."""


def load_config(repo: Path) -> CodegraphConfig:
    """Load configuration from the repo root.

    Returns an empty :class:`CodegraphConfig` if no config file is found —
    this is not an error on its own; the caller decides whether ``packages``
    is required (it is, for ``index``; not for ``query`` / ``validate``).
    """
    repo = repo.resolve()

    # 1. codegraph.toml takes precedence
    dedicated = repo / "codegraph.toml"
    if dedicated.exists():
        data = _read_toml(dedicated)
        return _build_config(data, source="codegraph.toml")

    # 2. pyproject.toml [tool.codegraph]
    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        data = _read_toml(pyproject).get("tool", {}).get("codegraph", {})
        if data:
            return _build_config(data, source="pyproject.toml")

    return CodegraphConfig()


def merge_cli_overrides(
    config: CodegraphConfig,
    *,
    packages: Optional[Iterable[str]] = None,
    exclude_dirs: Optional[Iterable[str]] = None,
    exclude_suffixes: Optional[Iterable[str]] = None,
) -> CodegraphConfig:
    """Return a new config with CLI-provided values taking precedence.

    ``None`` means "not provided"; an empty list means "explicitly empty"
    (which is currently treated the same as None for ``packages`` — an empty
    packages list is never what you want).
    """
    merged = CodegraphConfig(
        packages=list(config.packages),
        exclude_dirs=set(config.exclude_dirs),
        exclude_suffixes=tuple(config.exclude_suffixes),
        source=config.source,
    )
    if packages:
        merged.packages = list(packages)
    if exclude_dirs:
        merged.exclude_dirs = set(exclude_dirs)
    if exclude_suffixes:
        merged.exclude_suffixes = tuple(exclude_suffixes)
    return merged


def require_packages(config: CodegraphConfig) -> None:
    """Raise :class:`ConfigError` if ``packages`` is empty, with a helpful
    message pointing the user at the config options."""
    if config.packages:
        return
    raise ConfigError(
        "No packages to index.\n\n"
        "Specify packages in one of three ways:\n"
        "  1. Create a codegraph.toml at the repo root:\n"
        "       packages = [\"packages/server\", \"packages/web\"]\n"
        "  2. Add a [tool.codegraph] section to pyproject.toml:\n"
        "       [tool.codegraph]\n"
        "       packages = [\"packages/server\", \"packages/web\"]\n"
        "  3. Pass --package / -p on the command line:\n"
        "       codegraph repo index <path> -p packages/server -p packages/web\n"
    )


def _read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Invalid TOML in {path}: {e}") from e


def _build_config(data: dict, *, source: str) -> CodegraphConfig:
    packages = data.get("packages", [])
    if not isinstance(packages, list) or not all(isinstance(p, str) for p in packages):
        raise ConfigError(
            f"{source}: `packages` must be a list of strings (got {type(packages).__name__})"
        )
    exclude_dirs = data.get("exclude_dirs", [])
    if not isinstance(exclude_dirs, list) or not all(isinstance(p, str) for p in exclude_dirs):
        raise ConfigError(f"{source}: `exclude_dirs` must be a list of strings")
    exclude_suffixes = data.get("exclude_suffixes", [])
    if not isinstance(exclude_suffixes, list) or not all(isinstance(p, str) for p in exclude_suffixes):
        raise ConfigError(f"{source}: `exclude_suffixes` must be a list of strings")
    return CodegraphConfig(
        packages=list(packages),
        exclude_dirs=set(exclude_dirs),
        exclude_suffixes=tuple(exclude_suffixes),
        source=source,
    )
