"""Neo4j writer: constraints, batched UNWIND-MERGE, idempotent. Phases 1-8."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from neo4j import Driver, GraphDatabase

from .resolver import Index
from .schema import (
    CALLS,
    CALLS_ENDPOINT,
    CONTRIBUTED_BY,
    DECLARES_CONTROLLER,
    DECORATED_BY,
    DEFINES_CLASS,
    DEFINES_FUNC,
    DEFINES_ATOM,
    DEFINES_IFACE,
    Edge,
    EMITS_EVENT,
    EXPOSES,
    EXPORTS_PROVIDER,
    EXTENDS,
    HANDLES,
    HANDLES_EVENT,
    HAS_COLUMN,
    HAS_METHOD,
    IMPLEMENTS,
    IMPORTS,
    IMPORTS_EXTERNAL,
    IMPORTS_MODULE,
    IMPORTS_SYMBOL,
    INJECTS,
    LAST_MODIFIED_BY,
    OWNED_BY,
    PROVIDES,
    READS_ATOM,
    READS_ENV,
    RELATES_TO,
    RENDERS,
    RENDERS_COMPONENT,
    REPOSITORY_OF,
    RESOLVES,
    RETURNS,
    TESTS,
    TESTS_CLASS,
    USES_HOOK,
    USES_OPERATION,
    WRITES_ATOM,
)


BATCH = 1000


_CONSTRAINTS = [
    "CREATE CONSTRAINT file_path IF NOT EXISTS FOR (n:File) REQUIRE n.path IS UNIQUE",
    "CREATE CONSTRAINT class_id IF NOT EXISTS FOR (n:Class) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT func_id IF NOT EXISTS FOR (n:Function) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT method_id IF NOT EXISTS FOR (n:Method) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT iface_id IF NOT EXISTS FOR (n:Interface) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT endpoint_id IF NOT EXISTS FOR (n:Endpoint) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT gqlop_id IF NOT EXISTS FOR (n:GraphQLOperation) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT column_id IF NOT EXISTS FOR (n:Column) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT atom_id IF NOT EXISTS FOR (n:Atom) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT envvar_name IF NOT EXISTS FOR (n:EnvVar) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT event_name IF NOT EXISTS FOR (n:Event) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT external_spec IF NOT EXISTS FOR (n:External) REQUIRE n.specifier IS UNIQUE",
    "CREATE CONSTRAINT hook_name IF NOT EXISTS FOR (n:Hook) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT decorator_name IF NOT EXISTS FOR (n:Decorator) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT author_email IF NOT EXISTS FOR (n:Author) REQUIRE n.email IS UNIQUE",
    "CREATE CONSTRAINT team_name IF NOT EXISTS FOR (n:Team) REQUIRE n.name IS UNIQUE",
    "CREATE CONSTRAINT route_id IF NOT EXISTS FOR (n:Route) REQUIRE n.id IS UNIQUE",
]

_INDEXES = [
    "CREATE INDEX class_name IF NOT EXISTS FOR (n:Class) ON (n.name)",
    "CREATE INDEX func_name IF NOT EXISTS FOR (n:Function) ON (n.name)",
    "CREATE INDEX method_name IF NOT EXISTS FOR (n:Method) ON (n.name)",
    "CREATE INDEX file_package IF NOT EXISTS FOR (n:File) ON (n.package)",
    "CREATE INDEX endpoint_path IF NOT EXISTS FOR (n:Endpoint) ON (n.path)",
    "CREATE INDEX class_file IF NOT EXISTS FOR (n:Class) ON (n.file)",
    "CREATE INDEX gqlop_name IF NOT EXISTS FOR (n:GraphQLOperation) ON (n.name)",
]


@dataclass
class LoadStats:
    files: int = 0
    classes: int = 0
    functions: int = 0
    methods: int = 0
    interfaces: int = 0
    endpoints: int = 0
    externals: int = 0
    columns: int = 0
    gql_operations: int = 0
    atoms: int = 0
    edges: dict = field(default_factory=dict)


class Neo4jLoader:
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j") -> None:
        self.driver: Driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database

    def close(self) -> None:
        self.driver.close()

    def init_schema(self) -> None:
        with self.driver.session(database=self.database) as s:
            for stmt in _CONSTRAINTS + _INDEXES:
                s.run(stmt)

    def wipe(self) -> None:
        with self.driver.session(database=self.database) as s:
            s.run("MATCH (n) DETACH DELETE n")

    def load(self, index: Index, edges: list[Edge], ownership: dict | None = None) -> LoadStats:
        stats = LoadStats()
        files = [r.file for r in index.files_by_path.values()]
        classes = [c for r in index.files_by_path.values() for c in r.classes]
        funcs = [f for r in index.files_by_path.values() for f in r.functions]
        methods = [m for r in index.files_by_path.values() for m in r.methods]
        ifaces = [i for r in index.files_by_path.values() for i in r.interfaces]
        endpoints = [e for r in index.files_by_path.values() for e in r.endpoints]
        columns = [c for r in index.files_by_path.values() for c in r.columns]
        gql_ops = [o for r in index.files_by_path.values() for o in r.gql_operations]
        atoms = [a for r in index.files_by_path.values() for a in r.atoms]

        # Collect atomic sets
        externals: set[str] = set()
        hooks: set[str] = set()
        decorators: set[str] = set()
        env_vars: set[str] = set()
        events: set[str] = set()
        for e in edges:
            if e.kind == IMPORTS and e.dst_id.startswith("external:"):
                externals.add(e.dst_id[len("external:"):])
            elif e.kind == USES_HOOK:
                hooks.add(e.props.get("hook", ""))
            elif e.kind == DECORATED_BY:
                decorators.add(e.dst_id[len("dec:"):])

        for r in index.files_by_path.values():
            for env in r.env_reads:
                env_vars.add(env)
            for _, ev in r.event_handlers:
                events.add(ev)
            for _, ev in r.event_emitters:
                events.add(ev)

        stats.files = len(files)
        stats.classes = len(classes)
        stats.functions = len(funcs)
        stats.methods = len(methods)
        stats.interfaces = len(ifaces)
        stats.endpoints = len(endpoints)
        stats.externals = len(externals)
        stats.columns = len(columns)
        stats.gql_operations = len(gql_ops)
        stats.atoms = len(atoms)

        with self.driver.session(database=self.database) as s:
            # ── Files ─────────────────────────────────────────────
            _run(s, """
                UNWIND $rows AS r
                MERGE (n:File {path: r.path})
                SET n.package = r.package,
                    n.language = r.language,
                    n.loc = r.loc,
                    n.is_controller = r.is_controller,
                    n.is_injectable = r.is_injectable,
                    n.is_module = r.is_module,
                    n.is_component = r.is_component,
                    n.is_entity = r.is_entity,
                    n.is_resolver = r.is_resolver,
                    n.is_test = r.is_test
            """, [
                dict(path=f.path, package=f.package, language=f.language, loc=f.loc,
                     is_controller=f.is_controller, is_injectable=f.is_injectable,
                     is_module=f.is_module, is_component=f.is_component,
                     is_entity=f.is_entity, is_resolver=f.is_resolver, is_test=f.is_test)
                for f in files
            ])

            # Test files get :TestFile label
            _run(s, """
                UNWIND $rows AS r
                MATCH (f:File {path: r.path})
                SET f:TestFile
            """, [dict(path=f.path) for f in files if f.is_test])

            # ── Classes ───────────────────────────────────────────
            _run(s, """
                UNWIND $rows AS r
                MERGE (n:Class {id: r.id})
                SET n.name = r.name, n.file = r.file,
                    n.is_controller = r.is_controller,
                    n.is_injectable = r.is_injectable,
                    n.is_module = r.is_module,
                    n.is_entity = r.is_entity,
                    n.is_resolver = r.is_resolver,
                    n.is_abstract = r.is_abstract,
                    n.base_path = r.base_path,
                    n.table_name = r.table_name
                WITH n, r
                MATCH (f:File {path: r.file})
                MERGE (f)-[:DEFINES_CLASS]->(n)
            """, [
                dict(id=c.id, name=c.name, file=c.file,
                     is_controller=c.is_controller, is_injectable=c.is_injectable,
                     is_module=c.is_module, is_entity=c.is_entity,
                     is_resolver=c.is_resolver, is_abstract=c.is_abstract,
                     base_path=c.base_path, table_name=c.table_name)
                for c in classes
            ])

            # Add specialized labels
            _run(s, "UNWIND $rows AS r MATCH (c:Class {id: r.id}) SET c:Entity",
                 [dict(id=c.id) for c in classes if c.is_entity])
            _run(s, "UNWIND $rows AS r MATCH (c:Class {id: r.id}) SET c:Module",
                 [dict(id=c.id) for c in classes if c.is_module])
            _run(s, "UNWIND $rows AS r MATCH (c:Class {id: r.id}) SET c:Controller",
                 [dict(id=c.id) for c in classes if c.is_controller])
            _run(s, "UNWIND $rows AS r MATCH (c:Class {id: r.id}) SET c:Resolver",
                 [dict(id=c.id) for c in classes if c.is_resolver])

            # ── Functions ─────────────────────────────────────────
            _run(s, """
                UNWIND $rows AS r
                MERGE (n:Function {id: r.id})
                SET n.name = r.name, n.file = r.file,
                    n.is_component = r.is_component, n.exported = r.exported
                WITH n, r
                MATCH (f:File {path: r.file})
                MERGE (f)-[:DEFINES_FUNC]->(n)
            """, [
                dict(id=f.id, name=f.name, file=f.file,
                     is_component=f.is_component, exported=f.exported)
                for f in funcs
            ])
            _run(s, "UNWIND $rows AS r MATCH (f:Function {id: r.id}) SET f:Component",
                 [dict(id=f.id) for f in funcs if f.is_component])

            # ── Methods ───────────────────────────────────────────
            _run(s, """
                UNWIND $rows AS r
                MERGE (n:Method {id: r.id})
                SET n.name = r.name, n.file = r.file,
                    n.is_static = r.is_static, n.is_async = r.is_async,
                    n.is_constructor = r.is_constructor,
                    n.visibility = r.visibility
                WITH n, r
                MATCH (c:Class {id: r.class_id})
                MERGE (c)-[:HAS_METHOD]->(n)
            """, [
                dict(id=m.id, name=m.name, file=m.file, class_id=m.class_id,
                     is_static=m.is_static, is_async=m.is_async,
                     is_constructor=m.is_constructor, visibility=m.visibility)
                for m in methods
            ])

            # ── Interfaces ────────────────────────────────────────
            _run(s, """
                UNWIND $rows AS r
                MERGE (n:Interface {id: r.id})
                SET n.name = r.name, n.file = r.file
                WITH n, r
                MATCH (f:File {path: r.file})
                MERGE (f)-[:DEFINES_IFACE]->(n)
            """, [dict(id=i.id, name=i.name, file=i.file) for i in ifaces])

            # ── Endpoints ─────────────────────────────────────────
            _run(s, """
                UNWIND $rows AS r
                MERGE (e:Endpoint {id: r.id})
                SET e.method = r.method, e.path = r.path,
                    e.handler = r.handler, e.file = r.file
                WITH e, r
                MATCH (c:Class {id: r.cls})
                MERGE (c)-[:EXPOSES]->(e)
            """, [
                dict(id=e.id, method=e.method, path=e.path, handler=e.handler,
                     file=e.file, cls=e.controller_class)
                for e in endpoints
            ])

            # ── GraphQL Operations ────────────────────────────────
            _run(s, """
                UNWIND $rows AS r
                MERGE (o:GraphQLOperation {id: r.id})
                SET o.type = r.type, o.name = r.name,
                    o.return_type = r.return_type, o.handler = r.handler,
                    o.file = r.file
                WITH o, r
                MATCH (c:Class {id: r.cls})
                MERGE (c)-[:RESOLVES]->(o)
            """, [
                dict(id=o.id, type=o.op_type, name=o.name, return_type=o.return_type,
                     handler=o.handler, file=o.file, cls=o.resolver_class)
                for o in gql_ops
            ])

            # ── Columns ───────────────────────────────────────────
            _run(s, """
                UNWIND $rows AS r
                MERGE (c:Column {id: r.id})
                SET c.name = r.name, c.type = r.type, c.nullable = r.nullable,
                    c.unique = r.unique, c.primary = r.primary, c.generated = r.generated
                WITH c, r
                MATCH (e:Class {id: r.entity_id})
                MERGE (e)-[:HAS_COLUMN]->(c)
            """, [
                dict(id=c.id, entity_id=c.entity_id, name=c.name, type=c.type,
                     nullable=c.nullable, unique=c.unique, primary=c.primary,
                     generated=c.generated)
                for c in columns
            ])

            # ── Atoms ─────────────────────────────────────────────
            _run(s, """
                UNWIND $rows AS r
                MERGE (a:Atom {id: r.id})
                SET a.name = r.name, a.file = r.file, a.family = r.family
                WITH a, r
                MATCH (f:File {path: r.file})
                MERGE (f)-[:DEFINES_ATOM]->(a)
            """, [dict(id=a.id, name=a.name, file=a.file, family=a.family) for a in atoms])

            # ── Externals / Hooks / Decorators / EnvVars / Events ─
            _run(s, "UNWIND $rows AS r MERGE (:External {specifier: r.spec})",
                 [dict(spec=x) for x in externals])
            _run(s, "UNWIND $rows AS r MERGE (:Hook {name: r.name})",
                 [dict(name=h) for h in hooks if h])
            _run(s, "UNWIND $rows AS r MERGE (:Decorator {name: r.name})",
                 [dict(name=d) for d in decorators])
            _run(s, "UNWIND $rows AS r MERGE (:EnvVar {name: r.name})",
                 [dict(name=e) for e in env_vars])
            _run(s, "UNWIND $rows AS r MERGE (:Event {name: r.name})",
                 [dict(name=e) for e in events])

            # ── Edges ─────────────────────────────────────────────
            _write_edges(s, edges, stats)

            # ── Atom reads/writes, env reads, events (per-file) ──
            _write_per_file_extras(s, index, stats)

            # ── Test pairing (TESTS edges) ────────────────────────
            _write_test_edges(s, index, stats)

            # ── Ownership (Phase 7) ───────────────────────────────
            if ownership:
                _write_ownership(s, ownership, stats)

        return stats


def _run(session, cypher: str, rows: list) -> None:
    if not rows:
        return
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        session.run(cypher, rows=chunk)


def _write_edges(session, edges: list[Edge], stats: LoadStats) -> None:
    # Partition
    buckets: dict[str, list] = {}
    dec_class: list = []
    dec_method: list = []

    for e in edges:
        if e.kind == "__STATS__":
            continue

        if e.kind == DECORATED_BY:
            dname = e.dst_id[len("dec:"):]
            if e.src_id.startswith("class:"):
                dec_class.append(dict(src=e.src_id, name=dname))
            elif e.src_id.startswith("method:"):
                dec_method.append(dict(src=e.src_id, name=dname))
            continue

        if e.kind == IMPORTS:
            if e.props.get("external"):
                buckets.setdefault("IMPORTS_EXT", []).append(dict(
                    src=e.src_id[len("file:"):],
                    spec=e.dst_id[len("external:"):],
                    specifier=e.props.get("specifier", ""),
                    type_only=e.props.get("type_only", False),
                ))
            else:
                buckets.setdefault("IMPORTS", []).append(dict(
                    src=e.src_id[len("file:"):],
                    dst=e.dst_id[len("file:"):],
                    specifier=e.props.get("specifier", ""),
                    type_only=e.props.get("type_only", False),
                ))
            continue

        if e.kind == IMPORTS_SYMBOL:
            buckets.setdefault("IMPORTS_SYMBOL", []).append(dict(
                src=e.src_id[len("file:"):],
                dst=e.dst_id[len("file:"):],
                symbol=e.props.get("symbol", ""),
                type_only=e.props.get("type_only", False),
            ))
            continue

        if e.kind in (EXTENDS, IMPLEMENTS, INJECTS, REPOSITORY_OF,
                       PROVIDES, EXPORTS_PROVIDER, IMPORTS_MODULE, DECLARES_CONTROLLER):
            buckets.setdefault(e.kind, []).append(dict(src=e.src_id, dst=e.dst_id))
            continue

        if e.kind == RELATES_TO:
            buckets.setdefault(RELATES_TO, []).append(dict(
                src=e.src_id, dst=e.dst_id,
                kind=e.props.get("kind", ""),
                field=e.props.get("field", ""),
            ))
            continue

        if e.kind == RENDERS:
            buckets.setdefault(RENDERS, []).append(dict(src=e.src_id, dst=e.dst_id))
            continue

        if e.kind == USES_HOOK:
            buckets.setdefault(USES_HOOK, []).append(dict(
                src=e.src_id, hook=e.props.get("hook", ""),
            ))
            continue

        if e.kind == RETURNS:
            buckets.setdefault(RETURNS, []).append(dict(src=e.src_id, dst=e.dst_id))
            continue

        if e.kind == CALLS_ENDPOINT:
            buckets.setdefault(CALLS_ENDPOINT, []).append(dict(
                src=e.src_id, dst=e.dst_id, url=e.props.get("url", ""),
            ))
            continue

        if e.kind == USES_OPERATION:
            buckets.setdefault(USES_OPERATION, []).append(dict(
                src=e.src_id, dst=e.dst_id, op_name=e.props.get("op_name", ""),
            ))
            continue

        if e.kind == CALLS:
            buckets.setdefault(CALLS, []).append(dict(
                src=e.src_id, dst=e.dst_id,
                confidence=e.props.get("confidence", "name"),
            ))
            continue

        if e.kind == HANDLES:
            buckets.setdefault(HANDLES, []).append(dict(src=e.src_id, dst=e.dst_id))
            continue

    # Write each bucket with its specific Cypher
    _run(session, """
        UNWIND $rows AS r
        MATCH (a:File {path: r.src}) MATCH (b:File {path: r.dst})
        MERGE (a)-[rel:IMPORTS]->(b)
        SET rel.specifier = r.specifier, rel.type_only = r.type_only
    """, buckets.get("IMPORTS", []))
    stats.edges[IMPORTS] = len(buckets.get("IMPORTS", []))

    _run(session, """
        UNWIND $rows AS r
        MATCH (a:File {path: r.src}) MATCH (b:External {specifier: r.spec})
        MERGE (a)-[rel:IMPORTS_EXTERNAL]->(b)
        SET rel.specifier = r.specifier, rel.type_only = r.type_only
    """, buckets.get("IMPORTS_EXT", []))
    stats.edges[IMPORTS_EXTERNAL] = len(buckets.get("IMPORTS_EXT", []))

    _run(session, """
        UNWIND $rows AS r
        MATCH (a:File {path: r.src}) MATCH (b:File {path: r.dst})
        MERGE (a)-[rel:IMPORTS_SYMBOL {symbol: r.symbol}]->(b)
        SET rel.type_only = r.type_only
    """, buckets.get("IMPORTS_SYMBOL", []))
    stats.edges[IMPORTS_SYMBOL] = len(buckets.get("IMPORTS_SYMBOL", []))

    for kind in (EXTENDS, IMPLEMENTS, INJECTS, REPOSITORY_OF,
                 PROVIDES, EXPORTS_PROVIDER, IMPORTS_MODULE, DECLARES_CONTROLLER):
        rows = buckets.get(kind, [])
        if not rows:
            stats.edges[kind] = 0
            continue
        _run(session, f"""
            UNWIND $rows AS r
            MATCH (a:Class {{id: r.src}})
            MATCH (b:Class {{id: r.dst}})
            MERGE (a)-[:{kind}]->(b)
        """, rows)
        stats.edges[kind] = len(rows)

    _run(session, """
        UNWIND $rows AS r
        MATCH (a:Class {id: r.src})
        MATCH (b:Class {id: r.dst})
        MERGE (a)-[rel:RELATES_TO {kind: r.kind, field: r.field}]->(b)
    """, buckets.get(RELATES_TO, []))
    stats.edges[RELATES_TO] = len(buckets.get(RELATES_TO, []))

    _run(session, """
        UNWIND $rows AS r
        MATCH (a:Function {id: r.src})
        MATCH (b:Function {id: r.dst})
        MERGE (a)-[:RENDERS]->(b)
    """, buckets.get(RENDERS, []))
    stats.edges[RENDERS] = len(buckets.get(RENDERS, []))

    _run(session, """
        UNWIND $rows AS r
        MATCH (a:Function {id: r.src})
        MATCH (h:Hook {name: r.hook})
        MERGE (a)-[:USES_HOOK]->(h)
    """, buckets.get(USES_HOOK, []))
    stats.edges[USES_HOOK] = len(buckets.get(USES_HOOK, []))

    _run(session, """
        UNWIND $rows AS r
        MATCH (o:GraphQLOperation {id: r.src})
        MATCH (c:Class {id: r.dst})
        MERGE (o)-[:RETURNS]->(c)
    """, buckets.get(RETURNS, []))
    stats.edges[RETURNS] = len(buckets.get(RETURNS, []))

    _run(session, """
        UNWIND $rows AS r
        MATCH (a) WHERE a.id = r.src
        MATCH (e:Endpoint {id: r.dst})
        MERGE (a)-[rel:CALLS_ENDPOINT]->(e)
        SET rel.url = r.url
    """, buckets.get(CALLS_ENDPOINT, []))
    stats.edges[CALLS_ENDPOINT] = len(buckets.get(CALLS_ENDPOINT, []))

    _run(session, """
        UNWIND $rows AS r
        MATCH (a) WHERE a.id = r.src
        MATCH (o:GraphQLOperation {id: r.dst})
        MERGE (a)-[rel:USES_OPERATION]->(o)
        SET rel.op_name = r.op_name
    """, buckets.get(USES_OPERATION, []))
    stats.edges[USES_OPERATION] = len(buckets.get(USES_OPERATION, []))

    _run(session, """
        UNWIND $rows AS r
        MATCH (a:Method {id: r.src})
        MATCH (b:Method {id: r.dst})
        MERGE (a)-[rel:CALLS]->(b)
        SET rel.confidence = r.confidence
    """, buckets.get(CALLS, []))
    stats.edges[CALLS] = len(buckets.get(CALLS, []))

    _run(session, """
        UNWIND $rows AS r
        MATCH (m:Method {id: r.src})
        MATCH (e:Endpoint {id: r.dst})
        MERGE (m)-[:HANDLES]->(e)
    """, [row for row in buckets.get(HANDLES, []) if ":Endpoint" or "endpoint:" in row["dst"]])
    # Also method -> GraphQL operation for HANDLES (distinct query)
    _run(session, """
        UNWIND $rows AS r
        MATCH (m:Method {id: r.src})
        MATCH (o:GraphQLOperation {id: r.dst})
        MERGE (m)-[:HANDLES]->(o)
    """, buckets.get(HANDLES, []))
    stats.edges[HANDLES] = len(buckets.get(HANDLES, []))

    # Decorator edges
    _run(session, """
        UNWIND $rows AS r
        MATCH (a:Class {id: r.src})
        MATCH (d:Decorator {name: r.name})
        MERGE (a)-[:DECORATED_BY]->(d)
    """, dec_class)
    _run(session, """
        UNWIND $rows AS r
        MATCH (a:Method {id: r.src})
        MATCH (d:Decorator {name: r.name})
        MERGE (a)-[:DECORATED_BY]->(d)
    """, dec_method)
    stats.edges[DECORATED_BY] = len(dec_class) + len(dec_method)


def _write_per_file_extras(session, index: Index, stats: LoadStats) -> None:
    """Atom reads/writes, env reads, events — sourced from ParseResult per-file lists."""
    atom_reads: list = []
    atom_writes: list = []
    env_reads: list = []
    event_handlers: list = []
    event_emitters: list = []

    for rel, result in index.files_by_path.items():
        # Atom reads/writes: (component_name, atom_name) — lookup atom by name across files
        for comp, atom_name in result.atom_reads:
            atom_reads.append(dict(
                fn_id=f"func:{rel}#{comp}",
                atom_name=atom_name,
            ))
        for comp, atom_name in result.atom_writes:
            atom_writes.append(dict(
                fn_id=f"func:{rel}#{comp}",
                atom_name=atom_name,
            ))
        for env_name in set(result.env_reads):
            env_reads.append(dict(
                file=rel,
                env=env_name,
            ))
        for method_id, ev in result.event_handlers:
            event_handlers.append(dict(method=method_id, event=ev))
        for method_id, ev in result.event_emitters:
            event_emitters.append(dict(method=method_id, event=ev))

    _run(session, """
        UNWIND $rows AS r
        MATCH (fn:Function {id: r.fn_id})
        MATCH (a:Atom {name: r.atom_name})
        MERGE (fn)-[:READS_ATOM]->(a)
    """, atom_reads)
    stats.edges[READS_ATOM] = len(atom_reads)

    _run(session, """
        UNWIND $rows AS r
        MATCH (fn:Function {id: r.fn_id})
        MATCH (a:Atom {name: r.atom_name})
        MERGE (fn)-[:WRITES_ATOM]->(a)
    """, atom_writes)
    stats.edges[WRITES_ATOM] = len(atom_writes)

    _run(session, """
        UNWIND $rows AS r
        MATCH (f:File {path: r.file})
        MATCH (e:EnvVar {name: r.env})
        MERGE (f)-[:READS_ENV]->(e)
    """, env_reads)
    stats.edges[READS_ENV] = len(env_reads)

    _run(session, """
        UNWIND $rows AS r
        MATCH (m:Method {id: r.method})
        MATCH (e:Event {name: r.event})
        MERGE (m)-[:HANDLES_EVENT]->(e)
    """, event_handlers)
    stats.edges[HANDLES_EVENT] = len(event_handlers)

    _run(session, """
        UNWIND $rows AS r
        MATCH (m:Method {id: r.method})
        MATCH (e:Event {name: r.event})
        MERGE (m)-[:EMITS_EVENT]->(e)
    """, event_emitters)
    stats.edges[EMITS_EVENT] = len(event_emitters)


def _write_test_edges(session, index: Index, stats: LoadStats) -> None:
    """Link *.spec.ts / *.test.ts to their production peer by filename."""
    rows: list = []
    rows_class: list = []
    files = index.files_by_path

    for rel, r in files.items():
        if not r.file.is_test:
            continue
        # Derive peer: foo.spec.ts -> foo.ts
        peer = None
        for suf in (".spec.ts", ".spec.tsx", ".test.ts", ".test.tsx"):
            if rel.endswith(suf):
                base = rel[: -len(suf)]
                for ext in (".ts", ".tsx"):
                    cand = base + ext
                    if cand in files:
                        peer = cand
                        break
                break
        if peer:
            rows.append(dict(test=rel, peer=peer))
        # Also link by described subject
        for subj in r.described_subjects:
            rows_class.append(dict(test=rel, name=subj))

    _run(session, """
        UNWIND $rows AS r
        MATCH (t:File {path: r.test})
        MATCH (p:File {path: r.peer})
        MERGE (t)-[:TESTS]->(p)
    """, rows)
    stats.edges[TESTS] = len(rows)

    _run(session, """
        UNWIND $rows AS r
        MATCH (t:File {path: r.test})
        MATCH (c:Class {name: r.name})
        MERGE (t)-[:TESTS_CLASS]->(c)
    """, rows_class)
    stats.edges[TESTS_CLASS] = len(rows_class)


def _write_ownership(session, ownership: dict, stats: LoadStats) -> None:
    """Phase 7: git log + CODEOWNERS ingestion."""
    authors = ownership.get("authors", [])
    teams = ownership.get("teams", [])
    last_mod = ownership.get("last_modified", [])
    contribs = ownership.get("contributors", [])
    owned = ownership.get("owned_by", [])

    _run(session, "UNWIND $rows AS r MERGE (:Author {email: r.email}) SET email = r.email",
         [dict(email=a["email"], name=a.get("name", "")) for a in authors])
    _run(session, """
        UNWIND $rows AS r
        MERGE (a:Author {email: r.email})
        SET a.name = r.name
    """, [dict(email=a["email"], name=a.get("name", "")) for a in authors])
    _run(session, "UNWIND $rows AS r MERGE (:Team {name: r.name})",
         [dict(name=t) for t in teams])

    _run(session, """
        UNWIND $rows AS r
        MATCH (f:File {path: r.path})
        MATCH (a:Author {email: r.email})
        MERGE (f)-[rel:LAST_MODIFIED_BY]->(a)
        SET rel.at = r.at
    """, last_mod)
    stats.edges[LAST_MODIFIED_BY] = len(last_mod)

    _run(session, """
        UNWIND $rows AS r
        MATCH (f:File {path: r.path})
        MATCH (a:Author {email: r.email})
        MERGE (f)-[rel:CONTRIBUTED_BY]->(a)
        SET rel.commits = r.commits
    """, contribs)
    stats.edges[CONTRIBUTED_BY] = len(contribs)

    _run(session, """
        UNWIND $rows AS r
        MATCH (f:File {path: r.path})
        MATCH (t:Team {name: r.team})
        MERGE (f)-[:OWNED_BY]->(t)
    """, owned)
    stats.edges[OWNED_BY] = len(owned)
