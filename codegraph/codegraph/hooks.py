"""Git hook management — install/uninstall codegraph post-commit and post-checkout hooks.

Ported from graphify's ``hooks.py`` with attribution, adapted to invoke
``codegraph index`` via subprocess (shell-level, portable across pipx / uv /
venv / system installs).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

_HOOK_MARKER = "# codegraph-hook-start"
_HOOK_MARKER_END = "# codegraph-hook-end"
_CHECKOUT_MARKER = "# codegraph-checkout-hook-start"
_CHECKOUT_MARKER_END = "# codegraph-checkout-hook-end"

_PYTHON_DETECT = """\
# Detect the correct Python interpreter (handles pipx, venv, system installs)
CODEGRAPH_BIN=$(command -v codegraph 2>/dev/null)
if [ -n "$CODEGRAPH_BIN" ]; then
    case "$CODEGRAPH_BIN" in
        *.exe) _SHEBANG="" ;;
        *)     _SHEBANG=$(head -1 "$CODEGRAPH_BIN" | sed 's/^#![[:space:]]*//') ;;
    esac
    case "$_SHEBANG" in
        */env\\ *) CODEGRAPH_PYTHON="${_SHEBANG#*/env }" ;;
        *)         CODEGRAPH_PYTHON="$_SHEBANG" ;;
    esac
    # Allowlist: only keep characters valid in a filesystem path to prevent
    # injection if the shebang contains shell metacharacters
    case "$CODEGRAPH_PYTHON" in
        *[!a-zA-Z0-9/_.@-]*) CODEGRAPH_PYTHON="" ;;
    esac
    if [ -n "$CODEGRAPH_PYTHON" ] && ! "$CODEGRAPH_PYTHON" -c "import codegraph" 2>/dev/null; then
        CODEGRAPH_PYTHON=""
    fi
fi
# Fall back: try python3, then python (Windows has no python3 shim)
if [ -z "$CODEGRAPH_PYTHON" ]; then
    if command -v python3 >/dev/null 2>&1 && python3 -c "import codegraph" 2>/dev/null; then
        CODEGRAPH_PYTHON="python3"
    elif command -v python >/dev/null 2>&1 && python -c "import codegraph" 2>/dev/null; then
        CODEGRAPH_PYTHON="python"
    else
        exit 0
    fi
fi
"""

_HOOK_SCRIPT = """\
# codegraph-hook-start
# Auto-rebuilds the knowledge graph after each commit (code files only).
# Installed by: codegraph hook install

# Skip during rebase/merge/cherry-pick to avoid blocking --continue
GIT_DIR=$(git rev-parse --git-dir 2>/dev/null)
[ -d "$GIT_DIR/rebase-merge" ] && exit 0
[ -d "$GIT_DIR/rebase-apply" ] && exit 0
[ -f "$GIT_DIR/MERGE_HEAD" ] && exit 0
[ -f "$GIT_DIR/CHERRY_PICK_HEAD" ] && exit 0

CHANGED=$(git diff --name-only HEAD~1 HEAD 2>/dev/null || git diff --name-only HEAD 2>/dev/null)
if [ -z "$CHANGED" ]; then
    exit 0
fi

""" + _PYTHON_DETECT + """\
echo "[codegraph hook] Rebuilding graph (--since HEAD~1)..."
"$CODEGRAPH_PYTHON" -m codegraph.cli index . --since HEAD~1 --json >/dev/null 2>&1
STATUS=$?
if [ $STATUS -ne 0 ]; then
    echo "[codegraph hook] Rebuild failed (exit $STATUS)"
    exit $STATUS
fi
# codegraph-hook-end
"""

_CHECKOUT_SCRIPT = """\
# codegraph-checkout-hook-start
# Auto-rebuilds the knowledge graph (code only) when switching branches.
# Installed by: codegraph hook install

PREV_HEAD=$1
NEW_HEAD=$2
BRANCH_SWITCH=$3

# Only run on branch switches, not file checkouts
if [ "$BRANCH_SWITCH" != "1" ]; then
    exit 0
fi

# Skip during rebase/merge/cherry-pick
GIT_DIR=$(git rev-parse --git-dir 2>/dev/null)
[ -d "$GIT_DIR/rebase-merge" ] && exit 0
[ -d "$GIT_DIR/rebase-apply" ] && exit 0
[ -f "$GIT_DIR/MERGE_HEAD" ] && exit 0
[ -f "$GIT_DIR/CHERRY_PICK_HEAD" ] && exit 0

""" + _PYTHON_DETECT + """\
echo "[codegraph hook] Branch switched - rebuilding graph..."
"$CODEGRAPH_PYTHON" -m codegraph.cli index . --since "$PREV_HEAD" --json >/dev/null 2>&1
STATUS=$?
if [ $STATUS -ne 0 ]; then
    echo "[codegraph hook] Rebuild failed (exit $STATUS)"
    exit $STATUS
fi
# codegraph-checkout-hook-end
"""


def _git_root(path: Path) -> Path | None:
    """Walk up to find .git directory."""
    current = path.resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def _hooks_dir(root: Path) -> Path:
    """Return the git hooks directory, respecting core.hooksPath if set (e.g. Husky)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "config", "core.hooksPath"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            custom = result.stdout.strip()
            if custom:
                p = Path(custom)
                if not p.is_absolute():
                    p = root / p
                p.mkdir(parents=True, exist_ok=True)
                return p
    except (OSError, FileNotFoundError):
        pass
    d = root / ".git" / "hooks"
    d.mkdir(exist_ok=True)
    return d


def _install_hook(hooks_dir: Path, name: str, script: str, marker: str) -> str:
    """Install a single git hook, appending if an existing hook is present."""
    hook_path = hooks_dir / name
    if hook_path.exists():
        content = hook_path.read_text(encoding="utf-8")
        if marker in content:
            return f"already installed at {hook_path}"
        hook_path.write_text(
            content.rstrip() + "\n\n" + script, encoding="utf-8", newline="\n",
        )
        return f"appended to existing {name} hook at {hook_path}"
    hook_path.write_text("#!/bin/sh\n" + script, encoding="utf-8", newline="\n")
    hook_path.chmod(0o755)
    return f"installed at {hook_path}"


def _uninstall_hook(
    hooks_dir: Path, name: str, marker: str, marker_end: str,
) -> str:
    """Remove codegraph section from a git hook using start/end markers."""
    hook_path = hooks_dir / name
    if not hook_path.exists():
        return f"no {name} hook found - nothing to remove."
    content = hook_path.read_text(encoding="utf-8")
    if marker not in content:
        return f"codegraph hook not found in {name} - nothing to remove."
    new_content = re.sub(
        rf"{re.escape(marker)}.*?{re.escape(marker_end)}\n?",
        "",
        content,
        flags=re.DOTALL,
    ).strip()
    if not new_content or new_content in ("#!/bin/bash", "#!/bin/sh"):
        hook_path.unlink()
        return f"removed {name} hook at {hook_path}"
    hook_path.write_text(new_content + "\n", encoding="utf-8", newline="\n")
    return f"codegraph removed from {name} at {hook_path} (other hook content preserved)"


def install(path: Path = Path(".")) -> str:
    """Install codegraph post-commit and post-checkout hooks in the nearest git repo."""
    root = _git_root(path)
    if root is None:
        raise RuntimeError(f"No git repository found at or above {path.resolve()}")

    hooks = _hooks_dir(root)
    commit_msg = _install_hook(hooks, "post-commit", _HOOK_SCRIPT, _HOOK_MARKER)
    checkout_msg = _install_hook(
        hooks, "post-checkout", _CHECKOUT_SCRIPT, _CHECKOUT_MARKER,
    )
    return f"post-commit: {commit_msg}\npost-checkout: {checkout_msg}"


def uninstall(path: Path = Path(".")) -> str:
    """Remove codegraph post-commit and post-checkout hooks."""
    root = _git_root(path)
    if root is None:
        raise RuntimeError(f"No git repository found at or above {path.resolve()}")

    hooks = _hooks_dir(root)
    commit_msg = _uninstall_hook(
        hooks, "post-commit", _HOOK_MARKER, _HOOK_MARKER_END,
    )
    checkout_msg = _uninstall_hook(
        hooks, "post-checkout", _CHECKOUT_MARKER, _CHECKOUT_MARKER_END,
    )
    return f"post-commit: {commit_msg}\npost-checkout: {checkout_msg}"


def status(path: Path = Path(".")) -> str:
    """Check if codegraph hooks are installed."""
    root = _git_root(path)
    if root is None:
        return "Not in a git repository."
    hooks = _hooks_dir(root)

    def _check(name: str, marker: str) -> str:
        p = hooks / name
        if not p.exists():
            return "not installed"
        if marker in p.read_text(encoding="utf-8"):
            return "installed"
        return "not installed (hook exists but codegraph not found)"

    commit = _check("post-commit", _HOOK_MARKER)
    checkout = _check("post-checkout", _CHECKOUT_MARKER)
    return f"post-commit: {commit}\npost-checkout: {checkout}"
