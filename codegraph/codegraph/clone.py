"""`codegraph clone <github-url>` — clone, cache, auto-index.

Wraps ``git clone`` + ``codegraph index`` into a single command for indexing
third-party repos. Manages a local clone cache under ``~/.codegraph/repos/``
so repeated runs do ``git pull --ff-only`` instead of a fresh clone.

Supports GitHub HTTPS and SSH URLs. Shallow clones by default (``--depth 1``)
which disables ownership (git-log) data; pass ``--full-clone`` to get a full
history and enable ownership edges.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

from rich.console import Console

from .config import ConfigError, load_config

# ── Constants ──────────────────────────────────────────────────────────

CLONE_CACHE_ROOT = Path.home() / ".codegraph" / "repos"

GITHUB_HTTPS_RE = re.compile(
    r"^https?://github\.com/([^/]+)/([^/.]+?)(?:\.git)?/?$"
)
GITHUB_SSH_RE = re.compile(
    r"^git@github\.com:([^/]+)/([^/.]+?)(?:\.git)?$"
)


# ── URL parsing ────────────────────────────────────────────────────────

def parse_github_url(url: str) -> tuple[str, str]:
    """Parse a GitHub URL and return ``(owner, repo)``.

    Raises :class:`~codegraph.config.ConfigError` for non-GitHub or
    malformed URLs.
    """
    if not url:
        raise ConfigError("URL must not be empty")

    m = GITHUB_HTTPS_RE.match(url) or GITHUB_SSH_RE.match(url)
    if not m:
        raise ConfigError(
            f"Not a recognised GitHub URL: {url!r}\n"
            "Expected https://github.com/<owner>/<repo> or "
            "git@github.com:<owner>/<repo>.git"
        )
    return m.group(1), m.group(2)


# ── Cache management ───────────────────────────────────────────────────

def cache_dir(owner: str, repo: str) -> Path:
    """Return the local cache directory for a given owner/repo pair."""
    return CLONE_CACHE_ROOT / owner / repo


# ── Git operations ─────────────────────────────────────────────────────

def clone_or_pull(
    url: str,
    dest: Path,
    *,
    shallow: bool = True,
    console: Console,
) -> None:
    """Clone *url* into *dest*, or pull if already cached.

    Raises :class:`~codegraph.config.ConfigError` on git failure.
    """
    if (dest / ".git").is_dir():
        console.print(f"[dim]Updating cached clone:[/] {dest}")
        try:
            subprocess.run(
                ["git", "pull", "--ff-only"],
                cwd=dest,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise ConfigError(
                f"git pull failed in {dest}:\n{exc.stderr.strip()}"
            ) from exc
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["git", "clone"]
        if shallow:
            cmd += ["--depth", "1"]
        cmd += [url, str(dest)]
        console.print(f"[dim]Cloning:[/] {url}")
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise ConfigError(
                f"git clone failed:\n{exc.stderr.strip()}"
            ) from exc


# ── Orchestrator ───────────────────────────────────────────────────────

def run_clone(
    url: str,
    *,
    packages: Optional[list[str]],
    uri: str,
    user: str,
    password: str,
    full_clone: bool = False,
    as_json: bool = False,
    no_export: bool = False,
    no_benchmark: bool = False,
    no_analyze: bool = False,
    console: Console,
) -> int:
    """Clone a GitHub repo and index it. Returns exit code (0 success, 2 error)."""
    import json

    from neo4j.exceptions import AuthError, ServiceUnavailable

    from .cli import _emit_error, _print_load_stats_dict, _run_index

    # 1. Parse URL
    try:
        owner, repo_name = parse_github_url(url)
    except ConfigError as e:
        _emit_error(as_json, "config", str(e))
        return 2

    # 2. Clone or update
    dest = cache_dir(owner, repo_name)
    try:
        clone_or_pull(url, dest, shallow=not full_clone, console=console)
    except ConfigError as e:
        _emit_error(as_json, "config", str(e))
        return 2

    # 3. Resolve packages
    if packages:
        packages_resolved = list(packages)
    else:
        cfg = load_config(dest)
        if cfg.packages:
            packages_resolved = list(cfg.packages)
        else:
            _emit_error(
                as_json, "config",
                f"No packages detected in {dest}. Pass --package/-p explicitly.\n"
                f"Hint: create a codegraph.toml in the repo with "
                f'packages = ["src", "lib"] or pass -p <dir>.',
            )
            return 2

    # 4. Index
    repo_name_ns = f"{owner}/{repo_name}"
    try:
        stats = _run_index(
            repo=dest,
            packages=packages_resolved,
            wipe=False,
            uri=uri,
            user=user,
            password=password,
            skip_ownership=not full_clone,
            repo_name=repo_name_ns,
            quiet=as_json,
        )
    except ConfigError as e:
        _emit_error(as_json, "config", str(e))
        return 2
    except (ServiceUnavailable, AuthError) as e:
        _emit_error(as_json, "connection", str(e))
        return 2

    # 5. Output
    if as_json:
        print(json.dumps({"ok": True, "stats": stats, "path": str(dest)}, indent=2))
    else:
        _print_load_stats_dict(stats)
        console.print(f"\n[green]✓[/] Cloned to {dest}")

    # 6. Post-processing (mirrors index command)
    from neo4j import GraphDatabase

    from .config import merge_cli_overrides

    if not no_export:
        try:
            from .export import dump_graph as _dump_graph, to_html, to_json
            out_dir = dest / "codegraph-out"
            driver = GraphDatabase.driver(uri, auth=(user, password))
            try:
                driver.verify_connectivity()
                nodes, edges = _dump_graph(driver, scope=packages_resolved)
            finally:
                driver.close()
            out_dir.mkdir(parents=True, exist_ok=True)
            to_html(nodes, edges, out_dir / "graph.html")
            to_json(nodes, edges, out_dir / "graph.json")
            if not as_json:
                console.print(f"[green]✓[/] exported graph.html + graph.json → {out_dir}")
        except Exception as exc:  # noqa: BLE001
            if not as_json:
                console.print(f"[yellow]warning:[/] export failed: {exc}")

    if not no_benchmark:
        try:
            from .benchmark import print_benchmark_summary, run_benchmark as _run_bench, write_benchmark_json
            bench_cfg = load_config(dest)
            bench_cfg = merge_cli_overrides(bench_cfg, packages=packages_resolved)
            bench_result = _run_bench(
                uri=uri, user=user, password=password,
                repo=dest,
                packages=list(bench_cfg.packages),
            )
            bench_out = dest / "codegraph-out"
            write_benchmark_json(bench_result, bench_out)
            if not as_json:
                print_benchmark_summary(bench_result, console)
        except Exception as exc:  # noqa: BLE001
            if not as_json:
                console.print(f"[yellow]warning:[/] benchmark failed: {exc}")

    if not no_analyze:
        try:
            from .analyze import run_analysis
            from .report import generate_report, write_report
            an_cfg = load_config(dest)
            an_cfg = merge_cli_overrides(an_cfg, packages=packages_resolved)
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
            out_dir = dest / "codegraph-out"
            write_report(report_text, out_dir / "GRAPH_REPORT.md")
            if not as_json:
                console.print(
                    f"[green]✓[/] GRAPH_REPORT.md → {out_dir} "
                    f"({analysis['community_count']} communities)"
                )
        except Exception as exc:  # noqa: BLE001
            if not as_json:
                console.print(f"[yellow]warning:[/] analyze failed: {exc}")

    return 0
