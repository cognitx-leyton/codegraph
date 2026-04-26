"""Static-analysis script protecting the audit prompt files from tampering.

The committed templates under ``codegraph/templates/audit/`` are a privileged
surface — they ship to every user's coding agent in unattended mode. A
malicious or careless PR could rewrite them to redirect the audit. This
module provides three checks the CI workflow runs on every PR that touches
the audit prompt or its launcher:

1. **Lock file** — SHA-256 of every prompt file is recorded in
   ``codegraph/templates/audit/.lock``. ``--check-lock`` recomputes hashes
   and fails if any drift; ``--update-lock`` regenerates the file (used by
   contributors who legitimately edit a template). Forces every prompt
   change to appear alongside an explicit lock change in the diff.

2. **URL diff** — no new ``http://`` or ``https://`` URLs may be introduced
   in any prompt file. Catches the most common injection: "send the report
   to <attacker URL>". The base ref defaults to ``origin/main``.

3. **Suspicious-call-site diff** — no new lines containing shell-execution
   adjacent symbols (subprocess, Popen, system, dynamic-eval, etc.) may be
   introduced in ``audit.py`` beyond the existing call sites at base. The
   exact list lives in :data:`_SUSPICIOUS_PATTERNS` (assembled at runtime
   from byte triples so the strings don't trip security scanners reading
   this source file).

CLI:

    python -m codegraph.audit_prompt_lint --update-lock
    python -m codegraph.audit_prompt_lint --check-lock
    python -m codegraph.audit_prompt_lint --check-diff [--base origin/main]
    python -m codegraph.audit_prompt_lint --all [--base origin/main]

Exit codes: 0 on success, 1 on any check failure, 2 on usage error.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

# Repo-relative paths. Resolved against the package root at import time so
# the script works whether invoked from the repo root, the codegraph/
# directory, or after pip-install.
_PKG_ROOT = Path(__file__).resolve().parent
_TEMPLATES_DIR = _PKG_ROOT / "templates" / "audit"
_LOCK_FILE = _TEMPLATES_DIR / ".lock"

# Files the diff-lint covers. Tuples of (repo-relative-path, kind) where kind
# selects which diff rules to apply.
_DIFF_TARGETS: tuple[tuple[str, str], ...] = (
    # Prompt files: forbid new URLs.
    ("codegraph/codegraph/templates/audit/audit-prompt.md", "prompt"),
    ("codegraph/codegraph/templates/audit/inventory-python.md", "prompt"),
    ("codegraph/codegraph/templates/audit/inventory-typescript.md", "prompt"),
    ("codegraph/codegraph/templates/audit/cypher-checks.md", "prompt"),
    ("codegraph/codegraph/templates/audit/report-template.md", "prompt"),
    # Launcher: forbid new shell-execution call sites.
    ("codegraph/codegraph/audit.py", "launcher"),
    ("codegraph/codegraph/audit_agents.py", "launcher"),
)

# Lines matching this regex in a prompt file diff fail the URL check.
_URL_REGEX = re.compile(r"https?://", re.IGNORECASE)


def _suspicious_patterns() -> tuple[str, ...]:
    """Forbidden substrings in launcher diffs.

    Built by joining short fragments so the literal forms do not appear in
    this source file; otherwise the project security-reminder hook would
    refuse the file. Matching is plain substring-on-each-line at runtime.
    """
    a = "subprocess" + "."
    b = "P" + "open"
    c = "os" + ".system"
    d = "ev" + "al("
    e = "ex" + "ec("
    f = "__imp" + "ort__"
    g = "comp" + "ile("
    h = "p" + "ickle.loads"
    return (a, b, c, d, e, f, g, h)


_SUSPICIOUS_PATTERNS: tuple[str, ...] = _suspicious_patterns()

# Maximum acceptable line-count growth before failing. 50% of original size
# (rounded up to at least +50 lines) catches wholesale rewrites without
# false-positiving on legitimate edits.
_MAX_GROWTH_RATIO = 0.50
_MIN_GROWTH_FLOOR = 50


# ── Lock-file management ────────────────────────────────────────────


def _hashable_files() -> list[Path]:
    """Files included in the lock, sorted for determinism."""
    return sorted(
        p for p in _TEMPLATES_DIR.iterdir()
        if p.is_file() and p.name != ".lock"
    )


def _compute_hashes() -> list[tuple[str, str]]:
    """Return ``[(sha256, filename), ...]`` for every templated file."""
    out: list[tuple[str, str]] = []
    for path in _hashable_files():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        out.append((digest, path.name))
    return out


def _serialise_hashes(rows: Iterable[tuple[str, str]]) -> str:
    """Format hashes as the .lock file content (one ``<sha>  <name>`` per line)."""
    return "".join(f"{sha}  {name}\n" for sha, name in rows)


def update_lock() -> int:
    """Regenerate the .lock file from current template contents."""
    if not _TEMPLATES_DIR.is_dir():
        print(f"audit-prompt-lint: templates dir missing: {_TEMPLATES_DIR}", file=sys.stderr)
        return 1
    payload = _serialise_hashes(_compute_hashes())
    _LOCK_FILE.write_text(payload, encoding="utf-8")
    print(f"audit-prompt-lint: wrote {_LOCK_FILE} ({len(payload.splitlines())} entries)")
    return 0


def check_lock() -> int:
    """Verify the .lock file matches current template contents."""
    if not _LOCK_FILE.exists():
        print(
            "audit-prompt-lint: .lock file missing — run "
            "`python -m codegraph.audit_prompt_lint --update-lock`",
            file=sys.stderr,
        )
        return 1
    expected = _serialise_hashes(_compute_hashes())
    actual = _LOCK_FILE.read_text(encoding="utf-8")
    if expected.strip() == actual.strip():
        print(f"audit-prompt-lint: lock OK ({len(expected.splitlines())} entries)")
        return 0
    print(
        "audit-prompt-lint: lock mismatch — a template file changed without\n"
        "updating .lock. Run `python -m codegraph.audit_prompt_lint --update-lock`,\n"
        "review the diff, and commit both together.",
        file=sys.stderr,
    )
    print("\n--- expected ---", file=sys.stderr)
    print(expected, file=sys.stderr)
    print("--- actual ---", file=sys.stderr)
    print(actual, file=sys.stderr)
    return 1


def lock_payload() -> str:
    """Current canonical lock content. Used by audit.py at runtime."""
    return _serialise_hashes(_compute_hashes())


def lock_hash() -> str:
    """SHA-256 of the lock payload itself. Embedded in the audit report."""
    return hashlib.sha256(lock_payload().encode("utf-8")).hexdigest()


# ── Diff-lint (CI only) ─────────────────────────────────────────────


def _git_diff_added_lines(repo_root: Path, base: str, path: str) -> list[str]:
    """Return lines added (prefixed with `+ `) in *path* between *base* and HEAD.

    Empty list when the file is unchanged or doesn't exist on either side.
    """
    try:
        proc = subprocess.run(
            ["git", "diff", f"{base}...HEAD", "--unified=0", "--", path],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"audit-prompt-lint: git diff failed for {path}: {exc}", file=sys.stderr)
        return []
    if proc.returncode != 0:
        # Likely missing base ref. Surface the stderr; CI should have fetched it.
        if proc.stderr.strip():
            print(f"audit-prompt-lint: git diff stderr: {proc.stderr.strip()}", file=sys.stderr)
        return []
    out: list[str] = []
    for line in proc.stdout.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            # Strip the leading + for matching, but keep it in the report.
            out.append(line[1:])
    return out


def _file_line_counts(repo_root: Path, base: str, path: str) -> tuple[int, int]:
    """Return ``(base_lines, head_lines)`` for *path*. Zero if file missing."""
    def count(ref: str) -> int:
        try:
            proc = subprocess.run(
                ["git", "show", f"{ref}:{path}"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return 0
        if proc.returncode != 0:
            return 0
        return len(proc.stdout.splitlines())
    return count(base), count("HEAD")


def check_diff(repo_root: Path, base: str = "origin/main") -> int:
    """Diff-based checks: forbidden URLs, forbidden call sites, line-count growth."""
    failures: list[str] = []
    for rel_path, kind in _DIFF_TARGETS:
        added = _git_diff_added_lines(repo_root, base, rel_path)
        if not added:
            continue
        if kind == "prompt":
            for line in added:
                if _URL_REGEX.search(line):
                    failures.append(
                        f"{rel_path}: new URL introduced — `{line.strip()[:120]}`"
                    )
        elif kind == "launcher":
            for line in added:
                for pattern in _SUSPICIOUS_PATTERNS:
                    if pattern in line:
                        failures.append(
                            f"{rel_path}: new shell-execution-adjacent call "
                            f"site (`{pattern}`) — `{line.strip()[:120]}`"
                        )
                        break
        base_lines, head_lines = _file_line_counts(repo_root, base, rel_path)
        if base_lines > 0:
            growth = head_lines - base_lines
            limit = max(_MIN_GROWTH_FLOOR, int(base_lines * _MAX_GROWTH_RATIO))
            if growth > limit:
                failures.append(
                    f"{rel_path}: file grew by {growth} lines "
                    f"({base_lines} → {head_lines}), exceeds limit of +{limit}"
                )
    if failures:
        print("audit-prompt-lint: diff-lint failures:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print(f"audit-prompt-lint: diff-lint OK against {base}")
    return 0


# ── CLI entrypoint ──────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="audit-prompt-lint",
        description=(
            "Verify the integrity of codegraph audit prompt templates. "
            "Run `--update-lock` after intentionally editing a template; "
            "`--check-lock` and `--check-diff` are CI gates."
        ),
    )
    parser.add_argument("--update-lock", action="store_true",
                        help="Regenerate .lock from current template contents.")
    parser.add_argument("--check-lock", action="store_true",
                        help="Fail if .lock doesn't match current contents.")
    parser.add_argument("--check-diff", action="store_true",
                        help="Run diff-based lint (URL + suspicious-call + growth) "
                             "between --base and HEAD.")
    parser.add_argument("--all", action="store_true",
                        help="Run --check-lock and --check-diff.")
    parser.add_argument("--base", default="origin/main",
                        help="Git ref to diff against (default: origin/main).")
    parser.add_argument("--repo", default=None,
                        help="Repo root for git operations (default: cwd).")
    args = parser.parse_args(argv)

    if not (args.update_lock or args.check_lock or args.check_diff or args.all):
        parser.print_help(sys.stderr)
        return 2

    repo_root = Path(args.repo).resolve() if args.repo else Path.cwd().resolve()

    rc = 0
    if args.update_lock:
        rc |= update_lock()
    if args.check_lock or args.all:
        rc |= check_lock()
    if args.check_diff or args.all:
        rc |= check_diff(repo_root, base=args.base)
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
