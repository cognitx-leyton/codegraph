"""Tests for :mod:`codegraph.ignore`."""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.ignore import IgnoreConfigError, IgnoreFilter


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / ".codegraphignore"
    p.write_text(content, encoding="utf-8")
    return p


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(IgnoreConfigError):
        IgnoreFilter(tmp_path / "does-not-exist")


def test_comments_and_blanks_skipped(tmp_path: Path) -> None:
    f = IgnoreFilter(_write(tmp_path, "\n# this is a comment\n\n   \n# another\n"))
    assert f.counts() == (0, 0, 0)


def test_file_glob_double_star(tmp_path: Path) -> None:
    f = IgnoreFilter(_write(tmp_path, "**/admin/**\n"))
    assert f.should_ignore_file("src/admin/Users.tsx")
    assert f.should_ignore_file("packages/server/src/admin/deep/nested/File.ts")
    assert not f.should_ignore_file("src/users/Admin.tsx")  # "admin" not a dir here
    assert not f.should_ignore_file("src/public/Home.tsx")


def test_file_glob_suffix(tmp_path: Path) -> None:
    f = IgnoreFilter(_write(tmp_path, "**/*.secret.ts\n"))
    assert f.should_ignore_file("src/lib/keys.secret.ts")
    assert not f.should_ignore_file("src/lib/keys.ts")


def test_file_glob_root_anchored(tmp_path: Path) -> None:
    f = IgnoreFilter(_write(tmp_path, "/src/admin/\n"))
    assert f.should_ignore_file("src/admin/Users.tsx")
    assert not f.should_ignore_file("packages/app/src/admin/Users.tsx")


def test_negation_restores_path(tmp_path: Path) -> None:
    f = IgnoreFilter(_write(tmp_path, "**/admin/**\n!**/admin/public/**\n"))
    assert f.should_ignore_file("src/admin/Users.tsx")
    assert not f.should_ignore_file("src/admin/public/Landing.tsx")


def test_route_wildcard(tmp_path: Path) -> None:
    f = IgnoreFilter(_write(tmp_path, "@route:/admin/*\n"))
    assert f.should_ignore_route("/admin/users")
    assert f.should_ignore_route("admin/users")  # auto-prefixed with /
    assert not f.should_ignore_route("/users")
    assert not f.should_ignore_route("/dashboard/admin")


def test_route_double_star(tmp_path: Path) -> None:
    f = IgnoreFilter(_write(tmp_path, "@route:/admin/**\n"))
    assert f.should_ignore_route("/admin/users/123/edit")
    assert f.should_ignore_route("/admin/x")


def test_component_substring(tmp_path: Path) -> None:
    f = IgnoreFilter(_write(tmp_path, "@component:*Admin*\n"))
    assert f.should_ignore_component("AdminPanel")
    assert f.should_ignore_component("UserAdminList")
    assert not f.should_ignore_component("UserList")


def test_component_case_insensitive(tmp_path: Path) -> None:
    f = IgnoreFilter(_write(tmp_path, "@component:*internal*\n"))
    assert f.should_ignore_component("InternalDashboard")


def test_mixed_pattern_types_count(tmp_path: Path) -> None:
    content = (
        "**/admin/**\n"
        "**/*.secret.ts\n"
        "@route:/admin/*\n"
        "@route:/settings/system/*\n"
        "@component:*Admin*\n"
    )
    f = IgnoreFilter(_write(tmp_path, content))
    assert f.counts() == (2, 2, 1)


def test_no_matches_returns_false(tmp_path: Path) -> None:
    f = IgnoreFilter(_write(tmp_path, "**/admin/**\n"))
    assert not f.should_ignore_file("src/users/Profile.tsx")
    assert not f.should_ignore_route("/users")
    assert not f.should_ignore_component("UserList")
