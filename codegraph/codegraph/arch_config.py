"""Configuration for :mod:`codegraph.arch_check`.

Parses ``.arch-policies.toml`` at the repo root (or a user-provided path) and
returns a typed :class:`ArchConfig` object that :mod:`codegraph.arch_check`
consumes. Missing file → all defaults, which match the previously-hardcoded
behaviour exactly. Extends the policy set with user-authored Cypher policies
so users can add rules without forking the Python package.

TOML schema (all sections optional):

    [meta]
    schema_version = 1

    [settings]
    sample_limit = 50          # max violation rows fetched per policy (default 10)

    [policies.import_cycles]
    enabled  = true
    min_hops = 2
    max_hops = 6

    [policies.cross_package]
    enabled = true
    pairs = [
      { importer = "apps/web", importee = "apps/api" },
    ]

    [policies.layer_bypass]
    enabled           = true
    controller_labels = ["Controller"]
    repository_suffix = "Repository"
    service_suffix    = "Service"
    call_depth        = 3

    [policies.coupling_ceiling]
    enabled     = true
    max_imports = 20

    [policies.orphan_detection]
    enabled     = true
    path_prefix = ""
    kinds       = ["function", "class", "atom", "endpoint"]

    [[policies.custom]]
    name          = "no_fat_files"
    description   = "Files over 500 LOC"
    count_cypher  = "MATCH (f:File) WHERE f.loc > 500 RETURN count(f) AS v"
    sample_cypher = "MATCH (f:File) WHERE f.loc > 500 RETURN f.path AS file LIMIT $limit"
"""
from __future__ import annotations

import re
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


DEFAULT_CONFIG_FILENAME = ".arch-policies.toml"
CURRENT_SCHEMA_VERSION = 1
VALID_ORPHAN_KINDS = frozenset({"function", "class", "atom", "endpoint"})


class ArchConfigError(ValueError):
    """Raised when ``.arch-policies.toml`` is malformed or semantically invalid."""


# ── Per-policy config dataclasses ────────────────────────────


@dataclass
class ImportCyclesConfig:
    enabled: bool = True
    min_hops: int = 2
    max_hops: int = 6


@dataclass
class CrossPackagePair:
    importer: str
    importee: str


@dataclass
class CrossPackageConfig:
    enabled: bool = True
    pairs: list[CrossPackagePair] = field(
        default_factory=lambda: [
            # Preserve the previously-hardcoded default from arch_check.py.
            CrossPackagePair(importer="twenty-front", importee="twenty-server"),
        ]
    )


@dataclass
class LayerBypassConfig:
    enabled: bool = True
    controller_labels: list[str] = field(default_factory=lambda: ["Controller"])
    repository_suffix: str = "Repository"
    service_suffix: str = "Service"
    call_depth: int = 3


@dataclass
class CouplingCeilingConfig:
    enabled: bool = True
    max_imports: int = 20


@dataclass
class OrphanDetectionConfig:
    enabled: bool = True
    path_prefix: str = ""
    kinds: list[str] = field(default_factory=lambda: [
        "function", "class", "atom", "endpoint",
    ])


@dataclass
class CustomPolicy:
    """User-authored policy, identified by a pair of Cypher queries."""

    name: str
    count_cypher: str
    sample_cypher: str
    description: str = ""
    enabled: bool = True


@dataclass
class Suppression:
    """A single suppressed violation — accepted technical debt."""

    policy: str
    key: str
    reason: str


@dataclass
class ArchConfig:
    """Aggregate config for ``codegraph arch-check``.

    Defaults match the previously-hardcoded behaviour so callers that don't
    supply a config file get identical results to pre-refactor.
    """

    import_cycles: ImportCyclesConfig = field(default_factory=ImportCyclesConfig)
    cross_package: CrossPackageConfig = field(default_factory=CrossPackageConfig)
    layer_bypass: LayerBypassConfig = field(default_factory=LayerBypassConfig)
    coupling_ceiling: CouplingCeilingConfig = field(default_factory=CouplingCeilingConfig)
    orphan_detection: OrphanDetectionConfig = field(default_factory=OrphanDetectionConfig)
    custom: list[CustomPolicy] = field(default_factory=list)
    suppressions: list[Suppression] = field(default_factory=list)
    schema_version: int = 1
    sample_limit: int = 10


# ── Loader ───────────────────────────────────────────────────


def load_arch_config(repo_root: Path, path: Optional[Path] = None) -> ArchConfig:
    """Load ``.arch-policies.toml`` from ``repo_root`` (or explicit ``path``).

    Missing file is not an error — returns :class:`ArchConfig` with all
    defaults. Malformed TOML or invalid fields raise :class:`ArchConfigError`.
    """
    config_path = path if path is not None else (repo_root / DEFAULT_CONFIG_FILENAME)
    if not config_path.exists():
        return ArchConfig()

    try:
        with config_path.open("rb") as f:
            raw = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise ArchConfigError(f"Malformed TOML in {config_path}: {exc}") from exc

    # ── [meta] section — schema versioning ──
    meta = raw.get("meta", {})
    if not isinstance(meta, dict):
        raise ArchConfigError(
            f"{config_path}: [meta] must be a table, got {type(meta).__name__}"
        )
    schema_version = meta.get("schema_version", CURRENT_SCHEMA_VERSION)
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ArchConfigError(
            f"{config_path}: meta.schema_version must be an integer"
        )
    if schema_version < 1:
        raise ArchConfigError(
            f"{config_path}: meta.schema_version must be a positive integer "
            f"(got {schema_version})"
        )
    if schema_version > CURRENT_SCHEMA_VERSION:
        raise ArchConfigError(
            f"{config_path}: schema_version {schema_version} is not supported "
            f"by this version of codegraph (max {CURRENT_SCHEMA_VERSION}). "
            f"Please upgrade: pip install --upgrade codegraph"
        )

    # ── [settings] section ──
    settings = raw.get("settings", {})
    if not isinstance(settings, dict):
        raise ArchConfigError(
            f"{config_path}: [settings] must be a table, got {type(settings).__name__}"
        )
    sample_limit = _int(settings, "sample_limit", 10, config_path, "settings")
    if sample_limit < 1:
        raise ArchConfigError(
            f"{config_path}: settings.sample_limit must be >= 1 (got {sample_limit})"
        )

    # ── [policies] section ──
    policies = raw.get("policies", {})
    if not isinstance(policies, dict):
        raise ArchConfigError(
            f"{config_path}: [policies] must be a table, got {type(policies).__name__}"
        )

    return ArchConfig(
        import_cycles=_parse_import_cycles(policies.get("import_cycles", {}), config_path),
        cross_package=_parse_cross_package(policies.get("cross_package", {}), config_path),
        layer_bypass=_parse_layer_bypass(policies.get("layer_bypass", {}), config_path),
        coupling_ceiling=_parse_coupling_ceiling(policies.get("coupling_ceiling", {}), config_path),
        orphan_detection=_parse_orphan_detection(policies.get("orphan_detection", {}), config_path),
        custom=_parse_custom(policies.get("custom", []), config_path),
        suppressions=_parse_suppressions(raw.get("suppress", []), config_path),
        schema_version=schema_version,
        sample_limit=sample_limit,
    )


# ── Parsers ──────────────────────────────────────────────────


def _parse_import_cycles(raw: dict, path: Path) -> ImportCyclesConfig:
    defaults = ImportCyclesConfig()
    cfg = ImportCyclesConfig(
        enabled=_bool(raw, "enabled", defaults.enabled, path, "policies.import_cycles"),
        min_hops=_int(raw, "min_hops", defaults.min_hops, path, "policies.import_cycles"),
        max_hops=_int(raw, "max_hops", defaults.max_hops, path, "policies.import_cycles"),
    )
    if cfg.min_hops < 2:
        raise ArchConfigError(
            f"{path}: policies.import_cycles.min_hops must be >= 2 (got {cfg.min_hops})"
        )
    if cfg.max_hops < cfg.min_hops:
        raise ArchConfigError(
            f"{path}: policies.import_cycles.max_hops ({cfg.max_hops}) "
            f"must be >= min_hops ({cfg.min_hops})"
        )
    return cfg


def _parse_cross_package(raw: dict, path: Path) -> CrossPackageConfig:
    defaults = CrossPackageConfig()
    enabled = _bool(raw, "enabled", defaults.enabled, path, "policies.cross_package")
    pairs_raw = raw.get("pairs")
    if pairs_raw is None:
        return CrossPackageConfig(enabled=enabled, pairs=defaults.pairs)
    if not isinstance(pairs_raw, list):
        raise ArchConfigError(
            f"{path}: policies.cross_package.pairs must be a list, "
            f"got {type(pairs_raw).__name__}"
        )
    pairs: list[CrossPackagePair] = []
    for i, p in enumerate(pairs_raw):
        if not isinstance(p, dict):
            raise ArchConfigError(
                f"{path}: policies.cross_package.pairs[{i}] must be a table"
            )
        try:
            importer = p["importer"]
            importee = p["importee"]
        except KeyError as missing:
            raise ArchConfigError(
                f"{path}: policies.cross_package.pairs[{i}] missing key: {missing}"
            ) from missing
        if not (isinstance(importer, str) and isinstance(importee, str)):
            raise ArchConfigError(
                f"{path}: policies.cross_package.pairs[{i}] importer/importee must be strings"
            )
        pairs.append(CrossPackagePair(importer=importer, importee=importee))
    return CrossPackageConfig(enabled=enabled, pairs=pairs)


def _parse_layer_bypass(raw: dict, path: Path) -> LayerBypassConfig:
    defaults = LayerBypassConfig()
    labels = raw.get("controller_labels", defaults.controller_labels)
    if not (isinstance(labels, list) and all(isinstance(x, str) for x in labels)):
        raise ArchConfigError(
            f"{path}: policies.layer_bypass.controller_labels must be a list of strings"
        )
    if not labels:
        raise ArchConfigError(
            f"{path}: policies.layer_bypass.controller_labels must not be empty"
        )
    return LayerBypassConfig(
        enabled=_bool(raw, "enabled", defaults.enabled, path, "policies.layer_bypass"),
        controller_labels=list(labels),
        repository_suffix=_str(
            raw, "repository_suffix", defaults.repository_suffix, path, "policies.layer_bypass"
        ),
        service_suffix=_str(
            raw, "service_suffix", defaults.service_suffix, path, "policies.layer_bypass"
        ),
        call_depth=_int(raw, "call_depth", defaults.call_depth, path, "policies.layer_bypass"),
    )


def _parse_coupling_ceiling(raw: dict, path: Path) -> CouplingCeilingConfig:
    defaults = CouplingCeilingConfig()
    cfg = CouplingCeilingConfig(
        enabled=_bool(raw, "enabled", defaults.enabled, path, "policies.coupling_ceiling"),
        max_imports=_int(raw, "max_imports", defaults.max_imports, path, "policies.coupling_ceiling"),
    )
    if cfg.max_imports < 1:
        raise ArchConfigError(
            f"{path}: policies.coupling_ceiling.max_imports must be >= 1 (got {cfg.max_imports})"
        )
    return cfg


def _parse_orphan_detection(raw: dict, path: Path) -> OrphanDetectionConfig:
    defaults = OrphanDetectionConfig()
    enabled = _bool(raw, "enabled", defaults.enabled, path, "policies.orphan_detection")
    path_prefix = _str(raw, "path_prefix", defaults.path_prefix, path, "policies.orphan_detection")
    kinds_raw = raw.get("kinds", defaults.kinds)
    if not isinstance(kinds_raw, list):
        raise ArchConfigError(
            f"{path}: policies.orphan_detection.kinds must be a list of strings"
        )
    if not kinds_raw:
        raise ArchConfigError(
            f"{path}: policies.orphan_detection.kinds must not be empty"
        )
    for i, k in enumerate(kinds_raw):
        if not isinstance(k, str):
            raise ArchConfigError(
                f"{path}: policies.orphan_detection.kinds[{i}] must be a string"
            )
        if k not in VALID_ORPHAN_KINDS:
            raise ArchConfigError(
                f"{path}: policies.orphan_detection.kinds[{i}] = '{k}' is not valid "
                f"(choose from: {', '.join(sorted(VALID_ORPHAN_KINDS))})"
            )
    return OrphanDetectionConfig(enabled=enabled, path_prefix=path_prefix, kinds=list(kinds_raw))


def _parse_custom(raw: list, path: Path) -> list[CustomPolicy]:
    if not isinstance(raw, list):
        raise ArchConfigError(
            f"{path}: policies.custom must be an array of tables, got {type(raw).__name__}"
        )
    seen: set[str] = set()
    builtins = {"import_cycles", "cross_package", "layer_bypass", "coupling_ceiling", "orphan_detection"}
    out: list[CustomPolicy] = []
    for i, p in enumerate(raw):
        if not isinstance(p, dict):
            raise ArchConfigError(
                f"{path}: policies.custom[{i}] must be a table"
            )
        name = p.get("name")
        count_cypher = p.get("count_cypher")
        sample_cypher = p.get("sample_cypher")
        for field_name, value in (
            ("name", name),
            ("count_cypher", count_cypher),
            ("sample_cypher", sample_cypher),
        ):
            if not (isinstance(value, str) and value.strip()):
                raise ArchConfigError(
                    f"{path}: policies.custom[{i}].{field_name} must be a non-empty string"
                )
        if name in builtins:
            raise ArchConfigError(
                f"{path}: custom policy name '{name}' collides with a built-in policy"
            )
        if name in seen:
            raise ArchConfigError(
                f"{path}: duplicate custom policy name '{name}'"
            )
        seen.add(name)
        enabled = p.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ArchConfigError(
                f"{path}: policies.custom[{i}].enabled must be a boolean"
            )
        description = p.get("description", "")
        if not isinstance(description, str):
            raise ArchConfigError(
                f"{path}: policies.custom[{i}].description must be a string"
            )
        if re.search(r'LIMIT\s+\d+', sample_cypher, re.IGNORECASE):
            warnings.warn(
                f"{path}: policies.custom[{i}] ('{name}') sample_cypher contains a "
                f"hardcoded LIMIT. Use LIMIT $limit instead — the value is injected "
                f"from settings.sample_limit at runtime.",
                stacklevel=2,
            )
        out.append(CustomPolicy(
            name=name,
            count_cypher=count_cypher,
            sample_cypher=sample_cypher,
            description=description,
            enabled=enabled,
        ))
    return out


def _parse_suppressions(raw: list, path: Path) -> list[Suppression]:
    if not isinstance(raw, list):
        raise ArchConfigError(
            f"{path}: suppress must be an array of tables, got {type(raw).__name__}"
        )
    out: list[Suppression] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ArchConfigError(
                f"{path}: suppress[{i}] must be a table"
            )
        for field_name in ("policy", "key", "reason"):
            value = entry.get(field_name)
            if not (isinstance(value, str) and value.strip()):
                raise ArchConfigError(
                    f"{path}: suppress[{i}].{field_name} must be a non-empty string"
                )
        out.append(Suppression(
            policy=entry["policy"],
            key=entry["key"],
            reason=entry["reason"],
        ))
    return out


# ── Tiny typed-getters ───────────────────────────────────────


def _bool(raw: dict, key: str, default: bool, path: Path, section_path: str) -> bool:
    if key not in raw:
        return default
    v = raw[key]
    if not isinstance(v, bool):
        raise ArchConfigError(f"{path}: {section_path}.{key} must be a boolean")
    return v


def _int(raw: dict, key: str, default: int, path: Path, section_path: str) -> int:
    if key not in raw:
        return default
    v = raw[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ArchConfigError(f"{path}: {section_path}.{key} must be an integer")
    return v


def _str(raw: dict, key: str, default: str, path: Path, section_path: str) -> str:
    if key not in raw:
        return default
    v = raw[key]
    if not isinstance(v, str):
        raise ArchConfigError(f"{path}: {section_path}.{key} must be a string")
    return v
