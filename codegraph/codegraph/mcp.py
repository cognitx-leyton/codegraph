"""Stdio MCP server exposing the codegraph Neo4j graph to LLM coding agents.

Registered as a console script via ``pyproject.toml``::

    [project.scripts]
    codegraph-mcp = "codegraph.mcp:main"

Install with::

    pip install "codegraph[mcp]"

Then add to ``~/.claude.json``::

    {
      "mcpServers": {
        "codegraph": {
          "command": "codegraph-mcp",
          "type": "stdio",
          "env": {
            "CODEGRAPH_NEO4J_URI":  "bolt://localhost:7688",
            "CODEGRAPH_NEO4J_USER": "neo4j",
            "CODEGRAPH_NEO4J_PASS": "codegraph123"
          }
        }
      }
    }

All tools are read-only: every session is opened with
``default_access_mode=neo4j.READ_ACCESS`` so an LLM-generated ``DROP`` or
``DELETE`` query will surface as a Neo4j ``ClientError`` rather than mutating
the graph.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from neo4j import READ_ACCESS, Driver, GraphDatabase
from neo4j.exceptions import ClientError, CypherSyntaxError, ServiceUnavailable

from .utils.neo4j_json import clean_row


# ── Configuration ───────────────────────────────────────────────────

_URI = os.environ.get("CODEGRAPH_NEO4J_URI", "bolt://localhost:7688")
_USER = os.environ.get("CODEGRAPH_NEO4J_USER", "neo4j")
_PASS = os.environ.get("CODEGRAPH_NEO4J_PASS", "codegraph123")


# ── Driver lifecycle ────────────────────────────────────────────────

_driver: "Driver | None" = None
"""Module-scoped Neo4j driver. Lazily constructed on first tool call so that
``import codegraph.mcp`` can succeed even when Neo4j is unreachable or the
env vars are mis-set — the error surfaces as a tool-call error instead of
an import-time traceback that kills the MCP server before Claude Code can
see it. Tests monkeypatch this attribute with a fake driver directly."""


def _get_driver() -> "Driver":
    """Return the module-scoped driver, constructing it on first use."""
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(_URI, auth=(_USER, _PASS))
    return _driver


def _read_session():
    """Open a read-only session via the module-scoped driver."""
    return _get_driver().session(default_access_mode=READ_ACCESS)


def _err_msg(e: BaseException) -> str:
    """Extract a human-readable message from a Neo4j exception.

    ``Neo4jError.message`` is the preferred field but is only populated when
    the driver constructs the exception via its internal factory. When an
    exception is built ad-hoc (e.g. in tests) ``message`` is ``None``, so
    fall back to ``str(e)``.
    """
    msg = getattr(e, "message", None)
    return msg if msg else str(e)


def _validate_limit(limit: int, *, max_limit: int = 1000) -> Optional[str]:
    """Return an error message if ``limit`` is out of range, ``None`` if OK.

    Limits must be interpolated into the Cypher string rather than passed as
    a bind parameter — Neo4j 5.x rejects ``LIMIT $param`` as a syntax error,
    so the only way to parameterise is to interpolate. Every caller must
    validate through this helper before building the Cypher to close the
    injection surface: if the agent passes a non-int, we reject cleanly
    instead of letting it land as a format-string exception.
    """
    if not isinstance(limit, int) or isinstance(limit, bool):
        return f"limit must be an integer in 1..{max_limit}"
    if limit < 1 or limit > max_limit:
        return f"limit must be an integer in 1..{max_limit}"
    return None


def _run_read(cypher: str, **params: Any) -> list[dict]:
    """Execute a read-only Cypher query and return JSON-clean rows.

    Catches every Neo4j exception we know how to recover from and returns
    ``[{"error": "..."}]`` so the calling agent can reason about the failure
    instead of having the MCP client surface a tool-call error.
    """
    try:
        with _read_session() as s:
            records = list(s.run(cypher, **params))
    except CypherSyntaxError as e:
        return [{"error": f"Cypher syntax error: {_err_msg(e)}"}]
    except ClientError as e:
        return [{"error": f"Neo4j rejected query: {_err_msg(e)}"}]
    except ServiceUnavailable as e:
        return [{"error": f"Neo4j is unreachable: {e}"}]
    return [clean_row(r) for r in records]


# ── FastMCP server + tools ──────────────────────────────────────────

mcp = FastMCP("codegraph")


@mcp.tool()
def query_graph(cypher: str, limit: int = 20) -> list[dict]:
    """Run a read-only Cypher query against the codegraph Neo4j database.

    Writes (CREATE/MERGE/DELETE/SET) are rejected by the server because the
    underlying session is read-only. Returns up to ``limit`` rows, each a flat
    dict of column → JSON-safe value. Neo4j ``Node`` / ``Relationship`` values
    are unwrapped to their property dict.

    Args:
        cypher: Cypher query string. Example:
            ``MATCH (c:Class {is_controller:true}) RETURN c.name LIMIT 10``
        limit: Maximum rows to return (default 20, cap 1000).
    """
    if not isinstance(limit, int) or limit < 1:
        return [{"error": "limit must be a positive integer"}]
    limit = min(limit, 1000)
    try:
        with _read_session() as s:
            records = list(s.run(cypher))[:limit]
    except CypherSyntaxError as e:
        return [{"error": f"Cypher syntax error: {_err_msg(e)}"}]
    except ClientError as e:
        return [{"error": f"Neo4j rejected query: {_err_msg(e)}"}]
    except ServiceUnavailable as e:
        return [{"error": f"Neo4j is unreachable: {e}"}]
    return [clean_row(r) for r in records]


@mcp.tool()
def describe_schema() -> dict:
    """Return labels, relationship types, and node counts per label.

    Agents should call this once at session start to learn what's in the graph
    instead of guessing from documentation. Shape:

        {
          "labels":    ["File", "Class", "Function", ...],
          "rel_types": ["IMPORTS", "DEFINES_CLASS", ...],
          "counts":    {"File": 1234, "Class": 567, ...},
        }
    """
    try:
        with _read_session() as s:
            labels = [r["label"] for r in s.run("CALL db.labels() YIELD label RETURN label ORDER BY label")]
            rel_types = [
                r["relationshipType"]
                for r in s.run(
                    "CALL db.relationshipTypes() YIELD relationshipType "
                    "RETURN relationshipType ORDER BY relationshipType"
                )
            ]
            count_rows = list(s.run(
                "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n"
            ))
    except ClientError as e:
        return {"error": f"Neo4j rejected query: {_err_msg(e)}"}
    except ServiceUnavailable as e:
        return {"error": f"Neo4j is unreachable: {_err_msg(e)}"}
    counts = {r["label"]: r["n"] for r in count_rows if r["label"]}
    return {"labels": labels, "rel_types": rel_types, "counts": counts}


@mcp.tool()
def list_packages() -> list[dict]:
    """Return every indexed monorepo package with its detected framework.

    Fields: ``name``, ``framework``, ``framework_version``, ``typescript``,
    ``package_manager``, ``confidence``. Ordered by package name. Empty list
    if no packages have been detected yet (run ``codegraph index`` first).
    """
    return _run_read(
        "MATCH (p:Package) "
        "RETURN p.name AS name, p.framework AS framework, "
        "       p.framework_version AS framework_version, "
        "       p.typescript AS typescript, "
        "       p.package_manager AS package_manager, "
        "       p.confidence AS confidence "
        "ORDER BY p.name"
    )


@mcp.tool()
def callers_of_class(class_name: str, max_depth: int = 3) -> list[dict]:
    """Blast-radius traversal: who reaches the given class transitively?

    Walks ``INJECTS`` / ``EXTENDS`` / ``IMPLEMENTS`` edges in reverse from the
    target class up to ``max_depth`` hops. Returns distinct caller classes
    with their file and backend-role flags.

    Args:
        class_name: Exact ``:Class.name`` to query (e.g. ``"AuthService"``).
        max_depth: Max hops to traverse (1..10, default 3).
    """
    if not isinstance(max_depth, int) or not 1 <= max_depth <= 10:
        return [{"error": "max_depth must be an integer in 1..10"}]
    # Variable-length path bounds cannot be bind parameters in Cypher; the
    # integer is validated above before we interpolate it.
    cypher = (
        f"MATCH (caller:Class)-[:INJECTS|EXTENDS|IMPLEMENTS*1..{max_depth}]->"
        "(target:Class {name: $class_name}) "
        "RETURN DISTINCT caller.name AS name, caller.file AS file, "
        "       caller.is_injectable AS is_injectable, "
        "       caller.is_controller AS is_controller "
        "ORDER BY caller.name"
    )
    return _run_read(cypher, class_name=class_name)


@mcp.tool()
def endpoints_for_controller(controller_name: str) -> list[dict]:
    """Return the HTTP endpoints exposed by a NestJS controller class.

    Args:
        controller_name: Exact ``:Class.name`` of the controller
            (e.g. ``"UserController"``). Must have ``is_controller=true``.
    """
    return _run_read(
        "MATCH (c:Class {name: $controller_name, is_controller: true})"
        "-[:EXPOSES]->(e:Endpoint) "
        "RETURN e.method AS method, e.path AS path, e.handler AS handler "
        "ORDER BY e.path",
        controller_name=controller_name,
    )


@mcp.tool()
def files_in_package(name: str, limit: int = 50) -> list[dict]:
    """List files belonging to a monorepo package.

    Uses the existing ``file_package`` property index directly rather than
    hopping through ``:BELONGS_TO`` — faster, same result. Returns an empty
    list for unknown package names (no error; the empty result *is* the
    answer).

    Args:
        name: Exact ``:Package.name`` (equivalently ``:File.package``), e.g.
            ``"twenty-server"`` or ``"packages/web"`` depending on how the
            monorepo was configured.
        limit: Max rows to return. Integer in 1..1000, default 50.
    """
    err = _validate_limit(limit)
    if err:
        return [{"error": err}]
    cypher = (
        "MATCH (f:File {package: $name}) "
        "RETURN f.path AS path, f.language AS language, f.loc AS loc, "
        "       f.is_controller AS is_controller, f.is_component AS is_component, "
        "       f.is_injectable AS is_injectable, f.is_module AS is_module, "
        "       f.is_entity AS is_entity "
        f"ORDER BY f.path LIMIT {limit}"
    )
    return _run_read(cypher, name=name)


@mcp.tool()
def hook_usage(hook_name: str, limit: int = 50) -> list[dict]:
    """Return the functions / components that use a given React hook.

    Direction in the graph is ``(:Function)-[:USES_HOOK]->(:Hook)``.
    ``fn.is_component`` is included so the agent can tell apart true React
    components from helper functions that happen to live in the same file.

    Args:
        hook_name: Exact ``:Hook.name`` (e.g. ``"useAuth"``, ``"useDeepMemo"``).
            Only custom hooks that codegraph detected are present as
            ``:Hook`` nodes — built-in React hooks like ``useState`` are
            imports, not nodes.
        limit: Max rows to return. Integer in 1..1000, default 50.
    """
    err = _validate_limit(limit)
    if err:
        return [{"error": err}]
    cypher = (
        "MATCH (fn:Function)-[:USES_HOOK]->(:Hook {name: $hook_name}) "
        "RETURN DISTINCT fn.name AS name, fn.file AS file, "
        "       fn.is_component AS is_component, "
        "       fn.docstring AS docstring, "
        "       fn.params_json AS params_json, "
        "       fn.return_type AS return_type "
        f"ORDER BY fn.name LIMIT {limit}"
    )
    return _run_read(cypher, hook_name=hook_name)


_GQL_OP_TYPES = ("query", "mutation", "subscription")


@mcp.tool()
def gql_operation_callers(
    op_name: str,
    op_type: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Return callers of a GraphQL operation (query / mutation / subscription).

    Direction in the graph is ``(caller)-[:USES_OPERATION]->(:GraphQLOperation)``.
    ``op_name`` alone may match multiple operations if the same name exists
    across query / mutation / subscription types — pass ``op_type`` to narrow.

    ``labels(caller)[0]`` is returned as ``caller_kind`` so the agent can tell
    apart ``Function`` / ``Method`` / ``Class`` callers without a second query.

    Args:
        op_name: Exact ``:GraphQLOperation.name``, e.g. ``"findManyUsers"``.
        op_type: Optional filter, one of ``"query"``, ``"mutation"``,
            ``"subscription"``. ``None`` (default) returns callers across all
            three types.
        limit: Max rows to return. Integer in 1..1000, default 50.
    """
    err = _validate_limit(limit)
    if err:
        return [{"error": err}]
    if op_type is not None and op_type not in _GQL_OP_TYPES:
        return [{
            "error": "op_type must be one of 'query' | 'mutation' | 'subscription'"
        }]
    cypher = (
        "MATCH (caller)-[:USES_OPERATION]->(op:GraphQLOperation {name: $op_name}) "
        "WHERE $op_type IS NULL OR op.type = $op_type "
        "RETURN DISTINCT caller.name AS caller_name, caller.file AS caller_file, "
        "       labels(caller)[0] AS caller_kind, "
        "       caller.docstring AS caller_docstring, "
        "       caller.params_json AS caller_params_json, "
        "       op.type AS op_type, op.return_type AS return_type "
        f"ORDER BY caller.name LIMIT {limit}"
    )
    return _run_read(cypher, op_name=op_name, op_type=op_type)


@mcp.tool()
def most_injected_services(limit: int = 20) -> list[dict]:
    """Rank ``@Injectable`` classes by number of unique callers.

    The canonical "DI hub detection" query advertised on the codegraph README
    front page. Counts distinct caller classes (not raw edges) so a caller
    injecting the same service into multiple methods still counts once.

    Args:
        limit: Max rows to return. Integer in 1..100, default 20. Tighter
            cap than the other tools — nobody wants 1000 hubs.
    """
    err = _validate_limit(limit, max_limit=100)
    if err:
        return [{"error": err}]
    cypher = (
        "MATCH (svc:Class {is_injectable: true})<-[:INJECTS]-(caller:Class) "
        "RETURN svc.name AS name, svc.file AS file, "
        "       count(DISTINCT caller) AS injections, "
        "       svc.is_controller AS is_controller "
        f"ORDER BY injections DESC LIMIT {limit}"
    )
    return _run_read(cypher)


@mcp.tool()
def find_class(name_pattern: str, limit: int = 50) -> list[dict]:
    """Case-sensitive substring search over class names.

    Backed by the ``class_name`` index so ``CONTAINS`` stays cheap. Bypassing
    the index via ``toLower()`` for case-insensitive matching would turn this
    into a full scan; agents can retry with the correct case instead.

    Args:
        name_pattern: Non-empty substring to match against ``:Class.name``.
            Empty strings are rejected — they'd match every class in the graph.
        limit: Max rows to return. Integer in 1..1000, default 50.
    """
    if not name_pattern:
        return [{"error": "name_pattern must be non-empty"}]
    err = _validate_limit(limit)
    if err:
        return [{"error": err}]
    cypher = (
        "MATCH (c:Class) WHERE c.name CONTAINS $name_pattern "
        "RETURN c.name AS name, c.file AS file, "
        "       c.is_controller AS is_controller, c.is_injectable AS is_injectable, "
        "       c.is_module AS is_module, c.is_entity AS is_entity, "
        "       c.is_resolver AS is_resolver "
        f"ORDER BY c.name LIMIT {limit}"
    )
    return _run_read(cypher, name_pattern=name_pattern)


@mcp.tool()
def calls_from(
    name: str,
    file: Optional[str] = None,
    max_depth: int = 1,
    limit: int = 50,
) -> list[dict]:
    """Return what a function/method calls, optionally transitively.

    Walks outgoing ``:CALLS`` edges from every ``:Function`` / ``:Method`` node
    whose ``name`` matches. Targets can be functions, methods, or ``:External``
    nodes (unresolved calls — stdlib, builtins, dynamic). Use ``file`` to
    disambiguate collisions across modules.

    Args:
        name: Exact ``:Function.name`` or ``:Method.name`` to traverse from.
        file: Optional exact file path to narrow the source node.
        max_depth: 1 for direct calls, up to 5 for transitive reach.
        limit: Max rows to return. Integer in 1..1000, default 50.
    """
    if not isinstance(max_depth, int) or not 1 <= max_depth <= 5:
        return [{"error": "max_depth must be an integer in 1..5"}]
    err = _validate_limit(limit)
    if err:
        return [{"error": err}]
    cypher = (
        "MATCH (src) WHERE (src:Function OR src:Method) AND src.name = $name "
        "  AND ($file IS NULL OR src.file = $file) "
        f"MATCH (src)-[:CALLS*1..{max_depth}]->(dst) "
        "RETURN DISTINCT labels(dst)[0] AS kind, dst.name AS name, "
        "       coalesce(dst.file, '') AS file, "
        "       coalesce(dst.docstring, '') AS docstring "
        f"ORDER BY file, name LIMIT {limit}"
    )
    return _run_read(cypher, name=name, file=file)


@mcp.tool()
def callers_of(
    name: str,
    file: Optional[str] = None,
    max_depth: int = 1,
    limit: int = 50,
) -> list[dict]:
    """Return who calls a function/method, optionally transitively.

    Walks incoming ``:CALLS`` edges in reverse to the named target. Callers
    are always ``:Function`` or ``:Method`` — only those emit calls. Use
    ``file`` to disambiguate collisions.

    Args:
        name: Exact ``:Function.name`` or ``:Method.name`` to find callers of.
        file: Optional exact file path to narrow the target node.
        max_depth: 1 for direct callers, up to 5 for transitive reach.
        limit: Max rows to return. Integer in 1..1000, default 50.
    """
    if not isinstance(max_depth, int) or not 1 <= max_depth <= 5:
        return [{"error": "max_depth must be an integer in 1..5"}]
    err = _validate_limit(limit)
    if err:
        return [{"error": err}]
    cypher = (
        "MATCH (dst) WHERE (dst:Function OR dst:Method) AND dst.name = $name "
        "  AND ($file IS NULL OR dst.file = $file) "
        f"MATCH (src)-[:CALLS*1..{max_depth}]->(dst) "
        "WHERE src:Function OR src:Method "
        "RETURN DISTINCT labels(src)[0] AS kind, src.name AS name, src.file AS file "
        f"ORDER BY src.file, src.name LIMIT {limit}"
    )
    return _run_read(cypher, name=name, file=file)


@mcp.tool()
def describe_function(name: str, file: Optional[str] = None) -> list[dict]:
    """Return rich signature info for functions and methods matching ``name``.

    Projects ``docstring``, ``params_json``, ``return_type`` and the list of
    decorator names so an agent can answer "what does X do" in one tool call
    instead of reading the source. Matches both ``:Function`` and ``:Method``
    nodes. The same name may exist in several files — pass ``file`` to
    narrow, otherwise every match is returned.

    Args:
        name: Exact ``:Function.name`` or ``:Method.name``.
        file: Optional exact file path (``:File.path``) to disambiguate
            collisions across modules.
    """
    cypher = (
        "MATCH (n) WHERE (n:Function OR n:Method) AND n.name = $name "
        "  AND ($file IS NULL OR n.file = $file) "
        "OPTIONAL MATCH (n)-[:DECORATED_BY]->(d:Decorator) "
        "WITH n, collect(DISTINCT d.name) AS decorators "
        "RETURN labels(n)[0] AS kind, n.name AS name, n.file AS file, "
        "       n.docstring AS docstring, n.params_json AS params_json, "
        "       n.return_type AS return_type, decorators "
        "ORDER BY n.file, n.name"
    )
    return _run_read(cypher, name=name, file=file)


# ── Entry point ─────────────────────────────────────────────────────

def main() -> None:
    """Run the stdio MCP server. Closes the driver on exit (if constructed)."""
    try:
        mcp.run(transport="stdio")
    finally:
        if _driver is not None:
            _driver.close()
