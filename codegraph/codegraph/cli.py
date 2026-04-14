"""codegraph CLI: index, query, validate."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Optional

import typer
from neo4j import GraphDatabase
from rich.console import Console
from rich.table import Table

from .loader import Neo4jLoader
from .ownership import collect_ownership
from .parser import TsParser
from .resolver import Index, Resolver, link_cross_file, load_package_config
from .schema import RouteNode

app = typer.Typer(help="codegraph — map a TS/TSX codebase into Neo4j")
console = Console()


DEFAULT_URI = os.environ.get("CODEGRAPH_NEO4J_URI", "bolt://localhost:7688")
DEFAULT_USER = os.environ.get("CODEGRAPH_NEO4J_USER", "neo4j")
DEFAULT_PASS = os.environ.get("CODEGRAPH_NEO4J_PASS", "codegraph123")

DEFAULT_EXCLUDE_DIRS = {
    "node_modules", "dist", "build", ".next", ".turbo", "coverage",
    ".git", "generated", "__generated__", ".cache",
}
DEFAULT_EXCLUDE_SUFFIXES = (
    ".stories.tsx", ".d.ts",
)
TEST_SUFFIXES = (".spec.ts", ".spec.tsx", ".test.ts", ".test.tsx")


# ── index ────────────────────────────────────────────────────

@app.command()
def index(
    repo: Path = typer.Argument(..., exists=True, file_okay=False),
    packages: list[str] = typer.Option(
        ["twenty-server", "twenty-front"],
        "--package", "-p",
    ),
    wipe: bool = typer.Option(True, help="Wipe Neo4j database before load"),
    uri: str = DEFAULT_URI,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASS,
    max_files: Optional[int] = typer.Option(None, help="Limit files (debug)"),
    skip_ownership: bool = typer.Option(False, help="Skip git log ingestion"),
) -> None:
    repo = repo.resolve()
    console.print(f"[bold]Indexing[/] {repo}  packages={packages}")

    parser = TsParser()
    index_obj = Index()

    pkg_configs = []
    for pkg_name in packages:
        pkg_dir = repo / "packages" / pkg_name
        if not pkg_dir.exists():
            console.print(f"[yellow]skip[/] package {pkg_name} (not found)")
            continue
        pkg_configs.append(load_package_config(repo, pkg_dir))
        console.print(
            f"  [green]•[/] {pkg_name}: aliases={list(pkg_configs[-1].aliases.keys())}"
        )

    # Walk files (now keeping tests)
    to_parse: list[tuple[Path, str, str, bool]] = []
    for pkg in pkg_configs:
        for p in pkg.root.rglob("*"):
            if not p.is_file():
                continue
            if any(part in DEFAULT_EXCLUDE_DIRS for part in p.parts):
                continue
            if p.suffix.lower() not in (".ts", ".tsx"):
                continue
            name_lower = p.name.lower()
            if any(name_lower.endswith(suf) for suf in DEFAULT_EXCLUDE_SUFFIXES):
                continue
            try:
                if p.stat().st_size > 1_500_000:
                    continue
            except OSError:
                continue
            is_test = any(name_lower.endswith(suf) for suf in TEST_SUFFIXES)
            rel = str(p.resolve().relative_to(repo)).replace("\\", "/")
            to_parse.append((p, rel, pkg.name, is_test))
    if max_files is not None:
        to_parse = to_parse[:max_files]
    console.print(f"[bold]Parsing[/] {len(to_parse)} files…")

    t0 = time.time()
    progress_step = max(1, len(to_parse) // 20)
    for i, (abs_p, rel, pkg_name, is_test) in enumerate(to_parse):
        result = parser.parse_file(abs_p, rel, pkg_name, is_test=is_test)
        if result is None:
            continue
        index_obj.add(result)
        if (i + 1) % progress_step == 0:
            console.print(f"  parsed {i+1}/{len(to_parse)}  [{time.time()-t0:.1f}s]")
    console.print(f"[bold green]✓[/] parsed {len(index_obj.files_by_path)} files in {time.time()-t0:.1f}s")

    # Phase 8.3: route detection (regex over absolute files)
    _extract_routes(repo, index_obj)

    console.print("[bold]Resolving imports + references…")
    resolver = Resolver(repo, pkg_configs)
    t0 = time.time()
    all_edges = link_cross_file(index_obj, resolver)
    stats_edge = next((e for e in all_edges if e.kind == "__STATS__"), None)
    if stats_edge:
        ti = stats_edge.props.get("total_imports", 0)
        ui = stats_edge.props.get("unresolved_imports", 0)
        pct = 100.0 * (ti - ui) / ti if ti else 0.0
        console.print(
            f"  imports: total={ti} resolved={ti-ui} unresolved={ui} "
            f"({pct:.1f}% resolved)  [{time.time()-t0:.1f}s]"
        )

    # Per-file edges (DECORATED_BY etc.)
    for r in index_obj.files_by_path.values():
        all_edges.extend(r.edges)

    # Phase 7: ownership
    ownership = None
    if not skip_ownership:
        console.print("[bold]Collecting git ownership…")
        t0 = time.time()
        ownership = collect_ownership(repo, set(index_obj.files_by_path.keys()))
        if ownership:
            console.print(
                f"  authors={len(ownership['authors'])} "
                f"last_mod={len(ownership['last_modified'])} "
                f"teams={len(ownership['teams'])}  [{time.time()-t0:.1f}s]"
            )

    console.print("[bold]Connecting to Neo4j…", uri)
    loader = Neo4jLoader(uri, user, password)
    try:
        loader.init_schema()
        if wipe:
            console.print("[yellow]Wiping database…")
            loader.wipe()
            loader.init_schema()
        t0 = time.time()
        ls = loader.load(index_obj, [e for e in all_edges if e.kind != "__STATS__"], ownership=ownership)
        console.print(f"[bold green]✓[/] loaded in {time.time()-t0:.1f}s")
        _print_load_stats(ls)
    finally:
        loader.close()


_ROUTE_RE = re.compile(
    r"<\s*Route\b[^>]*\bpath\s*=\s*[\"']([^\"']+)[\"'][^>]*\belement\s*=\s*\{\s*<\s*([A-Z]\w*)",
    re.MULTILINE,
)


def _extract_routes(repo: Path, index_obj: Index) -> None:
    """Phase 8.3: best-effort React Router <Route path="..." element={<X/>}/> detection."""
    for rel, result in index_obj.files_by_path.items():
        if not rel.endswith(".tsx"):
            continue
        # Cheap gate: only files mentioning Route or router are likely
        name_l = rel.lower()
        if "route" not in name_l and "router" not in name_l and "app.tsx" not in name_l:
            continue
        try:
            text = (repo / rel).read_text(errors="replace")
        except OSError:
            continue
        if "<Route" not in text:
            continue
        for m in _ROUTE_RE.finditer(text):
            path, comp = m.group(1), m.group(2)
            result.routes.append(RouteNode(path=path, component_name=comp, file=rel))


# ── validate ─────────────────────────────────────────────────

@app.command()
def validate(
    repo: Path = typer.Argument(..., exists=True, file_okay=False),
    uri: str = DEFAULT_URI,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASS,
) -> None:
    from .validate import run_validation
    report = run_validation(uri, user, password, repo.resolve(), console)
    raise typer.Exit(code=0 if report.ok else 1)


# ── query ────────────────────────────────────────────────────

@app.command()
def query(
    cypher: str = typer.Argument(...),
    uri: str = DEFAULT_URI,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASS,
    limit: int = typer.Option(20),
) -> None:
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as s:
            rows = list(s.run(cypher))[:limit]
    finally:
        driver.close()

    if not rows:
        console.print("[dim](no rows)[/]")
        return
    headers = list(rows[0].keys())
    t = Table(show_header=True, header_style="bold magenta")
    for h in headers:
        t.add_column(h)
    for r in rows:
        t.add_row(*[str(r.get(h, "")) for h in headers])
    console.print(t)


# ── wipe ─────────────────────────────────────────────────────

@app.command()
def wipe(
    uri: str = DEFAULT_URI,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASS,
) -> None:
    loader = Neo4jLoader(uri, user, password)
    try:
        loader.wipe()
        console.print("[green]✓[/] wiped")
    finally:
        loader.close()


def _print_load_stats(stats) -> None:
    t = Table(title="Load stats", show_header=True, header_style="bold magenta")
    t.add_column("entity"); t.add_column("count", justify="right")
    for k in ("files", "classes", "functions", "methods", "interfaces", "endpoints",
              "gql_operations", "columns", "atoms", "externals"):
        t.add_row(k, str(getattr(stats, k, 0)))
    for k, v in sorted(stats.edges.items()):
        t.add_row(f"edge:{k}", str(v))
    console.print(t)


if __name__ == "__main__":
    app()
