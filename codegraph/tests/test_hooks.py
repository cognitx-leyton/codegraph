"""Tests for :mod:`codegraph.hooks` — git hook install/uninstall/status.

All tests scaffold into ``tmp_path`` with a real ``git init``, so marker
detection and file-permission checks run against real files.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from codegraph.hooks import (
    _git_root,
    _hooks_dir,
    _HOOK_MARKER,
    _HOOK_MARKER_END,
    _CHECKOUT_MARKER,
    _CHECKOUT_MARKER_END,
    install,
    status,
    uninstall,
)


# ── Helpers ─────────────────────────────────────────────────


def _make_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)


# ── _git_root ──────────────────────────────────────────────


def test_git_root_finds_from_nested_dir(tmp_path: Path):
    _make_git_repo(tmp_path)
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    assert _git_root(nested) == tmp_path.resolve()


def test_git_root_returns_none_outside_repo(tmp_path: Path):
    assert _git_root(tmp_path) is None


# ── _hooks_dir ─────────────────────────────────────────────


def test_hooks_dir_defaults_to_git_hooks(tmp_path: Path):
    _make_git_repo(tmp_path)
    result = _hooks_dir(tmp_path)
    assert result == tmp_path / ".git" / "hooks"
    assert result.is_dir()


def test_hooks_dir_respects_core_hookspath(tmp_path: Path, monkeypatch):
    _make_git_repo(tmp_path)
    custom = tmp_path / "custom-hooks"
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "core.hooksPath", str(custom)],
        check=True,
    )
    result = _hooks_dir(tmp_path)
    assert result == custom
    assert result.is_dir()


# ── install ────────────────────────────────────────────────


def test_install_creates_hooks_in_fresh_repo(tmp_path: Path):
    _make_git_repo(tmp_path)
    result = install(tmp_path)
    assert "installed" in result

    post_commit = tmp_path / ".git" / "hooks" / "post-commit"
    post_checkout = tmp_path / ".git" / "hooks" / "post-checkout"

    assert post_commit.exists()
    assert post_checkout.exists()

    # Check executable permissions
    assert post_commit.stat().st_mode & 0o755 == 0o755
    assert post_checkout.stat().st_mode & 0o755 == 0o755

    # Check markers
    commit_content = post_commit.read_text()
    assert _HOOK_MARKER in commit_content
    assert _HOOK_MARKER_END in commit_content

    checkout_content = post_checkout.read_text()
    assert _CHECKOUT_MARKER in checkout_content
    assert _CHECKOUT_MARKER_END in checkout_content


def test_install_includes_rebase_guards(tmp_path: Path):
    _make_git_repo(tmp_path)
    install(tmp_path)
    content = (tmp_path / ".git" / "hooks" / "post-commit").read_text()
    assert "rebase-merge" in content
    assert "MERGE_HEAD" in content
    assert "CHERRY_PICK_HEAD" in content


def test_install_includes_python_detection(tmp_path: Path):
    _make_git_repo(tmp_path)
    install(tmp_path)
    content = (tmp_path / ".git" / "hooks" / "post-commit").read_text()
    assert "CODEGRAPH_PYTHON" in content
    assert "CODEGRAPH_BIN" in content


def test_install_idempotent(tmp_path: Path):
    _make_git_repo(tmp_path)
    install(tmp_path)
    result = install(tmp_path)
    assert "already installed" in result

    content = (tmp_path / ".git" / "hooks" / "post-commit").read_text()
    assert content.count(_HOOK_MARKER) == 1


def test_install_appends_to_existing_hook(tmp_path: Path):
    _make_git_repo(tmp_path)
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    existing = hooks_dir / "post-commit"
    existing.write_text("#!/bin/sh\necho 'custom hook'\n")
    existing.chmod(0o755)

    install(tmp_path)

    content = existing.read_text()
    assert "echo 'custom hook'" in content
    assert _HOOK_MARKER in content


# ── uninstall ──────────────────────────────────────────────


def test_uninstall_removes_codegraph_only_hooks(tmp_path: Path):
    _make_git_repo(tmp_path)
    install(tmp_path)
    uninstall(tmp_path)

    assert not (tmp_path / ".git" / "hooks" / "post-commit").exists()
    assert not (tmp_path / ".git" / "hooks" / "post-checkout").exists()


def test_uninstall_preserves_other_hook_content(tmp_path: Path):
    _make_git_repo(tmp_path)
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    existing = hooks_dir / "post-commit"
    existing.write_text("#!/bin/sh\necho 'my custom hook'\n")
    existing.chmod(0o755)

    install(tmp_path)
    uninstall(tmp_path)

    assert existing.exists()
    content = existing.read_text()
    assert "my custom hook" in content
    assert _HOOK_MARKER not in content


def test_uninstall_no_hooks_is_noop(tmp_path: Path):
    _make_git_repo(tmp_path)
    result = uninstall(tmp_path)
    assert "nothing to remove" in result


# ── status ─────────────────────────────────────────────────


def test_status_before_install(tmp_path: Path):
    _make_git_repo(tmp_path)
    result = status(tmp_path)
    assert "not installed" in result


def test_status_after_install(tmp_path: Path):
    _make_git_repo(tmp_path)
    install(tmp_path)
    result = status(tmp_path)
    assert "post-commit: installed" in result
    assert "post-checkout: installed" in result


def test_status_after_uninstall(tmp_path: Path):
    _make_git_repo(tmp_path)
    install(tmp_path)
    uninstall(tmp_path)
    result = status(tmp_path)
    assert "not installed" in result


def test_status_outside_git_repo(tmp_path: Path):
    result = status(tmp_path)
    assert "Not in a git repository" in result


def test_status_existing_hook_without_codegraph(tmp_path: Path):
    _make_git_repo(tmp_path)
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    (hooks_dir / "post-commit").write_text("#!/bin/sh\necho 'other'\n")

    result = status(tmp_path)
    assert "not installed (hook exists but codegraph not found)" in result


# ── error cases ────────────────────────────────────────────


def test_install_outside_git_repo_raises(tmp_path: Path):
    with pytest.raises(RuntimeError, match="No git repository"):
        install(tmp_path)


def test_uninstall_outside_git_repo_raises(tmp_path: Path):
    with pytest.raises(RuntimeError, match="No git repository"):
        uninstall(tmp_path)
