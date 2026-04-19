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
          "args": ["--allow-write"],
          "type": "stdio",
          "env": {
            "CODEGRAPH_NEO4J_URI":  "bolt://localhost:7688",
            "CODEGRAPH_NEO4J_USER": "neo4j",
            "CODEGRAPH_NEO4J_PASS": "codegraph123"
          }
        }
      }
    }

Read-only tools use ``neo4j.READ_ACCESS`` sessions so an LLM-generated
``DROP`` or ``DELETE`` query surfaces as a ``ClientError`` rather than
mutating the graph. Two write tools (``reindex_file``, ``wipe_graph``) are
available when ``--allow-write`` is passed on the CLI; without the flag they
return a descriptive error.
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Any, NamedTuple, Optional

from mcp.server.fastmcp import FastMCP
from neo4j import READ_ACCESS, WRITE_ACCESS, Driver, GraphDatabase
from neo4j.exceptions import ClientError, CypherSyntaxError, ServiceUnavailable

from .utils.neo4j_json import clean_row


# ── Query prompt helpers ─────────────────────────────────────────────

_QUERIES_MD = Path(__file__).resolve().parent.parent / "queries.md"


class _QueryEntry(NamedTuple):
    name: str
    description: str
    cypher: str


def _slugify(text: str) -> str:
    """Convert a heading string to a URL-safe slug."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _parse_queries_md(text: str) -> list[_QueryEntry]:
    """Parse fenced ```cypher blocks from *text* into a list of _QueryEntry objects.

    Rules:
    - Each ``## `` heading sets the current section name.
    - Each ` ```cypher ` block under that heading becomes one entry.
    - If multiple blocks share a heading, the second gets suffix ``-2``, etc.
    - The first ``//`` comment line inside a block becomes the description;
      otherwise the heading text is used.
    """
    entries: list[_QueryEntry] = []
    heading: str = ""
    heading_counts: dict[str, int] = {}
    in_block = False
    block_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
        elif line.startswith("```cypher") and not in_block:
            in_block = True
            block_lines = []
        elif line.startswith("```") and in_block:
            in_block = False
            cypher = "\n".join(block_lines).strip()
            if not cypher or not heading:
                continue
            slug = _slugify(heading)
            count = heading_counts.get(slug, 0) + 1
            heading_counts[slug] = count
            name = slug if count == 1 else f"{slug}-{count}"
            # First // comment becomes description; fall back to heading
            description = heading
            for bl in block_lines:
                stripped = bl.strip()
                if stripped.startswith("//"):
                    description = stripped.lstrip("/").strip()
                    break
            entries.append(_QueryEntry(name=name, description=description, cypher=cypher))
        elif in_block:
            block_lines.append(line)

    return entries


def _register_query_prompts(server: FastMCP) -> None:
    """Register each Cypher block from queries.md as a FastMCP prompt."""
    from mcp.server.fastmcp.prompts.base import Prompt

    if not _QUERIES_MD.exists():
        return

    with open(_QUERIES_MD, encoding="utf-8", newline="") as fh:
        entries = _parse_queries_md(fh.read())
    for entry in entries:
        cypher = entry.cypher
        description = entry.description

        def _make_fn(q: str):
            def fn() -> str:
                return q
            return fn

        prompt = Prompt.from_function(
            _make_fn(cypher),
            name=entry.name,
            description=description,
        )
        server.add_prompt(prompt)


# ── Configuration ───────────────────────────────────────────────────

_URI = os.environ.get("CODEGRAPH_NEO4J_URI", "bolt://localhost:7688")
_USER = os.environ.get("CODEGRAPH_NEO4J_USER", "neo4j")
_PASS = os.environ.get("CODEGRAPH_NEO4J_PASS", "codegraph123")

_allow_write: bool = False
"""Set to ``True`` by ``main()`` when ``--allow-write`` is passed on the CLI.
Write tools check this flag and return an error when it is ``False``."""


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


def _write_session():
    """Open a write-enabled session via the module-scoped driver."""
    return _get_driver().session(default_access_mode=WRITE_ACCESS)


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


def _validate_max_depth(max_depth: int, *, max_val: int = 5) -> Optional[str]:
    """Return an error message if ``max_depth`` is out of range, ``None`` if OK.

    Variable-length path bounds cannot be bind parameters in Cypher, so the
    integer is validated here before interpolation — same rationale as
    :func:`_validate_limit`.
    """
    if not isinstance(max_depth, int) or isinstance(max_depth, bool):
        return f"max_depth must be an integer in 1..{max_val}"
    if max_depth < 1 or max_depth > max_val:
        return f"max_depth must be an integer in 1..{max_val}"
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
_register_query_prompts(mcp)


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
        limit: Maximum rows to return (default 20, max 1000).
    """
    err = _validate_limit(limit)
    if err:
        return [{"error": err}]
    return _run_read(cypher)[:limit]


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
    except CypherSyntaxError as e:
        return {"error": f"Cypher syntax error: {_err_msg(e)}"}
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
def callers_of_class(class_name: str, max_depth: int = 1) -> list[dict]:
    """Blast-radius traversal: who reaches the given class transitively?

    Walks ``INJECTS`` / ``EXTENDS`` / ``IMPLEMENTS`` edges in reverse from the
    target class up to ``max_depth`` hops. Returns distinct caller classes
    with their file and backend-role flags.

    Args:
        class_name: Exact ``:Class.name`` to query (e.g. ``"AuthService"``).
        max_depth: Max hops to traverse (1..5, default 1).
    """
    err = _validate_max_depth(max_depth)
    if err:
        return [{"error": err}]
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
    err = _validate_max_depth(max_depth)
    if err:
        return [{"error": err}]
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
    err = _validate_max_depth(max_depth)
    if err:
        return [{"error": err}]
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


# ── Write tools (gated by --allow-write) ──────────────────────────


_WRITE_GATE_MSG = "Write tools require --allow-write flag on codegraph-mcp"


@mcp.tool()
def wipe_graph(confirm: bool = False) -> dict:
    """Wipe all nodes and relationships from the Neo4j graph.

    This is a DESTRUCTIVE operation. The server must be started with
    ``--allow-write`` and the caller must pass ``confirm=True``.

    Args:
        confirm: Must be ``True`` to proceed. Safety guard against
            accidental invocation.
    """
    if not _allow_write:
        return {"error": _WRITE_GATE_MSG}
    if not confirm:
        return {"error": "Pass confirm=True to wipe the entire graph"}
    try:
        with _write_session() as s:
            s.run("MATCH (n) DETACH DELETE n")
    except ClientError as e:
        return {"error": f"Neo4j rejected query: {_err_msg(e)}"}
    except ServiceUnavailable as e:
        return {"error": f"Neo4j is unreachable: {e}"}
    return {"ok": True, "action": "wipe"}


@mcp.tool()
def reindex_file(path: str, package: Optional[str] = None) -> dict:
    """Re-index a single file: delete its old subgraph, parse it, and reload.

    Refreshes the file's nodes (classes, functions, methods, etc.) and
    intra-file edges. Cross-file edges (IMPORTS, CALLS across files) are
    NOT refreshed — run a full ``codegraph index`` for that.

    The server must be started with ``--allow-write``.

    Args:
        path: Repo-relative file path (e.g. ``"codegraph/codegraph/mcp.py"``).
            Must end in ``.py``, ``.ts``, or ``.tsx``.
        package: Package name to associate the file with. If omitted, looked
            up from the existing ``:File`` node in the graph.
    """
    if not _allow_write:
        return {"error": _WRITE_GATE_MSG}

    # ── Validate extension ──────────────────────────────────────
    allowed_exts = (".py", ".ts", ".tsx")
    if not any(path.endswith(ext) for ext in allowed_exts):
        return {"error": "path must end in .py, .ts, or .tsx"}

    # ── Resolve package from graph if not provided ──────────────
    if package is None:
        rows = _run_read(
            "MATCH (f:File {path: $path}) RETURN f.package AS pkg",
            path=path,
        )
        if rows and "error" in rows[0]:
            return rows[0]
        if rows and "pkg" in rows[0] and rows[0]["pkg"]:
            package = rows[0]["pkg"]
        else:
            return {
                "error": f"File {path} not found in graph and no package specified"
            }

    # ── Locate file on disk ─────────────────────────────────────
    abs_path = Path(path)
    if not abs_path.is_absolute():
        abs_path = Path.cwd() / path
    if not abs_path.is_file():
        return {"error": f"File not found on disk: {abs_path}"}

    # ── Detect test file ────────────────────────────────────────
    from .schema import PY_TEST_PREFIX, PY_TEST_SUFFIX_TRAILING, TS_TEST_SUFFIXES

    name_lower = abs_path.name.lower()
    if path.endswith(".py"):
        is_test = (
            name_lower.startswith(PY_TEST_PREFIX)
            or name_lower.endswith(PY_TEST_SUFFIX_TRAILING)
        )
    else:
        is_test = any(name_lower.endswith(suf) for suf in TS_TEST_SUFFIXES)

    # ── Parse ───────────────────────────────────────────────────
    try:
        if path.endswith(".py"):
            from .py_parser import PyParser

            result = PyParser().parse_file(abs_path, path, package, is_test=is_test)
        else:
            from .parser import TsParser

            result = TsParser().parse_file(abs_path, path, package, is_test=is_test)
    except Exception as e:
        return {"error": f"Parse failed: {e}"}

    if result is None:
        return {"error": f"Parser returned no result for {path}"}

    # ── Delete old subgraph (3-step DETACH DELETE) ───────────────
    try:
        with _write_session() as s:
            # 1. Grandchildren of owned classes (Methods, Endpoints, etc.)
            s.run(
                "MATCH (f:File {path: $path})-[:DEFINES_CLASS]->(c:Class)-->(child) "
                "WHERE NOT child:Class AND NOT child:Decorator "
                "DETACH DELETE child",
                path=path,
            )
            # 2. Direct owned children (Classes, Functions, Interfaces, Atoms)
            s.run(
                "MATCH (f:File {path: $path})"
                "-[:DEFINES_CLASS|DEFINES_FUNC|DEFINES_IFACE|DEFINES_ATOM]->(child) "
                "DETACH DELETE child",
                path=path,
            )
            # 3. File node (DETACH DELETE auto-removes IMPORTS, BELONGS_TO, etc.)
            s.run(
                "MATCH (f:File {path: $path}) DETACH DELETE f",
                path=path,
            )

            # ── Load new nodes ──────────────────────────────────
            f = result.file
            s.run(
                "MERGE (n:File {path: $path}) "
                "SET n.package = $package, n.language = $language, "
                "    n.loc = $loc, n.is_controller = $is_controller, "
                "    n.is_injectable = $is_injectable, n.is_module = $is_module, "
                "    n.is_component = $is_component, n.is_entity = $is_entity, "
                "    n.is_resolver = $is_resolver, n.is_test = $is_test",
                path=f.path, package=f.package, language=f.language,
                loc=f.loc, is_controller=f.is_controller,
                is_injectable=f.is_injectable, is_module=f.is_module,
                is_component=f.is_component, is_entity=f.is_entity,
                is_resolver=f.is_resolver, is_test=f.is_test,
            )

            node_count = 1  # the File node

            for c in result.classes:
                s.run(
                    "MERGE (n:Class {id: $id}) "
                    "SET n.name = $name, n.file = $file, "
                    "    n.is_controller = $is_controller, "
                    "    n.is_injectable = $is_injectable, "
                    "    n.is_module = $is_module, n.is_entity = $is_entity, "
                    "    n.is_resolver = $is_resolver, "
                    "    n.is_abstract = $is_abstract, "
                    "    n.base_path = $base_path, n.table_name = $table_name "
                    "WITH n "
                    "MATCH (f:File {path: $file}) "
                    "MERGE (f)-[:DEFINES_CLASS]->(n)",
                    id=c.id, name=c.name, file=c.file,
                    is_controller=c.is_controller,
                    is_injectable=c.is_injectable,
                    is_module=c.is_module, is_entity=c.is_entity,
                    is_resolver=c.is_resolver, is_abstract=c.is_abstract,
                    base_path=c.base_path, table_name=c.table_name,
                )
                node_count += 1

            for fn in result.functions:
                s.run(
                    "MERGE (n:Function {id: $id}) "
                    "SET n.name = $name, n.file = $file, "
                    "    n.is_component = $is_component, "
                    "    n.exported = $exported, "
                    "    n.docstring = $docstring, "
                    "    n.return_type = $return_type, "
                    "    n.params_json = $params_json "
                    "WITH n "
                    "MATCH (f:File {path: $file}) "
                    "MERGE (f)-[:DEFINES_FUNC]->(n)",
                    id=fn.id, name=fn.name, file=fn.file,
                    is_component=fn.is_component, exported=fn.exported,
                    docstring=fn.docstring, return_type=fn.return_type,
                    params_json=fn.params_json,
                )
                node_count += 1

            for m in result.methods:
                s.run(
                    "MERGE (n:Method {id: $id}) "
                    "SET n.name = $name, n.file = $file, "
                    "    n.is_static = $is_static, n.is_async = $is_async, "
                    "    n.is_constructor = $is_constructor, "
                    "    n.visibility = $visibility, "
                    "    n.return_type = $return_type, "
                    "    n.params_json = $params_json, "
                    "    n.docstring = $docstring "
                    "WITH n "
                    "MATCH (c:Class {id: $class_id}) "
                    "MERGE (c)-[:HAS_METHOD]->(n)",
                    id=m.id, name=m.name, file=m.file,
                    class_id=m.class_id, is_static=m.is_static,
                    is_async=m.is_async,
                    is_constructor=m.is_constructor,
                    visibility=m.visibility,
                    return_type=m.return_type,
                    params_json=m.params_json,
                    docstring=m.docstring,
                )
                node_count += 1

            for i in result.interfaces:
                s.run(
                    "MERGE (n:Interface {id: $id}) "
                    "SET n.name = $name, n.file = $file "
                    "WITH n "
                    "MATCH (f:File {path: $file}) "
                    "MERGE (f)-[:DEFINES_IFACE]->(n)",
                    id=i.id, name=i.name, file=i.file,
                )
                node_count += 1

            for ep in result.endpoints:
                s.run(
                    "MERGE (e:Endpoint {id: $id}) "
                    "SET e.method = $method, e.path = $epath, "
                    "    e.handler = $handler, e.file = $file "
                    "WITH e "
                    "MATCH (c:Class {id: $cls}) "
                    "MERGE (c)-[:EXPOSES]->(e)",
                    id=ep.id, method=ep.method, epath=ep.path,
                    handler=ep.handler, file=ep.file,
                    cls=ep.controller_class,
                )
                node_count += 1

            for gql in result.gql_operations:
                s.run(
                    "MERGE (o:GraphQLOperation {id: $id}) "
                    "SET o.type = $type, o.name = $name, "
                    "    o.return_type = $return_type, "
                    "    o.handler = $handler, o.file = $file "
                    "WITH o "
                    "MATCH (c:Class {id: $cls}) "
                    "MERGE (c)-[:RESOLVES]->(o)",
                    id=gql.id, type=gql.op_type, name=gql.name,
                    return_type=gql.return_type, handler=gql.handler,
                    file=gql.file, cls=gql.resolver_class,
                )
                node_count += 1

            for col in result.columns:
                s.run(
                    "MERGE (c:Column {id: $id}) "
                    "SET c.name = $name, c.type = $type, "
                    "    c.nullable = $nullable, c.unique = $uniq, "
                    "    c.primary = $primary, c.generated = $generated "
                    "WITH c "
                    "MATCH (e:Class {id: $entity_id}) "
                    "MERGE (e)-[:HAS_COLUMN]->(c)",
                    id=col.id, entity_id=col.entity_id,
                    name=col.name, type=col.type,
                    nullable=col.nullable, uniq=col.unique,
                    primary=col.primary, generated=col.generated,
                )
                node_count += 1

            for a in result.atoms:
                s.run(
                    "MERGE (n:Atom {id: $id}) "
                    "SET n.name = $name, n.file = $file, n.family = $family "
                    "WITH n "
                    "MATCH (f:File {path: $file}) "
                    "MERGE (f)-[:DEFINES_ATOM]->(n)",
                    id=a.id, name=a.name, file=a.file, family=a.family,
                )
                node_count += 1

            # ── Load intra-file edges ───────────────────────────
            from .schema import (
                IMPORTS, IMPORTS_SYMBOL, IMPORTS_EXTERNAL,
                EXPOSES, HANDLES, INJECTS,
                EXTENDS, IMPLEMENTS, DECORATED_BY,
                RENDERS, USES_HOOK,
                RELATES_TO, REPOSITORY_OF,
                RETURNS, CALLS_ENDPOINT, USES_OPERATION,
                CALLS,
                PROVIDES, EXPORTS_PROVIDER, IMPORTS_MODULE,
                DECLARES_CONTROLLER,
                TESTS, TESTS_CLASS, HANDLES_EVENT, EMITS_EVENT,
                LAST_MODIFIED_BY, CONTRIBUTED_BY, OWNED_BY,
                READS_ATOM, WRITES_ATOM, READS_ENV,
                BELONGS_TO,
            )
            # HAS_METHOD, RESOLVES, HAS_COLUMN are written inline during
            # node-creation MERGEs above — excluded here to avoid double-write.
            # EXPOSES stays: file-level endpoints (no owning class) need the
            # generic loop because the inline MATCH (c:Class ...) silently fails.
            _EDGE_WHITELIST = frozenset({
                IMPORTS, IMPORTS_SYMBOL, IMPORTS_EXTERNAL,
                EXPOSES, HANDLES, INJECTS,
                EXTENDS, IMPLEMENTS, DECORATED_BY,
                RENDERS, USES_HOOK,
                RELATES_TO, REPOSITORY_OF,
                RETURNS, CALLS_ENDPOINT, USES_OPERATION,
                CALLS,
                PROVIDES, EXPORTS_PROVIDER, IMPORTS_MODULE,
                DECLARES_CONTROLLER,
                TESTS, TESTS_CLASS, HANDLES_EVENT, EMITS_EVENT,
                LAST_MODIFIED_BY, CONTRIBUTED_BY, OWNED_BY,
                READS_ATOM, WRITES_ATOM, READS_ENV,
                BELONGS_TO,
            })

            edge_count = 0
            for edge in result.edges:
                if edge.kind not in _EDGE_WHITELIST:
                    continue

                if edge.kind == DECORATED_BY:
                    # Decorator nodes are keyed on name, not id.
                    # dst_id has shape "dec:<decorator_name>".
                    dname = edge.dst_id[len("dec:"):]
                    s.run(
                        "MERGE (d:Decorator {name: $name})",
                        name=dname,
                    )
                    if edge.src_id.startswith("class:"):
                        label = "Class"
                    elif edge.src_id.startswith("func:"):
                        label = "Function"
                    elif edge.src_id.startswith("method:"):
                        label = "Method"
                    else:
                        continue
                    s.run(
                        f"MATCH (a:{label} {{id: $src}}) "
                        f"MATCH (d:Decorator {{name: $name}}) "
                        f"MERGE (a)-[:DECORATED_BY]->(d)",
                        src=edge.src_id, name=dname,
                    )
                else:
                    s.run(
                        f"MATCH (a {{id: $src}}) "
                        f"MATCH (b {{id: $dst}}) "
                        f"MERGE (a)-[:{edge.kind}]->(b)",
                        src=edge.src_id, dst=edge.dst_id,
                    )
                edge_count += 1

    except ClientError as e:
        return {"error": f"Neo4j rejected query: {_err_msg(e)}"}
    except ServiceUnavailable as e:
        return {"error": f"Neo4j is unreachable: {e}"}

    return {"ok": True, "file": path, "nodes": node_count, "edges": edge_count}


# ── Entry point ─────────────────────────────────────────────────────

def main() -> None:
    """Run the stdio MCP server. Closes the driver on exit (if constructed)."""
    global _allow_write
    parser = argparse.ArgumentParser(prog="codegraph-mcp")
    parser.add_argument(
        "--allow-write", action="store_true",
        help="Enable write tools (reindex_file, wipe_graph).",
    )
    args = parser.parse_args()
    _allow_write = args.allow_write
    try:
        mcp.run(transport="stdio")
    finally:
        if _driver is not None:
            _driver.close()
