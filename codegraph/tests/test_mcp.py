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
    """Fake Neo4j session. Responses are a FIFO queue of per-call row lists.

    Each call to :meth:`run` pops the next response off the queue. Calls past
    the end of the queue return an empty iterator — this makes test
    multi-call bugs surface as "no rows" rather than silently reusing the
    last response (which hides queue-exhaustion bugs).
    """

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
        rows = self._responses.pop(0)
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
    assert result == [{"error": "limit must be an integer in 1..1000"}]


@pytest.mark.parametrize("bad", [True, False])
def test_query_graph_rejects_bool_limit(monkeypatch, bad):
    _patch(monkeypatch, [[{"n": 1}]])
    result = mcp_mod.query_graph("MATCH (n) RETURN n", limit=bad)
    assert result == [{"error": "limit must be an integer in 1..1000"}]


def test_query_graph_rejects_huge_limit(monkeypatch):
    _patch(monkeypatch, [[{"n": 1}]])
    result = mcp_mod.query_graph("MATCH (n) RETURN n", limit=5000)
    assert result == [{"error": "limit must be an integer in 1..1000"}]


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


def test_describe_schema_surfaces_client_error(monkeypatch):
    """Regression: describe_schema previously used `e.message` directly,
    which is None on ad-hoc Neo4jError instances. The handler now routes
    through `_err_msg` like every other tool; verify the fallback works.
    """
    _patch(monkeypatch, ClientError("db is read-only for some reason"))
    out = mcp_mod.describe_schema()
    assert "error" in out
    assert "Neo4j rejected query" in out["error"]
    assert "read-only" in out["error"]


def test_describe_schema_surfaces_cypher_syntax_error(monkeypatch):
    _patch(monkeypatch, CypherSyntaxError("Invalid input 'MATC'"))
    out = mcp_mod.describe_schema()
    assert "error" in out
    assert "Cypher syntax error" in out["error"]
    assert "MATC" in out["error"]


def test_describe_schema_surfaces_service_unavailable(monkeypatch):
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _patch(monkeypatch, ServiceUnavailable("cannot connect"))
        out = mcp_mod.describe_schema()
    assert "error" in out
    assert "Neo4j is unreachable" in out["error"]


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
    assert "*1..1" in cypher
    assert params == {"class_name": "AuthService"}


def test_callers_of_class_custom_depth(monkeypatch):
    driver = _patch(monkeypatch, [[]])
    mcp_mod.callers_of_class("AuthService", max_depth=4)
    cypher, _ = driver.session_obj.calls[0]
    assert "*1..4" in cypher


@pytest.mark.parametrize("bad", [0, -1, 6, 100, "3", True, False])
def test_callers_of_class_rejects_bad_depth(monkeypatch, bad):
    _patch(monkeypatch, [[]])
    out = mcp_mod.callers_of_class("AuthService", max_depth=bad)
    assert out == [{"error": "max_depth must be an integer in 1..5"}]


# ── calls_from ─────────────────────────────────────────────────────


def test_calls_from_default_depth(monkeypatch):
    driver = _patch(monkeypatch, [[]])
    mcp_mod.calls_from("parse")
    cypher, params = driver.session_obj.calls[0]
    assert "*1..1" in cypher
    assert params["name"] == "parse"


def test_calls_from_custom_depth(monkeypatch):
    driver = _patch(monkeypatch, [[]])
    mcp_mod.calls_from("parse", max_depth=3)
    cypher, _ = driver.session_obj.calls[0]
    assert "*1..3" in cypher


@pytest.mark.parametrize("bad", [0, -1, 6, 100, "3", True, False])
def test_calls_from_rejects_bad_depth(monkeypatch, bad):
    _patch(monkeypatch, [[]])
    out = mcp_mod.calls_from("parse", max_depth=bad)
    assert out == [{"error": "max_depth must be an integer in 1..5"}]


def test_calls_from_happy_path(monkeypatch):
    driver = _patch(
        monkeypatch,
        [[
            {"kind": "Function", "name": "helper", "file": "src/utils.py",
             "docstring": "A helper"},
        ]],
    )
    out = mcp_mod.calls_from("parse")
    assert len(out) == 1
    assert out[0]["kind"] == "Function"
    assert out[0]["name"] == "helper"
    assert out[0]["file"] == "src/utils.py"
    assert out[0]["docstring"] == "A helper"
    cypher, params = driver.session_obj.calls[0]
    assert "src:Function OR src:Method" in cypher
    assert "CALLS*1..1" in cypher
    assert params == {"name": "parse", "file": None}


def test_calls_from_with_file_filter(monkeypatch):
    driver = _patch(monkeypatch, [[]])
    mcp_mod.calls_from("parse", file="src/parser.py")
    _, params = driver.session_obj.calls[0]
    assert params["file"] == "src/parser.py"


def test_calls_from_rejects_bad_limit(monkeypatch):
    _patch(monkeypatch, [[]])
    out = mcp_mod.calls_from("parse", limit=0)
    assert out == [{"error": "limit must be an integer in 1..1000"}]


# ── callers_of ─────────────────────────────────────────────────────


def test_callers_of_default_depth(monkeypatch):
    driver = _patch(monkeypatch, [[]])
    mcp_mod.callers_of("parse")
    cypher, params = driver.session_obj.calls[0]
    assert "*1..1" in cypher
    assert params["name"] == "parse"


def test_callers_of_custom_depth(monkeypatch):
    driver = _patch(monkeypatch, [[]])
    mcp_mod.callers_of("parse", max_depth=4)
    cypher, _ = driver.session_obj.calls[0]
    assert "*1..4" in cypher


@pytest.mark.parametrize("bad", [0, -1, 6, 100, "3", True, False])
def test_callers_of_rejects_bad_depth(monkeypatch, bad):
    _patch(monkeypatch, [[]])
    out = mcp_mod.callers_of("parse", max_depth=bad)
    assert out == [{"error": "max_depth must be an integer in 1..5"}]


def test_callers_of_happy_path(monkeypatch):
    driver = _patch(
        monkeypatch,
        [[
            {"kind": "Method", "name": "run_pipeline", "file": "src/pipeline.py"},
        ]],
    )
    out = mcp_mod.callers_of("parse")
    assert len(out) == 1
    assert out[0]["kind"] == "Method"
    assert out[0]["name"] == "run_pipeline"
    assert out[0]["file"] == "src/pipeline.py"
    cypher, params = driver.session_obj.calls[0]
    assert "src:Function OR src:Method" in cypher
    assert "CALLS*1..1" in cypher
    assert params == {"name": "parse", "file": None}


def test_callers_of_with_file_filter(monkeypatch):
    driver = _patch(monkeypatch, [[]])
    mcp_mod.callers_of("parse", file="src/parser.py")
    _, params = driver.session_obj.calls[0]
    assert params["file"] == "src/parser.py"


def test_callers_of_rejects_bad_limit(monkeypatch):
    _patch(monkeypatch, [[]])
    out = mcp_mod.callers_of("parse", limit=0)
    assert out == [{"error": "limit must be an integer in 1..1000"}]


# ── describe_function ──────────────────────────────────────────────


def test_describe_function_happy_path(monkeypatch):
    driver = _patch(
        monkeypatch,
        [[
            {"kind": "Function", "name": "parse", "file": "src/parser.py",
             "docstring": "Parse source.", "params_json": '[{"name": "source"}]',
             "return_type": "ParseResult", "decorators": ["mcp.tool"]},
        ]],
    )
    out = mcp_mod.describe_function("parse")
    assert len(out) == 1
    assert out[0]["kind"] == "Function"
    assert out[0]["name"] == "parse"
    assert out[0]["file"] == "src/parser.py"
    assert out[0]["docstring"] == "Parse source."
    assert out[0]["return_type"] == "ParseResult"
    assert out[0]["decorators"] == ["mcp.tool"]
    cypher, params = driver.session_obj.calls[0]
    assert "n:Function OR n:Method" in cypher
    assert "OPTIONAL MATCH (n)-[:DECORATED_BY]->(d:Decorator)" in cypher
    assert "collect(DISTINCT d.name)" in cypher
    assert params == {"name": "parse", "file": None}


def test_describe_function_with_file_filter(monkeypatch):
    driver = _patch(monkeypatch, [[]])
    mcp_mod.describe_function("parse", file="src/parser.py")
    _, params = driver.session_obj.calls[0]
    assert params["file"] == "src/parser.py"


def test_describe_function_no_decorators(monkeypatch):
    _patch(
        monkeypatch,
        [[
            {"kind": "Function", "name": "helper", "file": "src/utils.py",
             "docstring": "", "params_json": "[]",
             "return_type": None, "decorators": []},
        ]],
    )
    out = mcp_mod.describe_function("helper")
    assert len(out) == 1
    assert out[0]["decorators"] == []
    assert out[0]["return_type"] is None


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


# ── _validate_limit ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad",
    [0, -1, 1001, "10", None, 3.5, True, False],
)
def test_validate_limit_rejects(bad):
    assert mcp_mod._validate_limit(bad) is not None


@pytest.mark.parametrize("good", [1, 50, 1000])
def test_validate_limit_accepts(good):
    assert mcp_mod._validate_limit(good) is None


def test_validate_limit_custom_max():
    assert mcp_mod._validate_limit(50, max_limit=100) is None
    assert mcp_mod._validate_limit(101, max_limit=100) is not None


# ── _validate_max_depth ────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad",
    [0, -1, 6, 100, "3", None, 3.5, True, False],
)
def test_validate_max_depth_rejects(bad):
    assert mcp_mod._validate_max_depth(bad) is not None


@pytest.mark.parametrize("good", [1, 3, 5])
def test_validate_max_depth_accepts(good):
    assert mcp_mod._validate_max_depth(good) is None


def test_validate_max_depth_custom_max():
    assert mcp_mod._validate_max_depth(8, max_val=10) is None
    assert mcp_mod._validate_max_depth(11, max_val=10) is not None


# ── files_in_package ────────────────────────────────────────────────


def test_files_in_package_happy_path(monkeypatch):
    driver = _patch(
        monkeypatch,
        [[
            {
                "path": "packages/srv/src/a.ts",
                "language": "ts",
                "loc": 120,
                "is_controller": False,
                "is_component": False,
                "is_injectable": True,
                "is_module": False,
                "is_entity": False,
            }
        ]],
    )
    out = mcp_mod.files_in_package("srv")
    assert len(out) == 1
    assert out[0]["path"] == "packages/srv/src/a.ts"
    cypher, params = driver.session_obj.calls[0]
    assert "(f:File {package: $name})" in cypher
    assert "LIMIT 50" in cypher
    assert params == {"name": "srv"}


def test_files_in_package_interpolates_custom_limit(monkeypatch):
    driver = _patch(monkeypatch, [[]])
    mcp_mod.files_in_package("srv", limit=250)
    cypher, _ = driver.session_obj.calls[0]
    assert "LIMIT 250" in cypher


def test_files_in_package_rejects_bad_limit(monkeypatch):
    _patch(monkeypatch, [[]])
    out = mcp_mod.files_in_package("srv", limit=0)
    assert out == [{"error": "limit must be an integer in 1..1000"}]


# ── hook_usage ──────────────────────────────────────────────────────


def test_hook_usage_happy_path(monkeypatch):
    driver = _patch(
        monkeypatch,
        [[
            {"name": "LoginForm", "file": "src/ui/LoginForm.tsx", "is_component": True},
            {"name": "useAuthGate", "file": "src/hooks/useAuthGate.ts", "is_component": False},
        ]],
    )
    out = mcp_mod.hook_usage("useAuth")
    assert [row["name"] for row in out] == ["LoginForm", "useAuthGate"]
    cypher, params = driver.session_obj.calls[0]
    assert "(fn:Function)-[:USES_HOOK]->(:Hook {name: $hook_name})" in cypher
    assert "DISTINCT" in cypher
    assert params == {"hook_name": "useAuth"}


def test_hook_usage_empty_result(monkeypatch):
    _patch(monkeypatch, [[]])
    assert mcp_mod.hook_usage("useNonexistent") == []


def test_hook_usage_rejects_bad_limit(monkeypatch):
    _patch(monkeypatch, [[]])
    out = mcp_mod.hook_usage("useAuth", limit=-5)
    assert out == [{"error": "limit must be an integer in 1..1000"}]


# ── gql_operation_callers ───────────────────────────────────────────


def test_gql_operation_callers_no_type_filter(monkeypatch):
    driver = _patch(
        monkeypatch,
        [[
            {
                "caller_name": "UserListPage",
                "caller_file": "src/pages/UserList.tsx",
                "caller_kind": "Function",
                "op_type": "query",
                "return_type": "UserConnection",
            }
        ]],
    )
    out = mcp_mod.gql_operation_callers("findManyUsers")
    assert out[0]["caller_kind"] == "Function"
    cypher, params = driver.session_obj.calls[0]
    assert "labels(caller)[0] AS caller_kind" in cypher
    assert params == {"op_name": "findManyUsers", "op_type": None}


def test_gql_operation_callers_with_type(monkeypatch):
    driver = _patch(monkeypatch, [[]])
    mcp_mod.gql_operation_callers("createUser", op_type="mutation")
    _, params = driver.session_obj.calls[0]
    assert params == {"op_name": "createUser", "op_type": "mutation"}


@pytest.mark.parametrize("bad_type", ["fetch", "qurey", "QUERY", "", "subscription ", "all"])
def test_gql_operation_callers_rejects_bad_op_type(monkeypatch, bad_type):
    _patch(monkeypatch, [[]])
    out = mcp_mod.gql_operation_callers("findManyUsers", op_type=bad_type)
    assert out == [{"error": "op_type must be one of 'query' | 'mutation' | 'subscription'"}]


# ── most_injected_services ──────────────────────────────────────────


def test_most_injected_services_happy_path(monkeypatch):
    driver = _patch(
        monkeypatch,
        [[
            {"name": "ConfigService", "file": "src/config/config.service.ts",
             "injections": 136, "is_controller": False},
            {"name": "AuthService", "file": "src/auth/auth.service.ts",
             "injections": 87, "is_controller": False},
        ]],
    )
    out = mcp_mod.most_injected_services(limit=5)
    assert out[0]["injections"] == 136
    cypher, _ = driver.session_obj.calls[0]
    assert "(svc:Class {is_injectable: true})<-[:INJECTS]-(caller:Class)" in cypher
    assert "count(DISTINCT caller)" in cypher
    assert "LIMIT 5" in cypher
    assert "ORDER BY injections DESC" in cypher


def test_most_injected_services_tight_limit_cap(monkeypatch):
    _patch(monkeypatch, [[]])
    out = mcp_mod.most_injected_services(limit=500)
    assert out == [{"error": "limit must be an integer in 1..100"}]


# ── find_class ──────────────────────────────────────────────────────


def test_find_class_happy_path(monkeypatch):
    driver = _patch(
        monkeypatch,
        [[
            {"name": "AuthService", "file": "src/auth/auth.service.ts",
             "is_controller": False, "is_injectable": True, "is_module": False,
             "is_entity": False, "is_resolver": False},
            {"name": "AuthGuard", "file": "src/auth/auth.guard.ts",
             "is_controller": False, "is_injectable": True, "is_module": False,
             "is_entity": False, "is_resolver": False},
        ]],
    )
    out = mcp_mod.find_class("Auth")
    assert [r["name"] for r in out] == ["AuthService", "AuthGuard"]
    cypher, params = driver.session_obj.calls[0]
    assert "c.name CONTAINS $name_pattern" in cypher
    assert params == {"name_pattern": "Auth"}


def test_find_class_rejects_empty_pattern(monkeypatch):
    _patch(monkeypatch, [[]])
    out = mcp_mod.find_class("")
    assert out == [{"error": "name_pattern must be non-empty"}]


def test_find_class_rejects_bad_limit(monkeypatch):
    _patch(monkeypatch, [[]])
    out = mcp_mod.find_class("Auth", limit=99999)
    assert out == [{"error": "limit must be an integer in 1..1000"}]


# ── Parametrized error paths across all new tools ───────────────────


@pytest.mark.parametrize(
    "call",
    [
        lambda: mcp_mod.files_in_package("srv"),
        lambda: mcp_mod.hook_usage("useAuth"),
        lambda: mcp_mod.gql_operation_callers("findManyUsers"),
        lambda: mcp_mod.most_injected_services(),
        lambda: mcp_mod.find_class("Auth"),
        lambda: mcp_mod.calls_from("parse"),
        lambda: mcp_mod.callers_of("parse"),
        lambda: mcp_mod.describe_function("parse"),
    ],
)
def test_new_tools_surface_client_error(monkeypatch, call):
    _patch(monkeypatch, ClientError("nope"))
    out = call()
    assert len(out) == 1 and "error" in out[0]
    assert "Neo4j rejected query" in out[0]["error"]


@pytest.mark.parametrize(
    "call",
    [
        lambda: mcp_mod.files_in_package("srv"),
        lambda: mcp_mod.hook_usage("useAuth"),
        lambda: mcp_mod.gql_operation_callers("findManyUsers"),
        lambda: mcp_mod.most_injected_services(),
        lambda: mcp_mod.find_class("Auth"),
        lambda: mcp_mod.calls_from("parse"),
        lambda: mcp_mod.callers_of("parse"),
        lambda: mcp_mod.describe_function("parse"),
    ],
)
def test_new_tools_surface_service_unavailable(monkeypatch, call):
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _patch(monkeypatch, ServiceUnavailable("down"))
        out = call()
    assert len(out) == 1 and "error" in out[0]
    assert "Neo4j is unreachable" in out[0]["error"]


# ── query prompt parsing ─────────────────────────────────────────────


def test_parse_queries_md_extracts_all_blocks():
    """Real queries.md should yield exactly 29 entries."""
    text = mcp_mod._QUERIES_MD.read_text(encoding="utf-8")
    entries = mcp_mod._parse_queries_md(text)
    assert len(entries) == 29


def test_parse_queries_md_single_block_section():
    md = "## My Section\n\n```cypher\n// My description\nMATCH (n) RETURN n\n```\n"
    entries = mcp_mod._parse_queries_md(md)
    assert len(entries) == 1
    assert entries[0].name == "my-section"
    assert entries[0].description == "My description"
    assert "MATCH (n) RETURN n" in entries[0].cypher


def test_parse_queries_md_multi_block_naming():
    md = "## Foo\n\n```cypher\nRETURN 1\n```\n\n```cypher\nRETURN 2\n```\n\n```cypher\nRETURN 3\n```\n"
    entries = mcp_mod._parse_queries_md(md)
    assert [e.name for e in entries] == ["foo", "foo-2", "foo-3"]


def test_parse_queries_md_comment_as_description():
    md = "## Section\n\n```cypher\n// Explicit description\nMATCH (n) RETURN n\n```\n"
    entries = mcp_mod._parse_queries_md(md)
    assert entries[0].description == "Explicit description"


def test_parse_queries_md_heading_fallback_when_no_comment():
    md = "## My Heading\n\n```cypher\nMATCH (n) RETURN n\n```\n"
    entries = mcp_mod._parse_queries_md(md)
    assert entries[0].description == "My Heading"


def test_parse_queries_md_empty_input():
    assert mcp_mod._parse_queries_md("") == []


def test_slugify():
    assert mcp_mod._slugify("4. Impact analysis: who depends on X?") == "4-impact-analysis-who-depends-on-x"
    assert mcp_mod._slugify("Schema overview") == "schema-overview"
    assert mcp_mod._slugify("  Leading & trailing  ") == "leading-trailing"


# ── query prompt registration ────────────────────────────────────────


def test_query_prompts_registered_on_server():
    prompts = mcp_mod.mcp._prompt_manager._prompts
    assert len(prompts) >= 29


def test_query_prompt_renders_cypher():
    prompts = mcp_mod.mcp._prompt_manager._prompts
    schema_prompt = prompts.get("schema-overview")
    assert schema_prompt is not None
    # Calling the underlying function returns the Cypher string
    result = schema_prompt.fn()
    assert "CALL db.labels()" in result


def test_register_query_prompts_skips_missing_file(monkeypatch, tmp_path):
    from mcp.server.fastmcp import FastMCP as _FastMCP
    monkeypatch.setattr(mcp_mod, "_QUERIES_MD", tmp_path / "nonexistent.md")
    fresh = _FastMCP("test")
    mcp_mod._register_query_prompts(fresh)
    assert len(fresh._prompt_manager._prompts) == 0


# ── write session contract ─────────────────────────────────────────


def test_write_session_uses_write_access(monkeypatch):
    """Sanity check: `_write_session` asks the driver for a WRITE_ACCESS session."""
    captured: dict = {}

    class _Spy:
        def session(self, **kw):
            captured.update(kw)
            return _FakeSession([])

        def close(self):
            pass

    monkeypatch.setattr(mcp_mod, "_driver", _Spy())
    with mcp_mod._write_session():
        pass
    from neo4j import WRITE_ACCESS
    assert captured.get("default_access_mode") == WRITE_ACCESS


# ── --allow-write gate ─────────────────────────────────────────────


def test_write_tools_blocked_without_allow_write(monkeypatch):
    """Both write tools return an error when _allow_write is False."""
    monkeypatch.setattr(mcp_mod, "_allow_write", False)
    _patch(monkeypatch, [[]])

    wipe_result = mcp_mod.wipe_graph(confirm=True)
    assert "error" in wipe_result
    assert "allow-write" in wipe_result["error"]

    reindex_result = mcp_mod.reindex_file("foo.py")
    assert "error" in reindex_result
    assert "allow-write" in reindex_result["error"]


def test_main_parses_allow_write(monkeypatch):
    """main() sets _allow_write to True when --allow-write is passed."""
    import sys
    monkeypatch.setattr(sys, "argv", ["codegraph-mcp", "--allow-write"])
    monkeypatch.setattr(mcp_mod.mcp, "run", lambda **kw: None)
    monkeypatch.setattr(mcp_mod, "_driver", None)
    mcp_mod.main()
    assert mcp_mod._allow_write is True
    # Reset
    monkeypatch.setattr(mcp_mod, "_allow_write", False)


def test_main_default_no_allow_write(monkeypatch):
    """main() leaves _allow_write as False by default."""
    import sys
    monkeypatch.setattr(sys, "argv", ["codegraph-mcp"])
    monkeypatch.setattr(mcp_mod.mcp, "run", lambda **kw: None)
    monkeypatch.setattr(mcp_mod, "_driver", None)
    mcp_mod.main()
    assert mcp_mod._allow_write is False


# ── wipe_graph ─────────────────────────────────────────────────────


def test_wipe_graph_requires_confirm(monkeypatch):
    monkeypatch.setattr(mcp_mod, "_allow_write", True)
    _patch(monkeypatch, [[]])
    out = mcp_mod.wipe_graph()
    assert out == {"error": "Pass confirm=True to wipe the entire graph"}


def test_wipe_graph_blocked_without_allow_write(monkeypatch):
    monkeypatch.setattr(mcp_mod, "_allow_write", False)
    _patch(monkeypatch, [[]])
    out = mcp_mod.wipe_graph(confirm=True)
    assert "error" in out
    assert "allow-write" in out["error"]


def test_wipe_graph_happy_path(monkeypatch):
    monkeypatch.setattr(mcp_mod, "_allow_write", True)
    driver = _patch(monkeypatch, [[]])
    out = mcp_mod.wipe_graph(confirm=True)
    assert out == {"ok": True, "action": "wipe"}
    cypher, _ = driver.session_obj.calls[0]
    assert "DETACH DELETE" in cypher


def test_wipe_graph_surfaces_service_unavailable(monkeypatch):
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        monkeypatch.setattr(mcp_mod, "_allow_write", True)
        _patch(monkeypatch, ServiceUnavailable("down"))
        out = mcp_mod.wipe_graph(confirm=True)
    assert "error" in out
    assert "Neo4j is unreachable" in out["error"]


def test_wipe_graph_surfaces_client_error(monkeypatch):
    monkeypatch.setattr(mcp_mod, "_allow_write", True)
    _patch(monkeypatch, ClientError("forbidden"))
    out = mcp_mod.wipe_graph(confirm=True)
    assert "error" in out
    assert "Neo4j rejected query" in out["error"]


# ── reindex_file ───────────────────────────────────────────────────


def test_reindex_file_rejects_bad_extension(monkeypatch):
    monkeypatch.setattr(mcp_mod, "_allow_write", True)
    out = mcp_mod.reindex_file("foo.go")
    assert out == {"error": "path must end in .py, .ts, or .tsx"}


def test_reindex_file_blocked_without_allow_write(monkeypatch):
    monkeypatch.setattr(mcp_mod, "_allow_write", False)
    out = mcp_mod.reindex_file("foo.py")
    assert "error" in out
    assert "allow-write" in out["error"]


def test_reindex_file_errors_when_no_package(monkeypatch):
    """When no package param and file not in graph, return clear error."""
    monkeypatch.setattr(mcp_mod, "_allow_write", True)
    _patch(monkeypatch, [[]])  # Empty result for package lookup
    out = mcp_mod.reindex_file("unknown.py")
    assert "error" in out
    assert "not found in graph" in out["error"]


def test_reindex_file_propagates_neo4j_error_on_package_lookup(monkeypatch):
    """Neo4j errors during package lookup should surface, not mask as 'not found'."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        monkeypatch.setattr(mcp_mod, "_allow_write", True)
        _patch(monkeypatch, ServiceUnavailable("down"))
        out = mcp_mod.reindex_file("some_file.py")
    assert "error" in out
    assert "Neo4j is unreachable" in out["error"]


def test_reindex_file_looks_up_package_from_graph(monkeypatch, tmp_path):
    """When no package param, the tool queries the graph for f.package."""
    monkeypatch.setattr(mcp_mod, "_allow_write", True)

    # Create a real .py file so the disk check passes
    py_file = tmp_path / "src" / "app.py"
    py_file.parent.mkdir(parents=True)
    py_file.write_text("x = 1\n")

    # First call returns the package from graph; subsequent calls are writes
    driver = _patch(monkeypatch, [[{"pkg": "mypackage"}]])

    # Mock the parser so we don't need tree-sitter
    from codegraph.py_parser import PyParser
    from codegraph.schema import FileNode, ParseResult
    fake_result = ParseResult(
        file=FileNode(path=str(py_file), package="mypackage", language="py", loc=1),
    )

    monkeypatch.setattr(PyParser, "parse_file", lambda *a, **kw: fake_result)

    out = mcp_mod.reindex_file(str(py_file), package=None)
    # The first query should be the package lookup
    first_cypher, first_params = driver.session_obj.calls[0]
    assert "f.package AS pkg" in first_cypher
    assert first_params["path"] == str(py_file)


def test_reindex_file_happy_path(monkeypatch, tmp_path):
    """Happy path: parses file, deletes old subgraph, loads new nodes."""
    monkeypatch.setattr(mcp_mod, "_allow_write", True)

    # Create a real .py file
    py_file = tmp_path / "mod.py"
    py_file.write_text("class Foo:\n    pass\n")

    driver = _patch(monkeypatch, [[]])

    # Mock the parser
    from codegraph.py_parser import PyParser
    from codegraph.schema import ClassNode, FileNode, FunctionNode, ParseResult
    fake_result = ParseResult(
        file=FileNode(path=str(py_file), package="pkg", language="py", loc=2),
        classes=[ClassNode(name="Foo", file=str(py_file))],
        functions=[FunctionNode(name="bar", file=str(py_file))],
    )

    monkeypatch.setattr(PyParser, "parse_file", lambda *a, **kw: fake_result)

    out = mcp_mod.reindex_file(str(py_file), package="pkg")
    assert out["ok"] is True
    assert out["file"] == str(py_file)
    assert out["nodes"] == 3  # 1 File + 1 Class + 1 Function
    assert out["edges"] == 0


def test_reindex_file_file_not_on_disk(monkeypatch):
    """Error when the file doesn't exist on disk."""
    monkeypatch.setattr(mcp_mod, "_allow_write", True)
    out = mcp_mod.reindex_file("/nonexistent/path/foo.py", package="pkg")
    assert "error" in out
    assert "not found on disk" in out["error"]


def test_reindex_file_surfaces_client_error(monkeypatch, tmp_path):
    """Neo4j ClientError during write is surfaced."""
    monkeypatch.setattr(mcp_mod, "_allow_write", True)

    py_file = tmp_path / "mod.py"
    py_file.write_text("x = 1\n")

    _patch(monkeypatch, ClientError("write rejected"))

    from codegraph.py_parser import PyParser
    from codegraph.schema import FileNode, ParseResult
    fake_result = ParseResult(
        file=FileNode(path=str(py_file), package="pkg", language="py", loc=1),
    )

    monkeypatch.setattr(PyParser, "parse_file", lambda *a, **kw: fake_result)

    out = mcp_mod.reindex_file(str(py_file), package="pkg")
    assert "error" in out
    assert "Neo4j rejected query" in out["error"]


def test_reindex_file_loads_decorated_by_edges(monkeypatch, tmp_path):
    """DECORATED_BY edges match Decorator by name, not by id."""
    monkeypatch.setattr(mcp_mod, "_allow_write", True)

    py_file = tmp_path / "mod.py"
    py_file.write_text("@mcp.tool()\ndef helper():\n    pass\n")

    driver = _patch(monkeypatch, [[]])

    from codegraph.py_parser import PyParser
    from codegraph.schema import (
        DECORATED_BY, Edge, FileNode, FunctionNode, ParseResult,
    )
    fake_result = ParseResult(
        file=FileNode(path=str(py_file), package="pkg", language="py", loc=3),
        functions=[FunctionNode(name="helper", file=str(py_file))],
        edges=[
            Edge(kind=DECORATED_BY, src_id="func:mod.py#helper", dst_id="dec:mcp.tool()"),
        ],
    )

    monkeypatch.setattr(PyParser, "parse_file", lambda *a, **kw: fake_result)

    out = mcp_mod.reindex_file(str(py_file), package="pkg")
    assert out["ok"] is True
    assert out["edges"] == 1

    # Verify the Decorator MERGE uses {name: ...}, not {id: ...}
    decorator_merges = [
        cypher for cypher, _ in driver.session_obj.calls
        if "Decorator" in cypher and "MERGE" in cypher
    ]
    assert len(decorator_merges) >= 1
    # Should match by name, not id
    assert any("{name:" in c or "name: " in c for c in decorator_merges)

    # Verify the edge MERGE matches Function by label
    edge_merges = [
        cypher for cypher, _ in driver.session_obj.calls
        if "DECORATED_BY" in cypher and "Function" in cypher
    ]
    assert len(edge_merges) == 1


def test_reindex_file_ownership_edges_not_doubled(monkeypatch, tmp_path):
    """Ownership edges (DEFINES_*) come only from node MERGEs, not the generic edge loop."""
    monkeypatch.setattr(mcp_mod, "_allow_write", True)

    py_file = tmp_path / "mod.py"
    py_file.write_text("class Foo:\n    pass\ndef bar(): ...\n")

    driver = _patch(monkeypatch, [[]])

    from codegraph.py_parser import PyParser
    from codegraph.schema import (
        DEFINES_CLASS, DEFINES_FUNC, DEFINES_IFACE, DEFINES_ATOM,
        Edge, FileNode, ClassNode, FunctionNode, InterfaceNode, AtomNode,
        ParseResult,
    )
    fake_result = ParseResult(
        file=FileNode(path=str(py_file), package="pkg", language="py", loc=3),
        classes=[ClassNode(name="Foo", file=str(py_file))],
        functions=[FunctionNode(name="bar", file=str(py_file))],
        interfaces=[InterfaceNode(name="IFoo", file=str(py_file))],
        atoms=[AtomNode(name="myAtom", file=str(py_file), family="jotai")],
        edges=[
            Edge(kind=DEFINES_CLASS, src_id=f"file:{py_file}", dst_id=f"class:{py_file}#Foo"),
            Edge(kind=DEFINES_FUNC, src_id=f"file:{py_file}", dst_id=f"func:{py_file}#bar"),
            Edge(kind=DEFINES_IFACE, src_id=f"file:{py_file}", dst_id=f"iface:{py_file}#IFoo"),
            Edge(kind=DEFINES_ATOM, src_id=f"file:{py_file}", dst_id=f"atom:{py_file}#myAtom"),
        ],
    )

    monkeypatch.setattr(PyParser, "parse_file", lambda *a, **kw: fake_result)

    out = mcp_mod.reindex_file(str(py_file), package="pkg")
    assert out["ok"] is True

    all_cypher = " ".join(cypher for cypher, _ in driver.session_obj.calls)

    # The old mismatched value must never appear
    assert "DEFINES_INTERFACE" not in all_cypher

    # DEFINES_IFACE must appear in node-creation MERGEs
    assert "DEFINES_IFACE" in all_cypher

    # Generic edge loop uses MATCH(a {id:$src}) MATCH(b {id:$dst}) MERGE pattern.
    # Ownership edges must NOT appear via that path.
    generic_edge_calls = [
        (cypher, params) for cypher, params in driver.session_obj.calls
        if "MATCH (a {id: $src})" in cypher and "MATCH (b {id: $dst})" in cypher
    ]
    for cypher, _ in generic_edge_calls:
        assert "DEFINES_CLASS" not in cypher
        assert "DEFINES_FUNC" not in cypher
        assert "DEFINES_IFACE" not in cypher
        assert "DEFINES_ATOM" not in cypher

    # Ownership edges are excluded from the generic loop count
    assert out["edges"] == 0


def test_reindex_file_structural_edges_not_doubled(monkeypatch, tmp_path):
    """Structural edges (HAS_METHOD, EXPOSES, RESOLVES, HAS_COLUMN) come only
    from inline node-creation MERGEs, not the generic edge loop."""
    monkeypatch.setattr(mcp_mod, "_allow_write", True)

    py_file = tmp_path / "ctrl.py"
    py_file.write_text("class Ctrl:\n    def handle(self): ...\n")

    driver = _patch(monkeypatch, [[]])

    from codegraph.py_parser import PyParser
    from codegraph.schema import (
        HAS_METHOD, EXPOSES, RESOLVES, HAS_COLUMN,
        Edge, FileNode, ClassNode, MethodNode,
        EndpointNode, GraphQLOperationNode, ColumnNode,
        ParseResult,
    )

    class_id = f"class:{py_file}#Ctrl"
    fake_result = ParseResult(
        file=FileNode(path=str(py_file), package="pkg", language="py", loc=2),
        classes=[ClassNode(name="Ctrl", file=str(py_file))],
        methods=[MethodNode(name="handle", class_id=class_id, file=str(py_file))],
        endpoints=[EndpointNode(
            method="GET", path="/foo",
            controller_class=class_id,
            file=str(py_file), handler="handle",
        )],
        gql_operations=[GraphQLOperationNode(
            op_type="query", name="getCtrl", return_type="Ctrl",
            file=str(py_file), resolver_class=class_id, handler="handle",
        )],
        columns=[ColumnNode(entity_id=class_id, name="id", type="int")],
        edges=[
            Edge(kind=HAS_METHOD, src_id=class_id,
                 dst_id=f"method:{class_id}#handle"),
            Edge(kind=EXPOSES, src_id=class_id,
                 dst_id=f"endpoint:GET:/foo@{py_file}#handle"),
            Edge(kind=RESOLVES, src_id=class_id,
                 dst_id=f"gqlop:query:getCtrl@{py_file}#handle"),
            Edge(kind=HAS_COLUMN, src_id=class_id,
                 dst_id=f"column:{class_id}#id"),
        ],
    )

    monkeypatch.setattr(PyParser, "parse_file", lambda *a, **kw: fake_result)

    out = mcp_mod.reindex_file(str(py_file), package="pkg")
    assert out["ok"] is True

    all_cypher = " ".join(cypher for cypher, _ in driver.session_obj.calls)

    # Inline MERGEs must still contain these edge types
    assert "HAS_METHOD" in all_cypher
    assert "EXPOSES" in all_cypher
    assert "RESOLVES" in all_cypher
    assert "HAS_COLUMN" in all_cypher

    # Generic edge loop calls use MATCH(a {id:$src}) MATCH(b {id:$dst}) pattern
    generic_edge_calls = [
        (cypher, params) for cypher, params in driver.session_obj.calls
        if "MATCH (a {id: $src})" in cypher and "MATCH (b {id: $dst})" in cypher
    ]

    # HAS_METHOD, EXPOSES, RESOLVES, HAS_COLUMN must NOT appear in the generic loop
    for cypher, _ in generic_edge_calls:
        assert "HAS_METHOD" not in cypher
        assert "EXPOSES" not in cypher
        assert "RESOLVES" not in cypher
        assert "HAS_COLUMN" not in cypher


def test_reindex_file_file_level_exposes_edge(monkeypatch, tmp_path):
    """File-level endpoints (controller_class='file:<path>') get EXPOSES edges
    written via MATCH (f:File {path: ...}), not MATCH (c:Class ...)."""
    monkeypatch.setattr(mcp_mod, "_allow_write", True)

    py_file = tmp_path / "app.py"
    py_file.write_text("@app.get('/')\ndef index(): ...\n")

    driver = _patch(monkeypatch, [[]])

    from codegraph.py_parser import PyParser
    from codegraph.schema import (
        EXPOSES, Edge, FileNode, FunctionNode, EndpointNode, ParseResult,
    )

    file_id = f"file:{py_file}"
    ep = EndpointNode(
        method="GET", path="/",
        controller_class=file_id,
        file=str(py_file), handler="index",
    )
    fake_result = ParseResult(
        file=FileNode(path=str(py_file), package="pkg", language="py", loc=2),
        functions=[FunctionNode(name="index", file=str(py_file))],
        endpoints=[ep],
        edges=[Edge(kind=EXPOSES, src_id=file_id, dst_id=ep.id)],
    )

    monkeypatch.setattr(PyParser, "parse_file", lambda *a, **kw: fake_result)

    out = mcp_mod.reindex_file(str(py_file), package="pkg")
    assert out["ok"] is True

    # EXPOSES must use File path match, not Class id match
    exposes_calls = [
        (cypher, params) for cypher, params in driver.session_obj.calls
        if "EXPOSES" in cypher
    ]
    assert len(exposes_calls) >= 1
    file_exposes = [c for c, _ in exposes_calls if "File {path:" in c]
    class_exposes = [c for c, _ in exposes_calls if "Class {id:" in c]
    assert len(file_exposes) == 1
    assert len(class_exposes) == 0

    # No EXPOSES in the generic edge loop
    generic_edge_calls = [
        (cypher, params) for cypher, params in driver.session_obj.calls
        if "MATCH (a {id: $src})" in cypher and "MATCH (b {id: $dst})" in cypher
    ]
    for cypher, _ in generic_edge_calls:
        assert "EXPOSES" not in cypher

    # File + Function + Endpoint = 3 nodes
    assert out["nodes"] == 3
