"""Tests for :mod:`codegraph.audit_prompt_lint` — lock & diff lint."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from codegraph import audit_prompt_lint as lint


# ── Lock-file management ────────────────────────────────────────────


def test_compute_hashes_is_deterministic() -> None:
    """Same templates → same hash list, regardless of call order."""
    a = lint._compute_hashes()
    b = lint._compute_hashes()
    assert a == b
    # Hashes should look like SHA-256 hex.
    assert all(len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)
               for sha, _ in a)


def test_serialise_hashes_format() -> None:
    """Each line is `<sha>  <name>\\n`, SHA first, two spaces, name, newline."""
    payload = lint._serialise_hashes([("abc123", "foo.md"), ("def456", "bar.md")])
    assert payload == "abc123  foo.md\ndef456  bar.md\n"


def test_check_lock_passes_on_committed_state(capsys) -> None:
    """The .lock file shipped in the repo matches its templates."""
    rc = lint.check_lock()
    assert rc == 0


def test_lock_payload_matches_lock_file() -> None:
    """``lock_payload()`` is byte-equal to the on-disk .lock file."""
    on_disk = lint._LOCK_FILE.read_text(encoding="utf-8")
    assert lint.lock_payload() == on_disk


def test_lock_hash_is_deterministic_sha256() -> None:
    """``lock_hash()`` returns sha256 of the payload."""
    expected = hashlib.sha256(lint.lock_payload().encode("utf-8")).hexdigest()
    assert lint.lock_hash() == expected


def test_check_lock_fails_when_template_modified(monkeypatch, tmp_path, capsys) -> None:
    """Tampering with a template (in a temp tree) must fail check_lock."""
    # Copy templates + lock to tmp, point lint at it.
    tmp_templates = tmp_path / "templates" / "audit"
    tmp_templates.mkdir(parents=True)
    for src in lint._TEMPLATES_DIR.iterdir():
        (tmp_templates / src.name).write_bytes(src.read_bytes())
    monkeypatch.setattr(lint, "_TEMPLATES_DIR", tmp_templates)
    monkeypatch.setattr(lint, "_LOCK_FILE", tmp_templates / ".lock")
    # Sanity: should pass before tampering.
    assert lint.check_lock() == 0
    # Tamper.
    tampered = tmp_templates / "audit-prompt.md"
    tampered.write_text(tampered.read_text(encoding="utf-8") + "\nINJECTED\n",
                        encoding="utf-8")
    # Now it must fail.
    assert lint.check_lock() == 1


def test_update_lock_round_trips(monkeypatch, tmp_path) -> None:
    """update_lock followed by check_lock = pass, even after edits."""
    tmp_templates = tmp_path / "templates" / "audit"
    tmp_templates.mkdir(parents=True)
    for src in lint._TEMPLATES_DIR.iterdir():
        (tmp_templates / src.name).write_bytes(src.read_bytes())
    monkeypatch.setattr(lint, "_TEMPLATES_DIR", tmp_templates)
    monkeypatch.setattr(lint, "_LOCK_FILE", tmp_templates / ".lock")
    # Edit a file, regenerate, verify.
    target = tmp_templates / "audit-prompt.md"
    target.write_text(target.read_text(encoding="utf-8") + "\nupdated\n",
                      encoding="utf-8")
    assert lint.update_lock() == 0
    assert lint.check_lock() == 0


# ── Suspicious-pattern obfuscation ──────────────────────────────────


def test_suspicious_patterns_resolve_to_expected_strings() -> None:
    """Verify the obfuscated assembly produces the right strings.

    If anyone refactors `_suspicious_patterns` and breaks one of these,
    the corresponding diff-lint check silently stops working.
    """
    patterns = set(lint._SUSPICIOUS_PATTERNS)
    expected = {
        "subprocess.",
        "P" + "open",                # split for the same scanner reason
        "os" + ".system",
        "ev" + "al(",
        "ex" + "ec(",
        "__imp" + "ort__",
        "comp" + "ile(",
        "p" + "ickle.loads",
    }
    assert patterns == expected, (patterns, expected)


# ── Diff lint (mocked git output) ──────────────────────────────────


@pytest.fixture
def mock_git_repo(tmp_path, monkeypatch):
    """Set up a minimal git repo in tmp_path so subprocess git ops succeed."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    return tmp_path


def test_check_diff_no_target_files_passes(mock_git_repo, capsys) -> None:
    """When no DIFF_TARGETS files exist, check_diff is a no-op pass."""
    # Empty repo — no diff targets, so nothing to fail on.
    rc = lint.check_diff(mock_git_repo, base="HEAD")
    assert rc == 0


def test_check_diff_flags_url_in_added_prompt_lines(monkeypatch, mock_git_repo) -> None:
    """When _git_diff_added_lines yields a URL line in a prompt path, fail."""
    def fake_added(repo_root, base, path):
        if path.endswith("audit-prompt.md"):
            return ["See https://example.com for more"]
        return []
    def fake_lines(repo_root, base, path):
        return (10, 11)
    monkeypatch.setattr(lint, "_git_diff_added_lines", fake_added)
    monkeypatch.setattr(lint, "_file_line_counts", fake_lines)
    rc = lint.check_diff(mock_git_repo, base="HEAD")
    assert rc == 1


def test_check_diff_flags_subprocess_in_launcher(monkeypatch, mock_git_repo) -> None:
    """A new ``subprocess.`` call site in audit.py must fail."""
    def fake_added(repo_root, base, path):
        if path.endswith("audit.py"):
            return ["    subprocess.run(['rm', '-rf', '/'])"]
        return []
    def fake_lines(repo_root, base, path):
        return (10, 11)
    monkeypatch.setattr(lint, "_git_diff_added_lines", fake_added)
    monkeypatch.setattr(lint, "_file_line_counts", fake_lines)
    rc = lint.check_diff(mock_git_repo, base="HEAD")
    assert rc == 1


def test_check_diff_flags_excessive_growth(monkeypatch, mock_git_repo) -> None:
    """A 100% line-count growth on a sizeable file must fail."""
    def fake_added(repo_root, base, path):
        return []  # No content rules tripped.
    def fake_lines(repo_root, base, path):
        if path.endswith("audit-prompt.md"):
            return (200, 500)  # +300 on 200, well above 50% (=100).
        return (0, 0)
    monkeypatch.setattr(lint, "_git_diff_added_lines", fake_added)
    monkeypatch.setattr(lint, "_file_line_counts", fake_lines)
    # No added lines → file_line_counts isn't even called by current logic
    # because we short-circuit on empty added. So we need at least one added
    # line that doesn't trip URL/suspicious to exercise the growth branch.
    monkeypatch.setattr(lint, "_git_diff_added_lines", lambda r, b, p: [
        "harmless line"
    ] if p.endswith("audit-prompt.md") else [])
    rc = lint.check_diff(mock_git_repo, base="HEAD")
    assert rc == 1


def test_check_diff_passes_on_clean_diff(monkeypatch, mock_git_repo) -> None:
    """No URLs, no suspicious calls, modest growth → pass."""
    monkeypatch.setattr(lint, "_git_diff_added_lines", lambda r, b, p: [])
    monkeypatch.setattr(lint, "_file_line_counts", lambda r, b, p: (0, 0))
    rc = lint.check_diff(mock_git_repo, base="HEAD")
    assert rc == 0
