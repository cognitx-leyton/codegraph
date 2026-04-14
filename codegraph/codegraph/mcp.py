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
from typing import Any

from mcp.server.fastmcp import FastMCP
from neo4j import READ_ACCESS, GraphDatabase
from neo4j.exceptions import ClientError, CypherSyntaxError, ServiceUnavailable

from .utils.neo4j_json import clean_row


# ── Configuration ───────────────────────────────────────────────────

_URI = os.environ.get("CODEGRAPH_NEO4J_URI", "bolt://localhost:7688")
_USER = os.environ.get("CODEGRAPH_NEO4J_USER", "neo4j")
_PASS = os.environ.get("CODEGRAPH_NEO4J_PASS", "codegraph123")


# ── Driver lifecycle ────────────────────────────────────────────────

_driver = GraphDatabase.driver(_URI, auth=(_USER, _PASS))
"""Module-scoped Neo4j driver. One driver, many sessions — mirrors the
:class:`codegraph.loader.Neo4jLoader` pattern. Tests monkeypatch this
attribute directly."""


def _read_session():
    """Open a read-only session via the module-scoped driver."""
    return _driver.session(default_access_mode=READ_ACCESS)


def _err_msg(e: BaseException) -> str:
    """Extract a human-readable message from a Neo4j exception.

    ``Neo4jError.message`` is the preferred field but is only populated when
    the driver constructs the exception via its internal factory. When an
    exception is built ad-hoc (e.g. in tests) ``message`` is ``None``, so
    fall back to ``str(e)``.
    """
    msg = getattr(e, "message", None)
    return msg if msg else str(e)


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
        return {"error": f"Neo4j rejected query: {e.message}"}
    except ServiceUnavailable as e:
        return {"error": f"Neo4j is unreachable: {e}"}
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


# ── Entry point ─────────────────────────────────────────────────────

def main() -> None:
    """Run the stdio MCP server. Closes the driver on exit."""
    try:
        mcp.run(transport="stdio")
    finally:
        _driver.close()
