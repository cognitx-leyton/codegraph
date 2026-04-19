"""Tests for :mod:`codegraph.ownership`."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from codegraph.ownership import (
    _EMPTY_OWNERSHIP,
    _co_pattern_match,
    _match_codeowners,
    _parse_codeowners,
    collect_ownership,
)


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
    """Non-zero git exit code must return empty ownership dict, not silently continue."""
    proc = subprocess.CompletedProcess(
        args=[], returncode=128, stdout="", stderr="fatal: not a git repository",
    )
    with patch("codegraph.ownership.subprocess.run", return_value=proc):
        result = collect_ownership(tmp_path, {"src/app.py"})
    assert result == dict(_EMPTY_OWNERSHIP)


# --- Issue #159: warnings on silent failures ---

def test_collect_ownership_logs_on_os_error(tmp_path: Path, caplog) -> None:
    """OSError during subprocess.run must log a warning."""
    with patch(
        "codegraph.ownership.subprocess.run",
        side_effect=OSError("git not found"),
    ):
        result = collect_ownership(tmp_path, {"src/app.py"})
    assert result == dict(_EMPTY_OWNERSHIP)
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


# --- Issue #172: CODEOWNERS pattern matching coverage ---

@pytest.mark.parametrize(
    ("pat", "path", "expected"),
    [
        pytest.param("*.py", "src/models/user.py", True, id="bare-glob-match"),
        pytest.param("*.py", "src/models/user.ts", False, id="bare-glob-no-match"),
        pytest.param("/docs/", "docs/readme.md", True, id="rooted-match"),
        pytest.param("/docs/", "src/docs/readme.md", False, id="rooted-no-match"),
        pytest.param("src/", "src/app.ts", True, id="path-pattern"),
        pytest.param("**/*.ts", "src/deep/file.ts", True, id="double-star"),
    ],
)
def test_co_pattern_match_cases(pat: str, path: str, expected: bool) -> None:
    """_co_pattern_match must handle bare globs, rooted, path, and ** patterns."""
    assert _co_pattern_match(pat, path) is expected


def test_match_codeowners_last_rule_wins() -> None:
    """Last matching rule wins (CODEOWNERS semantics)."""
    rules = [("*.py", ["@general"]), ("src/*.py", ["@src-team"])]
    assert _match_codeowners("src/app.py", rules) == ["@src-team"]


def test_match_codeowners_no_matching_rule() -> None:
    """No matching rule returns an empty list."""
    rules = [("*.go", ["@go-team"])]
    assert _match_codeowners("src/app.py", rules) == []


# --- Issue #175: rooted CODEOWNERS pattern false-positive on sibling paths ---

@pytest.mark.parametrize(
    ("pat", "path", "expected"),
    [
        pytest.param("/docs", "docs/readme.md", True, id="rooted-no-slash-child"),
        pytest.param("/docs", "docs-internal/readme.md", False, id="rooted-no-slash-sibling"),
        pytest.param("/docs/", "docs/readme.md", True, id="rooted-slash-child"),
        pytest.param("/docs/", "docs-internal/readme.md", False, id="rooted-slash-sibling"),
    ],
)
def test_co_pattern_match_rooted_no_sibling_false_positive(
    pat: str, path: str, expected: bool,
) -> None:
    """Rooted CODEOWNERS patterns must not false-positive match sibling directories."""
    assert _co_pattern_match(pat, path) is expected


def test_collect_ownership_subprocess_timeout(tmp_path: Path, caplog) -> None:
    """subprocess.TimeoutExpired must return empty ownership dict and log a warning."""
    with patch(
        "codegraph.ownership.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="git", timeout=120),
    ):
        result = collect_ownership(tmp_path, {"src/app.py"})
    assert result == dict(_EMPTY_OWNERSHIP)
    assert "git log failed" in caplog.text


def test_collect_ownership_empty_git_log(tmp_path: Path) -> None:
    """Empty git log stdout must return dict with all keys but empty values."""
    proc = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr="",
    )
    with patch("codegraph.ownership.subprocess.run", return_value=proc):
        result = collect_ownership(tmp_path, {"src/app.py"})
    assert result["authors"] == []
    assert result["teams"] == []
    assert result["last_modified"] == []
    assert result["contributors"] == []
    assert result["owned_by"] == []
