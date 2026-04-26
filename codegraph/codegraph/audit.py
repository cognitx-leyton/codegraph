"""``codegraph audit`` orchestrator — agent-driven extraction self-check.

Pipeline:

1. Verify the audit prompt lock file matches on-disk template hashes
   (defends against post-install tampering of a privileged surface).
2. Pick an agent (interactive prompt, ``--agent`` flag, or ``--list-agents``).
3. Build the prompt: substitute ``$EXTRACTION_INVENTORY`` (filtered to the
   frameworks detected in the live graph), ``$SAMPLE_FILES`` (highest-LOC
   per language), ``$CYPHER_PATTERNS``, plus run-time metadata.
4. Launch the agent as a subprocess in headless + permission-bypass mode.
   Stream stdout to the console.
5. Parse the agent's report at ``codegraph-out/audit-report.md`` and produce
   a summary dataclass with ``to_json()``.
6. Optionally hand the report to ``gh issue create``.

The audit never writes to the graph. It only reads — via shell-out to
``codegraph query --json`` so this module stays decoupled from the Neo4j
driver.
"""
from __future__ import annotations

import contextlib
import dataclasses
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from importlib.resources import files as _pkg_files
from pathlib import Path
from string import Template
from typing import Optional


@contextlib.contextmanager
def _redirect_stdout_to_devnull():
    """Suppress stdout writes inside the with-block (stderr stays live)."""
    saved = sys.stdout
    try:
        with open(os.devnull, "w", encoding="utf-8") as devnull:
            sys.stdout = devnull
            yield
    finally:
        sys.stdout = saved

from rich.console import Console
from rich.prompt import Confirm, Prompt

from .audit_agents import AUDIT_AGENTS, AuditAgent, get_agent
from .audit_prompt_lint import (
    check_lock as _check_lock,
    lock_hash as _lock_hash,
    update_lock as _update_lock,
)


_TEMPLATES_DIR = _pkg_files("codegraph") / "templates" / "audit"

_REPORT_REL_PATH = "codegraph-out/audit-report.md"

# Map FrameworkType.value (the string stored in :Package.framework's source)
# to the inventory section that audits it. Display names are looser; we match
# against multiple aliases below in _filter_inventory.
_PYTHON_FRAMEWORK_ALIASES = {"FastAPI", "Flask", "Django", "Odoo"}
_TS_FRAMEWORK_ALIASES = {
    "React",
    "React (TypeScript)",
    "Next.js",
    "Vue",
    "Vue 3",
    "Angular",
    "Svelte",
    "SvelteKit",
    "NestJS",
    "Fastify",
}


# ── Report shape ────────────────────────────────────────────────────


@dataclass
class AuditFinding:
    """One issue extracted from the agent's report."""

    index: int
    category: str
    severity: str
    construct: str = ""
    raw_block: str = ""


@dataclass
class AuditReport:
    """Outcome of one audit run, suitable for ``--json`` emission."""

    ok: bool
    agent: str
    repo: str
    report_path: str
    issues_found: int
    findings: list[AuditFinding] = field(default_factory=list)
    gh_issue_url: Optional[str] = None
    error: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "ok": self.ok,
                "agent": self.agent,
                "repo": self.repo,
                "report_path": self.report_path,
                "issues_found": self.issues_found,
                "findings": [dataclasses.asdict(f) for f in self.findings],
                "gh_issue_url": self.gh_issue_url,
                "error": self.error,
                "warnings": self.warnings,
            },
            indent=2,
        )


# ── Lock check (runtime) ────────────────────────────────────────────


def verify_lock_or_die(console: Console, recompute: bool = False) -> None:
    """Refuse to launch the audit if the prompt lock file doesn't match.

    When ``recompute=True``, regenerate the lock instead — the user has
    inspected the diff and is explicitly authorising the new content.

    Suppresses :func:`audit_prompt_lint.check_lock`'s success chatter so we
    don't pollute ``--json`` stdout. On failure we surface a clearer error
    via the console.
    """
    if recompute:
        # Capture stdout to keep the user-facing summary concise.
        with _redirect_stdout_to_devnull():
            _update_lock()
        return
    with _redirect_stdout_to_devnull():
        rc = _check_lock()
    if rc != 0:
        console.print(
            "[bold red]codegraph audit refuses to launch:[/] "
            "audit prompt files have drifted from the recorded hashes.\n"
            "  Possible causes: tampering, partial install, or a legitimate edit\n"
            "  that wasn't followed by a lock update.\n"
            "  After inspecting the diff, re-run with [bold]--recompute-lock[/] "
            "to authorise the new content."
        )
        raise SystemExit(2)


# ── Agent selection ────────────────────────────────────────────────


def choose_agent(
    console: Console,
    requested: Optional[str],
    yes: bool,
) -> AuditAgent:
    """Resolve the agent to use. Raises SystemExit on ambiguity or missing binary."""
    if requested is not None:
        agent = get_agent(requested)
        if agent is None:
            console.print(
                f"[bold red]Unknown agent[/] '{requested}'. "
                f"Known: {', '.join(AUDIT_AGENTS)}."
            )
            raise SystemExit(2)
        if not agent.is_installed() and agent.fallback_skill_path is None:
            console.print(
                f"[bold red]{agent.display_name} binary[/] '{agent.binary}' "
                f"not found on PATH."
            )
            raise SystemExit(2)
        return agent

    detected = [a for a in AUDIT_AGENTS.values() if a.is_installed()]
    if not detected:
        console.print(
            "[bold red]No supported coding agent detected on PATH.[/]\n"
            "Install one of: " + ", ".join(a.binary for a in AUDIT_AGENTS.values())
        )
        raise SystemExit(2)

    if yes or len(detected) == 1:
        return detected[0]

    console.print("[bold]Detected coding agents:[/]")
    for a in detected:
        console.print(f"  • {a.display_name} ({a.binary})")
    name = Prompt.ask(
        "Pick an agent",
        choices=[a.name for a in detected],
        default=detected[0].name,
    )
    return AUDIT_AGENTS[name]


# ── Prompt assembly ────────────────────────────────────────────────


def _read_template(name: str) -> str:
    """Read a template file shipped with the package."""
    path = _TEMPLATES_DIR / name
    return path.read_text(encoding="utf-8")


def _query_graph_json(uri: str, cypher: str, console: Console) -> list[dict]:
    """Run a Cypher query through the codegraph CLI; return parsed rows.

    Empty list on error (graph not loaded yet, neo4j down, etc.). The audit
    can still render — the agent will discover the missing data via its own
    queries — but the prompt won't be filtered to detected frameworks.
    """
    try:
        proc = subprocess.run(
            ["codegraph", "query", "--json", "--uri", uri, cypher],
            capture_output=True, text=True, check=False, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    return list(payload.get("rows", []))


def _detect_frameworks(
    uri: str,
    console: Console,
    repo: Optional[Path] = None,
) -> tuple[set[str], set[str]]:
    """Detect (frameworks, languages) present in the live graph.

    Returns ``(frameworks, languages)`` where frameworks is e.g.
    ``{'NestJS', 'React (TypeScript)'}`` and languages is e.g. ``{'py','ts'}``.

    With *repo* set and a ``codegraph.toml`` (or ``[tool.codegraph]``) at
    that root, the detection is scoped to the configured packages — so an
    audit launched from repo A doesn't pull in repo B's frameworks just
    because they share the same Neo4j. Without config, falls back to the
    global query (legacy behaviour).
    """
    package_filter = ""
    package_names: list[str] = []
    if repo is not None:
        try:
            from .config import load_config
            cfg = load_config(repo)
            package_names = list(cfg.packages or [])
        except Exception:
            package_names = []
    if package_names:
        # Build a literal IN clause; package names are simple repo-relative
        # paths from a config file we wrote ourselves, so no injection risk.
        joined = ", ".join(json.dumps(p) for p in package_names)
        package_filter = f" WHERE p.name IN [{joined}]"

    fw_rows = _query_graph_json(
        uri,
        f"MATCH (p:Package){package_filter} RETURN DISTINCT p.framework AS framework",
        console,
    )
    frameworks: set[str] = set()
    for row in fw_rows:
        fw = row.get("framework")
        if isinstance(fw, str) and fw and fw != "Unknown":
            frameworks.add(fw)

    if package_names:
        joined = ", ".join(json.dumps(p) for p in package_names)
        lang_query = (
            f"MATCH (f:File) WHERE f.package IN [{joined}] "
            "RETURN DISTINCT f.language AS language"
        )
    else:
        lang_query = "MATCH (f:File) RETURN DISTINCT f.language AS language"
    lang_rows = _query_graph_json(uri, lang_query, console)
    languages: set[str] = set()
    for row in lang_rows:
        lang = row.get("language")
        if isinstance(lang, str) and lang:
            languages.add(lang)

    return frameworks, languages


def _filter_inventory(frameworks: set[str], languages: set[str]) -> str:
    """Compose the per-framework inventory snippet from the templates.

    The inventory templates contain framework subsections; we keep only
    those that match a detected framework or are language-baseline. Falls
    back to the full inventory if detection produced nothing (graph not
    loaded yet).
    """
    sections: list[str] = []
    py_inv = _read_template("inventory-python.md")
    ts_inv = _read_template("inventory-typescript.md")

    has_py = "py" in languages
    has_ts = bool(languages & {"ts", "tsx"})

    if not languages:
        # No graph data — include both inventories in full and let the agent
        # filter as it goes.
        sections.append("## Python\n\n" + py_inv)
        sections.append("## TypeScript / TSX\n\n" + ts_inv)
        return "\n\n".join(sections)

    if has_py:
        sections.append("## Python\n\n" + _filter_sections(py_inv, frameworks, _PYTHON_FRAMEWORK_ALIASES))
    if has_ts:
        sections.append("## TypeScript / TSX\n\n" + _filter_sections(ts_inv, frameworks, _TS_FRAMEWORK_ALIASES))
    if not sections:
        sections.append("## Python\n\n" + py_inv)
        sections.append("## TypeScript / TSX\n\n" + ts_inv)
    return "\n\n".join(sections)


_SECTION_RE = re.compile(r"^### (.+?)$", re.MULTILINE)


def _filter_sections(inventory_text: str, detected: set[str], aliases: set[str]) -> str:
    """Keep ``### Section`` blocks whose heading matches a detected framework.

    Also always keeps the language-baseline section (the first one — labelled
    "(plain)" by convention).
    """
    headings = list(_SECTION_RE.finditer(inventory_text))
    if not headings:
        return inventory_text

    blocks: list[str] = []
    for i, m in enumerate(headings):
        title = m.group(1).strip()
        start = m.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(inventory_text)
        block = inventory_text[start:end].rstrip()

        # Always keep the baseline section (first block tagged "(plain)").
        if i == 0 and "(plain)" in title:
            blocks.append(block)
            continue

        # Keep when any detected-framework name appears in the heading, but
        # only consider headings for frameworks codegraph knows about (the
        # alias set), so unrelated headings can't be cherry-picked by an
        # adversarial inventory edit.
        keep = False
        for fw in detected:
            if fw in title and fw in aliases:
                keep = True
                break
        # Also accept the heading if it lists a framework alias literally —
        # covers SQLAlchemy / TypeORM which are dependency-driven, not
        # FrameworkType-driven.
        if not keep:
            for alias in ("SQLAlchemy", "TypeORM", "GraphQL"):
                if alias in title:
                    keep = True
                    break
        if keep:
            blocks.append(block)
    return "\n\n".join(blocks)


def _sample_files(uri: str, languages: set[str], console: Console) -> str:
    """Render the ``$SAMPLE_FILES`` block: top files per language by LOC."""
    if not languages:
        return "_No graph data available — pick representative files yourself._"
    lines: list[str] = []
    for lang in sorted(languages):
        cypher = (
            "MATCH (f:File {language:'" + lang + "'}) "
            "RETURN f.path AS path, f.loc AS loc "
            "ORDER BY f.loc DESC LIMIT 3"
        )
        rows = _query_graph_json(uri, cypher, console)
        if not rows:
            continue
        lines.append(f"**{lang}**")
        for r in rows:
            lines.append(f"- `{r.get('path')}` ({int(r.get('loc') or 0)} LOC)")
        lines.append("")
    return "\n".join(lines).strip() or "_No graph data available._"


def build_prompt(
    repo: Path,
    agent: AuditAgent,
    uri: str,
    console: Console,
) -> str:
    """Assemble the final prompt as a single string."""
    frameworks, languages = _detect_frameworks(uri, console, repo=repo)
    inventory = _filter_inventory(frameworks, languages)
    samples = _sample_files(uri, languages, console)
    cypher_patterns = _read_template("cypher-checks.md")
    template = Template(_read_template("audit-prompt.md"))
    return template.safe_substitute(
        REPO_ROOT=str(repo),
        NEO4J_URI=uri,
        AGENT_NAME=agent.name,
        EXTRACTION_INVENTORY=inventory,
        SAMPLE_FILES=samples,
        CYPHER_PATTERNS=cypher_patterns,
        INVENTORY_HASH=_lock_hash(),
    )


# ── Agent launch ───────────────────────────────────────────────────


def _write_cursor_fallback(repo: Path, prompt: str, agent: AuditAgent) -> Path:
    """Cursor (no headless mode): write the prompt as a Cursor rules file."""
    target = repo / agent.fallback_skill_path
    target.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "---\n"
        "description: codegraph extraction audit\n"
        "alwaysApply: false\n"
        "---\n\n"
        + prompt
    )
    target.write_text(body, encoding="utf-8")
    return target


def launch_agent(
    repo: Path,
    agent: AuditAgent,
    prompt: str,
    bypass: bool,
    unsafe: bool,
    timeout_sec: int,
    console: Console,
) -> int:
    """Run the agent. Returns the agent's exit code (0 on success)."""
    if agent.fallback_skill_path is not None:
        # Cursor path: write the rules file and tell the user how to invoke.
        target = _write_cursor_fallback(repo, prompt, agent)
        console.print(
            f"[yellow]ℹ {agent.display_name}[/] has no headless CLI. "
            f"The prompt was written to [cyan]{target.relative_to(repo)}[/].\n"
            "Open Cursor in this repo and start a chat — the rules file will\n"
            "be picked up automatically. Save the agent's report to "
            f"[cyan]{_REPORT_REL_PATH}[/]."
        )
        return 0

    prompt_file = repo / "codegraph-out" / f"_audit-prompt-{agent.name}.md"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(prompt, encoding="utf-8")

    argv = agent.build_argv(str(prompt_file), bypass=bypass, unsafe=unsafe)
    console.print(f"[dim]Launching:[/] {' '.join(argv)}")
    console.print(f"[dim]Timeout:[/] {timeout_sec}s")

    try:
        proc = subprocess.run(
            argv,
            cwd=str(repo),
            check=False,
            timeout=timeout_sec,
        )
    except FileNotFoundError:
        console.print(
            f"[bold red]Could not invoke {agent.binary}[/] — binary missing or "
            "not on PATH at launch time."
        )
        return 127
    except subprocess.TimeoutExpired:
        console.print(
            f"[bold red]Agent exceeded timeout ({timeout_sec}s).[/] "
            "Partial report (if any) at " + _REPORT_REL_PATH
        )
        return 124
    return int(proc.returncode)


# ── Report parsing ─────────────────────────────────────────────────


_ISSUE_HEADER_RE = re.compile(r"^##\s+Issue\s+(\d+)\s*$", re.MULTILINE)
_FIELD_RE = re.compile(r"^\*\*(?P<key>[A-Za-z]+):\*\*\s*(?P<value>.+?)\s*$", re.MULTILINE)


def parse_report(report_path: Path) -> tuple[int, list[AuditFinding]]:
    """Read the agent's markdown report and extract issue blocks."""
    if not report_path.exists():
        return 0, []
    text = report_path.read_text(encoding="utf-8")
    if "No extraction issues found" in text and "## Issue" not in text:
        return 0, []

    headers = list(_ISSUE_HEADER_RE.finditer(text))
    findings: list[AuditFinding] = []
    for i, h in enumerate(headers):
        idx = int(h.group(1))
        start = h.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        block = text[start:end].strip()
        category = _extract_field(block, "Category") or "UNKNOWN"
        severity = _extract_field(block, "Severity") or "unknown"
        construct = _extract_field(block, "Construct") or ""
        findings.append(AuditFinding(
            index=idx,
            category=category.upper().split("|")[0].strip(),
            severity=severity.lower().strip(),
            construct=construct,
            raw_block=block,
        ))
    return len(findings), findings


def _extract_field(block: str, key: str) -> Optional[str]:
    for m in _FIELD_RE.finditer(block):
        if m.group("key").lower() == key.lower():
            return m.group("value")
    return None


# ── GitHub-issue path ──────────────────────────────────────────────


def create_github_issue(
    repo: Path,
    report_path: Path,
    issues_found: int,
    console: Console,
) -> Optional[str]:
    """Shell out to ``gh issue create``; return the new issue URL on success."""
    if shutil.which("gh") is None:
        console.print(
            "[yellow]gh CLI not found.[/] Skipping issue creation. "
            "Install: see GitHub CLI docs."
        )
        return None
    title = f"codegraph audit: {issues_found} extraction "
    title += "issue" if issues_found == 1 else "issues"
    title += " found"
    argv = [
        "gh", "issue", "create",
        "--title", title,
        "--body-file", str(report_path),
        "--label", "codegraph-audit",
    ]
    try:
        proc = subprocess.run(
            argv,
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        console.print(f"[bold red]gh issue create failed:[/] {exc}")
        return None
    if proc.returncode != 0:
        # Common case: label doesn't exist yet. Retry without --label.
        if "could not add label" in proc.stderr.lower() or "label" in proc.stderr.lower():
            console.print(
                "[yellow]Label 'codegraph-audit' missing — retrying without it.[/]"
            )
            return _retry_without_label(repo, title, report_path, console)
        console.print(f"[bold red]gh issue create failed:[/] {proc.stderr.strip()}")
        return None
    url = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else None
    return url


def _retry_without_label(
    repo: Path, title: str, report_path: Path, console: Console
) -> Optional[str]:
    argv = [
        "gh", "issue", "create",
        "--title", title,
        "--body-file", str(report_path),
    ]
    try:
        proc = subprocess.run(
            argv, cwd=str(repo), capture_output=True, text=True,
            check=False, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        console.print(f"[bold red]gh issue create retry failed:[/] {exc}")
        return None
    if proc.returncode != 0:
        console.print(f"[bold red]gh issue create retry failed:[/] {proc.stderr.strip()}")
        return None
    return proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else None


# ── Top-level entry point ──────────────────────────────────────────


def run_audit(
    repo: Path,
    uri: str,
    agent_name: Optional[str],
    bypass: bool,
    unsafe: bool,
    gh_issue: Optional[bool],
    print_prompt_only: bool,
    yes: bool,
    timeout_sec: int,
    recompute_lock: bool,
    console: Optional[Console],
) -> AuditReport:
    """Execute one audit run; return an :class:`AuditReport`.

    ``console=None`` runs in quiet mode (no Rich output) — used when the
    caller wants pure JSON on stdout.
    """
    if console is None:
        console = Console(quiet=True)
    verify_lock_or_die(console, recompute=recompute_lock)

    # `--recompute-lock` is a maintenance action — the user just edited
    # templates and wants to refresh the .lock file. Don't go on to launch
    # an agent; that would make the CLI hang for minutes on a flag whose
    # name doesn't suggest "and also run the audit".
    if recompute_lock:
        console.print(
            "[green]✓[/] regenerated audit prompt lock at "
            f"{Path(__file__).resolve().parent / 'templates' / 'audit' / '.lock'}"
        )
        return AuditReport(
            ok=True,
            agent="(none)",
            repo=str(repo),
            report_path="(lock recomputed)",
            issues_found=0,
        )

    agent = choose_agent(console, agent_name, yes=yes)
    prompt = build_prompt(repo, agent, uri, console)

    if print_prompt_only:
        # Side-channel: when called from the CLI with --print-prompt-only,
        # cli.py reads this attribute via the report.report_path field.
        # Here we just dump to stdout and return a sentinel report.
        sys.stdout.write(prompt)
        return AuditReport(
            ok=True,
            agent=agent.name,
            repo=str(repo),
            report_path="(stdout)",
            issues_found=0,
        )

    report_path = repo / _REPORT_REL_PATH
    # Remove stale report so we don't accidentally credit the agent for an
    # old run.
    if report_path.exists():
        report_path.unlink()

    rc = launch_agent(
        repo=repo,
        agent=agent,
        prompt=prompt,
        bypass=bypass,
        unsafe=unsafe,
        timeout_sec=timeout_sec,
        console=console,
    )
    warnings: list[str] = []
    if rc not in (0, 124):
        warnings.append(f"agent exited non-zero: {rc}")

    issues_found, findings = parse_report(report_path)

    gh_url: Optional[str] = None
    should_open = gh_issue
    if should_open is None and not yes and issues_found > 0:
        should_open = Confirm.ask(
            f"Create a GitHub issue from this report ({issues_found} findings)?",
            default=False,
        )
    if should_open and issues_found > 0:
        gh_url = create_github_issue(repo, report_path, issues_found, console)

    return AuditReport(
        ok=(rc == 0 and (issues_found == 0 or gh_url is not None or not should_open)),
        agent=agent.name,
        repo=str(repo),
        report_path=str(report_path),
        issues_found=issues_found,
        findings=findings,
        gh_issue_url=gh_url,
        warnings=warnings,
    )
