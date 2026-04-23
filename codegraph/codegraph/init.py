"""`codegraph init` — scaffold codegraph into any repo.

Does four things in order:

1. Detect repo shape (git root + obvious package directories).
2. Ask a short interactive Q&A (or use ``--yes`` for defaults).
3. Scaffold ``.claude/commands/``, ``.github/workflows/arch-check.yml``,
   ``.arch-policies.toml``, ``docker-compose.yml``, and an appended snippet
   to ``CLAUDE.md`` — all from templates shipped with the package.
4. (Optional) Start Neo4j via ``docker compose up -d`` and run the first
   ``codegraph index`` so the graph is queryable immediately.

Flags:

- ``--yes`` / ``-y``  skip prompts, accept every default
- ``--force``         overwrite existing scaffolded files (never CLAUDE.md)
- ``--skip-docker``   write compose file but don't start it
- ``--skip-index``    don't run the first index

Templates live in :mod:`codegraph.templates` and use ``string.Template``
(``$VAR`` / ``${VAR}``) substitution — stdlib, no new dependencies.
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from importlib.resources import files as _pkg_files
from pathlib import Path
from string import Template
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt


_TEMPLATES_ROOT = _pkg_files("codegraph") / "templates"

_DEFAULT_BOLT_PORT = 7687
_DEFAULT_HTTP_PORT = 7474
_NEO4J_READY_TIMEOUT_SEC = 90


# ── Detection ────────────────────────────────────────────────


@dataclass
class RepoShape:
    """What we learned about the target repo by scanning it."""

    root: Path
    languages: list[str] = field(default_factory=list)      # "py", "ts"
    package_candidates: list[str] = field(default_factory=list)  # repo-relative


def _find_git_root(start: Path) -> Path:
    """Walk up from ``start`` to find a ``.git`` directory. Raises if none."""
    cur = start.resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / ".git").exists():
            return candidate
    raise typer.BadParameter(
        f"Not a git repository: no .git/ found from {start} upward. "
        "Run `git init` first."
    )


def _detect_repo_shape(root: Path) -> RepoShape:
    """Quick scan for language frontends + candidate package dirs.

    Looks at the top level and one layer of well-known monorepo conventions
    (``apps/``, ``packages/``, ``services/``). Does not recurse further —
    keeps init fast on big repos.
    """
    langs: set[str] = set()
    candidates: set[str] = set()

    # Top level
    if (root / "pyproject.toml").exists() or list(root.glob("*.py"))[:1]:
        langs.add("py")
    if any((root / name).exists() for name in ("package.json", "tsconfig.json")):
        langs.add("ts")

    # One-layer monorepo convention
    for container in ("apps", "packages", "services"):
        container_dir = root / container
        if not container_dir.is_dir():
            continue
        for pkg_dir in sorted(container_dir.iterdir()):
            if not pkg_dir.is_dir() or pkg_dir.name.startswith("."):
                continue
            if (pkg_dir / "pyproject.toml").exists():
                langs.add("py")
                candidates.add(str(pkg_dir.relative_to(root)))
            if (pkg_dir / "package.json").exists():
                langs.add("ts")
                candidates.add(str(pkg_dir.relative_to(root)))

    # Root-level package fallback
    if not candidates:
        if (root / "pyproject.toml").exists():
            candidates.add(".")
        if (root / "package.json").exists():
            candidates.add(".")

    return RepoShape(
        root=root,
        languages=sorted(langs),
        package_candidates=sorted(candidates),
    )


# ── Config gathered from prompts ─────────────────────────────


@dataclass
class InitConfig:
    packages: list[str]
    cross_pairs: list[tuple[str, str]]
    install_claude: bool
    install_ci: bool
    setup_neo4j: bool
    container_name: str
    bolt_port: int = _DEFAULT_BOLT_PORT
    http_port: int = _DEFAULT_HTTP_PORT
    pipx_version: str = "0.2.0"
    default_package_prefix: str = ""


def _prompt_config(
    detected: RepoShape,
    non_interactive: bool,
    console: Console,
    bolt_port: int | None = None,
    http_port: int | None = None,
) -> InitConfig:
    """Run the interactive Q&A. With ``--yes``, every answer defaults to True
    and every path comes from detection.
    """
    default_packages = detected.package_candidates or ["."]
    default_pkg_str = ",".join(default_packages)
    repo_name = detected.root.name
    path_hash = hashlib.sha1(str(detected.root.resolve()).encode()).hexdigest()[:8]

    if non_interactive:
        return InitConfig(
            packages=default_packages,
            cross_pairs=[],
            install_claude=True,
            install_ci=True,
            setup_neo4j=True,
            container_name=f"cognitx-codegraph-{repo_name}-{path_hash}",
            bolt_port=bolt_port if bolt_port is not None else _DEFAULT_BOLT_PORT,
            http_port=http_port if http_port is not None else _DEFAULT_HTTP_PORT,
            default_package_prefix=default_packages[0] + "/" if default_packages[0] != "." else "",
        )

    console.print(
        f"[dim]Detected languages:[/] {', '.join(detected.languages) or '(none — add files first)'}"
    )
    console.print(
        f"[dim]Package candidates:[/] {default_pkg_str}"
    )
    console.print()

    pkg_answer = Prompt.ask(
        "Package paths to index (comma-separated)",
        default=default_pkg_str,
    )
    packages = [p.strip() for p in pkg_answer.split(",") if p.strip()]

    cross_pairs: list[tuple[str, str]] = []
    if Confirm.ask("Add cross-package boundaries (importer must not import importee)?", default=False):
        while True:
            importer = Prompt.ask(
                "  Forbidden import — importer package (empty to finish)",
                default="",
            )
            if not importer:
                break
            importee = Prompt.ask("  Forbidden import — importee package")
            cross_pairs.append((importer, importee))

    install_claude = Confirm.ask(
        "Install Claude Code slash commands into .claude/commands/?", default=True
    )
    install_ci = Confirm.ask(
        "Install GitHub Actions arch-check gate into .github/workflows/?", default=True
    )
    setup_neo4j = Confirm.ask(
        "Set up local Neo4j via docker-compose?", default=True
    )

    return InitConfig(
        packages=packages,
        cross_pairs=cross_pairs,
        install_claude=install_claude,
        install_ci=install_ci,
        setup_neo4j=setup_neo4j,
        container_name=f"cognitx-codegraph-{repo_name}-{path_hash}",
        bolt_port=bolt_port if bolt_port is not None else _DEFAULT_BOLT_PORT,
        http_port=http_port if http_port is not None else _DEFAULT_HTTP_PORT,
        default_package_prefix=packages[0] + "/" if packages and packages[0] != "." else "",
    )


# ── Scaffolder ───────────────────────────────────────────────


def _template_vars(config: InitConfig) -> dict[str, str]:
    """Build the substitution dict consumed by :class:`string.Template`."""
    flags = " ".join(f"-p {p}" for p in config.packages) if config.packages else ""

    cross_pairs_toml = ""
    for importer, importee in config.cross_pairs:
        cross_pairs_toml += (
            f'  {{ importer = "{importer}", importee = "{importee}" }},\n'
        )

    return {
        "PACKAGE_PATHS_FLAGS": flags,
        "DEFAULT_PACKAGE_PREFIX": config.default_package_prefix,
        "CROSS_PAIRS_TOML": cross_pairs_toml,
        "CONTAINER_NAME": config.container_name,
        "NEO4J_BOLT_PORT": str(config.bolt_port),
        "NEO4J_HTTP_PORT": str(config.http_port),
        "PIPX_VERSION": config.pipx_version,
    }


def _render(template_rel: str, variables: dict[str, str]) -> str:
    """Load a packaged template and substitute vars (safely; unknowns pass through)."""
    text = (_TEMPLATES_ROOT / template_rel).read_text(encoding="utf-8")
    return Template(text).safe_substitute(variables)


def _write_if_new(path: Path, content: str, *, force: bool, console: Console) -> bool:
    """Write ``path`` unless it already exists and ``force`` is False.

    Returns True if written. Prints a skip/overwrite line either way.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    already_exists = path.exists()
    if already_exists and not force:
        console.print(f"  [yellow]skip[/] {path} ([dim]exists; pass --force to overwrite[/])")
        return False
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(content)
    verb = "overwrote" if already_exists else "wrote"
    console.print(f"  [green]{verb}[/] {path}")
    return True


def _append_claude_md(root: Path, snippet: str, console: Console) -> None:
    """Append the CLAUDE.md snippet if not already present. Never clobbers."""
    target = root / "CLAUDE.md"
    marker = "## Using the codegraph knowledge graph"
    if target.exists():
        with open(target, encoding="utf-8", newline="") as fh:
            existing = fh.read()
        if marker in existing:
            console.print(f"  [yellow]skip[/] {target} (already contains codegraph section)")
            return
        with open(target, "w", encoding="utf-8", newline="") as fh:
            fh.write(existing.rstrip() + "\n\n" + snippet)
        console.print(f"  [green]appended[/] codegraph section to {target}")
    else:
        with open(target, "w", encoding="utf-8", newline="") as fh:
            fh.write(snippet)
        console.print(f"  [green]wrote[/] {target}")


def _scaffold_files(
    root: Path,
    config: InitConfig,
    *,
    force: bool,
    console: Console,
) -> None:
    """Render every template to its target path under ``root``."""
    variables = _template_vars(config)

    # Claude Code slash commands
    if config.install_claude:
        for cmd in [
            "graph.md", "graph-refresh.md", "blast-radius.md", "dead-code.md",
            "who-owns.md", "trace-endpoint.md", "arch-check.md",
        ]:
            rendered = _render(f"claude/commands/{cmd}", variables)
            _write_if_new(
                root / ".claude" / "commands" / cmd,
                rendered, force=force, console=console,
            )

    # Arch-policies config
    _write_if_new(
        root / ".arch-policies.toml",
        _render("arch-policies.toml", variables),
        force=force, console=console,
    )

    # GitHub Actions gate
    if config.install_ci:
        _write_if_new(
            root / ".github" / "workflows" / "arch-check.yml",
            _render("github/workflows/arch-check.yml", variables),
            force=force, console=console,
        )

    # Local Neo4j
    if config.setup_neo4j:
        _write_if_new(
            root / "docker-compose.yml",
            _render("docker-compose.yml", variables),
            force=force, console=console,
        )

    # CLAUDE.md snippet — appended rather than overwritten
    _append_claude_md(root, _render("claude-md-snippet.md", variables), console)


# ── Docker orchestration + first index ───────────────────────


def _start_and_wait_for_neo4j(
    root: Path,
    config: InitConfig,
    console: Console,
) -> bool:
    """Run ``docker compose up -d`` and wait for Neo4j HTTP readiness."""
    compose_path = root / "docker-compose.yml"
    console.print(f"[bold]Starting Neo4j ({config.container_name})…[/]")
    try:
        subprocess.run(
            ["docker", "compose", "-f", str(compose_path), "up", "-d"],
            check=True, cwd=root,
        )
    except FileNotFoundError:
        console.print("[red]docker not found on PATH — skipping.[/]")
        return False
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]docker compose up failed:[/] {exc}")
        return False

    url = f"http://localhost:{config.http_port}"
    deadline = time.monotonic() + _NEO4J_READY_TIMEOUT_SEC
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    console.print(f"  [green]Neo4j ready[/] ({url})")
                    return True
        except (urllib.error.URLError, ConnectionResetError, OSError):
            pass
        time.sleep(2)
    console.print(f"[red]Neo4j did not become ready in {_NEO4J_READY_TIMEOUT_SEC}s[/]")
    return False


def _run_first_index(
    root: Path,
    config: InitConfig,
    console: Console,
) -> bool:
    """Run ``codegraph index`` via subprocess against the freshly-started Neo4j."""
    if not config.packages:
        console.print("[yellow]No packages configured — skipping first index[/]")
        return False

    console.print("[bold]Running first index…[/]")
    cmd = [
        sys.executable, "-m", "codegraph.cli", "index", str(root),
        *sum((["-p", p] for p in config.packages), []),
        "--skip-ownership",
        "--uri", f"bolt://localhost:{config.bolt_port}",
    ]
    try:
        subprocess.run(cmd, check=True, cwd=root)
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]First index failed:[/] {exc}")
        return False
    console.print("  [green]Indexed[/]")
    return True


# ── Next-steps banner ────────────────────────────────────────


def _print_next_steps(root: Path, config: InitConfig, console: Console) -> None:
    console.rule("[bold green]codegraph init complete")
    console.print("Try these:\n")
    console.print("  [cyan]codegraph query \"MATCH (c:Class) RETURN c.name LIMIT 5\"[/]")
    console.print("  [cyan]codegraph arch-check[/]")
    console.print("  Inside Claude Code: [cyan]/graph \"MATCH (f:File) RETURN count(f)\"[/]")
    console.print()
    console.print(f"Docs: https://github.com/cognitx-leyton/graphrag-code")


# ── Entry point wired into cli.py ────────────────────────────


def run_init(
    *,
    force: bool,
    non_interactive: bool,
    skip_docker: bool,
    skip_index: bool,
    console: Console,
    bolt_port: int | None = None,
    http_port: int | None = None,
) -> int:
    """Main orchestrator. Returns the exit code the CLI should propagate."""
    cwd = Path.cwd()
    try:
        root = _find_git_root(cwd)
    except typer.BadParameter as exc:
        console.print(f"[red]{exc}[/]")
        return 1

    console.rule("[bold cyan]codegraph init")
    detected = _detect_repo_shape(root)
    config = _prompt_config(
        detected, non_interactive=non_interactive, console=console,
        bolt_port=bolt_port, http_port=http_port,
    )

    _scaffold_files(root, config, force=force, console=console)

    if config.setup_neo4j and not skip_docker:
        if not _start_and_wait_for_neo4j(root, config, console):
            console.print("[yellow]Skipping first index (Neo4j not ready)[/]")
            _print_next_steps(root, config, console)
            return 0

    if not skip_index and config.packages:
        if not _run_first_index(root, config, console):
            _print_next_steps(root, config, console)
            return 1

    _print_next_steps(root, config, console)
    return 0
