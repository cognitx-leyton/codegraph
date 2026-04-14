"""Tests for :mod:`codegraph.mcp`.

Every test monkeypatches ``codegraph.mcp._driver`` with a fake implementation,
so no Neo4j instance is required. FastMCP 1.x leaves ``@mcp.tool()``-decorated
functions as plain callables — the tests invoke them directly.
"""
from __future__ import annotations

from typing import Any

import pytest
from neo4j.exceptions import ClientError, CypherSyntaxError, ServiceUnavailable

import codegraph.mcp as mcp_mod


# ── Fakes ───────────────────────────────────────────────────────────


class _FakeRecord:
    """Stand-in for a neo4j ``Record``. Supports ``items()`` + subscript."""

    def __init__(self, data: dict) -> None:
        self._data = data

    def items(self):
        return self._data.items()

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)


class _FakeSession:
    def __init__(self, responses: list[list[dict]] | Exception) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc: Any) -> None:
        pass

    def run(self, cypher: str, **params: Any):
        self.calls.append((cypher, params))
        if isinstance(self._responses, Exception):
            raise self._responses
        if not self._responses:
            return iter([])
        rows = self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        return iter([_FakeRecord(r) for r in rows])


class _FakeDriver:
    def __init__(self, responses: list[list[dict]] | Exception) -> None:
        self.session_obj = _FakeSession(responses)
        self.closed = False

    def session(self, **kwargs: Any):
        return self.session_obj

    def close(self) -> None:
        self.closed = True


def _patch(monkeypatch, responses):
    driver = _FakeDriver(responses)
    monkeypatch.setattr(mcp_mod, "_driver", driver)
    return driver


# ── query_graph ─────────────────────────────────────────────────────


def test_query_graph_returns_flat_dicts(monkeypatch):
    driver = _patch(monkeypatch, [[{"f.path": "src/a.ts", "n": 3}]])
    out = mcp_mod.query_graph("MATCH (f:File) RETURN f.path, count(*) AS n")
    assert out == [{"f.path": "src/a.ts", "n": 3}]
    cypher, _ = driver.session_obj.calls[0]
    assert "MATCH (f:File)" in cypher


def test_query_graph_respects_limit(monkeypatch):
    _patch(monkeypatch, [[{"n": i} for i in range(50)]])
    out = mcp_mod.query_graph("MATCH (n) RETURN n", limit=5)
    assert len(out) == 5


def test_query_graph_rejects_bad_limit(monkeypatch):
    _patch(monkeypatch, [[{"n": 1}]])
    result = mcp_mod.query_graph("MATCH (n) RETURN n", limit=0)
    assert result == [{"error": "limit must be a positive integer"}]


def test_query_graph_caps_huge_limit(monkeypatch):
    _patch(monkeypatch, [[{"n": i} for i in range(2000)]])
    out = mcp_mod.query_graph("MATCH (n) RETURN n", limit=5000)
    assert len(out) == 1000  # capped


def test_query_graph_surfaces_client_error(monkeypatch):
    _patch(monkeypatch, ClientError("Write queries are not allowed on this session"))
    out = mcp_mod.query_graph("CREATE (x:Foo)")
    assert out[0]["error"].startswith("Neo4j rejected query:")
    assert "Write queries" in out[0]["error"]


def test_query_graph_surfaces_syntax_error(monkeypatch):
    _patch(monkeypatch, CypherSyntaxError("Invalid input 'QQ'"))
    out = mcp_mod.query_graph("QQ")
    assert out[0]["error"].startswith("Cypher syntax error:")


def test_query_graph_surfaces_service_unavailable(monkeypatch):
    _patch(monkeypatch, ServiceUnavailable("connection refused"))
    out = mcp_mod.query_graph("MATCH (n) RETURN n")
    assert "Neo4j is unreachable" in out[0]["error"]


# ── describe_schema ─────────────────────────────────────────────────


def test_describe_schema_stitches_three_queries(monkeypatch):
    driver = _patch(
        monkeypatch,
        [
            [{"label": "Class"}, {"label": "File"}],
            [{"relationshipType": "IMPORTS"}, {"relationshipType": "INJECTS"}],
            [{"label": "Class", "n": 50}, {"label": "File", "n": 200}],
        ],
    )
    out = mcp_mod.describe_schema()
    assert out == {
        "labels": ["Class", "File"],
        "rel_types": ["IMPORTS", "INJECTS"],
        "counts": {"Class": 50, "File": 200},
    }
    assert len(driver.session_obj.calls) == 3


# ── list_packages ───────────────────────────────────────────────────


def test_list_packages_returns_framework_rows(monkeypatch):
    driver = _patch(
        monkeypatch,
        [[
            {
                "name": "packages/server",
                "framework": "Next.js",
                "framework_version": "^14.0.0",
                "typescript": True,
                "package_manager": "bun",
                "confidence": 0.95,
            }
        ]],
    )
    out = mcp_mod.list_packages()
    assert len(out) == 1
    assert out[0]["framework"] == "Next.js"
    cypher, _ = driver.session_obj.calls[0]
    assert "MATCH (p:Package)" in cypher


# ── callers_of_class ────────────────────────────────────────────────


def test_callers_of_class_default_depth(monkeypatch):
    driver = _patch(monkeypatch, [[]])
    mcp_mod.callers_of_class("AuthService")
    cypher, params = driver.session_obj.calls[0]
    assert "*1..3" in cypher
    assert params == {"class_name": "AuthService"}


def test_callers_of_class_custom_depth(monkeypatch):
    driver = _patch(monkeypatch, [[]])
    mcp_mod.callers_of_class("AuthService", max_depth=7)
    cypher, _ = driver.session_obj.calls[0]
    assert "*1..7" in cypher


@pytest.mark.parametrize("bad", [0, -1, 11, 100, "3"])
def test_callers_of_class_rejects_bad_depth(monkeypatch, bad):
    _patch(monkeypatch, [[]])
    out = mcp_mod.callers_of_class("AuthService", max_depth=bad)
    assert out == [{"error": "max_depth must be an integer in 1..10"}]


# ── endpoints_for_controller ────────────────────────────────────────


def test_endpoints_for_controller_binds_name(monkeypatch):
    driver = _patch(
        monkeypatch,
        [[{"method": "GET", "path": "/users/:id", "handler": "findOne"}]],
    )
    out = mcp_mod.endpoints_for_controller("UserController")
    assert out[0]["path"] == "/users/:id"
    cypher, params = driver.session_obj.calls[0]
    assert "is_controller: true" in cypher
    assert params == {"controller_name": "UserController"}


# ── read-only session contract ──────────────────────────────────────


def test_read_session_is_read_only(monkeypatch):
    """Sanity check: `_read_session` asks the driver for a READ_ACCESS session.

    If this ever regresses, write-Cypher from an agent would actually mutate
    the graph. Worth pinning.
    """
    captured: dict = {}

    class _Spy:
        def session(self, **kw):
            captured.update(kw)
            return _FakeSession([])

        def close(self):
            pass

    monkeypatch.setattr(mcp_mod, "_driver", _Spy())
    with mcp_mod._read_session():
        pass
    from neo4j import READ_ACCESS
    assert captured.get("default_access_mode") == READ_ACCESS
