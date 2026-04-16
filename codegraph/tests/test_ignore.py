"""Tests for :mod:`codegraph.ignore` and the ``cli.py`` ignore hooks."""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.cli import _load_ignore_filter, _strip_ignored_components
from codegraph.ignore import IgnoreConfigError, IgnoreFilter
from codegraph.resolver import Index
from codegraph.schema import FileNode, FunctionNode, ParseResult


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


# ── cli.py integration ──────────────────────────────────────────────


def _make_index_with_components(*names_and_flags: tuple[str, bool]) -> Index:
    """Build a minimal :class:`Index` containing one file with the given
    functions. Each tuple is ``(name, is_component)``."""
    idx = Index()
    fnode = FileNode(path="src/ui.tsx", package="web", language="tsx", loc=10)
    pr = ParseResult(file=fnode)
    for name, is_component in names_and_flags:
        pr.functions.append(
            FunctionNode(name=name, file="src/ui.tsx", is_component=is_component)
        )
    idx.files_by_path["src/ui.tsx"] = pr
    return idx


def test_strip_ignored_components_flips_only_matching_ones(tmp_path: Path) -> None:
    f = IgnoreFilter(_write(tmp_path, "@component:*Admin*\n"))
    idx = _make_index_with_components(
        ("AdminPanel", True),    # should flip
        ("UserList", True),      # should NOT flip — no match
        ("AdminHelper", False),  # should NOT flip — already not a component
    )

    dropped = _strip_ignored_components(idx, f)

    assert dropped == 1
    fns = {fn.name: fn.is_component for fn in idx.files_by_path["src/ui.tsx"].functions}
    assert fns == {
        "AdminPanel": False,    # flipped
        "UserList": True,       # untouched
        "AdminHelper": False,   # was already False
    }


def test_strip_ignored_components_zero_matches(tmp_path: Path) -> None:
    f = IgnoreFilter(_write(tmp_path, "@component:*Secret*\n"))
    idx = _make_index_with_components(("UserList", True), ("AdminPanel", True))
    dropped = _strip_ignored_components(idx, f)
    assert dropped == 0
    # Both components remain flagged.
    fns = {fn.name: fn.is_component for fn in idx.files_by_path["src/ui.tsx"].functions}
    assert fns == {"UserList": True, "AdminPanel": True}


def test_load_ignore_filter_auto_detects_default(tmp_path: Path) -> None:
    (tmp_path / ".codegraphignore").write_text("**/admin/**\n")
    filt = _load_ignore_filter(tmp_path, configured=None)
    assert filt is not None
    assert filt.should_ignore_file("src/admin/Users.tsx")


def test_load_ignore_filter_returns_none_when_no_default(tmp_path: Path) -> None:
    assert _load_ignore_filter(tmp_path, configured=None) is None


def test_load_ignore_filter_explicit_missing_relative_path_raises(tmp_path: Path) -> None:
    """Relative path resolved against ``repo`` and missing → hard error.

    Paired with the absolute-path case below so both resolution branches of
    :func:`_load_ignore_filter` are covered."""
    with pytest.raises(IgnoreConfigError):
        _load_ignore_filter(tmp_path, configured="does-not-exist.ignore")


def test_load_ignore_filter_explicit_missing_absolute_path_raises(tmp_path: Path) -> None:
    """Absolute path bypasses the ``repo / candidate`` join; missing → hard error."""
    missing = tmp_path / "nowhere" / "absent.ignore"
    assert missing.is_absolute()
    assert not missing.exists()
    with pytest.raises(IgnoreConfigError):
        _load_ignore_filter(tmp_path, configured=str(missing))


def test_load_ignore_filter_explicit_absolute_path(tmp_path: Path) -> None:
    target = tmp_path / "custom" / "my.ignore"
    target.parent.mkdir()
    target.write_text("@component:*Admin*\n")
    filt = _load_ignore_filter(tmp_path, configured=str(target))
    assert filt is not None
    assert filt.should_ignore_component("AdminPanel")
