"""Tests for :mod:`codegraph.watch` — file watcher + incremental rebuild.

All tests use monkeypatch / MagicMock to avoid starting real file watchers
or running real ``codegraph index`` subprocesses.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from codegraph import watch as watch_module
from codegraph.watch import (
    _EXCLUDE_DIRS,
    _WATCHED_EXTENSIONS,
    _make_handler,
    _rebuild,
)


# ── Constants ──────────────────────────────────────────────


def test_watched_extensions_contains_expected():
    assert ".py" in _WATCHED_EXTENSIONS
    assert ".ts" in _WATCHED_EXTENSIONS
    assert ".tsx" in _WATCHED_EXTENSIONS


def test_watched_extensions_excludes_non_code():
    assert ".md" not in _WATCHED_EXTENSIONS
    assert ".json" not in _WATCHED_EXTENSIONS
    assert ".yml" not in _WATCHED_EXTENSIONS
    assert ".html" not in _WATCHED_EXTENSIONS


def test_exclude_dirs_contains_expected():
    assert ".git" in _EXCLUDE_DIRS
    assert "node_modules" in _EXCLUDE_DIRS
    assert ".venv" in _EXCLUDE_DIRS
    assert "__pycache__" in _EXCLUDE_DIRS


# ── Handler event filtering ───────────────────────────────


def _fake_event(src_path: str, is_directory: bool = False) -> SimpleNamespace:
    return SimpleNamespace(src_path=src_path, is_directory=is_directory)


def test_handler_accepts_py_file():
    handler = _make_handler()
    handler.on_any_event(_fake_event("/repo/src/foo.py"))
    assert handler.pending is True
    assert len(handler.changed) == 1


def test_handler_accepts_ts_file():
    handler = _make_handler()
    handler.on_any_event(_fake_event("/repo/src/bar.ts"))
    assert handler.pending is True


def test_handler_accepts_tsx_file():
    handler = _make_handler()
    handler.on_any_event(_fake_event("/repo/src/App.tsx"))
    assert handler.pending is True


def test_handler_rejects_md_file():
    handler = _make_handler()
    handler.on_any_event(_fake_event("/repo/README.md"))
    assert handler.pending is False
    assert len(handler.changed) == 0


def test_handler_rejects_json_file():
    handler = _make_handler()
    handler.on_any_event(_fake_event("/repo/package.json"))
    assert handler.pending is False


def test_handler_rejects_directory_event():
    handler = _make_handler()
    handler.on_any_event(_fake_event("/repo/src/newdir", is_directory=True))
    assert handler.pending is False


def test_handler_rejects_dotted_path():
    handler = _make_handler()
    handler.on_any_event(_fake_event("/repo/.git/hooks/post-commit.py"))
    assert handler.pending is False


def test_handler_rejects_node_modules():
    handler = _make_handler()
    handler.on_any_event(_fake_event("/repo/node_modules/pkg/index.ts"))
    assert handler.pending is False


def test_handler_rejects_venv():
    handler = _make_handler()
    handler.on_any_event(_fake_event("/repo/.venv/lib/site.py"))
    assert handler.pending is False


def test_handler_rejects_pycache():
    handler = _make_handler()
    handler.on_any_event(_fake_event("/repo/__pycache__/mod.py"))
    assert handler.pending is False


# ── Debounce logic ─────────────────────────────────────────


def test_handler_sets_last_trigger():
    handler = _make_handler()
    before = time.monotonic()
    handler.on_any_event(_fake_event("/repo/foo.py"))
    after = time.monotonic()
    assert before <= handler.last_trigger <= after


def test_handler_collects_multiple_changes():
    handler = _make_handler()
    handler.on_any_event(_fake_event("/repo/a.py"))
    handler.on_any_event(_fake_event("/repo/b.ts"))
    handler.on_any_event(_fake_event("/repo/c.tsx"))
    assert len(handler.changed) == 3
    assert handler.pending is True


# ── _rebuild ───────────────────────────────────────────────


def test_rebuild_invokes_correct_command(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = _rebuild(Path("/myrepo"))
    assert result is True
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[0] == sys.executable
    assert "-m" in cmd
    assert "codegraph.cli" in cmd
    assert "index" in cmd
    assert "/myrepo" in cmd
    assert "--since" in cmd
    assert "HEAD" in cmd
    assert "--json" in cmd


def test_rebuild_forwards_connection_params(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    _rebuild(
        Path("/myrepo"),
        uri="bolt://custom:7689",
        user="admin",
        password="secret",
        packages=["src", "lib"],
    )
    cmd = calls[0]
    # Connection params forwarded
    uri_idx = cmd.index("--uri")
    assert cmd[uri_idx + 1] == "bolt://custom:7689"
    user_idx = cmd.index("--user")
    assert cmd[user_idx + 1] == "admin"
    pw_idx = cmd.index("--password")
    assert cmd[pw_idx + 1] == "secret"
    # Packages forwarded
    pkg_indices = [i for i, v in enumerate(cmd) if v == "--package"]
    assert len(pkg_indices) == 2
    assert cmd[pkg_indices[0] + 1] == "src"
    assert cmd[pkg_indices[1] + 1] == "lib"


def test_rebuild_returns_false_on_failure(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: MagicMock(returncode=1, stdout="", stderr="error"),
    )
    assert _rebuild(Path("/repo"), quiet=True) is False


def test_rebuild_returns_false_on_exception(monkeypatch):
    def _raise(*a, **kw):
        raise OSError("no such file")

    monkeypatch.setattr(subprocess, "run", _raise)
    assert _rebuild(Path("/repo"), quiet=True) is False


# ── watchdog import guard ──────────────────────────────────


def test_require_watchdog_raises_when_missing(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def _block_watchdog(name, *args, **kwargs):
        if name.startswith("watchdog"):
            raise ImportError("mocked: no watchdog")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _block_watchdog)
    with pytest.raises(ImportError, match="pip install 'codegraph\\[watch\\]'"):
        watch_module._require_watchdog()
