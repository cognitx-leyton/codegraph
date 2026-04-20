"""Detect drift between live .claude/commands/ files and their bundled templates.

Only checks the 5 *literal* templates (no ``string.Template`` variables).
The stats section between ``<!-- codegraph:stats-begin -->`` / ``-end -->``
markers is normalised so per-repo counts don't cause false failures.
"""

from __future__ import annotations

import re
from importlib.resources import files as _pkg_files
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # tests/ -> codegraph/ -> repo root
_LIVE_DIR = _REPO_ROOT / ".claude" / "commands"
_TEMPLATE_DIR = _pkg_files("codegraph") / "templates" / "claude" / "commands"

_STATS_RE = re.compile(
    r"(<!-- codegraph:stats-begin -->\r?\n).*?(\r?\n<!-- codegraph:stats-end -->)",
    re.DOTALL,
)

_PLACEHOLDER = r"\g<1>STATS_PLACEHOLDER\g<2>"

_LITERAL_TEMPLATES = [
    "arch-check.md",
    "blast-radius.md",
    "graph.md",
    "trace-endpoint.md",
    "who-owns.md",
]


def _normalize(text: str) -> str:
    """Replace the stats section content with a fixed placeholder."""
    return _STATS_RE.sub(_PLACEHOLDER, text)


@pytest.mark.parametrize("filename", _LITERAL_TEMPLATES)
def test_template_matches_live(filename: str) -> None:
    live_path = _LIVE_DIR / filename
    template_path = _TEMPLATE_DIR / filename

    assert live_path.exists(), f"live file missing: {live_path}"

    live_text = _normalize(live_path.read_text(encoding="utf-8"))
    template_text = _normalize(template_path.read_text(encoding="utf-8"))

    assert live_text == template_text, (
        f"{filename} has drifted from its bundled template.\n"
        f"  live:     {live_path}\n"
        f"  template: {template_path}\n"
        f"Run: diff <(cat .claude/commands/{filename}) "
        f"<(cat codegraph/codegraph/templates/claude/commands/{filename})"
    )
