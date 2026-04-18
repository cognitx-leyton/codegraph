"""Tests for the ``codegraph stats`` subcommand and its helper functions.

All tests use a fake Neo4j driver — no live Neo4j instance required.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from codegraph.cli import (
    _format_stat_line,
    _query_graph_stats,
    _update_stat_placeholders,
)


# ── Fake Neo4j driver ───────────────────────────────────────────────


class _FakeResult:
    """Stand-in for a Neo4j result; supports iteration."""

    def __init__(self, rows: list[dict]):
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    """Routes ``run(cypher, **params)`` to a caller-supplied resolver."""

    def __init__(self, resolver):
        self._resolver = resolver
        self.calls: list[tuple[str, dict]] = []

    def run(self, cypher: str, **params: Any) -> _FakeResult:
        self.calls.append((cypher, params))
        return _FakeResult(self._resolver(cypher, **params))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeDriver:
    def __init__(self, resolver):
        self._resolver = resolver
        self._session = _FakeSession(resolver)
        self.closed = False

    def session(self):
        return self._session

    def close(self):
        self.closed = True


def _constant_driver(answers: dict[str, list[dict]]) -> _FakeDriver:
    """Build a driver whose session.run returns the row list whose key appears in the query."""

    def resolver(cypher: str, **_params):
        for key, rows in answers.items():
            if key in cypher:
                return rows
        return []

    return _FakeDriver(resolver)


# ── _query_graph_stats ──────────────────────────────────────────────


_SAMPLE_NODES = [
    {"label": "File", "count": 21},
    {"label": "Class", "count": 56},
    {"label": "Function", "count": 134},
    {"label": "Method", "count": 178},
    {"label": "Interface", "count": 10},
    {"label": "Endpoint", "count": 5},
    {"label": "Hook", "count": 3},
    {"label": "Decorator", "count": 2},
]

_SAMPLE_EDGES = [
    {"rel": "IMPORTS", "count": 100},
    {"rel": "CALLS", "count": 50},
]


def test_query_graph_stats_no_scope():
    driver = _constant_driver({
        "labels(n)": _SAMPLE_NODES,
        "type(r)": _SAMPLE_EDGES,
    })
    result = _query_graph_stats(driver, scope=None)
    assert result["files"] == 21
    assert result["classes"] == 56
    assert result["functions"] == 134
    assert result["methods"] == 178
    assert result["interfaces"] == 10
    assert result["endpoints"] == 5
    assert result["hooks"] == 3
    assert result["decorators"] == 2
    assert result["edges"]["IMPORTS"] == 100
    assert result["edges"]["CALLS"] == 50


def test_query_graph_stats_with_scope():
    driver = _constant_driver({
        "labels(n)": [{"label": "File", "count": 5}],
        "type(r)": [{"rel": "IMPORTS", "count": 10}],
    })
    result = _query_graph_stats(driver, scope=["codegraph/codegraph"])
    assert result["files"] == 5
    assert result["edges"]["IMPORTS"] == 10
    # Verify the Cypher contained the scope parameter
    session = driver._session
    assert len(session.calls) == 2
    node_cypher, node_params = session.calls[0]
    assert "scopes" in node_params
    assert node_params["scopes"] == ["codegraph/codegraph"]
    assert "STARTS WITH" in node_cypher


@pytest.mark.parametrize("scope", [None, []])
def test_query_graph_stats_empty_scope_is_global(scope):
    """Both None and [] should produce unscoped (global) queries."""
    driver = _constant_driver({
        "labels(n)": _SAMPLE_NODES,
        "type(r)": _SAMPLE_EDGES,
    })
    result = _query_graph_stats(driver, scope=scope)
    assert result["files"] == 21
    assert result["classes"] == 56
    assert result["functions"] == 134
    assert result["methods"] == 178
    # Verify no scope filtering in the Cypher
    session = driver._session
    node_cypher, node_params = session.calls[0]
    assert "STARTS WITH" not in node_cypher
    assert "scopes" not in node_params


@pytest.mark.parametrize("scope_val", ["codegraph", "codegraph/"])
def test_query_graph_stats_scope_trailing_slash(scope_val):
    """Scope prefix is forwarded verbatim — trailing slash matters for STARTS WITH."""
    driver = _constant_driver({
        "labels(n)": [{"label": "File", "count": 5}],
        "type(r)": [{"rel": "IMPORTS", "count": 10}],
    })
    _query_graph_stats(driver, scope=[scope_val])
    session = driver._session
    node_cypher, node_params = session.calls[0]
    assert node_params["scopes"] == [scope_val]
    assert "STARTS WITH" in node_cypher


# ── _format_stat_line ───────────────────────────────────────────────


def test_format_stat_line_all_nonzero():
    stats = {"files": 21, "classes": 56, "functions": 134, "methods": 178}
    line = _format_stat_line(stats)
    assert line == "~21 files, 56 classes, 134 module functions, ~178 methods"


def test_format_stat_line_zero_omitted():
    stats = {"files": 5, "classes": 0, "functions": 3, "methods": 0}
    line = _format_stat_line(stats)
    assert line == "~5 files, 3 module functions"


def test_format_stat_line_empty():
    stats = {"files": 0, "classes": 0, "functions": 0, "methods": 0}
    line = _format_stat_line(stats)
    assert line == "(empty graph)"


@pytest.mark.parametrize(
    "stats, expected_present, expected_absent",
    [
        pytest.param(
            {"files": 10, "classes": 5, "functions": 3, "methods": 8,
             "hooks": 3, "decorators": 2},
            ["3 hooks", "2 decorators"],
            [],
            id="nonzero",
        ),
        pytest.param(
            {"files": 10, "classes": 5, "functions": 3, "methods": 8,
             "hooks": 0, "decorators": 0},
            [],
            ["hooks", "decorators"],
            id="zero_omitted",
        ),
    ],
)
def test_format_stat_line_hooks_decorators(stats, expected_present, expected_absent):
    """Hook/decorator labels appear when non-zero and are omitted when zero."""
    line = _format_stat_line(stats)
    for frag in expected_present:
        assert frag in line
    for frag in expected_absent:
        assert frag not in line


# ── _update_stat_placeholders ───────────────────────────────────────


def test_update_replaces_content(tmp_path: Path):
    md = tmp_path / "test.md"
    md.write_text(
        "# Title\n"
        "<!-- codegraph:stats-begin -->\n"
        "old stats\n"
        "<!-- codegraph:stats-end -->\n"
        "rest of file\n"
    )
    n = _update_stat_placeholders([md], "~10 files, 5 classes", quiet=True)
    assert n == 1
    content = md.read_text()
    assert "~10 files, 5 classes" in content
    assert "old stats" not in content
    assert "<!-- codegraph:stats-begin -->" in content
    assert "<!-- codegraph:stats-end -->" in content
    assert "rest of file" in content


def test_update_no_delimiters_skips(tmp_path: Path):
    md = tmp_path / "plain.md"
    md.write_text("# No placeholders here\nJust text.\n")
    original = md.read_text()
    n = _update_stat_placeholders([md], "~10 files", quiet=True)
    assert n == 0
    assert md.read_text() == original


def test_update_no_change_skips_write(tmp_path: Path):
    stat_line = "~10 files, 5 classes"
    md = tmp_path / "unchanged.md"
    md.write_text(
        "# Title\n"
        "<!-- codegraph:stats-begin -->\n"
        f"{stat_line}\n"
        "<!-- codegraph:stats-end -->\n"
    )
    mtime_before = md.stat().st_mtime
    # Ensure at least 1 second passes so mtime would differ if written
    time.sleep(0.05)
    n = _update_stat_placeholders([md], stat_line, quiet=True)
    assert n == 0
    assert md.stat().st_mtime == mtime_before


def test_update_missing_file_skips(tmp_path: Path):
    missing = tmp_path / "does_not_exist.md"
    n = _update_stat_placeholders([missing], "~10 files", quiet=True)
    assert n == 0


# ── stats CLI integration ──────────────────────────────────────────


def test_stats_json_output(monkeypatch):
    from typer.testing import CliRunner

    from codegraph.cli import app

    driver = _constant_driver({
        "labels(n)": _SAMPLE_NODES,
        "type(r)": _SAMPLE_EDGES,
    })

    from neo4j import GraphDatabase

    monkeypatch.setattr(GraphDatabase, "driver", lambda *a, **kw: driver)

    runner = CliRunner()
    result = runner.invoke(app, ["stats", "--json", "--no-scope"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["ok"] is True
    assert data["stats"]["files"] == 21
    assert data["stats"]["classes"] == 56
    assert "edges" in data["stats"]


def test_stats_update_flag(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from codegraph.cli import app
    from neo4j import GraphDatabase

    driver = _constant_driver({
        "labels(n)": _SAMPLE_NODES,
        "type(r)": _SAMPLE_EDGES,
    })

    monkeypatch.setattr(GraphDatabase, "driver", lambda *a, **kw: driver)

    md = tmp_path / "CLAUDE.md"
    md.write_text(
        "# Title\n"
        "<!-- codegraph:stats-begin -->\n"
        "old stats\n"
        "<!-- codegraph:stats-end -->\n"
    )

    runner = CliRunner()
    result = runner.invoke(app, [
        "stats", "--json", "--no-scope", "--update",
        "--file", str(md),
    ])
    assert result.exit_code == 0, result.output

    data = json.loads(result.output)
    assert data["ok"] is True
    assert data["files_updated"] == 1

    content = md.read_text()
    assert "~21 files" in content
    assert "old stats" not in content
