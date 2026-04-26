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
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

import typer
from neo4j import GraphDatabase
from neo4j.exceptions import AuthError, ServiceUnavailable
from rich.console import Console
from rich.table import Table

from .config import ConfigError, load_config, merge_cli_overrides, require_packages
from .framework import FrameworkDetector
from .ignore import IgnoreConfigError, IgnoreFilter
from .loader import LoadStats, Neo4jLoader
from .ownership import collect_ownership
from .parser import TsParser
from .resolver import (
    Index,
    Resolver,
    link_cross_file,
    load_package_config,
    load_python_package_config,
)
from .schema import (
    PackageNode,
    PY_TEST_PREFIX,
    PY_TEST_SUFFIX_TRAILING,
    RouteNode,
    TS_TEST_SUFFIXES,
)
from .utils.neo4j_json import clean_row

app = typer.Typer(
    help="codegraph — map a TS/TSX codebase into Neo4j and query it.",
    invoke_without_command=True,
    no_args_is_help=False,
)
hook_app = typer.Typer(help="Manage codegraph git hooks (post-commit, post-checkout).")
app.add_typer(hook_app, name="hook")
install_app = typer.Typer(help="Install codegraph as always-on context for an AI platform.")
app.add_typer(install_app, name="install")
uninstall_app = typer.Typer(help="Remove codegraph integration from an AI platform.")
app.add_typer(uninstall_app, name="uninstall")
console = Console()


DEFAULT_URI = os.environ.get("CODEGRAPH_NEO4J_URI", "bolt://localhost:7688")
DEFAULT_USER = os.environ.get("CODEGRAPH_NEO4J_USER", "neo4j")
DEFAULT_PASS = os.environ.get("CODEGRAPH_NEO4J_PASS", "codegraph123")

# Extensions recognised by the parsers; used to filter git diff output so that
# documentation, config, and other non-code files don't appear in the
# incremental index set.
_CODE_EXTENSIONS: frozenset[str] = frozenset({".py", ".ts", ".tsx"})


def _is_python_test_file(name_lower: str) -> bool:
    """Return True for conventional pytest file names (``test_*.py`` / ``*_test.py``)."""
    return name_lower.startswith(PY_TEST_PREFIX) or name_lower.endswith(PY_TEST_SUFFIX_TRAILING)


def _git_changed_files(repo: Path, since: str) -> tuple[set[str], set[str]]:
    """Return ``(modified_or_added, deleted)`` file paths changed since *since*.

    Runs ``git diff --name-status <since>`` and parses the output. Returns
    repo-relative paths matching the ``rel`` format used by the Index. Raises
    :class:`ConfigError` on git failure or invalid ref.
    """
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-status", since],
            cwd=str(repo), capture_output=True, text=True, check=False, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ConfigError(f"git diff failed: {exc}") from exc
    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise ConfigError(f"git diff --name-status {since} failed: {stderr}")

    modified: set[str] = set()
    deleted: set[str] = set()
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        if status == "D":
            deleted.add(parts[1])
        elif status.startswith("R"):
            # Rename: old path deleted, new path added
            if len(parts) >= 3:
                deleted.add(parts[1])
                modified.add(parts[2])
        else:
            # A, M, C, T, etc.
            modified.add(parts[1])
    _keep = lambda paths: {p for p in paths if Path(p).suffix.lower() in _CODE_EXTENSIONS}
    return _keep(modified), _keep(deleted)


# ── top-level callback: enter REPL when no subcommand ───────────────

@app.callback()
def _main(ctx: typer.Context) -> None:
    """Drop into the REPL when ``codegraph`` is invoked without a subcommand."""
    if ctx.invoked_subcommand is None:
        from .repl import run_repl
        raise typer.Exit(code=run_repl())


# ── init ─────────────────────────────────────────────────────────────

@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing files (never CLAUDE.md)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Non-interactive; accept all defaults."),
    skip_docker: bool = typer.Option(False, "--skip-docker", help="Write compose file but don't start Neo4j."),
    skip_index: bool = typer.Option(False, "--skip-index", help="Don't run the initial index."),
    bolt_port: Optional[int] = typer.Option(None, "--bolt-port", help="Neo4j Bolt port (default: 7688)."),
    http_port: Optional[int] = typer.Option(None, "--http-port", help="Neo4j HTTP port (default: 7475)."),
) -> None:
    """Scaffold codegraph into the current repo — commands, CI gate, config, Neo4j, first index."""
    from .init import run_init
    raise typer.Exit(code=run_init(
        force=force, non_interactive=yes,
        skip_docker=skip_docker, skip_index=skip_index,
        console=console,
        bolt_port=bolt_port, http_port=http_port,
    ))


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
    ignore_file: Optional[str] = typer.Option(
        None,
        "--ignore-file",
        help="Path to a .codegraphignore file (gitignore-style, plus @route: "
             "and @component: extensions). Overrides codegraph.toml. If unset, "
             "codegraph auto-detects <repo>/.codegraphignore.",
    ),
    since: Optional[str] = typer.Option(
        None, "--since",
        help="Git ref (commit, tag, HEAD~N). Only re-index files changed since "
             "this ref. Implies --no-wipe.",
    ),
    update: bool = typer.Option(
        False, "--update",
        help="Incremental mode: skip unchanged files via SHA256 content cache. "
             "Implies --no-wipe.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit stats as JSON on stdout."),
    no_export: bool = typer.Option(False, "--no-export",
                                   help="Skip HTML/JSON export after indexing."),
    no_benchmark: bool = typer.Option(False, "--no-benchmark",
                                      help="Skip token-reduction benchmark after indexing."),
    no_analyze: bool = typer.Option(False, "--no-analyze",
                                    help="Skip Leiden community detection + GRAPH_REPORT after indexing."),
    repo_name: Optional[str] = typer.Option(
        None, "--repo-name",
        help="Namespace for multi-repo indexing. Defaults to the repo "
             "directory name. Prevents File-node collisions when indexing "
             "multiple repos into one Neo4j with --no-wipe.",
    ),
    extract_docs: bool = typer.Option(
        False, "--extract-docs",
        help="Extract PDF documents as :Document/:DocumentSection nodes.",
    ),
    extract_markdown: bool = typer.Option(
        False, "--extract-markdown",
        help="Extract semantic concepts/decisions from markdown via Claude API. "
             "Requires the [semantic] extra and ANTHROPIC_API_KEY env var.",
    ),
    extract_images: bool = typer.Option(
        False, "--extract-images",
        help="Extract image content (diagrams, screenshots) via Claude vision API. "
             "Requires the [semantic] extra and ANTHROPIC_API_KEY env var.",
    ),
    extract_audio: bool = typer.Option(
        False, "--extract-audio",
        help="Transcribe audio/video files via Whisper. "
             "Requires the [transcribe] extra.",
    ),
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
            ignore_file=ignore_file,
            quiet=as_json,
            since=since,
            update=update,
            repo_name=repo_name,
            extract_docs=extract_docs,
            extract_markdown=extract_markdown,
            extract_images=extract_images,
            extract_audio=extract_audio,
        )
    except ConfigError as e:
        _emit_error(as_json, "config", str(e))
        raise typer.Exit(code=2)
    except IgnoreConfigError as e:
        _emit_error(as_json, "ignore", str(e))
        raise typer.Exit(code=2)
    except (ServiceUnavailable, AuthError) as e:
        _emit_error(as_json, "connection", str(e))
        raise typer.Exit(code=2)

    if as_json:
        print(json.dumps({"ok": True, "stats": stats}, indent=2))
    else:
        _print_load_stats_dict(stats)

    # Auto-export HTML + JSON unless suppressed
    if not no_export:
        try:
            from .export import dump_graph as _dump_graph, to_html, to_json
            out_dir = repo.resolve() / "codegraph-out"
            driver = GraphDatabase.driver(uri, auth=(user, password))
            try:
                driver.verify_connectivity()
                nodes, edges = _dump_graph(driver, scope=packages)
            finally:
                driver.close()
            out_dir.mkdir(parents=True, exist_ok=True)
            to_html(nodes, edges, out_dir / "graph.html")
            to_json(nodes, edges, out_dir / "graph.json")
            if not as_json:
                console.print(
                    f"[green]✓[/] exported graph.html + graph.json → {out_dir}"
                )
        except Exception as exc:  # noqa: BLE001
            if not as_json:
                console.print(f"[yellow]warning:[/] export failed: {exc}")

    # Auto-benchmark unless suppressed
    if not no_benchmark:
        try:
            from .benchmark import run_benchmark as _run_bench, print_benchmark_summary, write_benchmark_json
            bench_cfg = load_config(repo.resolve())
            bench_cfg = merge_cli_overrides(bench_cfg, packages=packages)
            bench_result = _run_bench(
                uri=uri, user=user, password=password,
                repo=repo.resolve(),
                packages=list(bench_cfg.packages),
            )
            bench_out = repo.resolve() / "codegraph-out"
            write_benchmark_json(bench_result, bench_out)
            if not as_json:
                print_benchmark_summary(bench_result, console)
        except Exception as exc:  # noqa: BLE001
            if not as_json:
                console.print(f"[yellow]warning:[/] benchmark failed: {exc}")

    # Auto-analyze unless suppressed
    if not no_analyze:
        try:
            from .analyze import run_analysis
            from .report import generate_report, write_report
            an_cfg = load_config(repo.resolve())
            an_cfg = merge_cli_overrides(an_cfg, packages=packages)
            an_scope = list(an_cfg.packages) or None
            an_driver = GraphDatabase.driver(uri, auth=(user, password))
            try:
                an_driver.verify_connectivity()
                analysis = run_analysis(
                    an_driver, scope=an_scope,
                    console=None if as_json else console,
                )
            finally:
                an_driver.close()
            report_text = generate_report(analysis)
            out_dir = repo.resolve() / "codegraph-out"
            write_report(report_text, out_dir / "GRAPH_REPORT.md")
            if not as_json:
                console.print(
                    f"[green]✓[/] GRAPH_REPORT.md → {out_dir} "
                    f"({analysis['community_count']} communities)"
                )
        except Exception as exc:  # noqa: BLE001
            if not as_json:
                console.print(f"[yellow]warning:[/] analyze failed: {exc}")


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
    ignore_file: Optional[str] = None,
    quiet: bool = False,
    since: Optional[str] = None,
    update: bool = False,
    repo_name: Optional[str] = None,
    extract_docs: bool = False,
    extract_markdown: bool = False,
    extract_images: bool = False,
    extract_audio: bool = False,
) -> dict[str, Any]:
    """Core indexing routine. Returns a flat dict of stats (files, edges, ...).

    Used by both the ``index`` command and the REPL's ``index`` handler.
    Pass ``quiet=True`` to suppress Rich output (used by ``--json`` mode).
    When *since* is set, only files changed since that git ref are loaded
    (incremental mode — implies ``wipe=False``).
    When *update* is set, uses SHA256 content hashing to skip unchanged
    files (implies ``wipe=False``).
    """
    def say(msg: str) -> None:
        if not quiet:
            console.print(msg)

    # ── Repo name derivation ───────────────────────────────────
    effective_repo_name = repo_name or repo.resolve().name
    if ":" in effective_repo_name or "#" in effective_repo_name:
        raise ConfigError("--repo-name must not contain ':' or '#' (they break node ID parsing)")
    say(f"[bold]Repo name[/] {effective_repo_name}")

    # --extract-markdown implies --extract-docs (we need the structural
    # markdown docs parsed before the semantic pass can run over them).
    if extract_markdown:
        extract_docs = True
    if extract_images:
        extract_docs = True
    if extract_audio:
        extract_docs = True

    # ── Incremental mode setup ──────────────────────────────────
    if since is not None and update:
        raise ConfigError("--since and --update are mutually exclusive")

    changed_files: set[str] | None = None
    deleted_files: set[str] = set()
    if since is not None:
        wipe = False
        skip_ownership = True
        say(f"[bold]Incremental mode[/] (--since {since})")
        changed_files, deleted_files = _git_changed_files(repo, since)
        if not changed_files and not deleted_files:
            say(f"[green]No changes since {since}[/]")
            return _flatten_load_stats(
                LoadStats(), total_imports=0, unresolved_imports=0,
            )
        say(f"  changed: {len(changed_files)} files, deleted: {len(deleted_files)} files")

    # ── --update (SHA256 cache) setup ──────────────────────────
    ast_cache = None
    cached_manifest: dict[str, str] = {}
    if update:
        from .cache import AstCache, file_content_hash
        wipe = False
        skip_ownership = True
        ast_cache = AstCache(repo)
        cached_manifest = ast_cache.load_manifest()
        say("[bold]Incremental mode[/] (--update, SHA256 cache)")

    config = load_config(repo)
    config = merge_cli_overrides(config, packages=packages, ignore_file=ignore_file)
    require_packages(config)

    source_note = f" (from {config.source})" if config.source and not packages else ""
    say(f"[bold]Indexing[/] {repo}  packages={config.packages}{source_note}")

    ignore_filter = _load_ignore_filter(repo, config.ignore_file)
    if ignore_filter is not None:
        nf, nr, nc = ignore_filter.counts()
        say(
            f"[bold]Ignore rules[/] loaded from {ignore_filter.ignore_path.name} "
            f"({nf} file / {nr} route / {nc} component)"
        )

    ts_parser = TsParser()
    py_parser = None  # Lazy — only constructed if a Python package is configured.
    index_obj = Index()
    exclude_dirs = config.effective_exclude_dirs()
    exclude_suffixes = config.effective_exclude_suffixes()

    pkg_configs = []
    for pkg_path in config.packages:
        pkg_dir = (repo / pkg_path).resolve()
        if not pkg_dir.exists() or not pkg_dir.is_dir():
            say(f"[yellow]skip[/] package {pkg_path} (not found at {pkg_dir})")
            continue

        # Auto-detect language: Python if any of these exist at the package
        # root — legacy (__init__.py), modern (pyproject.toml), or older
        # (setup.py / setup.cfg). Otherwise fall through to the TS loader.
        py_markers = ("__init__.py", "pyproject.toml", "setup.py", "setup.cfg")
        if any((pkg_dir / marker).exists() for marker in py_markers):
            pkg_config = load_python_package_config(repo, pkg_dir)
        else:
            pkg_config = load_package_config(repo, pkg_dir)
        pkg_configs.append(pkg_config)

        lang_label = pkg_config.language
        name_note = f" name={pkg_config.pkg_json_name}" if pkg_config.pkg_json_name else ""
        say(f"  [green]•[/] {pkg_path} ({lang_label}):{name_note} aliases={list(pkg_config.aliases.keys())}")

        if pkg_config.language == "ts":
            info = FrameworkDetector(pkg_dir).detect()
            pkg_node = PackageNode.from_framework_info(pkg_config.name, info)
            pkg_node.repo = effective_repo_name
            index_obj.packages.append(pkg_node)
            version_str = f" v{info.version}" if info.version else ""
            say(
                f"    [cyan]framework[/] {pkg_node.framework}{version_str} "
                f"(conf {info.confidence:.0%}, ts={info.typescript}, "
                f"pm={info.package_manager or '?'})"
            )
        else:
            # Python: Stage 1 skips framework detection. Emit a placeholder
            # :Package node so the BELONGS_TO edges still wire up in the graph.
            pkg_node = PackageNode(
                name=pkg_config.name, framework="Unknown", confidence=0.0,
                repo=effective_repo_name,
            )
            index_obj.packages.append(pkg_node)
            say(f"    [cyan]framework[/] Unknown (python; detection in Stage 2)")
    if not pkg_configs:
        raise ConfigError(
            "No valid packages found — every configured package was missing on "
            "disk. Check your codegraph.toml or --package flags."
        )

    to_parse: list[tuple[Path, str, str, bool]] = []
    for pkg in pkg_configs:
        # Restrict accepted extensions to the package's language. A TS
        # package walking a .py script (or vice versa) would be a misconfig;
        # we skip silently rather than try to parse it with the wrong frontend.
        allowed_suffixes = (".py",) if pkg.language == "py" else (".ts", ".tsx")
        for p in pkg.root.rglob("*"):
            if not p.is_file():
                continue
            if any(part in exclude_dirs for part in p.parts):
                continue
            if p.suffix.lower() not in allowed_suffixes:
                continue
            name_lower = p.name.lower()
            if any(name_lower.endswith(suf) for suf in exclude_suffixes):
                continue
            try:
                if p.stat().st_size > 1_500_000:
                    continue
            except OSError:
                continue
            if pkg.language == "py":
                is_test = _is_python_test_file(name_lower)
            else:
                is_test = any(name_lower.endswith(suf) for suf in TS_TEST_SUFFIXES)
            rel = str(p.resolve().relative_to(repo)).replace("\\", "/")
            if ignore_filter is not None and ignore_filter.should_ignore_file(rel):
                continue
            to_parse.append((p, rel, pkg.name, is_test))
    if max_files is not None:
        to_parse = to_parse[:max_files]
    say(f"[bold]Parsing[/] {len(to_parse)} files…")

    t0 = time.time()
    progress_step = max(1, len(to_parse) // 20)
    new_manifest: dict[str, str] = {}
    cache_hits = 0
    for i, (abs_p, rel, pkg_name, is_test) in enumerate(to_parse):
        # Cache check
        if ast_cache is not None:
            content_hash = file_content_hash(abs_p, repo)
            new_manifest[rel] = content_hash
            cached = ast_cache.get(rel, content_hash)
            if cached is not None:
                index_obj.add(cached)
                cache_hits += 1
                continue
        # Parse (cache miss or no cache)
        if abs_p.suffix.lower() == ".py":
            if py_parser is None:
                from .py_parser import PyParser
                py_parser = PyParser()
            result = py_parser.parse_file(abs_p, rel, pkg_name, is_test=is_test,
                                              repo_name=effective_repo_name)
        else:
            result = ts_parser.parse_file(abs_p, rel, pkg_name, is_test=is_test,
                                           repo_name=effective_repo_name)
        if result is None:
            continue
        index_obj.add(result)
        if ast_cache is not None:
            ast_cache.put(rel, content_hash, result)
        if (i + 1) % progress_step == 0:
            say(f"  parsed {i+1}/{len(to_parse)}  [{time.time()-t0:.1f}s]")

    # --update: compute changed/deleted sets from manifest diff + save
    if ast_cache is not None:
        changed_files = {
            rel for rel in new_manifest
            if rel not in cached_manifest or cached_manifest[rel] != new_manifest[rel]
        }
        # Only detect deletions when the full file list was walked (max_files
        # truncates to_parse, so absent files aren't truly deleted).
        if max_files is None:
            deleted_files = {p for p in cached_manifest if p not in new_manifest}
        ast_cache.save_manifest(new_manifest)
        pruned = 0
        if max_files is None:
            pruned = ast_cache.prune_stale(cached_manifest, new_manifest)
        say(f"  cache: {cache_hits} hits, {len(changed_files)} misses, {len(deleted_files)} deleted, {pruned} pruned")

    parse_time = time.time() - t0
    say(f"[bold green]✓[/] parsed {len(index_obj.files_by_path)} files in {parse_time:.1f}s")

    _extract_routes(repo, index_obj, ignore_filter, repo_name=effective_repo_name)

    if ignore_filter is not None:
        dropped = _strip_ignored_components(index_obj, ignore_filter)
        if dropped:
            say(f"[bold]Ignore rules[/] stripped :Component label from {dropped} function(s)")

    say("[bold]Resolving imports + references…")
    resolver = Resolver(repo, pkg_configs)
    t0 = time.time()
    all_edges, edge_groups = link_cross_file(index_obj, resolver)
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
        if ownership is not None:
            say(
                f"  authors={len(ownership['authors'])} "
                f"last_mod={len(ownership['last_modified'])} "
                f"teams={len(ownership['teams'])}  [{time.time()-t0:.1f}s]"
            )

    # ── Document extraction (opt-in) ──────────────────────────
    doc_nodes: list = []
    doc_section_nodes: list = []
    if extract_docs:
        from .doc_parser import extract_markdown as _extract_md, extract_pdf
        say("[bold]Extracting documents…")
        pdf_count = 0
        for pkg in pkg_configs:
            for p in pkg.root.rglob("*.pdf"):
                if not p.is_file():
                    continue
                if any(part in exclude_dirs for part in p.parts):
                    continue
                rel = str(p.resolve().relative_to(repo)).replace("\\", "/")
                if ignore_filter is not None and ignore_filter.should_ignore_file(rel):
                    continue
                try:
                    doc, sections = extract_pdf(p, rel, repo_name=effective_repo_name)
                    doc_nodes.append(doc)
                    doc_section_nodes.extend(sections)
                    pdf_count += 1
                except Exception as exc:
                    say(f"  [yellow]skip[/] {rel}: {exc}")
        md_count = 0
        for pkg in pkg_configs:
            for p in pkg.root.rglob("*.md"):
                if not p.is_file():
                    continue
                if any(part in exclude_dirs for part in p.parts):
                    continue
                rel = str(p.resolve().relative_to(repo)).replace("\\", "/")
                if ignore_filter is not None and ignore_filter.should_ignore_file(rel):
                    continue
                try:
                    doc, sections = _extract_md(p, rel, repo_name=effective_repo_name)
                    doc_nodes.append(doc)
                    doc_section_nodes.extend(sections)
                    md_count += 1
                except Exception as exc:
                    say(f"  [yellow]skip[/] {rel}: {exc}")
        img_count = 0
        if extract_images:
            from .schema import DocumentNode
            from .vision_extract import IMAGE_EXTENSIONS, _MAX_IMAGE_SIZE
            from datetime import datetime, timezone
            for pkg in pkg_configs:
                for ext in IMAGE_EXTENSIONS:
                    for p in pkg.root.rglob(f"*{ext}"):
                        if not p.is_file():
                            continue
                        if any(part in exclude_dirs for part in p.parts):
                            continue
                        rel = str(p.resolve().relative_to(repo)).replace("\\", "/")
                        if ignore_filter is not None and ignore_filter.should_ignore_file(rel):
                            continue
                        fsize = p.stat().st_size
                        if fsize > _MAX_IMAGE_SIZE:
                            say(f"  [yellow]skip[/] {rel}: exceeds 20 MB size limit")
                            continue
                        doc_nodes.append(DocumentNode(
                            path=rel,
                            file_type="image",
                            loc=fsize,
                            extracted_at=datetime.now(timezone.utc).isoformat(),
                            repo=effective_repo_name,
                        ))
                        img_count += 1
        img_msg = f" + {img_count} image(s)" if img_count else ""
        say(
            f"[bold green]✓[/] extracted {pdf_count} PDF(s) + {md_count} markdown file(s)"
            f"{img_msg}, {len(doc_section_nodes)} section(s)"
        )

    # ── Semantic extraction (opt-in) ─────────────────────────
    concept_nodes: list = []
    decision_nodes: list = []
    rationale_nodes: list = []
    semantic_edge_list: list = []
    if extract_markdown:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise ConfigError(
                "--extract-markdown requires ANTHROPIC_API_KEY in the environment. "
                "Set it or add it to .env."
            )
        from .semantic_extract import SemanticCache, extract_semantic
        say("[bold]Running semantic extraction…")
        sem_cache = SemanticCache(repo)
        md_docs = [d for d in doc_nodes if d.file_type == "markdown"]
        sem_hits = sem_misses = 0
        for md_doc in md_docs:
            md_path = repo / md_doc.path
            if not md_path.is_file():
                continue
            try:
                content = md_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            cache_key = SemanticCache.cache_key(content, md_doc.path, effective_repo_name)
            cached = sem_cache.get(cache_key)
            if cached is not None:
                result = cached
                sem_hits += 1
            else:
                try:
                    result = extract_semantic(content, md_doc.path, repo_name=effective_repo_name)
                except Exception as exc:
                    say(f"  [yellow]skip[/] {md_doc.path}: {exc}")
                    continue
                sem_cache.put(cache_key, result)
                sem_misses += 1
            concept_nodes.extend(result.concepts)
            decision_nodes.extend(result.decisions)
            rationale_nodes.extend(result.rationales)
            semantic_edge_list.extend(result.edges)
        say(
            f"[bold green]✓[/] semantic: {len(concept_nodes)} concepts, "
            f"{len(decision_nodes)} decisions, {len(rationale_nodes)} rationales "
            f"(cache: {sem_hits} hit, {sem_misses} miss)"
        )

    # ── Vision extraction (opt-in) ─────────────────────────────
    if extract_images:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise ConfigError(
                "--extract-images requires ANTHROPIC_API_KEY in the environment. "
                "Set it or add it to .env."
            )
        from .schema import ILLUSTRATES_CONCEPT
        from .semantic_extract import SemanticCache
        from .vision_extract import extract_vision, _file_content_hash, _vision_cache_key
        say("[bold]Running vision extraction…")
        vis_cache = SemanticCache(repo)
        img_docs = [d for d in doc_nodes if d.file_type == "image"]
        vis_hits = vis_misses = 0
        for img_doc in img_docs:
            img_path = repo / img_doc.path
            if not img_path.is_file():
                continue
            try:
                fhash = _file_content_hash(img_path)
            except OSError:
                continue
            cache_key = _vision_cache_key(fhash, img_doc.path, effective_repo_name)
            cached = vis_cache.get(cache_key)
            if cached is not None:
                result = cached
                vis_hits += 1
            else:
                try:
                    result = extract_vision(img_path, img_doc.path, repo_name=effective_repo_name)
                except Exception as exc:
                    say(f"  [yellow]skip[/] {img_doc.path}: {exc}")
                    continue
                vis_cache.put(cache_key, result)
                vis_misses += 1
            concept_nodes.extend(result.concepts)
            semantic_edge_list.extend(result.edges)
        say(
            f"[bold green]✓[/] vision: {len([d for d in doc_nodes if d.file_type == 'image'])} image(s), "
            f"{sum(1 for e in semantic_edge_list if e.kind == ILLUSTRATES_CONCEPT)} concept edges "
            f"(cache: {vis_hits} hit, {vis_misses} miss)"
        )

    # ── Audio/video transcription (opt-in) ─────────────────────
    if extract_audio:
        from .schema import DocumentNode as _DocNode
        from .transcribe import (
            transcribe as _transcribe,
            load_model as _load_model,
            MEDIA_EXTENSIONS,
            _MAX_MEDIA_SIZE,
            _file_content_hash as _audio_hash,
            _get_cached_transcript,
            _put_cached_transcript,
        )
        from datetime import datetime as _dt, timezone as _tz
        say("[bold]Transcribing audio/video…")
        try:
            whisper_model = _load_model()
        except ImportError as exc:
            raise ConfigError(str(exc))
        audio_count = 0
        audio_cache_hits = audio_cache_misses = 0
        for pkg in pkg_configs:
            for ext in MEDIA_EXTENSIONS:
                for p in pkg.root.rglob(f"*{ext}"):
                    if not p.is_file():
                        continue
                    if any(part in exclude_dirs for part in p.parts):
                        continue
                    rel = str(p.resolve().relative_to(repo)).replace("\\", "/")
                    if ignore_filter is not None and ignore_filter.should_ignore_file(rel):
                        continue
                    fsize = p.stat().st_size
                    if fsize > _MAX_MEDIA_SIZE:
                        say(f"  [yellow]skip[/] {rel}: exceeds 500 MB size limit")
                        continue
                    # Cache check
                    try:
                        fhash = _audio_hash(p)
                    except OSError:
                        continue
                    cached_text = _get_cached_transcript(repo, fhash)
                    if cached_text is not None:
                        text = cached_text
                        audio_cache_hits += 1
                        doc = _DocNode(
                            path=rel,
                            file_type="transcript",
                            loc=len(text),
                            extracted_at=_dt.now(_tz.utc).isoformat(),
                            repo=effective_repo_name,
                        )
                    else:
                        try:
                            doc, text = _transcribe(
                                p, rel, repo_name=effective_repo_name,
                                model=whisper_model,
                            )
                        except Exception as exc:
                            say(f"  [yellow]skip[/] {rel}: {exc}")
                            continue
                        _put_cached_transcript(repo, fhash, text)
                        audio_cache_misses += 1
                    doc_nodes.append(doc)
                    audio_count += 1
        say(
            f"[bold green]✓[/] transcribed {audio_count} media file(s) "
            f"(cache: {audio_cache_hits} hit, {audio_cache_misses} miss)"
        )

    say(f"[bold]Connecting to Neo4j…[/] {uri}")
    loader = Neo4jLoader(uri, user, password)
    try:
        loader.init_schema()
        if wipe:
            # Scope wipe to configured packages so re-indexing repo A doesn't
            # nuke repo B in a shared codegraph-neo4j. Standalone `codegraph
            # wipe` keeps the global wipe (explicit user intent).
            scoped_packages = [p.name for p in pkg_configs]
            if scoped_packages:
                say(f"[yellow]Wiping {len(scoped_packages)} package(s) from database…[/]")
                deleted = loader.wipe_scoped(scoped_packages, repo=effective_repo_name)
                say(f"  cleared {deleted} file subgraph(s)")
            else:
                # No packages resolved — fall back to the global wipe so the
                # user still gets a clean DB. Should be unreachable in practice
                # since require_packages() runs earlier.
                say("[yellow]Wiping database…[/]")
                loader.wipe()
            loader.init_schema()
        # Incremental: clean up stale subgraphs for changed + deleted files.
        if changed_files is not None:
            cleanup_paths = list((changed_files | deleted_files))
            if cleanup_paths:
                t0 = time.time()
                cleanup_ids = [f"file:{effective_repo_name}:{p}" for p in cleanup_paths]
                loader.delete_file_subgraph(cleanup_ids)
                say(f"[yellow]Cleaned subgraph for {len(cleanup_paths)} files[/]  [{time.time()-t0:.1f}s]")
        t0 = time.time()
        ls = loader.load(
            index_obj,
            [e for e in all_edges if e.kind != "__STATS__"],
            ownership=ownership,
            touched_files=changed_files,
            edge_groups=edge_groups,
            repo_name=effective_repo_name,
            documents=doc_nodes or None,
            document_sections=doc_section_nodes or None,
            concepts=concept_nodes or None,
            decisions=decision_nodes or None,
            rationales=rationale_nodes or None,
            semantic_edges=semantic_edge_list or None,
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
        "documents", "document_sections",
        "concepts", "decisions", "rationales",
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
        "documents", "document_sections",
        "concepts", "decisions", "rationales",
    ):
        t.add_row(k, str(stats.get(k, 0)))
    for k, v in sorted(stats.get("edges", {}).items()):
        t.add_row(f"edge:{k}", str(v))
    console.print(t)


# ── stats helpers ───────────────────────────────────────────────────

_STAT_NODE_LABELS = (
    "files", "classes", "functions", "methods", "interfaces",
    "endpoints", "hooks", "decorators",
)

_LABEL_MAP = {
    "files": "File", "classes": "Class", "functions": "Function",
    "methods": "Method", "interfaces": "Interface", "endpoints": "Endpoint",
    "hooks": "Hook", "decorators": "Decorator",
}


def _query_graph_stats(
    driver,
    scope: list[str] | None,
    *,
    cross_scope_edges: bool = False,
) -> dict[str, Any]:
    """Query Neo4j for node and edge counts, optionally filtered by scope prefixes.

    File nodes use ``.path`` while other nodes use ``.file``, so queries
    use ``coalesce(n.file, n.path)`` to handle both uniformly.

    When *scope* is set, edge counts default to AND logic (both endpoints
    must be in scope).  Pass ``cross_scope_edges=True`` to use OR logic
    (either endpoint in scope) — the pre-0.1.37 behaviour.
    """
    with driver.session() as s:
        if scope:
            node_cypher = (
                "MATCH (n) "
                "WITH n, coalesce(n.file, n.path) AS loc "
                "WHERE loc IS NOT NULL "
                "AND any(s IN $scopes WHERE loc STARTS WITH s) "
                "UNWIND labels(n) AS label "
                "WITH label WHERE label IN $known_labels "
                "RETURN label, count(*) AS count"
            )
            conjunction = "OR" if cross_scope_edges else "AND"
            edge_cypher = (
                "MATCH (a)-[r]->(b) "
                "WITH a, r, b, "
                "coalesce(a.file, a.path) AS aloc, "
                "coalesce(b.file, b.path) AS bloc "
                "WHERE (aloc IS NOT NULL AND any(s IN $scopes WHERE aloc STARTS WITH s)) "
                f"{conjunction} (bloc IS NOT NULL AND any(s IN $scopes WHERE bloc STARTS WITH s)) "
                "RETURN type(r) AS rel, count(*) AS count"
            )
            params = {"scopes": scope, "known_labels": list(_LABEL_MAP.values())}
        else:
            node_cypher = (
                "MATCH (n) "
                "WHERE n.file IS NOT NULL OR n.path IS NOT NULL "
                "UNWIND labels(n) AS label "
                "WITH label WHERE label IN $known_labels "
                "RETURN label, count(*) AS count"
            )
            edge_cypher = (
                "MATCH ()-[r]->() "
                "RETURN type(r) AS rel, count(*) AS count"
            )
            params = {"known_labels": list(_LABEL_MAP.values())}

        node_rows = list(s.run(node_cypher, **params))
        edge_rows = list(s.run(edge_cypher, **params))

    label_counts: dict[str, int] = {}
    for row in node_rows:
        label_counts[row["label"]] = int(row["count"])

    out: dict[str, Any] = {}
    for k in _STAT_NODE_LABELS:
        out[k] = label_counts.get(_LABEL_MAP[k], 0)

    edges: dict[str, int] = {}
    for row in edge_rows:
        edges[row["rel"]] = int(row["count"])
    out["edges"] = edges

    return out


def _format_stat_line(stats: dict[str, Any]) -> str:
    """Build a human-readable stat summary from a stats dict.

    Produces output like ``"~21 files, 56 classes, 134 module functions, ~178 methods"``.
    Zero-count entries are omitted. Files and methods get a ``~`` prefix (convention).
    """
    parts: list[str] = []
    spec: list[tuple[str, str, bool]] = [
        ("files", "files", True),
        ("classes", "classes", False),
        ("functions", "module functions", False),
        ("methods", "methods", True),
        ("interfaces", "interfaces", False),
        ("endpoints", "endpoints", False),
        ("hooks", "hooks", False),
        ("decorators", "decorators", False),
    ]
    for key, label, approx in spec:
        val = stats.get(key, 0)
        if val:
            prefix = "~" if approx else ""
            parts.append(f"{prefix}{val} {label}")
    return ", ".join(parts) if parts else "(empty graph)"


_STAT_PLACEHOLDER_RE = re.compile(
    r"(<!-- codegraph:stats-begin -->\r?\n).*?(\r?\n<!-- codegraph:stats-end -->)",
    re.DOTALL,
)


def _update_stat_placeholders(
    files: list[Path], stat_line: str, *, quiet: bool = False,
) -> int:
    """Replace content between stat placeholder delimiters in *files*.

    Returns the number of files that were actually modified.
    """
    updated = 0
    for path in files:
        if not path.exists():
            if not quiet:
                console.print(f"  [yellow]skip[/] {path} (not found)")
            continue
        with open(path, encoding="utf-8", newline="") as fh:
            content = fh.read()
        new_content = _STAT_PLACEHOLDER_RE.sub(
            lambda m: f"{m.group(1)}{stat_line}{m.group(2)}", content,
        )
        if new_content == content:
            if not quiet:
                console.print(f"  [dim]skip[/] {path} (no change)")
            continue
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(new_content)
        updated += 1
        if not quiet:
            console.print(f"  [green]updated[/] {path}")
    return updated


_ROUTE_RE = re.compile(
    r"<\s*Route\b[^>]*\bpath\s*=\s*[\"']([^\"']+)[\"'][^>]*\belement\s*=\s*\{\s*<\s*([A-Z]\w*)",
    re.MULTILINE,
)


def _extract_routes(
    repo: Path,
    index_obj: Index,
    ignore_filter: Optional[IgnoreFilter] = None,
    repo_name: str = "default",
) -> None:
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
            if ignore_filter is not None and ignore_filter.should_ignore_route(path):
                continue
            result.routes.append(RouteNode(path=path, component_name=comp, file=rel, repo=repo_name))


def _strip_ignored_components(index_obj: Index, ignore_filter: IgnoreFilter) -> int:
    """Flip ``is_component`` off for components whose name matches an ignore rule.

    Flipping the flag rather than deleting the :class:`FunctionNode` is
    deliberate: the function may still be legitimately imported or called
    elsewhere. :mod:`codegraph.loader` only applies the ``:Component`` label
    when ``is_component=True``, so this is all that's needed to keep the
    component out of the queryable graph.
    """
    dropped = 0
    for result in index_obj.files_by_path.values():
        for fn in result.functions:
            if fn.is_component and ignore_filter.should_ignore_component(fn.name):
                fn.is_component = False
                dropped += 1
    return dropped


def _load_ignore_filter(repo: Path, configured: Optional[str]) -> Optional[IgnoreFilter]:
    """Resolve and load a :class:`IgnoreFilter`.

    Resolution order:

    1. If ``configured`` is set (from ``--ignore-file`` or ``codegraph.toml``),
       use it as-is (absolute or repo-relative). Missing file is a hard error.
    2. Otherwise, auto-detect ``<repo>/.codegraphignore``. Missing file → no
       filter, no error.
    """
    if configured:
        candidate = Path(configured)
        if not candidate.is_absolute():
            candidate = repo / candidate
        return IgnoreFilter(candidate)
    default = repo / ".codegraphignore"
    if default.exists():
        return IgnoreFilter(default)
    return None


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

    try:
        report = run_validation(
            uri, user, password, repo.resolve(),
            console=None if as_json else console,
        )
    except (ServiceUnavailable, AuthError) as e:
        _emit_error(as_json, "connection", str(e))
        raise typer.Exit(code=2)
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


# ── arch-check ───────────────────────────────────────────────────────

@app.command(name="arch-check")
def arch_check(
    uri: str = DEFAULT_URI,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASS,
    as_json: bool = typer.Option(False, "--json", help="Emit report as JSON on stdout."),
    config: Optional[Path] = typer.Option(
        None, "--config",
        help="Path to .arch-policies.toml (defaults to ./ at the repo root).",
        exists=True, file_okay=True, dir_okay=False,
    ),
    repo: Path = typer.Option(
        Path("."), "--repo",
        help="Repo root used for locating .arch-policies.toml.",
        exists=True, file_okay=False,
    ),
    scope: Optional[list[str]] = typer.Option(
        None, "--scope",
        help="Restrict policies to nodes whose file path starts with this "
             "prefix. Repeatable. Mirrors --package/-p from 'codegraph index'.",
    ),
    no_scope: bool = typer.Option(
        False, "--no-scope",
        help="Disable auto-scope even when packages are configured. "
             "Checks the entire graph.",
    ),
) -> None:
    """Run architecture-conformance policies against the live graph.

    Exits 0 when every policy passes, 1 when any policy reports a violation.
    Suitable as a CI gate — see ``.github/workflows/arch-check.yml`` for the
    reference integration.

    When neither ``--scope`` nor ``--no-scope`` is given, auto-scopes to the
    packages listed in ``codegraph.toml`` or ``pyproject.toml
    [tool.codegraph]``.
    """
    from .arch_check import run_arch_check
    from .arch_config import ArchConfigError, load_arch_config

    try:
        arch_cfg = load_arch_config(repo.resolve(), path=config)
    except ArchConfigError as exc:
        console.print(f"[bold red]arch-check config error:[/] {exc}")
        raise typer.Exit(code=2)

    # Auto-scope: derive from configured packages when no explicit flag given.
    effective_scope = scope
    if scope is None and not no_scope:
        cfg = load_config(repo.resolve())
        if cfg.packages:
            effective_scope = list(cfg.packages)
            if not as_json:
                console.print(
                    f"[dim]auto-scope from {cfg.source}:[/] "
                    + ", ".join(effective_scope)
                )

    try:
        report = run_arch_check(
            uri, user, password,
            console=None if as_json else console,
            config=arch_cfg,
            scope=effective_scope,
        )
    except (ServiceUnavailable, AuthError) as e:
        _emit_error(as_json, "connection", str(e))
        raise typer.Exit(code=2)
    if as_json:
        print(report.to_json())
    raise typer.Exit(code=0 if report.ok else 1)


# ── audit ────────────────────────────────────────────────────────────

@app.command()
def audit(
    repo: Path = typer.Option(
        Path("."), "--repo",
        help="Repo root to audit (default: current directory).",
        exists=True, file_okay=False,
    ),
    uri: str = DEFAULT_URI,
    agent: Optional[str] = typer.Option(
        None, "--agent",
        help="Coding agent to launch (claude/codex/gemini/aider/opencode/droid/cursor). "
             "If omitted, prompts interactively.",
    ),
    list_agents: bool = typer.Option(
        False, "--list-agents",
        help="Print supported agents and detection status, then exit.",
    ),
    print_prompt_only: bool = typer.Option(
        False, "--print-prompt-only",
        help="Render the audit prompt to stdout without launching any agent.",
    ),
    gh_issue: Optional[bool] = typer.Option(
        None, "--gh-issue/--no-gh-issue",
        help="After the audit, open a GitHub issue from the report. "
             "If unset, prompts interactively when findings exist.",
    ),
    bypass: bool = typer.Option(
        True, "--bypass/--no-bypass",
        help="Pass the agent's permission-bypass flag (default: on, since "
             "the audit is unattended). --no-bypass runs the agent in "
             "interactive mode where each tool call prompts.",
    ),
    unsafe: bool = typer.Option(
        False, "--unsafe",
        help="For agents that distinguish 'sandboxed bypass' from 'no sandbox' "
             "(currently codex), pass the no-sandbox flag.",
    ),
    timeout_sec: int = typer.Option(
        1800, "--timeout",
        help="Agent timeout in seconds (default: 1800 = 30 minutes).",
    ),
    recompute_lock: bool = typer.Option(
        False, "--recompute-lock",
        help="Regenerate the audit prompt lock file before launching. Use "
             "after intentionally editing a template; otherwise the launch "
             "will refuse on lock mismatch.",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="Non-interactive mode. Auto-pick the only detected agent and "
             "skip the GitHub-issue confirmation prompt.",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Emit final report as JSON on stdout.",
    ),
) -> None:
    """Run an agent-driven extraction self-check against the live graph.

    Pipeline: (1) verify the prompt-template lock file is intact, (2) detect
    or pick a coding agent, (3) build a prompt scoped to the frameworks
    present in this repo, (4) launch the agent in headless + permission-
    bypass mode, (5) parse the agent's report at
    ``codegraph-out/audit-report.md``, (6) optionally open a GitHub issue.

    The audit reads the graph and source files; it never writes either.
    """
    from .audit import run_audit
    from .audit_agents import AUDIT_AGENTS

    if list_agents:
        if as_json:
            print(json.dumps({
                "ok": True,
                "agents": [
                    {
                        "name": a.name,
                        "display_name": a.display_name,
                        "binary": a.binary,
                        "installed": a.is_installed(),
                        "headless": a.fallback_skill_path is None,
                    }
                    for a in AUDIT_AGENTS.values()
                ],
            }, indent=2))
        else:
            t = Table(title="codegraph audit — supported agents",
                      show_header=True, header_style="bold magenta")
            t.add_column("name"); t.add_column("display"); t.add_column("binary")
            t.add_column("installed", justify="center")
            t.add_column("headless", justify="center")
            for a in AUDIT_AGENTS.values():
                t.add_row(
                    a.name, a.display_name, a.binary,
                    "[green]✓[/]" if a.is_installed() else "[red]✗[/]",
                    "[green]✓[/]" if a.fallback_skill_path is None else "[yellow]fallback[/]",
                )
            console.print(t)
        raise typer.Exit(code=0)

    try:
        report = run_audit(
            repo=repo.resolve(),
            uri=uri,
            agent_name=agent,
            bypass=bypass,
            unsafe=unsafe,
            gh_issue=gh_issue,
            print_prompt_only=print_prompt_only,
            yes=yes,
            timeout_sec=timeout_sec,
            recompute_lock=recompute_lock,
            console=None if as_json else console,
        )
    except SystemExit:
        raise

    if as_json:
        print(report.to_json())
        raise typer.Exit(code=0 if report.ok else 1)

    if not print_prompt_only:
        console.print()
        if report.issues_found == 0:
            console.print("[bold green]✓[/] No extraction issues found.")
        else:
            console.print(
                f"[bold yellow]Found {report.issues_found} potential extraction issue(s).[/]"
            )
            console.print(f"  Report: [cyan]{report.report_path}[/]")
            if report.gh_issue_url:
                console.print(f"  GitHub issue: [cyan]{report.gh_issue_url}[/]")
        for w in report.warnings:
            console.print(f"  [yellow]⚠[/] {w}")
    raise typer.Exit(code=0 if report.ok else 1)


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
        driver.verify_connectivity()
        with driver.session() as s:
            rows = list(s.run(cypher))[:limit]
    except (ServiceUnavailable, AuthError) as e:
        _emit_error(as_json, "connection", str(e))
        raise typer.Exit(code=2)
    finally:
        driver.close()

    if as_json:
        serialised = [dict(r) for r in rows]
        # neo4j Node/Relationship aren't directly JSON-serialisable, flatten them
        clean = [clean_row(r) for r in serialised]
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
    except (ServiceUnavailable, AuthError) as e:
        _emit_error(as_json, "connection", str(e))
        raise typer.Exit(code=2)
    finally:
        loader.close()
    if as_json:
        print(json.dumps({"ok": True, "action": "wipe", "uri": uri}, indent=2))
    else:
        console.print("[green]✓[/] wiped")


# ── stats ───────────────────────────────────────────────────────────

@app.command()
def stats(
    uri: str = DEFAULT_URI,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASS,
    as_json: bool = typer.Option(False, "--json", help="Emit stats as JSON on stdout."),
    scope: Optional[list[str]] = typer.Option(
        None, "--scope", "-s",
        help="Restrict counts to nodes/edges whose file path starts with "
             "this prefix. Repeatable. Edge counts include only edges "
             "where both endpoints match a scope prefix.",
    ),
    no_scope: bool = typer.Option(
        False, "--no-scope",
        help="Disable auto-scope even when packages are configured. "
             "Counts the entire graph.",
    ),
    include_cross_scope_edges: bool = typer.Option(
        False, "--include-cross-scope-edges",
        help="Include edges that cross scope boundaries (one endpoint "
             "inside scope, one outside). Default counts only edges "
             "where both endpoints are in scope.",
    ),
    update: bool = typer.Option(
        False, "--update",
        help="Update stat placeholders in markdown files in-place.",
    ),
    files: Optional[list[Path]] = typer.Option(
        None, "--file", "-f",
        help="Markdown file to update (repeatable). Defaults to "
             "CLAUDE.md + .claude/commands/graph.md.",
    ),
    repo: Path = typer.Option(
        Path("."), "--repo",
        help="Repo root for locating config and markdown files.",
        exists=True, file_okay=False,
    ),
) -> None:
    """Query the live graph for node/edge counts.

    Optionally patch markdown files that contain
    ``<!-- codegraph:stats-begin -->`` / ``<!-- codegraph:stats-end -->``
    placeholder delimiters with fresh numbers (``--update``).
    """
    # Auto-scope from config when no explicit flag given.
    effective_scope = scope
    if scope is None and not no_scope:
        cfg = load_config(repo.resolve())
        if cfg.packages:
            effective_scope = list(cfg.packages)
            if not as_json:
                console.print(
                    f"[dim]auto-scope from {cfg.source}:[/] "
                    + ", ".join(effective_scope)
                )

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
        result = _query_graph_stats(
            driver, effective_scope,
            cross_scope_edges=include_cross_scope_edges,
        )
    except (ServiceUnavailable, AuthError) as e:
        _emit_error(as_json, "connection", str(e))
        raise typer.Exit(code=2)
    finally:
        driver.close()

    output: dict[str, Any] = {"ok": True, "stats": result}

    if update:
        stat_line = _format_stat_line(result)
        repo_root = repo.resolve()
        if files:
            targets = list(files)
        else:
            targets = [
                repo_root / "CLAUDE.md",
                repo_root / ".claude" / "commands" / "graph.md",
            ]
        n = _update_stat_placeholders(targets, stat_line, quiet=as_json)
        output["files_updated"] = n
        if not as_json:
            console.print(f"[bold green]✓[/] updated {n} file(s)")

    if as_json:
        print(json.dumps(output, indent=2))
    else:
        t = Table(title="Graph stats", show_header=True, header_style="bold magenta")
        t.add_column("entity"); t.add_column("count", justify="right")
        for k in _STAT_NODE_LABELS:
            t.add_row(k, str(result.get(k, 0)))
        for k, v in sorted(result.get("edges", {}).items()):
            t.add_row(f"edge:{k}", str(v))
        console.print(t)


# ── export ──────────────────────────────────────────────────────────

@app.command()
def export(
    uri: str = DEFAULT_URI,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASS,
    output_dir: Path = typer.Option(Path("codegraph-out"), "--out", "-o",
                                    help="Directory for exported files."),
    do_html: bool = typer.Option(True, "--html/--no-html",
                                 help="Produce interactive graph.html."),
    do_json: bool = typer.Option(True, "--json-export/--no-json-export",
                                 help="Produce graph.json."),
    graphml: bool = typer.Option(False, "--graphml",
                                 help="Produce graph.graphml."),
    cypher: bool = typer.Option(False, "--cypher",
                                help="Produce graph.cypher."),
    scope: Optional[list[str]] = typer.Option(None, "--scope", "-s",
                                              help="Restrict to paths starting with prefix (repeatable)."),
    no_scope: bool = typer.Option(False, "--no-scope",
                                  help="Disable auto-scope even when packages are configured."),
    max_nodes: int = typer.Option(5000, "--max-nodes",
                                  help="Max nodes for HTML visualisation."),
    as_json: bool = typer.Option(False, "--json",
                                 help="Emit status as JSON on stdout."),
    repo: Path = typer.Option(Path("."), "--repo",
                              help="Repo root for config lookup.",
                              exists=True, file_okay=False),
) -> None:
    """Export the graph as interactive HTML, JSON, GraphML, or Cypher."""
    from .export import (
        dump_graph as _dump_graph,
        to_html as _to_html,
        to_json as _to_json,
        to_graphml as _to_graphml,
        to_cypher as _to_cypher,
    )

    # Auto-scope from config
    effective_scope = scope
    if scope is None and not no_scope:
        cfg = load_config(repo.resolve())
        if cfg.packages:
            effective_scope = list(cfg.packages)
            if not as_json:
                console.print(
                    f"[dim]auto-scope from {cfg.source}:[/] "
                    + ", ".join(effective_scope)
                )

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        driver.verify_connectivity()
        nodes, edges = _dump_graph(driver, scope=effective_scope)
    except (ServiceUnavailable, AuthError) as e:
        _emit_error(as_json, "connection", str(e))
        raise typer.Exit(code=2)
    finally:
        driver.close()

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    warnings: list[str] = []

    if do_html:
        html_path = output_dir / "graph.html"
        try:
            _to_html(nodes, edges, html_path, max_nodes=max_nodes)
            written.append(str(html_path))
        except ValueError as exc:
            warnings.append(str(exc))
            if not as_json:
                console.print(f"[yellow]warning:[/] {exc}")

    if do_json:
        json_path = output_dir / "graph.json"
        _to_json(nodes, edges, json_path)
        written.append(str(json_path))

    if graphml:
        gml_path = output_dir / "graph.graphml"
        _to_graphml(nodes, edges, gml_path)
        written.append(str(gml_path))

    if cypher:
        cyp_path = output_dir / "graph.cypher"
        _to_cypher(nodes, edges, cyp_path)
        written.append(str(cyp_path))

    if as_json:
        result: dict[str, Any] = {
            "ok": True,
            "nodes": len(nodes),
            "edges": len(edges),
            "files": written,
        }
        if warnings:
            result["warnings"] = warnings
        print(json.dumps(result, indent=2))
    else:
        for f in written:
            console.print(f"[green]✓[/] {f}")
        console.print(
            f"[bold]exported {len(nodes)} nodes, {len(edges)} edges "
            f"→ {len(written)} file(s)[/]"
        )


# ── benchmark ──────────────────────────────────────────────────────

@app.command()
def benchmark(
    repo: Path = typer.Argument(Path("."), exists=True, file_okay=False),
    uri: str = DEFAULT_URI,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASS,
    as_json: bool = typer.Option(False, "--json", help="Emit report as JSON on stdout."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show per-query breakdown."),
    min_reduction: Optional[float] = typer.Option(
        None, "--min-reduction",
        help="Exit 1 if the reduction ratio is below this threshold.",
    ),
    out: Path = typer.Option(Path("codegraph-out"), "--out", "-o",
                             help="Directory for benchmark.json output."),
    scope: Optional[list[str]] = typer.Option(
        None, "--scope", "-s",
        help="Restrict corpus counting to these package paths (repeatable).",
    ),
    no_scope: bool = typer.Option(
        False, "--no-scope",
        help="Disable auto-scope even when packages are configured.",
    ),
) -> None:
    """Run the token-reduction benchmark against the live graph."""
    from .benchmark import (
        print_benchmark_summary,
        print_benchmark_verbose,
        run_benchmark,
        write_benchmark_json,
    )

    # Auto-scope from config when no explicit flag given.
    effective_scope = scope
    if scope is None and not no_scope:
        cfg = load_config(repo.resolve())
        if cfg.packages:
            effective_scope = list(cfg.packages)
            if not as_json:
                console.print(
                    f"[dim]auto-scope from {cfg.source}:[/] "
                    + ", ".join(effective_scope)
                )

    packages = effective_scope or []
    try:
        result = run_benchmark(
            uri=uri, user=user, password=password,
            repo=repo.resolve(),
            packages=packages,
        )
    except (ServiceUnavailable, AuthError) as e:
        _emit_error(as_json, "connection", str(e))
        raise typer.Exit(code=2)

    out_dir = repo.resolve() / out
    write_benchmark_json(result, out_dir)

    if as_json:
        print(result.to_json())
    elif verbose:
        print_benchmark_verbose(result, console)
    else:
        print_benchmark_summary(result, console)

    if min_reduction is not None and result.reduction_ratio < min_reduction:
        raise typer.Exit(code=1)


# ── report ────────────────────────────────────────────────────────────

@app.command()
def report(
    repo: Path = typer.Argument(Path("."), exists=True, file_okay=False),
    uri: str = DEFAULT_URI,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASS,
    as_json: bool = typer.Option(False, "--json", help="Emit analysis as JSON on stdout."),
    out: Path = typer.Option(Path("codegraph-out"), "--out", "-o",
                             help="Directory for GRAPH_REPORT.md output."),
    scope: Optional[list[str]] = typer.Option(
        None, "--scope", "-s",
        help="Restrict analysis to these package paths (repeatable).",
    ),
    no_scope: bool = typer.Option(
        False, "--no-scope",
        help="Disable auto-scope even when packages are configured.",
    ),
) -> None:
    """Generate GRAPH_REPORT.md from community detection on the live graph."""
    try:
        from .analyze import run_analysis
        from .report import generate_report, write_report
    except ImportError as e:
        # Escape the brackets so Rich doesn't strip them as unknown style tags.
        console.print(
            f"[bold red]missing dependency:[/] {e}\n"
            r"Install the \[analyze] extra: pip install 'codegraph\[analyze]'"
        )
        raise typer.Exit(code=2)

    # Auto-scope from config when no explicit flag given.
    effective_scope = scope
    if scope is None and not no_scope:
        cfg = load_config(repo.resolve())
        if cfg.packages:
            effective_scope = list(cfg.packages)
            if not as_json:
                console.print(
                    f"[dim]auto-scope from {cfg.source}:[/] "
                    + ", ".join(effective_scope)
                )

    packages = effective_scope or []
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        try:
            driver.verify_connectivity()
            analysis = run_analysis(
                driver, scope=packages or None,
                console=None if as_json else console,
            )
        finally:
            driver.close()
    except (ServiceUnavailable, AuthError) as e:
        _emit_error(as_json, "connection", str(e))
        raise typer.Exit(code=2)

    if as_json:
        print(json.dumps({"ok": True, "analysis": analysis}, indent=2))
    else:
        report_text = generate_report(analysis)
        out_dir = repo.resolve() / out
        write_report(report_text, out_dir / "GRAPH_REPORT.md")
        console.print(
            f"[green]✓[/] GRAPH_REPORT.md → {out_dir} "
            f"({analysis['community_count']} communities)"
        )


# ── error emission helper ────────────────────────────────────────────

def _emit_error(as_json: bool, kind: str, message: str) -> None:
    if as_json:
        print(json.dumps({"ok": False, "error": kind, "message": message}, indent=2), file=sys.stdout)
    else:
        console.print(f"[bold red]{kind} error[/]\n{message}")


# ── hook sub-app ────────────────────────────────────────────────────


@hook_app.command(name="install")
def hook_install() -> None:
    """Install post-commit + post-checkout hooks that rebuild the graph."""
    from .hooks import install as _install
    try:
        console.print(_install())
    except RuntimeError as exc:
        console.print(f"[bold red]error:[/] {exc}")
        raise typer.Exit(code=1)


@hook_app.command(name="uninstall")
def hook_uninstall() -> None:
    """Remove codegraph hooks (other hooks preserved)."""
    from .hooks import uninstall as _uninstall
    try:
        console.print(_uninstall())
    except RuntimeError as exc:
        console.print(f"[bold red]error:[/] {exc}")
        raise typer.Exit(code=1)


@hook_app.command(name="status")
def hook_status() -> None:
    """Show whether codegraph hooks are installed."""
    from .hooks import status as _status
    console.print(_status())


# ── watch ───────────────────────────────────────────────────────────


@app.command()
def watch(
    repo: Path = typer.Argument(
        Path("."), exists=True, file_okay=False,
        help="Root of the repo to watch (default: cwd).",
    ),
    debounce: float = typer.Option(
        3.0, "--debounce",
        help="Seconds to wait after last change before rebuilding.",
    ),
    packages: Optional[list[str]] = typer.Option(
        None, "--package", "-p",
        help="Package to watch (repeatable). Defaults to codegraph.toml config.",
    ),
    uri: str = DEFAULT_URI,
    user: str = DEFAULT_USER,
    password: str = DEFAULT_PASS,
    repo_name: Optional[str] = typer.Option(
        None, "--repo-name",
        help="Repository namespace (default: folder name).",
    ),
) -> None:
    """Watch for file changes and rebuild the graph incrementally."""
    from .watch import run_watch
    raise typer.Exit(code=run_watch(
        repo=repo.resolve(),
        debounce=debounce,
        packages=packages,
        uri=uri, user=user, password=password,
        repo_name=repo_name,
    ))


# ── install / uninstall sub-apps ───────────────────────────────────


def _build_install_vars(root: Path) -> dict[str, str]:
    """Build the full template-variable dict for ``install`` commands.

    Delegates to :func:`codegraph.init.build_template_vars` so every
    ``$VAR`` in the shipped templates gets resolved even when
    ``codegraph init`` has not been run.
    """
    from .init import _DEFAULT_BOLT_PORT, build_template_vars, derive_container_name

    config = load_config(root)
    packages = config.packages
    prefix = (packages[0] + "/") if packages and packages[0] != "." else ""
    bolt = int(os.environ.get("CODEGRAPH_NEO4J_BOLT_PORT", str(_DEFAULT_BOLT_PORT)))

    return build_template_vars(
        packages=packages,
        container_name=derive_container_name(root),
        default_package_prefix=prefix,
        bolt_port=bolt,
    )


@install_app.callback(invoke_without_command=True)
def _install_callback(
    ctx: typer.Context,
    all_: bool = typer.Option(False, "--all", help="Install for all detected platforms."),
) -> None:
    """Install codegraph as always-on context for an AI platform."""
    if all_:
        from .platforms import install_all
        from .init import _find_git_root
        root = _find_git_root(Path.cwd())
        template_vars = _build_install_vars(root)
        results = install_all(root, template_vars=template_vars, console=console)
        for r in results:
            console.print(r)
    elif ctx.invoked_subcommand is None:
        console.print("[red]Specify a platform or use --all[/]")
        raise typer.Exit(code=1)


def _make_install_cmd(platform_name: str, display_name: str):
    def _cmd() -> None:
        from .platforms import install_platform
        from .init import _find_git_root
        root = _find_git_root(Path.cwd())
        template_vars = _build_install_vars(root)
        result = install_platform(root, platform_name, template_vars=template_vars, console=console)
        console.print(result)
    _cmd.__doc__ = f"Install codegraph for {display_name}."
    return _cmd


def _make_uninstall_cmd(platform_name: str, display_name: str):
    def _cmd() -> None:
        from .platforms import uninstall_platform
        from .init import _find_git_root
        root = _find_git_root(Path.cwd())
        result = uninstall_platform(root, platform_name, console=console)
        console.print(result)
    _cmd.__doc__ = f"Remove codegraph from {display_name}."
    return _cmd


from .platforms import PLATFORMS as _PLATFORMS

for _name, _cfg in _PLATFORMS.items():
    install_app.command(name=_name)(_make_install_cmd(_name, _cfg.display_name))
    uninstall_app.command(name=_name)(_make_uninstall_cmd(_name, _cfg.display_name))


if __name__ == "__main__":
    app()
