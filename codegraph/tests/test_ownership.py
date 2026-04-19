"""Tests for :mod:`codegraph.ownership`."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from codegraph.ownership import _parse_codeowners, collect_ownership


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


# --- Issue #167: deterministic contributor ordering on tie ---

def test_contributors_deterministic_on_tie(tmp_path: Path) -> None:
    """Contributors with equal commit counts sort alphabetically by email."""
    git_log = (
        "__COMMIT__aaa|zeta@example.com|Zeta|1000000\n"
        "src/app.py\n"
        "\n"
        "__COMMIT__bbb|alpha@example.com|Alpha|1000001\n"
        "src/app.py\n"
    )
    proc = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=git_log, stderr="",
    )
    with patch("codegraph.ownership.subprocess.run", return_value=proc):
        result = collect_ownership(tmp_path, {"src/app.py"})

    contribs = result["contributors"]
    emails = [c["email"] for c in contribs if c["path"] == "src/app.py"]
    # Both have 1 commit — alphabetical order must win
    assert emails == ["alpha@example.com", "zeta@example.com"]


# --- Issue #166: non-zero git exit code returns empty ---

def test_collect_ownership_git_nonzero_exit(tmp_path: Path) -> None:
    """Non-zero git exit code must return empty dict, not silently continue."""
    proc = subprocess.CompletedProcess(
        args=[], returncode=128, stdout="", stderr="fatal: not a git repository",
    )
    with patch("codegraph.ownership.subprocess.run", return_value=proc):
        result = collect_ownership(tmp_path, {"src/app.py"})
    assert result == {}


# --- Issue #159: warnings on silent failures ---

def test_collect_ownership_logs_on_os_error(tmp_path: Path, caplog) -> None:
    """OSError during subprocess.run must log a warning."""
    with patch(
        "codegraph.ownership.subprocess.run",
        side_effect=OSError("git not found"),
    ):
        result = collect_ownership(tmp_path, {"src/app.py"})
    assert result == {}
    assert "git log failed" in caplog.text


def test_collect_ownership_logs_malformed_commit(tmp_path: Path, caplog) -> None:
    """Malformed commit header must log a warning and skip the commit."""
    git_log = (
        "__COMMIT__badline_no_pipes\n"
        "src/app.py\n"
    )
    proc = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=git_log, stderr="",
    )
    with patch("codegraph.ownership.subprocess.run", return_value=proc):
        result = collect_ownership(tmp_path, {"src/app.py"})

    assert "malformed git log line" in caplog.text
    # The file should not appear in contributors since the commit was skipped
    assert result["contributors"] == []


# --- Issue #158: CODEOWNERS encoding ---

def test_parse_codeowners_non_utf8(tmp_path: Path, caplog) -> None:
    """Non-UTF-8 CODEOWNERS must warn and return empty, not silently corrupt."""
    co = tmp_path / "CODEOWNERS"
    co.write_bytes(b"*.py @team-\xff\xfe-bad\n")
    rules = _parse_codeowners(co)
    assert rules == []
    assert "cannot decode" in caplog.text
