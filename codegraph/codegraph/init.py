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

Shared Neo4j model: codegraph uses a single ``codegraph-neo4j`` container
across every repo on the machine.  Init detects an existing container and
reuses it (starting it first if it's stopped) before falling back to
``docker compose up -d`` for a fresh install.  See
:func:`find_existing_neo4j_container` and :func:`_resolve_neo4j_setup`.

Templates live in :mod:`codegraph.templates` and use ``string.Template``
(``$VAR`` / ``${VAR}``) substitution — stdlib, no new dependencies.
"""
from __future__ import annotations

import enum
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from importlib.resources import files as _pkg_files
from pathlib import Path
from string import Template
from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt

from .docker_setup import (
    DockerStatus,
    OsInfo,
    check_docker_installed,
    detect_os,
    suggest_daemon_start,
    suggest_docker_install,
    suggest_docker_update,
)


_TEMPLATES_ROOT = _pkg_files("codegraph") / "templates"

# Single shared container name for every repo on the machine.  Init detects
# and reuses this container instead of creating per-repo isolates.
SHARED_CONTAINER_NAME = "codegraph-neo4j"

_DEFAULT_BOLT_PORT = 7687
_DEFAULT_HTTP_PORT = 7474
_NEO4J_READY_TIMEOUT_SEC = 90
_DOCKER_PROBE_TIMEOUT_SEC = 5


def _sanitize_container_segment(name: str) -> str:
    """Replace chars invalid in Docker container names and collapse dashes."""
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "-", name)
    safe = re.sub(r"-{2,}", "-", safe)
    safe = safe.strip("-.")
    return safe or "repo"


def derive_container_name(root: Path) -> str:
    """Deterministic per-repo Docker container name (legacy / opt-in isolation).

    Format: ``cognitx-codegraph-<sanitized-dir>-<8-hex-chars>``.

    Not used by default — init now uses :data:`SHARED_CONTAINER_NAME` so
    every repo on the machine shares one Neo4j.  Kept here for any caller
    that wants per-repo isolation by passing a custom container name into
    :class:`InitConfig`.
    """
    repo_name = _sanitize_container_segment(root.name)
    path_hash = hashlib.sha1(str(root.resolve()).encode()).hexdigest()[:8]
    return f"cognitx-codegraph-{repo_name}-{path_hash}"


# ── Container detection / reuse ─────────────────────────────


class Neo4jSetup(enum.Enum):
    """Outcome of resolving how init should set up Neo4j."""

    REUSE_RUNNING = "reuse_running"           # existing container, already running
    REUSE_STOPPED = "reuse_stopped"           # existing container, was stopped, started
    CREATE_NEW = "create_new"                 # no existing container, fresh compose up
    DOCKER_MISSING = "docker_missing"         # docker binary not on PATH
    DAEMON_DOWN = "daemon_down"               # docker installed but daemon not answering
    PORT_TAKEN = "port_taken"                 # bolt or http port held by something else
    START_FAILED = "start_failed"             # docker start <name> failed for the existing container


def find_existing_neo4j_container(name: str = SHARED_CONTAINER_NAME) -> Optional[dict]:
    """Inspect a Docker container by name. Return its key facts or ``None``.

    Returns a dict like::

        {
            "name": "codegraph-neo4j",
            "state": "running" | "exited" | "created" | "paused" | …,
            "image": "neo4j:5.24-community",
            "ports": {"bolt": 7688, "http": 7475},  # host-side ports, may be empty
        }

    Returns ``None`` when the container doesn't exist *or* docker isn't
    available — callers should still call :func:`check_docker_installed`
    to distinguish those cases.
    """
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{json .}}", name],
            capture_output=True, text=True,
            timeout=_DOCKER_PROBE_TIMEOUT_SEC, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None  # "No such object" → container doesn't exist

    try:
        spec = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    state_block = spec.get("State", {}) or {}
    config_block = spec.get("Config", {}) or {}
    network_block = spec.get("NetworkSettings", {}) or {}
    port_bindings = network_block.get("Ports", {}) or {}

    ports = {
        "bolt": _extract_host_port(port_bindings.get("7687/tcp")),
        "http": _extract_host_port(port_bindings.get("7474/tcp")),
    }
    return {
        "name": name,
        "state": state_block.get("Status", "unknown"),
        "image": config_block.get("Image", ""),
        "ports": {k: v for k, v in ports.items() if v is not None},
    }


def _extract_host_port(bindings: Optional[list]) -> Optional[int]:
    """Pull the first host-side port out of a ``docker inspect`` Ports entry."""
    if not bindings:
        return None
    first = bindings[0] if isinstance(bindings, list) else None
    if not isinstance(first, dict):
        return None
    raw = first.get("HostPort")
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def start_existing_container(name: str, console: Console) -> bool:
    """Run ``docker start <name>``.  Returns True on success.

    Idempotent — a container that's already running becomes a no-op.
    """
    try:
        result = subprocess.run(
            ["docker", "start", name],
            capture_output=True, text=True,
            timeout=_DOCKER_PROBE_TIMEOUT_SEC, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        console.print("[red]docker not found on PATH[/]")
        return False
    if result.returncode != 0:
        console.print(f"[red]docker start failed:[/] {result.stderr.strip()}")
        return False
    return True


def _is_port_in_use(port: int) -> bool:
    """Best-effort check: is something listening on ``localhost:port``?"""
    import socket as _socket
    sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        # SO_REUSEADDR keeps this from leaving a TIME_WAIT entry.
        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        return False  # bind succeeded → port free
    except OSError:
        return True
    finally:
        sock.close()


def _resolve_neo4j_setup(
    config: "InitConfig",
    console: Console,
    *,
    docker_status: Optional[DockerStatus] = None,
) -> Neo4jSetup:
    """Decide how init should bring up Neo4j and (when reusing) sync the
    container's host ports back into ``config``.

    Side effects:
    - On REUSE_*: mutates ``config.bolt_port`` / ``config.http_port`` to
      the existing container's actual host-side port mapping so the rest
      of the init flow (compose template, readiness probe, first index)
      uses the right values.
    """
    status = docker_status if docker_status is not None else check_docker_installed()
    if not status.installed:
        return Neo4jSetup.DOCKER_MISSING
    if not status.daemon_running:
        return Neo4jSetup.DAEMON_DOWN

    existing = find_existing_neo4j_container(config.container_name)
    if existing is not None:
        # Sync ports so we probe the right URL and the first index dials home correctly.
        existing_ports = existing.get("ports", {})
        if existing_ports.get("bolt"):
            config.bolt_port = existing_ports["bolt"]
        if existing_ports.get("http"):
            config.http_port = existing_ports["http"]

        if existing["state"] == "running":
            console.print(
                f"[green]✓[/] Reusing existing [bold]{config.container_name}[/] container "
                f"(bolt {config.bolt_port}, http {config.http_port})."
            )
            return Neo4jSetup.REUSE_RUNNING

        console.print(
            f"[bold]Found stopped[/] [bold]{config.container_name}[/] — starting it…"
        )
        if not start_existing_container(config.container_name, console):
            return Neo4jSetup.START_FAILED
        return Neo4jSetup.REUSE_STOPPED

    # No existing container.  Make sure the requested ports are free before
    # we try a fresh `docker compose up -d`.
    for port_name, port in (("bolt", config.bolt_port), ("http", config.http_port)):
        if _is_port_in_use(port):
            console.print(
                f"[red]Port {port} ({port_name}) is already in use[/] — "
                f"and no [bold]{config.container_name}[/] container owns it. "
                f"Re-run with [cyan]--bolt-port[/] / [cyan]--http-port[/] to pick free ports."
            )
            return Neo4jSetup.PORT_TAKEN

    return Neo4jSetup.CREATE_NEW


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
    install_hooks: bool = True
    install_platforms: list[str] = field(default_factory=list)
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
    # Shared container across every repo on the machine.  See module docstring.
    container_name = SHARED_CONTAINER_NAME

    if non_interactive:
        return InitConfig(
            packages=default_packages,
            cross_pairs=[],
            install_claude=True,
            install_ci=True,
            setup_neo4j=True,
            container_name=container_name,
            install_hooks=True,
            install_platforms=["claude"],
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
    install_hooks = Confirm.ask(
        "Install git hooks (post-commit + post-checkout) for auto graph rebuild?",
        default=True,
    )
    install_platforms_answer = Prompt.ask(
        "Install for AI platforms (comma-separated, or 'all')",
        default="claude",
    )
    if install_platforms_answer.strip().lower() == "all":
        from .platforms import PLATFORMS
        install_platforms = list(PLATFORMS.keys())
    else:
        install_platforms = [
            p.strip() for p in install_platforms_answer.split(",") if p.strip()
        ]

    return InitConfig(
        packages=packages,
        cross_pairs=cross_pairs,
        install_claude=install_claude,
        install_ci=install_ci,
        setup_neo4j=setup_neo4j,
        container_name=container_name,
        install_hooks=install_hooks,
        install_platforms=install_platforms,
        bolt_port=bolt_port if bolt_port is not None else _DEFAULT_BOLT_PORT,
        http_port=http_port if http_port is not None else _DEFAULT_HTTP_PORT,
        default_package_prefix=packages[0] + "/" if packages and packages[0] != "." else "",
    )


# ── Scaffolder ───────────────────────────────────────────────


def build_template_vars(
    *,
    packages: list[str],
    container_name: str,
    cross_pairs: Sequence[tuple[str, str]] = (),
    default_package_prefix: str = "",
    bolt_port: int = _DEFAULT_BOLT_PORT,
    http_port: int = _DEFAULT_HTTP_PORT,
    pipx_version: str = "0.2.0",
) -> dict[str, str]:
    """Build the substitution dict consumed by :class:`string.Template`.

    Single source of truth for template variables used by both
    ``codegraph init`` and ``codegraph install``.
    """
    flags = " ".join(f"-p {p}" for p in packages) if packages else ""

    cross_pairs_toml = ""
    for importer, importee in cross_pairs:
        cross_pairs_toml += (
            f'  {{ importer = "{importer}", importee = "{importee}" }},\n'
        )

    return {
        "PACKAGE_PATHS_FLAGS": flags,
        "DEFAULT_PACKAGE_PREFIX": default_package_prefix,
        "CROSS_PAIRS_TOML": cross_pairs_toml,
        "CONTAINER_NAME": container_name,
        "NEO4J_BOLT_PORT": str(bolt_port),
        "NEO4J_HTTP_PORT": str(http_port),
        "PIPX_VERSION": pipx_version,
    }


def _template_vars(config: InitConfig) -> dict[str, str]:
    """Build the substitution dict consumed by :class:`string.Template`."""
    return build_template_vars(
        packages=config.packages,
        container_name=config.container_name,
        cross_pairs=config.cross_pairs,
        default_package_prefix=config.default_package_prefix,
        bolt_port=config.bolt_port,
        http_port=config.http_port,
        pipx_version=config.pipx_version,
    )


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


def _ensure_gitignore_entry(root: Path, console: Console) -> None:
    """Add ``.codegraph-cache/`` to ``.gitignore`` if not already present."""
    target = root / ".gitignore"
    entry = ".codegraph-cache/"
    if target.exists():
        with open(target, encoding="utf-8", newline="") as fh:
            existing = fh.read()
        if any(line.strip() == entry for line in existing.splitlines()):
            console.print(f"  [yellow]skip[/] {target} (already contains {entry})")
            return
        sep = "" if existing.endswith("\n") else "\n"
        with open(target, "w", encoding="utf-8", newline="") as fh:
            fh.write(existing + sep + "\n# codegraph\n" + entry + "\n")
        console.print(f"  [green]appended[/] {entry} to {target}")
    else:
        with open(target, "w", encoding="utf-8", newline="") as fh:
            fh.write("# codegraph\n" + entry + "\n")
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

    # .gitignore — ensure cache dir is excluded
    _ensure_gitignore_entry(root, console)


# ── Docker orchestration + first index ───────────────────────


def _warn_orphaned_containers(
    root: Path,
    config: InitConfig,
    console: Console,
) -> None:
    """Detect pre-0.1.10 containers (no hash suffix) and print a warning."""
    repo_name = _sanitize_container_segment(root.name)
    old_prefix = f"cognitx-codegraph-{repo_name}"
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", f"name={old_prefix}",
             "--format", "{{.Names}}"],
            capture_output=True, text=True, check=True,
        )
    except FileNotFoundError:
        return
    except subprocess.CalledProcessError:
        return

    for line in result.stdout.splitlines():
        name = line.strip()
        if not name or name == config.container_name:
            continue
        # Only flag containers that exactly match the old naming scheme
        # (prefix with no hash suffix).  docker ps --filter name= does
        # substring matching, so other repos' containers may appear.
        if name != old_prefix:
            continue
        console.print(
            f"[yellow]Warning:[/] found old container [bold]{name}[/] "
            f"from a pre-0.1.10 install. "
            f"Remove it with: [cyan]docker rm -f {name}[/]"
        )


def _preflight_docker(console: Console) -> Optional[DockerStatus]:
    """Print the Docker-presence banner at the top of init.

    Returns the :class:`DockerStatus` to thread into later helpers, or
    ``None`` if init should bail out (Docker missing or daemon down).
    The caller can soft-skip this whole stage with ``--skip-docker``.
    """
    status = check_docker_installed()
    os_info = detect_os()

    if not status.installed:
        console.print(suggest_docker_install(os_info))
        console.print("[dim]Re-run with [cyan]--skip-docker[/] to scaffold without Docker.[/]")
        return None

    if not status.daemon_running:
        console.print(suggest_daemon_start(os_info))
        console.print("[dim]Re-run with [cyan]--skip-docker[/] to scaffold without Docker.[/]")
        return None

    if status.needs_update:
        # Soft warning — old Docker still works, just nudge the user.
        console.print(
            suggest_docker_update(os_info, status.version)
            if status.version is not None
            else "[yellow]Docker is older than the recommended baseline.[/]"
        )

    console.print(f"[green]✓[/] {status.version_str}")
    return status


def _start_and_wait_for_neo4j(
    root: Path,
    config: InitConfig,
    console: Console,
    *,
    docker_status: Optional[DockerStatus] = None,
) -> bool:
    """Bring up the shared codegraph-neo4j container and wait until it's ready.

    Strategy (handled by :func:`_resolve_neo4j_setup`):
    1. If a container named ``codegraph-neo4j`` already exists and runs → reuse.
    2. If it exists but is stopped → ``docker start`` it.
    3. Otherwise → ``docker compose up -d`` (fresh install).

    Returns True iff the daemon answers HTTP within
    :data:`_NEO4J_READY_TIMEOUT_SEC`.
    """
    setup = _resolve_neo4j_setup(config, console, docker_status=docker_status)

    if setup == Neo4jSetup.DOCKER_MISSING:
        console.print(suggest_docker_install(detect_os()))
        return False
    if setup == Neo4jSetup.DAEMON_DOWN:
        console.print(suggest_daemon_start(detect_os()))
        return False
    if setup == Neo4jSetup.PORT_TAKEN:
        return False
    if setup == Neo4jSetup.START_FAILED:
        return False

    if setup == Neo4jSetup.CREATE_NEW:
        compose_path = root / "docker-compose.yml"
        console.print(f"[bold]Creating Neo4j ({config.container_name})…[/]")
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

    # All reuse / create paths converge on a readiness probe.
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

    # Pre-flight Docker checks.  We probe once and pass the status down so
    # later helpers don't redo `docker info`.
    docker_status: Optional[DockerStatus] = None
    if not skip_docker:
        docker_status = _preflight_docker(console)
        if docker_status is None:
            # Hard stop: Docker missing or daemon down.  The caller's --skip-docker
            # escape hatch turns this into a soft skip below.
            return 1

    detected = _detect_repo_shape(root)
    config = _prompt_config(
        detected, non_interactive=non_interactive, console=console,
        bolt_port=bolt_port, http_port=http_port,
    )

    if config.setup_neo4j and not skip_docker:
        _warn_orphaned_containers(root, config, console)

    _scaffold_files(root, config, force=force, console=console)

    if config.install_hooks:
        from .hooks import install as _install_hooks
        try:
            result = _install_hooks(root)
            console.print(f"[bold]Git hooks:[/] {result}")
        except RuntimeError as exc:
            console.print(f"[yellow]Git hooks:[/] {exc}")

    # Platform install — handles CLAUDE.md, AGENTS.md, hooks, etc.
    effective_platforms = list(config.install_platforms)
    if not effective_platforms and config.install_claude:
        effective_platforms = ["claude"]
    if effective_platforms:
        from .platforms import install_platform
        vars_ = _template_vars(config)
        for platform_name in effective_platforms:
            try:
                result = install_platform(
                    root, platform_name,
                    template_vars=vars_, console=console,
                )
                console.print(f"[bold]{platform_name}:[/] {result}")
            except Exception as exc:
                console.print(f"[yellow]{platform_name}:[/] {exc}")

    if config.setup_neo4j and not skip_docker:
        if not _start_and_wait_for_neo4j(root, config, console, docker_status=docker_status):
            console.print("[yellow]Skipping first index (Neo4j not ready)[/]")
            _print_next_steps(root, config, console)
            return 0

    if not skip_index and config.packages:
        if not _run_first_index(root, config, console):
            _print_next_steps(root, config, console)
            return 1

    _print_next_steps(root, config, console)
    return 0
