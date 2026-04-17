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
