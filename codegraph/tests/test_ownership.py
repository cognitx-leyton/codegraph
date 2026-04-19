"""Tests for :mod:`codegraph.ownership`."""
from __future__ import annotations

from pathlib import Path

from codegraph.ownership import _parse_codeowners


def test_parse_codeowners_crlf(tmp_path: Path) -> None:
    """CRLF line endings in CODEOWNERS must parse correctly."""
    co = tmp_path / "CODEOWNERS"
    co.write_bytes(
        b"*.py @backend-team\r\n"
        b"/docs/ @docs-team\r\n"
        b"# comment line\r\n"
        b"*.ts @frontend-team @design-team\r\n"
    )
    rules = _parse_codeowners(co)
    assert len(rules) == 3
    assert rules[0] == ("*.py", ["@backend-team"])
    assert rules[1] == ("/docs/", ["@docs-team"])
    assert rules[2] == ("*.ts", ["@frontend-team", "@design-team"])
