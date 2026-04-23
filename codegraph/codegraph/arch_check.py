"""Architecture-conformance policies.

Runs a fixed set of built-in policies plus any user-authored policies from
``.arch-policies.toml`` as Cypher against the live Neo4j graph and returns an
:class:`ArchReport`. Mirrors :mod:`codegraph.validate`'s shape: typed result
dataclasses, Rich-table rendering when a console is attached, JSON
serialisation for CI, and an ``ok`` rollup that maps directly to a process
exit code.

Built-in policies:

- **import_cycles** — file IMPORTS cycles of configurable length.
- **cross_package** — forbidden import directions (configurable pair list).
- **layer_bypass** — controllers reaching ``*Repository`` methods without
  traversing a ``*Service`` (suffixes configurable).
- **coupling_ceiling** — files with more than N distinct file-level imports
  (configurable threshold).
- **orphan_detection** — functions, classes, atoms, or endpoints with zero
  inbound references and no framework-entry-point decorator.

User-authored policies live under ``[[policies.custom]]`` in
``.arch-policies.toml`` (see :mod:`codegraph.arch_config`).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from neo4j import Driver, GraphDatabase
from rich.console import Console
from rich.table import Table

from .arch_config import (
    ArchConfig,
    CouplingCeilingConfig,
    CrossPackageConfig,
    CustomPolicy,
    ImportCyclesConfig,
    LayerBypassConfig,
    OrphanDetectionConfig,
    Suppression,
    load_arch_config,
)



def _scope_filter(
    var: str, prop: str, scope: list[str] | None,
) -> tuple[str, dict]:
    """Return ``(cypher_fragment, params)`` for optional scope filtering.

    *var* is the Cypher variable name (e.g. ``"a"``), *prop* is the property
    to match (``"path"`` for :label:`File` nodes, ``"file"`` for
    :label:`Class`/:label:`Function`/:label:`Method` nodes).  Returns an
    empty fragment when *scope* is ``None`` or empty.
    """
    if not scope:
        return "", {}
    parts: list[str] = []
    params: dict[str, str] = {}
    for i, prefix in enumerate(scope):
        key = f"_scope{i}"
        parts.append(f"{var}.{prop} STARTS WITH ${key}")
        params[key] = prefix
    return f"({' OR '.join(parts)})", params


# ── Result shapes ────────────────────────────────────────────

@dataclass
class PolicyResult:
    """Outcome of a single architecture policy."""
    name: str
    passed: bool
    violation_count: int
    sample: list[dict] = field(default_factory=list)
    detail: str = ""
    disabled: bool = False
    suppressed_count: int = 0
    suppressed_sample: list[dict] = field(default_factory=list)
    incomplete_suppression_coverage: bool = False


@dataclass
class ArchReport:
    """Aggregate result across all policies."""
    policies: list[PolicyResult] = field(default_factory=list)
    stale_suppressions: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(p.passed for p in self.policies)

    def to_json(self) -> str:
        return json.dumps(
            {
                "ok": self.ok,
                "policies": [asdict(p) for p in self.policies],
                "stale_suppressions": self.stale_suppressions,
            },
            indent=2,
            default=str,
        )


# ── Orchestrator ─────────────────────────────────────────────

def run_arch_check(
    uri: str,
    user: str,
    password: str,
    console: Optional[Console] = None,
    config: Optional[ArchConfig] = None,
    repo_root: Optional[Path] = None,
    scope: list[str] | None = None,
) -> ArchReport:
    """Open a driver, evaluate every configured policy, return an :class:`ArchReport`.

    ``config`` takes precedence if provided; otherwise :func:`load_arch_config`
    reads ``<repo_root>/.arch-policies.toml`` (``repo_root`` defaults to
    ``Path.cwd()``). Missing config file → all built-in defaults, no custom
    policies.

    ``scope``, when non-empty, restricts every built-in policy to nodes whose
    ``file`` / ``path`` property starts with at least one of the given
    prefixes.  Custom policies are *not* filtered — their Cypher is
    user-authored.
    """
    if config is None:
        config = load_arch_config(repo_root or Path.cwd())

    sample_limit = config.sample_limit

    driver = GraphDatabase.driver(uri, auth=(user, password))
    stale: list[dict] = []
    try:
        policies = _run_all(driver, config, scope, sample_limit)
        if config.suppressions:
            policies, stale = _apply_suppressions(
                policies, config.suppressions, sample_limit,
                driver=driver, scope=scope, config=config,
            )
    finally:
        driver.close()

    report = ArchReport(policies=policies, stale_suppressions=stale)
    if console is not None:
        _render(console, report)
    return report


def _run_all(
    driver: Driver, config: ArchConfig, scope: list[str] | None = None,
    sample_limit: int = 10,
) -> list[PolicyResult]:
    """Evaluate every policy in a stable order. Disabled policies emit a marker."""
    out: list[PolicyResult] = []

    if config.import_cycles.enabled:
        out.append(_check_import_cycles(driver, config.import_cycles, scope, sample_limit))
    else:
        out.append(_disabled("import_cycles"))

    if config.cross_package.enabled:
        out.append(_check_cross_package(driver, config.cross_package, scope, sample_limit))
    else:
        out.append(_disabled("cross_package"))

    if config.layer_bypass.enabled:
        out.append(_check_layer_bypass(driver, config.layer_bypass, scope, sample_limit))
    else:
        out.append(_disabled("layer_bypass"))

    if config.coupling_ceiling.enabled:
        out.append(_check_coupling_ceiling(driver, config.coupling_ceiling, scope, sample_limit))
    else:
        out.append(_disabled("coupling_ceiling"))

    if config.orphan_detection.enabled:
        out.append(_check_orphans(driver, config.orphan_detection, scope, sample_limit))
    else:
        out.append(_disabled("orphan_detection"))

    for custom in config.custom:
        if custom.enabled:
            out.append(_check_custom(driver, custom, scope, sample_limit))
        else:
            out.append(_disabled(custom.name))

    return out


def _disabled(name: str) -> PolicyResult:
    return PolicyResult(
        name=name,
        passed=True,
        violation_count=0,
        sample=[],
        detail="(disabled in .arch-policies.toml)",
        disabled=True,
    )


# ── Policies ─────────────────────────────────────────────────

def _check_import_cycles(
    driver: Driver, cfg: ImportCyclesConfig, scope: list[str] | None = None,
    sample_limit: int = 10,
) -> PolicyResult:
    """Detect file-level IMPORTS cycles of configurable length."""
    hops = f"*{cfg.min_hops}..{cfg.max_hops}"
    scope_frag, scope_params = _scope_filter("a", "path", scope)
    where = f"WHERE {scope_frag}\n" if scope_frag else ""
    sample_cypher = (
        f"MATCH path = (a:File)-[:IMPORTS{hops}]->(a)\n"
        f"{where}"
        f"WITH [n IN nodes(path) | n.path] AS cycle, length(path) AS hops\n"
        f"RETURN DISTINCT cycle, hops\n"
        f"ORDER BY hops ASC, cycle[0]\n"
        f"LIMIT $limit"
    )
    count_cypher = (
        f"MATCH path = (a:File)-[:IMPORTS{hops}]->(a)\n"
        f"{where}"
        f"RETURN count(DISTINCT path) AS v"
    )
    with driver.session() as s:
        total = int(s.run(count_cypher, **scope_params).single()["v"] or 0)
        sample = [dict(r) for r in s.run(sample_cypher, limit=sample_limit, **scope_params)]
    return PolicyResult(
        name="import_cycles",
        passed=(total == 0),
        violation_count=total,
        sample=sample,
        detail=f"Files (or packages) that import each other transitively (hops {cfg.min_hops}-{cfg.max_hops}).",
    )


def _check_cross_package(
    driver: Driver, cfg: CrossPackageConfig, scope: list[str] | None = None,
    sample_limit: int = 10,
) -> PolicyResult:
    """Detect imports that cross a forbidden package boundary."""
    scope_frag, scope_params = _scope_filter("a", "path", scope)
    scope_clause = f" AND {scope_frag}" if scope_frag else ""

    detected: list[dict] = []
    total = 0
    with driver.session() as s:
        for pair in cfg.pairs:
            count = int(s.run(
                "MATCH (a:File)-[:IMPORTS]->(b:File) "
                "WHERE a.package = $a AND b.package = $b"
                f"{scope_clause} "
                "RETURN count(*) AS v",
                a=pair.importer, b=pair.importee, **scope_params,
            ).single()["v"] or 0)
            total += count
            if count and len(detected) < sample_limit:
                rows = list(s.run(
                    "MATCH (a:File)-[:IMPORTS]->(b:File) "
                    "WHERE a.package = $a AND b.package = $b"
                    f"{scope_clause} "
                    "RETURN a.path AS importer, b.path AS importee "
                    "LIMIT $limit",
                    a=pair.importer, b=pair.importee,
                    limit=sample_limit - len(detected), **scope_params,
                ))
                for r in rows:
                    detected.append({
                        "importer_package": pair.importer,
                        "importee_package": pair.importee,
                        "importer": r["importer"],
                        "importee": r["importee"],
                    })
    detail_pairs = ", ".join(f"{p.importer}→{p.importee}" for p in cfg.pairs)
    return PolicyResult(
        name="cross_package",
        passed=(total == 0),
        violation_count=total,
        sample=detected,
        detail=f"Forbidden import directions: {detail_pairs or '(none configured)'}.",
    )


def _check_layer_bypass(
    driver: Driver, cfg: LayerBypassConfig, scope: list[str] | None = None,
    sample_limit: int = 10,
) -> PolicyResult:
    """Controllers reaching ``*Repository`` without traversing ``*Service``."""
    labels_or = "|".join(cfg.controller_labels)
    depth = f"*1..{cfg.call_depth}"
    scope_frag, scope_params = _scope_filter("ctrl", "file", scope)
    scope_clause = f"  AND {scope_frag}\n" if scope_frag else ""
    sample_cypher = (
        f"MATCH (ctrl:{labels_or})-[:HAS_METHOD]->(m:Method)"
        f"-[:CALLS{depth}]->(target:Method)\n"
        f"MATCH (repo:Class)-[:HAS_METHOD]->(target)\n"
        f"WHERE repo.name ENDS WITH $repo_suffix\n"
        f"{scope_clause}"
        f"  AND NOT EXISTS {{\n"
        f"    MATCH (ctrl)-[:HAS_METHOD]->(:Method)-[:CALLS{depth}]->(:Method)"
        f"<-[:HAS_METHOD]-(svc:Class)\n"
        f"    WHERE svc.name ENDS WITH $svc_suffix\n"
        f"  }}\n"
        f"RETURN DISTINCT ctrl.name AS controller, repo.name AS repository, "
        f"target.name AS method\n"
        f"ORDER BY ctrl.name, repo.name, target.name\n"
        f"LIMIT $limit"
    )
    count_cypher = (
        f"MATCH (ctrl:{labels_or})-[:HAS_METHOD]->(m:Method)"
        f"-[:CALLS{depth}]->(target:Method)\n"
        f"MATCH (repo:Class)-[:HAS_METHOD]->(target)\n"
        f"WHERE repo.name ENDS WITH $repo_suffix\n"
        f"{scope_clause}"
        f"  AND NOT EXISTS {{\n"
        f"    MATCH (ctrl)-[:HAS_METHOD]->(:Method)-[:CALLS{depth}]->(:Method)"
        f"<-[:HAS_METHOD]-(svc:Class)\n"
        f"    WHERE svc.name ENDS WITH $svc_suffix\n"
        f"  }}\n"
        f"RETURN count(DISTINCT ctrl) AS v"
    )
    with driver.session() as s:
        total = int(s.run(
            count_cypher,
            repo_suffix=cfg.repository_suffix,
            svc_suffix=cfg.service_suffix,
            **scope_params,
        ).single()["v"] or 0)
        sample = [dict(r) for r in s.run(
            sample_cypher,
            repo_suffix=cfg.repository_suffix,
            svc_suffix=cfg.service_suffix,
            limit=sample_limit,
            **scope_params,
        )]
    return PolicyResult(
        name="layer_bypass",
        passed=(total == 0),
        violation_count=total,
        sample=sample,
        detail=(
            f"{'/'.join(cfg.controller_labels)} calling *{cfg.repository_suffix} "
            f"methods without a *{cfg.service_suffix} layer in between."
        ),
    )


def _check_coupling_ceiling(
    driver: Driver, cfg: CouplingCeilingConfig, scope: list[str] | None = None,
    sample_limit: int = 10,
) -> PolicyResult:
    """Flag files with more than ``cfg.max_imports`` distinct file-level imports."""
    scope_frag, scope_params = _scope_filter("f", "path", scope)
    where = f"WHERE {scope_frag}\n" if scope_frag else ""
    count_cypher = (
        "MATCH (f:File)-[:IMPORTS]->(g:File)\n"
        f"{where}"
        "WITH f, count(g) AS deps\n"
        "WHERE deps > $threshold\n"
        "RETURN count(f) AS v"
    )
    sample_cypher = (
        "MATCH (f:File)-[:IMPORTS]->(g:File)\n"
        f"{where}"
        "WITH f, count(g) AS deps\n"
        "WHERE deps > $threshold\n"
        "RETURN f.path AS file, deps\n"
        "ORDER BY deps DESC\n"
        "LIMIT $limit"
    )
    with driver.session() as s:
        total = int(s.run(
            count_cypher, threshold=cfg.max_imports, **scope_params,
        ).single()["v"] or 0)
        sample = [dict(r) for r in s.run(
            sample_cypher, threshold=cfg.max_imports, limit=sample_limit,
            **scope_params,
        )]
    return PolicyResult(
        name="coupling_ceiling",
        passed=(total == 0),
        violation_count=total,
        sample=sample,
        detail=f"Files with more than {cfg.max_imports} distinct file-level imports.",
    )


def _check_orphans(
    driver: Driver, cfg: OrphanDetectionConfig, scope: list[str] | None = None,
    sample_limit: int = 10,
) -> PolicyResult:
    """Flag functions/classes/atoms/endpoints with zero inbound references."""
    # Build sub-queries for each requested kind.
    _kind_queries = {
        "function": (
            "MATCH (f:Function)\n"
            "WHERE NOT EXISTS { ()-[:CALLS]->(f) }\n"
            "  AND NOT EXISTS { ()-[:RENDERS]->(f) }\n"
            "  AND NOT EXISTS { (f)-[:DECORATED_BY]->(:Decorator) }\n"
            "  AND NONE(pfx IN $exclude_prefixes WHERE f.name STARTS WITH pfx)\n"
            "  AND NOT f.name IN $exclude_names\n"
            "{prefix_filter}"
            "RETURN 'orphan_function' AS kind, f.name AS name, f.file AS file"
        ),
        "class": (
            "MATCH (c:Class)\n"
            "WHERE NOT EXISTS { ()-[:EXTENDS]->(c) }\n"
            "  AND NOT EXISTS { ()-[:INJECTS]->(c) }\n"
            "  AND NOT EXISTS { ()-[:RESOLVES]->(c) }\n"
            "  AND NOT EXISTS { (:File)-[:IMPORTS_SYMBOL {symbol: c.name}]->(:File) }\n"
            "{prefix_filter}"
            "RETURN 'orphan_class' AS kind, c.name AS name, c.file AS file"
        ),
        "atom": (
            "MATCH (a:Atom)\n"
            "WHERE NOT EXISTS { ()-[:READS_ATOM]->(a) }\n"
            "  AND NOT EXISTS { ()-[:WRITES_ATOM]->(a) }\n"
            "{prefix_filter}"
            "RETURN 'orphan_atom' AS kind, a.name AS name, a.file AS file"
        ),
        "endpoint": (
            "MATCH (e:Endpoint)\n"
            "WHERE NOT EXISTS { (:Method)-[:HANDLES]->(e) }\n"
            "{prefix_filter}"
            "RETURN 'orphan_endpoint' AS kind, "
            "(e.method + ' ' + e.path) AS name, e.file AS file"
        ),
    }
    # Variable used in the prefix filter differs per kind.
    _kind_var = {"function": "f", "class": "c", "atom": "a", "endpoint": "e"}

    # Determine the path filter: explicit path_prefix wins, then --scope,
    # then no filter.  scope_extra holds any params the scope filter needs.
    scope_extra: dict = {}
    parts: list[str] = []
    for kind in cfg.kinds:
        tmpl = _kind_queries[kind]
        if cfg.path_prefix:
            pf = f"  AND {_kind_var[kind]}.file STARTS WITH $prefix\n"
        elif scope:
            sf, sp = _scope_filter(_kind_var[kind], "file", scope)
            pf = f"  AND {sf}\n"
            scope_extra.update(sp)
        else:
            pf = ""
        parts.append(tmpl.replace("{prefix_filter}", pf))

    union = "\nUNION ALL\n".join(parts)
    count_cypher = f"CALL () {{\n{union}\n}}\nRETURN count(*) AS v"
    sample_cypher = (
        f"{union}\n"
        f"ORDER BY kind, file, name\n"
        f"LIMIT $limit"
    )

    params: dict = {
        "exclude_prefixes": cfg.exclude_prefixes,
        "exclude_names": cfg.exclude_names,
    }
    if cfg.path_prefix:
        params["prefix"] = cfg.path_prefix
    params.update(scope_extra)

    with driver.session() as s:
        total = int(s.run(count_cypher, **params).single()["v"] or 0)
        sample = [dict(r) for r in s.run(sample_cypher, limit=sample_limit, **params)]

    kinds_str = ", ".join(cfg.kinds)
    return PolicyResult(
        name="orphan_detection",
        passed=(total == 0),
        violation_count=total,
        sample=sample,
        detail=f"Symbols with zero inbound references (kinds: {kinds_str}).",
    )


def _check_custom(
    driver: Driver, custom: CustomPolicy,
    scope: list[str] | None = None, sample_limit: int = 10,
) -> PolicyResult:
    """Run a user-authored policy from :class:`CustomPolicy`.

    Injects ``$limit`` (from *sample_limit*) and ``$scope`` (list of path
    prefixes, empty when unscoped) as Cypher parameters so user-authored
    queries can reference them.
    """
    scope_param = scope or []
    with driver.session() as s:
        count_result = s.run(custom.count_cypher, scope=scope_param).single()
        total = int((count_result["v"] if count_result else 0) or 0)
        sample: list[dict] = []
        if total > 0:
            sample = [dict(r) for r in s.run(custom.sample_cypher, limit=sample_limit, scope=scope_param)][:sample_limit]
    return PolicyResult(
        name=custom.name,
        passed=(total == 0),
        violation_count=total,
        sample=sample,
        detail=custom.description or "(user-defined policy)",
    )


# ── Exact suppression counting ─────────────────────────────


def _count_unsuppressed(
    driver: Driver,
    policy_name: str,
    suppressed_keys: list[str],
    scope: list[str] | None,
    config: ArchConfig,
) -> int | None:
    """Return the exact unsuppressed violation count for a built-in policy.

    Builds a filtered Cypher ``COUNT`` query that mirrors the original
    ``_check_*`` count query but adds ``WHERE NOT`` clauses to exclude
    violations whose keys appear in *suppressed_keys*.  Returns ``None``
    for custom (user-authored) policies — those fall back to Python-side
    sample counting in :func:`_apply_suppressions`.
    """
    if policy_name == "coupling_ceiling":
        return _count_unsuppressed_coupling(driver, suppressed_keys, scope, config.coupling_ceiling)
    if policy_name == "cross_package":
        return _count_unsuppressed_cross_package(driver, suppressed_keys, scope, config.cross_package)
    if policy_name == "layer_bypass":
        return _count_unsuppressed_layer_bypass(driver, suppressed_keys, scope, config.layer_bypass)
    if policy_name == "orphan_detection":
        return _count_unsuppressed_orphans(driver, suppressed_keys, scope, config.orphan_detection)
    if policy_name == "import_cycles":
        return _count_unsuppressed_import_cycles(driver, suppressed_keys, scope, config.import_cycles)
    # Custom / unknown policy — caller falls back to Python counting.
    return None


def _count_unsuppressed_coupling(
    driver: Driver, suppressed_keys: list[str],
    scope: list[str] | None, cfg: CouplingCeilingConfig,
) -> int:
    scope_frag, scope_params = _scope_filter("f", "path", scope)
    where = f"WHERE {scope_frag}\n" if scope_frag else ""
    cypher = (
        "MATCH (f:File)-[:IMPORTS]->(g:File)\n"
        f"{where}"
        "WITH f, count(g) AS deps\n"
        "WHERE deps > $threshold\n"
        "  AND NOT f.path IN $suppressed_keys\n"
        "RETURN count(f) AS v"
    )
    with driver.session() as s:
        return int(s.run(cypher, threshold=cfg.max_imports,
                         suppressed_keys=suppressed_keys, **scope_params).single()["v"] or 0)


def _count_unsuppressed_cross_package(
    driver: Driver, suppressed_keys: list[str],
    scope: list[str] | None, cfg: CrossPackageConfig,
) -> int:
    scope_frag, scope_params = _scope_filter("a", "path", scope)
    scope_clause = f" AND {scope_frag}" if scope_frag else ""
    total = 0
    with driver.session() as s:
        for pair in cfg.pairs:
            count = int(s.run(
                "MATCH (a:File)-[:IMPORTS]->(b:File) "
                "WHERE a.package = $a AND b.package = $b"
                f"{scope_clause} "
                "AND NOT (a.path + ' -> ' + b.path) IN $suppressed_keys "
                "RETURN count(*) AS v",
                a=pair.importer, b=pair.importee,
                suppressed_keys=suppressed_keys, **scope_params,
            ).single()["v"] or 0)
            total += count
    return total


def _count_unsuppressed_layer_bypass(
    driver: Driver, suppressed_keys: list[str],
    scope: list[str] | None, cfg: LayerBypassConfig,
) -> int:
    labels_or = "|".join(cfg.controller_labels)
    depth = f"*1..{cfg.call_depth}"
    scope_frag, scope_params = _scope_filter("ctrl", "file", scope)
    scope_clause = f"  AND {scope_frag}\n" if scope_frag else ""
    cypher = (
        f"MATCH (ctrl:{labels_or})-[:HAS_METHOD]->(m:Method)"
        f"-[:CALLS{depth}]->(target:Method)\n"
        f"MATCH (repo:Class)-[:HAS_METHOD]->(target)\n"
        f"WHERE repo.name ENDS WITH $repo_suffix\n"
        f"{scope_clause}"
        f"  AND NOT EXISTS {{\n"
        f"    MATCH (ctrl)-[:HAS_METHOD]->(:Method)-[:CALLS{depth}]->(:Method)"
        f"<-[:HAS_METHOD]-(svc:Class)\n"
        f"    WHERE svc.name ENDS WITH $svc_suffix\n"
        f"  }}\n"
        f"  AND NOT (ctrl.name + ' -> ' + repo.name + '.' + target.name) IN $suppressed_keys\n"
        f"RETURN count(DISTINCT ctrl) AS v"
    )
    with driver.session() as s:
        return int(s.run(
            cypher,
            repo_suffix=cfg.repository_suffix,
            svc_suffix=cfg.service_suffix,
            suppressed_keys=suppressed_keys,
            **scope_params,
        ).single()["v"] or 0)


def _count_unsuppressed_orphans(
    driver: Driver, suppressed_keys: list[str],
    scope: list[str] | None, cfg: OrphanDetectionConfig,
) -> int:
    _kind_queries = {
        "function": (
            "MATCH (f:Function)\n"
            "WHERE NOT EXISTS { ()-[:CALLS]->(f) }\n"
            "  AND NOT EXISTS { ()-[:RENDERS]->(f) }\n"
            "  AND NOT EXISTS { (f)-[:DECORATED_BY]->(:Decorator) }\n"
            "  AND NONE(pfx IN $exclude_prefixes WHERE f.name STARTS WITH pfx)\n"
            "  AND NOT f.name IN $exclude_names\n"
            "{prefix_filter}"
            "  AND NOT ('orphan_function:' + f.name) IN $suppressed_keys\n"
            "RETURN 'orphan_function' AS kind, f.name AS name, f.file AS file"
        ),
        "class": (
            "MATCH (c:Class)\n"
            "WHERE NOT EXISTS { ()-[:EXTENDS]->(c) }\n"
            "  AND NOT EXISTS { ()-[:INJECTS]->(c) }\n"
            "  AND NOT EXISTS { ()-[:RESOLVES]->(c) }\n"
            "  AND NOT EXISTS { (:File)-[:IMPORTS_SYMBOL {symbol: c.name}]->(:File) }\n"
            "{prefix_filter}"
            "  AND NOT ('orphan_class:' + c.name) IN $suppressed_keys\n"
            "RETURN 'orphan_class' AS kind, c.name AS name, c.file AS file"
        ),
        "atom": (
            "MATCH (a:Atom)\n"
            "WHERE NOT EXISTS { ()-[:READS_ATOM]->(a) }\n"
            "  AND NOT EXISTS { ()-[:WRITES_ATOM]->(a) }\n"
            "{prefix_filter}"
            "  AND NOT ('orphan_atom:' + a.name) IN $suppressed_keys\n"
            "RETURN 'orphan_atom' AS kind, a.name AS name, a.file AS file"
        ),
        "endpoint": (
            "MATCH (e:Endpoint)\n"
            "WHERE NOT EXISTS { (:Method)-[:HANDLES]->(e) }\n"
            "{prefix_filter}"
            "  AND NOT ('orphan_endpoint:' + e.method + ' ' + e.path) IN $suppressed_keys\n"
            "RETURN 'orphan_endpoint' AS kind, "
            "(e.method + ' ' + e.path) AS name, e.file AS file"
        ),
    }
    _kind_var = {"function": "f", "class": "c", "atom": "a", "endpoint": "e"}

    scope_extra: dict = {}
    parts: list[str] = []
    for kind in cfg.kinds:
        tmpl = _kind_queries[kind]
        if cfg.path_prefix:
            pf = f"  AND {_kind_var[kind]}.file STARTS WITH $prefix\n"
        elif scope:
            sf, sp = _scope_filter(_kind_var[kind], "file", scope)
            pf = f"  AND {sf}\n"
            scope_extra.update(sp)
        else:
            pf = ""
        parts.append(tmpl.replace("{prefix_filter}", pf))

    union = "\nUNION ALL\n".join(parts)
    cypher = f"CALL () {{\n{union}\n}}\nRETURN count(*) AS v"

    params: dict = {
        "suppressed_keys": suppressed_keys,
        "exclude_prefixes": cfg.exclude_prefixes,
        "exclude_names": cfg.exclude_names,
    }
    if cfg.path_prefix:
        params["prefix"] = cfg.path_prefix
    params.update(scope_extra)

    with driver.session() as s:
        return int(s.run(cypher, **params).single()["v"] or 0)


def _count_unsuppressed_import_cycles(
    driver: Driver, suppressed_keys: list[str],
    scope: list[str] | None, cfg: ImportCyclesConfig,
) -> int:
    hops = f"*{cfg.min_hops}..{cfg.max_hops}"
    scope_frag, scope_params = _scope_filter("a", "path", scope)
    where = f"WHERE {scope_frag}\n" if scope_frag else ""

    # Separate edge-pair keys ("A -> B") from full-cycle keys ("A -> B -> C -> A").
    edge_pairs: list[list[str]] = []
    full_cycle_keys: list[str] = []
    for key in suppressed_keys:
        parts = [p.strip() for p in key.split(" -> ")]
        if len(parts) == 2:
            edge_pairs.append(parts)
        else:
            full_cycle_keys.append(key)

    # Build WHERE NOT clauses for each type.
    filters: list[str] = []
    params: dict = {**scope_params}
    if edge_pairs:
        filters.append(
            "NONE(pair IN $edge_pairs WHERE\n"
            "  ANY(i IN range(0, size(cycle)-2) WHERE cycle[i] = pair[0] AND cycle[i+1] = pair[1]))"
        )
        params["edge_pairs"] = edge_pairs
    if full_cycle_keys:
        filters.append(
            "NOT reduce(s = '', x IN cycle | s + CASE WHEN s = '' THEN '' ELSE ' -> ' END + x)"
            " IN $full_cycle_keys"
        )
        params["full_cycle_keys"] = full_cycle_keys

    filter_clause = ""
    if filters:
        filter_clause = "  AND " + "\n  AND ".join(filters) + "\n"

    cypher = (
        f"MATCH path = (a:File)-[:IMPORTS{hops}]->(a)\n"
        f"{where}"
        f"WITH [n IN nodes(path) | n.path] AS cycle, path\n"
        f"WHERE size(cycle) > 0\n"
        f"{filter_clause}"
        f"RETURN count(DISTINCT path) AS v"
    )
    with driver.session() as s:
        return int(s.run(cypher, **params).single()["v"] or 0)


# ── Suppression matching ────────────────────────────────────


def _violation_key(policy_name: str, row: dict) -> str:
    """Compute a canonical string key from a violation sample row.

    The key format is policy-specific so suppressions can target individual
    violations precisely.
    """
    if policy_name == "import_cycles":
        cycle = row.get("cycle", [])
        return " -> ".join(str(p) for p in cycle)
    if policy_name == "cross_package":
        return f"{row.get('importer', '')} -> {row.get('importee', '')}"
    if policy_name == "layer_bypass":
        return (
            f"{row.get('controller', '')} -> "
            f"{row.get('repository', '')}.{row.get('method', '')}"
        )
    if policy_name == "coupling_ceiling":
        return str(row.get("file", ""))
    if policy_name == "orphan_detection":
        return f"{row.get('kind', '')}:{row.get('name', '')}"
    # Fallback for custom policies: join all values.
    return " | ".join(str(v) for v in row.values())


def _match_suppression_key(
    policy_name: str, row: dict, suppression_key: str,
) -> bool:
    """Check whether *suppression_key* matches the violation in *row*.

    For ``import_cycles``, the suppression key is an edge (``"A -> B"``)
    and matches if that consecutive pair appears anywhere in the cycle.
    For all other policies, it's an exact match against :func:`_violation_key`.
    """
    if policy_name == "import_cycles":
        cycle = row.get("cycle", [])
        parts = [s.strip() for s in suppression_key.split(" -> ")]
        if len(parts) == 2:
            # Edge-based matching: check consecutive pairs in the cycle.
            for a, b in zip(cycle, cycle[1:]):
                if str(a) == parts[0] and str(b) == parts[1]:
                    return True
            return False
        # Full-cycle match fallback.
        return _violation_key(policy_name, row) == suppression_key
    return _violation_key(policy_name, row) == suppression_key


def _apply_suppressions(
    policies: list[PolicyResult],
    suppressions: list[Suppression],
    sample_limit: int = 10,
    *,
    driver: Driver | None = None,
    scope: list[str] | None = None,
    config: ArchConfig | None = None,
) -> tuple[list[PolicyResult], list[dict]]:
    """Match suppressions against policy results.

    When *driver* and *config* are provided the function queries Neo4j for
    the exact unsuppressed count (built-in policies only).  Without a
    driver it falls back to sample-based subtraction — the pre-#93
    behaviour.

    Returns ``(updated_policies, stale_suppressions)``.
    """
    if not suppressions:
        return policies, []

    # Group suppressions by policy name.
    by_policy: dict[str, list[Suppression]] = {}
    for s in suppressions:
        by_policy.setdefault(s.policy, []).append(s)

    # Map each suppression object to its index by identity, so duplicate
    # (policy, key, reason) entries are tracked independently.
    id_to_idx: dict[int, int] = {id(s): i for i, s in enumerate(suppressions)}
    used: set[int] = set()  # indices into *suppressions*
    updated: list[PolicyResult] = []

    for p in policies:
        policy_supps = by_policy.get(p.name)
        # Skip when there are no suppressions for this policy, or when the
        # policy produced no sample rows (nothing to match against).
        if not policy_supps or not p.sample:
            updated.append(p)
            continue

        kept: list[dict] = []
        suppressed: list[dict] = []
        for row in p.sample:
            matched = False
            for s in policy_supps:
                if _match_suppression_key(p.name, row, s.key):
                    used.add(id_to_idx[id(s)])
                    matched = True
                    break
            if matched:
                suppressed.append(row)
            else:
                kept.append(row)

        suppressed_count = len(suppressed)

        # Try exact Cypher count when a driver is available.
        exact_count: int | None = None
        if driver is not None and config is not None:
            exact_count = _count_unsuppressed(
                driver, p.name,
                [s.key for s in policy_supps],
                scope, config,
            )

        if exact_count is not None:
            # Authoritative count from Neo4j — no guessing.
            new_violation_count = exact_count
            incomplete = False
        else:
            # Fallback: sample-based subtraction (custom policies, or
            # no driver).
            new_violation_count = max(0, p.violation_count - suppressed_count)
            incomplete = (
                p.violation_count > len(p.sample)
                and suppressed_count > 0
            )

        updated.append(PolicyResult(
            name=p.name,
            passed=(new_violation_count == 0),
            violation_count=new_violation_count,
            sample=kept[:sample_limit],
            detail=p.detail,
            suppressed_count=suppressed_count,
            suppressed_sample=suppressed[:sample_limit],
            incomplete_suppression_coverage=incomplete,
        ))

    stale = [
        {"policy": s.policy, "key": s.key, "reason": s.reason}
        for i, s in enumerate(suppressions)
        if i not in used
    ]
    return updated, stale


# ── Rendering ────────────────────────────────────────────────

def _render(console: Console, report: ArchReport) -> None:
    """Pretty-print an :class:`ArchReport` using Rich (mirrors validate._render)."""
    console.rule("[bold cyan]Architecture conformance")
    t = Table(show_header=True, header_style="bold magenta")
    t.add_column("result", width=6)
    t.add_column("policy")
    t.add_column("violations", justify="right")
    t.add_column("suppressed", justify="right")
    t.add_column("detail", style="dim")
    for p in report.policies:
        if p.disabled:
            mark = "[yellow]SKIP"
        elif p.passed and p.suppressed_count > 0:
            mark = "[yellow]WARN"
        elif p.passed:
            mark = "[green]PASS"
        else:
            mark = "[red]FAIL"
        suppressed_str = str(p.suppressed_count) if p.suppressed_count else ""
        t.add_row(mark, p.name, str(p.violation_count), suppressed_str, p.detail)
    console.print(t)

    # Failing policies — unsuppressed violations.
    for p in report.policies:
        if p.passed or (not p.sample and p.violation_count == 0):
            continue
        if not p.sample:
            console.print(
                f"\n[bold red]{p.name}[/] — {p.violation_count} violation(s) "
                f"beyond the sample window (all sampled rows were suppressed)"
            )
            continue
        console.print(f"\n[bold red]{p.name}[/] — first {len(p.sample)} of {p.violation_count}")
        headers = list(p.sample[0].keys())
        tbl = Table(show_header=True, header_style="bold magenta")
        for h in headers:
            tbl.add_column(h)
        for row in p.sample:
            tbl.add_row(*[str(row.get(h, "")) for h in headers])
        console.print(tbl)

    # Suppressed violations — printed as warnings.
    for p in report.policies:
        if not p.suppressed_sample:
            continue
        console.print(
            f"\n[yellow]{p.name}[/] — {p.suppressed_count} suppressed"
        )
        headers = list(p.suppressed_sample[0].keys())
        tbl = Table(show_header=True, header_style="bold magenta")
        for h in headers:
            tbl.add_column(h)
        for row in p.suppressed_sample:
            tbl.add_row(*[str(row.get(h, "")) for h in headers])
        console.print(tbl)

    # Incomplete suppression coverage warnings.
    for p in report.policies:
        if p.incomplete_suppression_coverage:
            total_violations = p.violation_count + p.suppressed_count
            sampled = len(p.sample) + len(p.suppressed_sample)
            console.print(
                f"\n[yellow]\u26a0 {p.name}: {total_violations} violations found "
                f"but only {sampled} sampled \u2014 suppression coverage is "
                f"partial.\n  Increase settings.sample_limit in .arch-policies.toml or reduce violations to "
                f"verify full suppression.[/]"
            )

    # Stale suppressions.
    if report.stale_suppressions:
        console.print(
            f"\n[yellow]stale suppression(s): {len(report.stale_suppressions)}[/]"
        )
        for s in report.stale_suppressions:
            console.print(f"  [dim]{s['policy']}[/]: {s['key']}")

    total_suppressed = sum(p.suppressed_count for p in report.policies)
    active = [p for p in report.policies if not p.disabled]
    passed = sum(1 for p in active if p.passed)
    total = len(active)
    skipped = len(report.policies) - total
    style = "bold green" if passed == total else "bold red"
    summary = f"{passed}/{total} policies passed"
    if skipped:
        summary += f" ({skipped} skipped)"
    if total_suppressed:
        summary += f" ({total_suppressed} violation(s) suppressed)"
    console.print(f"\n[{style}]{summary}[/]")
