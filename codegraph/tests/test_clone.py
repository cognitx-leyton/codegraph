"""Tests for :mod:`codegraph.clone`.

Covers URL parsing, cache directory logic, git operations (mocked), and the
``run_clone()`` orchestrator (mocked git + index delegation).
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from codegraph.clone import (
    CLONE_CACHE_ROOT,
    cache_dir,
    clone_or_pull,
    parse_github_url,
    run_clone,
)
from codegraph.config import ConfigError


# ── Helpers ─────────────────────────────────────────────────

def _silent_console() -> Console:
    return Console(quiet=True)


# ── parse_github_url ────────────────────────────────────────


class TestParseGithubUrl:
    """URL parsing for HTTPS and SSH GitHub URLs."""

    def test_https_basic(self):
        assert parse_github_url("https://github.com/nestjs/nest") == ("nestjs", "nest")

    def test_https_with_git_suffix(self):
        assert parse_github_url("https://github.com/owner/repo.git") == ("owner", "repo")

    def test_https_with_trailing_slash(self):
        assert parse_github_url("https://github.com/owner/repo/") == ("owner", "repo")

    def test_https_http_scheme(self):
        assert parse_github_url("http://github.com/foo/bar") == ("foo", "bar")

    def test_ssh_basic(self):
        assert parse_github_url("git@github.com:nestjs/nest.git") == ("nestjs", "nest")

    def test_ssh_without_git_suffix(self):
        assert parse_github_url("git@github.com:owner/repo") == ("owner", "repo")

    def test_invalid_host_raises(self):
        with pytest.raises(ConfigError, match="Not a recognised GitHub URL"):
            parse_github_url("https://gitlab.com/foo/bar")

    def test_malformed_url_raises(self):
        with pytest.raises(ConfigError, match="Not a recognised GitHub URL"):
            parse_github_url("https://github.com/only-owner")

    def test_empty_string_raises(self):
        with pytest.raises(ConfigError, match="URL must not be empty"):
            parse_github_url("")


# ── cache_dir ───────────────────────────────────────────────


class TestCacheDir:
    """Cache directory path derivation."""

    def test_returns_expected_path(self):
        result = cache_dir("nestjs", "nest")
        assert result == CLONE_CACHE_ROOT / "nestjs" / "nest"

    def test_different_combos_produce_different_paths(self):
        assert cache_dir("a", "b") != cache_dir("c", "d")

    def test_path_is_under_cache_root(self):
        result = cache_dir("owner", "repo")
        assert str(result).startswith(str(CLONE_CACHE_ROOT))


# ── clone_or_pull ───────────────────────────────────────────


class TestCloneOrPull:
    """Git clone/pull operations (subprocess mocked)."""

    def test_fresh_clone_shallow(self, tmp_path: Path):
        dest = tmp_path / "owner" / "repo"
        with patch("codegraph.clone.subprocess.run") as mock_run:
            clone_or_pull("https://github.com/o/r", dest, shallow=True, console=_silent_console())

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ["git", "clone", "--depth", "1", "https://github.com/o/r", str(dest)]

    def test_fresh_clone_full(self, tmp_path: Path):
        dest = tmp_path / "owner" / "repo"
        with patch("codegraph.clone.subprocess.run") as mock_run:
            clone_or_pull("https://github.com/o/r", dest, shallow=False, console=_silent_console())

        args = mock_run.call_args[0][0]
        assert args == ["git", "clone", "https://github.com/o/r", str(dest)]
        assert "--depth" not in args

    def test_cached_repo_pulls(self, tmp_path: Path):
        dest = tmp_path / "repo"
        (dest / ".git").mkdir(parents=True)
        with patch("codegraph.clone.subprocess.run") as mock_run:
            clone_or_pull("https://github.com/o/r", dest, console=_silent_console())

        args = mock_run.call_args[0][0]
        assert args == ["git", "pull", "--ff-only"]
        assert mock_run.call_args[1]["cwd"] == dest

    def test_clone_failure_raises_config_error(self, tmp_path: Path):
        dest = tmp_path / "repo"
        exc = subprocess.CalledProcessError(128, "git", stderr="fatal: repo not found")
        with patch("codegraph.clone.subprocess.run", side_effect=exc):
            with pytest.raises(ConfigError, match="git clone failed"):
                clone_or_pull("https://github.com/o/r", dest, console=_silent_console())

    def test_pull_failure_raises_config_error(self, tmp_path: Path):
        dest = tmp_path / "repo"
        (dest / ".git").mkdir(parents=True)
        exc = subprocess.CalledProcessError(1, "git", stderr="fatal: diverged")
        with patch("codegraph.clone.subprocess.run", side_effect=exc):
            with pytest.raises(ConfigError, match="git pull failed"):
                clone_or_pull("https://github.com/o/r", dest, console=_silent_console())

    def test_cached_shallow_repo_unshallowed_when_full_requested(self, tmp_path: Path):
        dest = tmp_path / "repo"
        (dest / ".git").mkdir(parents=True)
        (dest / ".git" / "shallow").touch()
        with patch("codegraph.clone.subprocess.run") as mock_run:
            clone_or_pull("https://github.com/o/r", dest, shallow=False, console=_silent_console())
        assert mock_run.call_count == 2
        assert mock_run.call_args_list[0][0][0] == ["git", "fetch", "--unshallow"]
        assert mock_run.call_args_list[0][1]["cwd"] == dest
        assert mock_run.call_args_list[1][0][0] == ["git", "pull", "--ff-only"]
        assert mock_run.call_args_list[1][1]["cwd"] == dest

    def test_cached_shallow_repo_stays_shallow_when_shallow_requested(self, tmp_path: Path):
        dest = tmp_path / "repo"
        (dest / ".git").mkdir(parents=True)
        (dest / ".git" / "shallow").touch()
        with patch("codegraph.clone.subprocess.run") as mock_run:
            clone_or_pull("https://github.com/o/r", dest, shallow=True, console=_silent_console())
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == ["git", "pull", "--ff-only"]

    def test_cached_full_repo_skips_unshallow(self, tmp_path: Path):
        dest = tmp_path / "repo"
        (dest / ".git").mkdir(parents=True)
        with patch("codegraph.clone.subprocess.run") as mock_run:
            clone_or_pull("https://github.com/o/r", dest, shallow=False, console=_silent_console())
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == ["git", "pull", "--ff-only"]

    def test_unshallow_failure_raises_config_error(self, tmp_path: Path):
        dest = tmp_path / "repo"
        (dest / ".git").mkdir(parents=True)
        (dest / ".git" / "shallow").touch()
        exc = subprocess.CalledProcessError(1, "git", stderr="fatal: unable to access remote")
        with patch("codegraph.clone.subprocess.run", side_effect=exc):
            with pytest.raises(ConfigError, match="git fetch --unshallow failed"):
                clone_or_pull("https://github.com/o/r", dest, shallow=False, console=_silent_console())


# ── run_clone ───────────────────────────────────────────────


class TestRunClone:
    """Integration tests for run_clone (git + index mocked)."""

    @patch("codegraph.clone.clone_or_pull")
    @patch("codegraph.clone.load_config")
    def test_happy_path(self, mock_config, mock_clone, tmp_path: Path):
        from codegraph.config import CodegraphConfig

        mock_config.return_value = CodegraphConfig(packages=["src"])
        with patch("codegraph.cli._run_index", return_value={"files": 10, "edges": {"IMPORTS": 50}}) as mock_index:
            code = run_clone(
                "https://github.com/nestjs/nest",
                packages=None,
                uri="bolt://localhost:7688",
                user="neo4j",
                password="pass",
                console=_silent_console(),
            )

        assert code == 0
        # Verify _run_index was called with correct args
        call_kw = mock_index.call_args[1]
        assert call_kw["repo"] == CLONE_CACHE_ROOT / "nestjs" / "nest"
        assert call_kw["repo_name"] == "nestjs/nest"
        assert call_kw["wipe"] is False
        assert call_kw["skip_ownership"] is True
        assert call_kw["packages"] == ["src"]

    @patch("codegraph.clone.clone_or_pull")
    @patch("codegraph.clone.load_config")
    def test_full_clone_enables_ownership(self, mock_config, mock_clone, tmp_path: Path):
        from codegraph.config import CodegraphConfig

        mock_config.return_value = CodegraphConfig(packages=["lib"])
        with patch("codegraph.cli._run_index", return_value={"files": 5, "edges": {}}) as mock_index:
            code = run_clone(
                "https://github.com/owner/repo",
                packages=None,
                uri="bolt://localhost:7688",
                user="neo4j",
                password="pass",
                full_clone=True,
                console=_silent_console(),
            )

        assert code == 0
        call_kw = mock_index.call_args[1]
        assert call_kw["skip_ownership"] is False

    @patch("codegraph.clone.clone_or_pull")
    def test_explicit_packages_override_config(self, mock_clone, tmp_path: Path):
        with patch("codegraph.cli._run_index", return_value={"files": 3, "edges": {}}) as mock_index:
            code = run_clone(
                "https://github.com/owner/repo",
                packages=["custom/pkg"],
                uri="bolt://localhost:7688",
                user="neo4j",
                password="pass",
                console=_silent_console(),
            )

        assert code == 0
        call_kw = mock_index.call_args[1]
        assert call_kw["packages"] == ["custom/pkg"]

    def test_invalid_url_returns_exit_2(self):
        code = run_clone(
            "https://gitlab.com/foo/bar",
            packages=None,
            uri="bolt://localhost:7688",
            user="neo4j",
            password="pass",
            console=_silent_console(),
        )
        assert code == 2

    @patch("codegraph.clone.clone_or_pull")
    @patch("codegraph.clone.load_config")
    def test_no_packages_returns_exit_2(self, mock_config, mock_clone):
        from codegraph.config import CodegraphConfig

        mock_config.return_value = CodegraphConfig(packages=[])
        code = run_clone(
            "https://github.com/owner/repo",
            packages=None,
            uri="bolt://localhost:7688",
            user="neo4j",
            password="pass",
            console=_silent_console(),
        )
        assert code == 2

    @patch("codegraph.clone.clone_or_pull")
    @patch("codegraph.clone.load_config")
    def test_json_mode_output(self, mock_config, mock_clone, capsys):
        from codegraph.config import CodegraphConfig
        import json

        mock_config.return_value = CodegraphConfig(packages=["src"])
        with patch("codegraph.cli._run_index", return_value={"files": 7, "edges": {"CALLS": 20}}):
            code = run_clone(
                "https://github.com/owner/repo",
                packages=None,
                uri="bolt://localhost:7688",
                user="neo4j",
                password="pass",
                as_json=True,
                console=_silent_console(),
            )

        assert code == 0
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is True
        assert out["stats"]["files"] == 7

    @patch("codegraph.clone.clone_or_pull", side_effect=ConfigError("git clone failed:\nfatal: error"))
    def test_clone_failure_returns_exit_2(self, mock_clone):
        code = run_clone(
            "https://github.com/owner/repo",
            packages=None,
            uri="bolt://localhost:7688",
            user="neo4j",
            password="pass",
            console=_silent_console(),
        )
        assert code == 2

    @patch("codegraph.clone.clone_or_pull")
    @patch("codegraph.clone.load_config")
    def test_connection_error_returns_exit_2(self, mock_config, mock_clone):
        from codegraph.config import CodegraphConfig
        from neo4j.exceptions import ServiceUnavailable

        mock_config.return_value = CodegraphConfig(packages=["src"])
        with patch("codegraph.cli._run_index", side_effect=ServiceUnavailable("connection refused")):
            code = run_clone(
                "https://github.com/owner/repo",
                packages=None,
                uri="bolt://localhost:7688",
                user="neo4j",
                password="pass",
                console=_silent_console(),
            )
        assert code == 2
