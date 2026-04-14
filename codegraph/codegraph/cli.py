"""codegraph CLI: REPL (default), index, validate, query, wipe.

Every subcommand supports a ``--json`` flag that switches output to a
single machine-parseable JSON document on stdout (nothing to stderr on
success). This is the agent-native path — Claude Code and other coding
agents should invoke codegraph with ``--json``.

Running ``codegraph`` with no subcommand drops you into an interactive
REPL with persistent session state (see :mod:`codegraph.repl`).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

import typer
from neo4j import GraphDatabase
from rich.console import Console
from rich.table import Table

from .config import ConfigError, load_config, merge_cli_overrides, require_packages
from .loader import Neo4jLoader
from .ownership import collect_ownership
from .parser import TsParser
from .resolver import Index, Resolver, link_cross_file, load_package_config
from .schema import RouteNode

app = typer.Typer(
    help="codegraph — map a TS/TSX codebase into Neo4j and query it.",
    invoke_without_command=True,
    no_args_is_help=False,
)
console = Console()


DEFAULT_URI = os.environ.get("CODEGRAPH_NEO4J_URI", "bolt://localhost:7688")
DEFAULT_USER = os.environ.get("CODEGRAPH_NEO4J_USER", "neo4j")
DEFAULT_PASS = os.environ.get("CODEGRAPH_NEO4J_PASS", "codegraph123")

TEST_SUFFIXES = (".spec.ts", ".spec.tsx", ".test.ts", ".test.tsx")


# ── top-level callback: enter REPL when no subcommand ───────────────

@app.callback()
def _main(ctx: typer.Context) -> None:
    """Drop into the REPL when ``codegraph`` is invoked without a subcommand."""
    if ctx.invoked_subcommand is None:
        from .repl import run_repl
        raise typer.Exit(code=run_repl())


# ── repl (explicit) ──────────────────────────────────────────────────

@app.command()
def repl(
    repo: Optional[Path] = typer.Option(None, "--repo", help="Pre-set the current repo."),
    uri: Optional[str] = typer.Option(None, "--uri", help="Pre-set the Neo4j URI."),
    user: Optional[str] = typer.Option(None, "--user", help="Pre-set the Neo4j user."),
) -> None:
    """Start the interactive REPL (same as running ``codegraph`` with no args)."""
    from .repl import run_repl
    raise typer.Exit(code=run_repl(repo=repo, uri=uri, user=user))


# ── index ────────────────────────────────────────────────────────────

@app.command()
def index(
    repo: Path = typer.Argument(..., exists=True, file_okay=False),
    packages: Optional[list[str]] = typer.Option(
        None,
        "--package", "-p",
        help="Repo-relative path of a TypeScript package to index (e.g. "
             "'packages/server'). Overrides codegraph.toml / pyproject.toml. "
             "Repeatable.",
    ),
    wipe: bool = typer.Option(True, help="Wipe Neo4j database before load"),
    uri: str = DEFAULT_URI,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASS,
    max_files: Optional[int] = typer.Option(None, help="Limit files (debug)"),
    skip_ownership: bool = typer.Option(False, help="Skip git log ingestion"),
    as_json: bool = typer.Option(False, "--json", help="Emit stats as JSON on stdout."),
) -> None:
    """Index a TypeScript monorepo into Neo4j."""
    try:
        stats = _run_index(
            repo=repo.resolve(),
            packages=packages,
            wipe=wipe,
            uri=uri,
            user=user,
            password=password,
            max_files=max_files,
            skip_ownership=skip_ownership,
            quiet=as_json,
        )
    except ConfigError as e:
        _emit_error(as_json, "config", str(e))
        raise typer.Exit(code=2)

    if as_json:
        print(json.dumps({"ok": True, "stats": stats}, indent=2))
    else:
        _print_load_stats_dict(stats)


def _run_index(
    *,
    repo: Path,
    packages: Optional[list[str]],
    wipe: bool,
    uri: str,
    user: str,
    password: str,
    max_files: Optional[int] = None,
    skip_ownership: bool = False,
    quiet: bool = False,
) -> dict[str, Any]:
    """Core indexing routine. Returns a flat dict of stats (files, edges, ...).

    Used by both the ``index`` command and the REPL's ``index`` handler.
    Pass ``quiet=True`` to suppress Rich output (used by ``--json`` mode).
    """
    def say(msg: str) -> None:
        if not quiet:
            console.print(msg)

    config = load_config(repo)
    config = merge_cli_overrides(config, packages=packages)
    require_packages(config)

    source_note = f" (from {config.source})" if config.source and not packages else ""
    say(f"[bold]Indexing[/] {repo}  packages={config.packages}{source_note}")

    parser = TsParser()
    index_obj = Index()
    exclude_dirs = config.effective_exclude_dirs()
    exclude_suffixes = config.effective_exclude_suffixes()

    pkg_configs = []
    for pkg_path in config.packages:
        pkg_dir = (repo / pkg_path).resolve()
        if not pkg_dir.exists() or not pkg_dir.is_dir():
            say(f"[yellow]skip[/] package {pkg_path} (not found at {pkg_dir})")
            continue
        pkg_configs.append(load_package_config(repo, pkg_dir))
        say(f"  [green]•[/] {pkg_path}: aliases={list(pkg_configs[-1].aliases.keys())}")
    if not pkg_configs:
        raise ConfigError(
            "No valid packages found — every configured package was missing on "
            "disk. Check your codegraph.toml or --package flags."
        )

    to_parse: list[tuple[Path, str, str, bool]] = []
    for pkg in pkg_configs:
        for p in pkg.root.rglob("*"):
            if not p.is_file():
                continue
            if any(part in exclude_dirs for part in p.parts):
                continue
            if p.suffix.lower() not in (".ts", ".tsx"):
                continue
            name_lower = p.name.lower()
            if any(name_lower.endswith(suf) for suf in exclude_suffixes):
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
    say(f"[bold]Parsing[/] {len(to_parse)} files…")

    t0 = time.time()
    progress_step = max(1, len(to_parse) // 20)
    for i, (abs_p, rel, pkg_name, is_test) in enumerate(to_parse):
        result = parser.parse_file(abs_p, rel, pkg_name, is_test=is_test)
        if result is None:
            continue
        index_obj.add(result)
        if (i + 1) % progress_step == 0:
            say(f"  parsed {i+1}/{len(to_parse)}  [{time.time()-t0:.1f}s]")
    parse_time = time.time() - t0
    say(f"[bold green]✓[/] parsed {len(index_obj.files_by_path)} files in {parse_time:.1f}s")

    _extract_routes(repo, index_obj)

    say("[bold]Resolving imports + references…")
    resolver = Resolver(repo, pkg_configs)
    t0 = time.time()
    all_edges = link_cross_file(index_obj, resolver)
    stats_edge = next((e for e in all_edges if e.kind == "__STATS__"), None)
    total_imports = unresolved_imports = 0
    if stats_edge:
        total_imports = stats_edge.props.get("total_imports", 0)
        unresolved_imports = stats_edge.props.get("unresolved_imports", 0)
        pct = 100.0 * (total_imports - unresolved_imports) / total_imports if total_imports else 0.0
        say(
            f"  imports: total={total_imports} resolved={total_imports-unresolved_imports} "
            f"unresolved={unresolved_imports} ({pct:.1f}% resolved)  [{time.time()-t0:.1f}s]"
        )

    for r in index_obj.files_by_path.values():
        all_edges.extend(r.edges)

    ownership = None
    if not skip_ownership:
        say("[bold]Collecting git ownership…")
        t0 = time.time()
        ownership = collect_ownership(repo, set(index_obj.files_by_path.keys()))
        if ownership:
            say(
                f"  authors={len(ownership['authors'])} "
                f"last_mod={len(ownership['last_modified'])} "
                f"teams={len(ownership['teams'])}  [{time.time()-t0:.1f}s]"
            )

    say(f"[bold]Connecting to Neo4j…[/] {uri}")
    loader = Neo4jLoader(uri, user, password)
    try:
        loader.init_schema()
        if wipe:
            say("[yellow]Wiping database…")
            loader.wipe()
            loader.init_schema()
        t0 = time.time()
        ls = loader.load(
            index_obj,
            [e for e in all_edges if e.kind != "__STATS__"],
            ownership=ownership,
        )
        say(f"[bold green]✓[/] loaded in {time.time()-t0:.1f}s")
    finally:
        loader.close()

    return _flatten_load_stats(ls, total_imports=total_imports, unresolved_imports=unresolved_imports)


def _flatten_load_stats(stats, *, total_imports: int, unresolved_imports: int) -> dict[str, Any]:
    out: dict[str, Any] = {
        "total_imports": total_imports,
        "unresolved_imports": unresolved_imports,
    }
    for k in (
        "files", "classes", "functions", "methods", "interfaces", "endpoints",
        "gql_operations", "columns", "atoms", "externals",
    ):
        out[k] = int(getattr(stats, k, 0))
    edges = getattr(stats, "edges", {}) or {}
    out["edges"] = {k: int(v) for k, v in edges.items()}
    return out


def _print_load_stats_dict(stats: dict[str, Any]) -> None:
    t = Table(title="Load stats", show_header=True, header_style="bold magenta")
    t.add_column("entity"); t.add_column("count", justify="right")
    for k in (
        "files", "classes", "functions", "methods", "interfaces", "endpoints",
        "gql_operations", "columns", "atoms", "externals",
    ):
        t.add_row(k, str(stats.get(k, 0)))
    for k, v in sorted(stats.get("edges", {}).items()):
        t.add_row(f"edge:{k}", str(v))
    console.print(t)


_ROUTE_RE = re.compile(
    r"<\s*Route\b[^>]*\bpath\s*=\s*[\"']([^\"']+)[\"'][^>]*\belement\s*=\s*\{\s*<\s*([A-Z]\w*)",
    re.MULTILINE,
)


def _extract_routes(repo: Path, index_obj: Index) -> None:
    """Best-effort ``<Route path="…" element={<X/>}/>`` detection."""
    for rel, result in index_obj.files_by_path.items():
        if not rel.endswith(".tsx"):
            continue
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


# ── validate ─────────────────────────────────────────────────────────

@app.command()
def validate(
    repo: Path = typer.Argument(..., exists=True, file_okay=False),
    uri: str = DEFAULT_URI,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASS,
    as_json: bool = typer.Option(False, "--json", help="Emit report as JSON on stdout."),
) -> None:
    """Run the validation suite against an already-loaded graph."""
    from .validate import run_validation

    report = run_validation(
        uri, user, password, repo.resolve(),
        console=None if as_json else console,
    )
    if as_json:
        print(json.dumps({"ok": report.ok, "report": _serialize_report(report)}, indent=2))
    raise typer.Exit(code=0 if report.ok else 1)


def _serialize_report(report) -> dict[str, Any]:
    """Best-effort serialisation of a ValidationReport — tolerant of shape drift."""
    out: dict[str, Any] = {"ok": bool(getattr(report, "ok", False))}
    for attr in ("coverage", "assertions", "smoke", "errors", "warnings"):
        val = getattr(report, attr, None)
        if val is not None:
            try:
                json.dumps(val)
                out[attr] = val
            except TypeError:
                out[attr] = str(val)
    return out


# ── query ────────────────────────────────────────────────────────────

@app.command()
def query(
    cypher: str = typer.Argument(...),
    uri: str = DEFAULT_URI,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASS,
    limit: int = typer.Option(20, "--limit", "-n"),
    as_json: bool = typer.Option(False, "--json", help="Emit rows as JSON on stdout."),
) -> None:
    """Run a Cypher query against the current graph."""
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as s:
            rows = list(s.run(cypher))[:limit]
    finally:
        driver.close()

    if as_json:
        serialised = [dict(r) for r in rows]
        # neo4j Node/Relationship aren't directly JSON-serialisable, flatten them
        clean = [_clean_row(r) for r in serialised]
        print(json.dumps({"ok": True, "rows": clean, "count": len(clean)}, indent=2, default=str))
        return

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


def _clean_row(row: dict) -> dict:
    """Best-effort JSON-clean of neo4j row values (nodes, relationships, paths)."""
    out = {}
    for k, v in row.items():
        try:
            json.dumps(v)
            out[k] = v
        except TypeError:
            if hasattr(v, "_properties"):
                out[k] = dict(v._properties)  # neo4j Node
            else:
                out[k] = str(v)
    return out


# ── wipe ─────────────────────────────────────────────────────────────

@app.command()
def wipe(
    uri: str = DEFAULT_URI,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASS,
    as_json: bool = typer.Option(False, "--json", help="Emit confirmation as JSON on stdout."),
) -> None:
    """Drop every node and relationship in the target Neo4j database."""
    loader = Neo4jLoader(uri, user, password)
    try:
        loader.wipe()
    finally:
        loader.close()
    if as_json:
        print(json.dumps({"ok": True, "action": "wipe", "uri": uri}, indent=2))
    else:
        console.print("[green]✓[/] wiped")


# ── error emission helper ────────────────────────────────────────────

def _emit_error(as_json: bool, kind: str, message: str) -> None:
    if as_json:
        print(json.dumps({"ok": False, "error": kind, "message": message}, indent=2), file=sys.stdout)
    else:
        console.print(f"[bold red]{kind} error[/]\n{message}")


if __name__ == "__main__":
    app()
