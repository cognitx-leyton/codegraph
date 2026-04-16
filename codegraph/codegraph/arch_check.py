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
    CrossPackageConfig,
    CustomPolicy,
    ImportCyclesConfig,
    LayerBypassConfig,
    load_arch_config,
)


# Sample-size cap per policy — keeps the report skimmable.
SAMPLE_LIMIT = 10


# ── Result shapes ────────────────────────────────────────────

@dataclass
class PolicyResult:
    """Outcome of a single architecture policy."""
    name: str
    passed: bool
    violation_count: int
    sample: list[dict] = field(default_factory=list)
    detail: str = ""


@dataclass
class ArchReport:
    """Aggregate result across all policies."""
    policies: list[PolicyResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(p.passed for p in self.policies)

    def to_json(self) -> str:
        return json.dumps(
            {
                "ok": self.ok,
                "policies": [asdict(p) for p in self.policies],
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
) -> ArchReport:
    """Open a driver, evaluate every configured policy, return an :class:`ArchReport`.

    ``config`` takes precedence if provided; otherwise :func:`load_arch_config`
    reads ``<repo_root>/.arch-policies.toml`` (``repo_root`` defaults to
    ``Path.cwd()``). Missing config file → all built-in defaults, no custom
    policies.
    """
    if config is None:
        config = load_arch_config(repo_root or Path.cwd())

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        policies = _run_all(driver, config)
    finally:
        driver.close()

    report = ArchReport(policies=policies)
    if console is not None:
        _render(console, report)
    return report


def _run_all(driver: Driver, config: ArchConfig) -> list[PolicyResult]:
    """Evaluate every policy in a stable order. Disabled policies emit a marker."""
    out: list[PolicyResult] = []

    if config.import_cycles.enabled:
        out.append(_check_import_cycles(driver, config.import_cycles))
    else:
        out.append(_disabled("import_cycles"))

    if config.cross_package.enabled:
        out.append(_check_cross_package(driver, config.cross_package))
    else:
        out.append(_disabled("cross_package"))

    if config.layer_bypass.enabled:
        out.append(_check_layer_bypass(driver, config.layer_bypass))
    else:
        out.append(_disabled("layer_bypass"))

    for custom in config.custom:
        if custom.enabled:
            out.append(_check_custom(driver, custom))
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
    )


# ── Policies ─────────────────────────────────────────────────

def _check_import_cycles(driver: Driver, cfg: ImportCyclesConfig) -> PolicyResult:
    """Detect file-level IMPORTS cycles of configurable length."""
    hops = f"*{cfg.min_hops}..{cfg.max_hops}"
    sample_cypher = (
        f"MATCH path = (a:File)-[:IMPORTS{hops}]->(a)\n"
        f"WITH [n IN nodes(path) | n.path] AS cycle, length(path) AS hops\n"
        f"RETURN DISTINCT cycle, hops\n"
        f"ORDER BY hops ASC, cycle[0]\n"
        f"LIMIT $limit"
    )
    count_cypher = (
        f"MATCH path = (a:File)-[:IMPORTS{hops}]->(a)\n"
        f"RETURN count(DISTINCT path) AS v"
    )
    with driver.session() as s:
        total = int(s.run(count_cypher).single()["v"] or 0)
        sample = [dict(r) for r in s.run(sample_cypher, limit=SAMPLE_LIMIT)]
    return PolicyResult(
        name="import_cycles",
        passed=(total == 0),
        violation_count=total,
        sample=sample,
        detail=f"Files (or packages) that import each other transitively (hops {cfg.min_hops}-{cfg.max_hops}).",
    )


def _check_cross_package(driver: Driver, cfg: CrossPackageConfig) -> PolicyResult:
    """Detect imports that cross a forbidden package boundary."""
    detected: list[dict] = []
    total = 0
    with driver.session() as s:
        for pair in cfg.pairs:
            count = int(s.run(
                "MATCH (a:File)-[:IMPORTS]->(b:File) "
                "WHERE a.package = $a AND b.package = $b "
                "RETURN count(*) AS v",
                a=pair.importer, b=pair.importee,
            ).single()["v"] or 0)
            total += count
            if count and len(detected) < SAMPLE_LIMIT:
                rows = list(s.run(
                    "MATCH (a:File)-[:IMPORTS]->(b:File) "
                    "WHERE a.package = $a AND b.package = $b "
                    "RETURN a.path AS importer, b.path AS importee "
                    "LIMIT $limit",
                    a=pair.importer, b=pair.importee,
                    limit=SAMPLE_LIMIT - len(detected),
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


def _check_layer_bypass(driver: Driver, cfg: LayerBypassConfig) -> PolicyResult:
    """Controllers reaching ``*Repository`` without traversing ``*Service``."""
    labels_or = "|".join(cfg.controller_labels)
    depth = f"*1..{cfg.call_depth}"
    sample_cypher = (
        f"MATCH (ctrl:{labels_or})-[:HAS_METHOD]->(m:Method)"
        f"-[:CALLS{depth}]->(target:Method)\n"
        f"MATCH (repo:Class)-[:HAS_METHOD]->(target)\n"
        f"WHERE repo.name ENDS WITH $repo_suffix\n"
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
        ).single()["v"] or 0)
        sample = [dict(r) for r in s.run(
            sample_cypher,
            repo_suffix=cfg.repository_suffix,
            svc_suffix=cfg.service_suffix,
            limit=SAMPLE_LIMIT,
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


def _check_custom(driver: Driver, custom: CustomPolicy) -> PolicyResult:
    """Run a user-authored policy from :class:`CustomPolicy`."""
    with driver.session() as s:
        count_result = s.run(custom.count_cypher).single()
        total = int((count_result["v"] if count_result else 0) or 0)
        sample: list[dict] = []
        if total > 0:
            sample = [dict(r) for r in s.run(custom.sample_cypher)][:SAMPLE_LIMIT]
    return PolicyResult(
        name=custom.name,
        passed=(total == 0),
        violation_count=total,
        sample=sample,
        detail=custom.description or "(user-defined policy)",
    )


# ── Rendering ────────────────────────────────────────────────

def _render(console: Console, report: ArchReport) -> None:
    """Pretty-print an :class:`ArchReport` using Rich (mirrors validate._render)."""
    console.rule("[bold cyan]Architecture conformance")
    t = Table(show_header=True, header_style="bold magenta")
    t.add_column("result", width=6)
    t.add_column("policy")
    t.add_column("violations", justify="right")
    t.add_column("detail", style="dim")
    for p in report.policies:
        if "(disabled" in p.detail:
            mark = "[yellow]SKIP"
        elif p.passed:
            mark = "[green]PASS"
        else:
            mark = "[red]FAIL"
        t.add_row(mark, p.name, str(p.violation_count), p.detail)
    console.print(t)

    for p in report.policies:
        if p.passed or not p.sample:
            continue
        console.print(f"\n[bold red]{p.name}[/] — first {len(p.sample)} of {p.violation_count}")
        headers = list(p.sample[0].keys())
        tbl = Table(show_header=True, header_style="bold magenta")
        for h in headers:
            tbl.add_column(h)
        for row in p.sample:
            tbl.add_row(*[str(row.get(h, "")) for h in headers])
        console.print(tbl)

    passed = sum(1 for p in report.policies if p.passed)
    total = len(report.policies)
    style = "bold green" if passed == total else "bold red"
    console.print(f"\n[{style}]{passed}/{total} policies passed[/]")
