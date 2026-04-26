"""Neo4j writer: constraints, batched UNWIND-MERGE, idempotent. Phases 1-8."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable

from neo4j import Driver, GraphDatabase

from .resolver import Index
from .schema import (
    BELONGS_TO,
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
    EdgeGroupNode,
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
    MEMBER_OF,
    OWNED_BY,
    PackageNode,
    PROVIDES,
    PY_CONFTEST_FILENAME,
    PY_TEST_PREFIX,
    PY_TEST_SUFFIX_TRAILING,
    READS_ATOM,
    READS_ENV,
    RELATES_TO,
    RENDERS,
    REPOSITORY_OF,
    RESOLVES,
    RETURNS,
    TESTS,
    TESTS_CLASS,
    TS_TEST_SUFFIXES,
    USES_HOOK,
    USES_OPERATION,
    WRITES_ATOM,
)

log = logging.getLogger(__name__)


BATCH = 1000

# Prefixes that encode a file path as ``<prefix>:<path>#<rest>``.
_FILE_BEARING_PREFIXES = ("file:", "class:", "func:", "method:", "endpoint:", "gqlop:", "atom:", "interface:", "route:")


def _file_from_id(node_id: str) -> str | None:
    """Extract the file path embedded in a node ID, or ``None``.

    IDs follow ``<prefix>:<repo>:<path>#<name>`` (class, func, …) or
    ``<prefix>:<repo>:<path>`` (file). Singletons like ``hook:``,
    ``external:``, ``dec:`` don't encode a file path — return ``None``.

    Special cases:
    - ``method:class:<repo>:<path>#<cls>#<method>`` — nested ``class:`` prefix.
    - ``endpoint:<method>:<route>@<repo>:<file>#<handler>`` — file after ``@``.
    - ``gqlop:<type>:<name>@<repo>:<file>#<handler>`` — file after ``@``.
    """
    for pfx in _FILE_BEARING_PREFIXES:
        if node_id.startswith(pfx):
            rest = node_id[len(pfx):]
            # ``method:class:<repo>:<path>#<cls>#<method>``
            if rest.startswith("class:"):
                rest = rest[len("class:"):]
                # rest = "<repo>:<path>#<cls>#<method>"
                repo_rest = rest.split(":", 1)
                if len(repo_rest) == 2:
                    return repo_rest[1].split("#", 1)[0]
                return rest.split("#", 1)[0]
            # ``endpoint:``, ``gqlop:``, and ``route:`` embed the file after ``@``
            if pfx in ("endpoint:", "gqlop:", "route:"):
                at_idx = rest.find("@")
                if at_idx >= 0:
                    after_at = rest[at_idx + 1:]
                    # after_at = "<repo>:<file>#<handler>"
                    repo_rest = after_at.split(":", 1)
                    if len(repo_rest) == 2:
                        return repo_rest[1].split("#", 1)[0]
                    return after_at.split("#", 1)[0]
                return None
            # Standard: "<repo>:<path>" or "<repo>:<path>#<name>"
            repo_rest = rest.split(":", 1)
            if len(repo_rest) == 2:
                return repo_rest[1].split("#", 1)[0]
            return rest.split("#", 1)[0]
    return None


_MIGRATIONS = [
    "DROP CONSTRAINT file_path IF EXISTS",
    "DROP CONSTRAINT package_name IF EXISTS",
]

_CONSTRAINTS = [
    "CREATE CONSTRAINT file_id IF NOT EXISTS FOR (n:File) REQUIRE n.id IS UNIQUE",
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
    "CREATE CONSTRAINT package_id IF NOT EXISTS FOR (n:Package) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT edgegroup_id IF NOT EXISTS FOR (n:EdgeGroup) REQUIRE n.id IS UNIQUE",
]

_INDEXES = [
    "CREATE INDEX class_name IF NOT EXISTS FOR (n:Class) ON (n.name)",
    "CREATE INDEX func_name IF NOT EXISTS FOR (n:Function) ON (n.name)",
    "CREATE INDEX method_name IF NOT EXISTS FOR (n:Method) ON (n.name)",
    "CREATE INDEX file_path IF NOT EXISTS FOR (n:File) ON (n.path)",
    "CREATE INDEX file_package IF NOT EXISTS FOR (n:File) ON (n.package)",
    "CREATE INDEX file_repo IF NOT EXISTS FOR (n:File) ON (n.repo)",
    "CREATE INDEX endpoint_path IF NOT EXISTS FOR (n:Endpoint) ON (n.path)",
    "CREATE INDEX class_file IF NOT EXISTS FOR (n:Class) ON (n.file)",
    "CREATE INDEX gqlop_name IF NOT EXISTS FOR (n:GraphQLOperation) ON (n.name)",
    "CREATE INDEX edgegroup_kind IF NOT EXISTS FOR (n:EdgeGroup) ON (n.kind)",
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
    packages: int = 0
    belongs_to_edges: int = 0
    edge_groups: int = 0
    member_of_edges: int = 0
    edges: dict = field(default_factory=dict)


class Neo4jLoader:
    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j") -> None:
        self.driver: Driver = GraphDatabase.driver(uri, auth=(user, password))
        self.database = database

    def close(self) -> None:
        self.driver.close()

    def init_schema(self) -> None:
        with self.driver.session(database=self.database) as s:
            for stmt in _MIGRATIONS + _CONSTRAINTS + _INDEXES:
                s.run(stmt)

    def wipe(self) -> None:
        with self.driver.session(database=self.database) as s:
            s.run("MATCH (n) DETACH DELETE n")

    def wipe_scoped(self, packages: list[str], repo: str = "default") -> int:
        """Delete every :File whose ``package`` is in *packages* and ``repo`` matches, plus all children.

        The shared-Neo4j model — every repo on the machine indexes into one
        ``codegraph-neo4j`` instance — makes a global ``MATCH (n) DETACH
        DELETE n`` dangerous: re-indexing repo A would nuke repo B's data.
        ``wipe_scoped`` is what ``codegraph index --wipe`` calls instead.
        Standalone ``codegraph wipe`` keeps the global wipe (explicit user
        intent for a clean slate).

        Returns the number of file subgraphs deleted.
        """
        if not packages:
            return 0
        with self.driver.session(database=self.database) as s:
            ids_result = s.run(
                "MATCH (f:File) WHERE f.package IN $packages AND f.repo = $repo "
                "RETURN f.id AS id",
                packages=packages, repo=repo,
            )
            file_ids = [row["id"] for row in ids_result]
        deleted = self.delete_file_subgraph(file_ids) if file_ids else 0
        # Drop orphaned :Package nodes for the wiped packages/repo — load()
        # will re-MERGE them with fresh framework metadata on the next index.
        with self.driver.session(database=self.database) as s:
            s.run(
                "MATCH (p:Package) WHERE p.name IN $packages AND p.repo = $repo "
                "DETACH DELETE p",
                packages=packages, repo=repo,
            )
        return deleted

    def delete_file_subgraph(self, file_ids: list[str]) -> int:
        """Delete :File nodes by *file_ids* and all owned children.

        Uses a 3-step DETACH DELETE cascade that is resilient to schema
        changes (new relationship types are handled automatically):

        1. Grandchildren of owned classes (Methods, Endpoints, Columns, …)
        2. Direct owned children (Classes, Functions, Interfaces, Atoms)
        3. File nodes themselves (DETACH DELETE auto-removes IMPORTS, etc.)

        Used by incremental re-indexing (``--since``) to clean up stale data
        before re-loading touched files.  Returns the number of IDs processed.
        """
        if not file_ids:
            return 0
        rows = [dict(id=fid) for fid in file_ids]
        with self.driver.session(database=self.database) as s:
            # 1. Grandchildren of owned classes (Methods, Endpoints, GQL ops,
            #    Columns, etc.) — excludes Class (cross-file EXTENDS/INJECTS)
            #    and Decorator (shared singletons).
            _run(s, """
                UNWIND $rows AS r
                MATCH (f:File {id: r.id})-[:DEFINES_CLASS]->(c:Class)-->(child)
                WHERE NOT child:Class AND NOT child:Decorator
                DETACH DELETE child
            """, rows)
            # 2. Direct owned children (Classes, Functions, Interfaces, Atoms)
            _run(s, """
                UNWIND $rows AS r
                MATCH (f:File {id: r.id})-[:DEFINES_CLASS|DEFINES_FUNC|DEFINES_IFACE|DEFINES_ATOM]->(child)
                DETACH DELETE child
            """, rows)
            # 3. File nodes (DETACH DELETE auto-removes IMPORTS, BELONGS_TO, etc.)
            _run(s, """
                UNWIND $rows AS r
                MATCH (f:File {id: r.id})
                DETACH DELETE f
            """, rows)
        return len(file_ids)

    def load(
        self,
        index: Index,
        edges: list[Edge],
        ownership: dict | None = None,
        touched_files: set[str] | None = None,
        edge_groups: list[EdgeGroupNode] | None = None,
        repo_name: str = "default",
    ) -> LoadStats:
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

        # Incremental mode: restrict nodes to touched files only.
        if touched_files is not None:
            files = [f for f in files if f.path in touched_files]
            classes = [c for c in classes if c.file in touched_files]
            funcs = [f for f in funcs if f.file in touched_files]
            methods = [m for m in methods if m.file in touched_files]
            ifaces = [i for i in ifaces if i.file in touched_files]
            endpoints = [e for e in endpoints if e.file in touched_files]
            columns = [c for c in columns if _file_from_id(c.entity_id) in touched_files]
            gql_ops = [o for o in gql_ops if o.file in touched_files]
            atoms = [a for a in atoms if a.file in touched_files]

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
                MERGE (n:File {id: r.id})
                SET n.path = r.path,
                    n.repo = r.repo,
                    n.package = r.package,
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
                dict(id=f.id, path=f.path, repo=f.repo, package=f.package,
                     language=f.language, loc=f.loc,
                     is_controller=f.is_controller, is_injectable=f.is_injectable,
                     is_module=f.is_module, is_component=f.is_component,
                     is_entity=f.is_entity, is_resolver=f.is_resolver, is_test=f.is_test)
                for f in files
            ])

            # Test files get :TestFile label
            _run(s, """
                UNWIND $rows AS r
                MATCH (f:File {id: r.id})
                SET f:TestFile
            """, [dict(id=f.id) for f in files if f.is_test])

            # ── Packages + BELONGS_TO edges ───────────────────────
            _write_packages(s, index.packages, stats)
            _write_belongs_to(s, files, stats)

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
                MATCH (f:File {id: r.file_id})
                MERGE (f)-[rel:DEFINES_CLASS]->(n)
                SET rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0
            """, [
                dict(id=c.id, name=c.name, file=c.file,
                     file_id=f"file:{c.repo}:{c.file}",
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
                    n.is_component = r.is_component, n.exported = r.exported,
                    n.docstring = r.docstring, n.return_type = r.return_type,
                    n.params_json = r.params_json
                WITH n, r
                MATCH (f:File {id: r.file_id})
                MERGE (f)-[rel:DEFINES_FUNC]->(n)
                SET rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0
            """, [
                dict(id=f.id, name=f.name, file=f.file,
                     file_id=f"file:{f.repo}:{f.file}",
                     is_component=f.is_component, exported=f.exported,
                     docstring=f.docstring, return_type=f.return_type,
                     params_json=f.params_json)
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
                    n.visibility = r.visibility,
                    n.return_type = r.return_type,
                    n.params_json = r.params_json,
                    n.docstring = r.docstring
                WITH n, r
                MATCH (c:Class {id: r.class_id})
                MERGE (c)-[rel:HAS_METHOD]->(n)
                SET rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0
            """, [
                dict(id=m.id, name=m.name, file=m.file, class_id=m.class_id,
                     is_static=m.is_static, is_async=m.is_async,
                     is_constructor=m.is_constructor, visibility=m.visibility,
                     return_type=m.return_type, params_json=m.params_json,
                     docstring=m.docstring)
                for m in methods
            ])

            # ── Interfaces ────────────────────────────────────────
            _run(s, """
                UNWIND $rows AS r
                MERGE (n:Interface {id: r.id})
                SET n.name = r.name, n.file = r.file
                WITH n, r
                MATCH (f:File {id: r.file_id})
                MERGE (f)-[rel:DEFINES_IFACE]->(n)
                SET rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0
            """, [dict(id=i.id, name=i.name, file=i.file,
                       file_id=f"file:{i.repo}:{i.file}") for i in ifaces])

            # ── Endpoints ─────────────────────────────────────────
            # Split: class-level vs file-level endpoints (see #195)
            _run(s, """
                UNWIND $rows AS r
                MERGE (e:Endpoint {id: r.id})
                SET e.method = r.method, e.path = r.path,
                    e.handler = r.handler, e.file = r.file
                WITH e, r
                MATCH (c:Class {id: r.cls})
                MERGE (c)-[rel:EXPOSES]->(e)
                SET rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0
            """, [
                dict(id=e.id, method=e.method, path=e.path, handler=e.handler,
                     file=e.file, cls=e.controller_class)
                for e in endpoints
                if not e.controller_class.startswith("file:")
            ])
            _run(s, """
                UNWIND $rows AS r
                MERGE (e:Endpoint {id: r.id})
                SET e.method = r.method, e.path = r.path,
                    e.handler = r.handler, e.file = r.file
                WITH e, r
                MATCH (f:File {id: r.file_id})
                MERGE (f)-[rel:EXPOSES]->(e)
                SET rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0
            """, [
                dict(id=e.id, method=e.method, path=e.path, handler=e.handler,
                     file=e.file, file_id=e.controller_class)
                for e in endpoints
                if e.controller_class.startswith("file:")
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
                MERGE (c)-[rel:RESOLVES]->(o)
                SET rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0
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
                MERGE (e)-[rel:HAS_COLUMN]->(c)
                SET rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0
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
                MATCH (f:File {id: r.file_id})
                MERGE (f)-[rel:DEFINES_ATOM]->(a)
                SET rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0
            """, [dict(id=a.id, name=a.name, file=a.file, family=a.family,
                       file_id=f"file:{a.repo}:{a.file}") for a in atoms])

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
            all_edges = edges
            if touched_files is not None:
                edges = [
                    e for e in edges
                    if _file_from_id(e.src_id) in touched_files
                    or _file_from_id(e.dst_id) in touched_files
                ]
            _write_edges(s, edges, stats)

            # ── Atom reads/writes, env reads, events (per-file) ──
            _write_per_file_extras(s, index, stats, touched_files)

            # ── Test pairing (TESTS edges) ────────────────────────
            _write_test_edges(s, index, stats)

            # ── Ownership (Phase 7) ───────────────────────────────
            if ownership is not None:
                _write_ownership(s, ownership, stats, repo_name=repo_name)

            # ── Edge groups (Phase 10) ───────────────────────────
            # Use unfiltered edges so MEMBER_OF edges survive incremental mode.
            if edge_groups:
                _write_edge_groups(s, edge_groups, all_edges, stats)

        return stats


def _run(session, cypher: str, rows: list) -> None:
    if not rows:
        return
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        session.run(cypher, rows=chunk)


def _write_packages(session, packages: list[PackageNode], stats: LoadStats) -> None:
    """MERGE one ``:Package`` node per configured monorepo package.

    All :class:`~.framework.FrameworkInfo` fields are flattened onto the node
    so queries can branch by stack in a single hop. The ``id`` (which embeds
    ``repo`` and ``name``) is the unique key.
    """
    rows = [
        dict(
            id=p.id,
            name=p.name,
            repo=p.repo,
            framework=p.framework,
            framework_version=p.framework_version,
            typescript=p.typescript,
            styling=p.styling,
            router=p.router,
            state_management=p.state_management,
            ui_library=p.ui_library,
            build_tool=p.build_tool,
            package_manager=p.package_manager,
            confidence=p.confidence,
        )
        for p in packages
    ]
    _run(session, """
        UNWIND $rows AS r
        MERGE (p:Package {id: r.id})
        SET p.name              = r.name,
            p.repo              = r.repo,
            p.framework         = r.framework,
            p.framework_version = r.framework_version,
            p.typescript        = r.typescript,
            p.styling           = r.styling,
            p.router            = r.router,
            p.state_management  = r.state_management,
            p.ui_library        = r.ui_library,
            p.build_tool        = r.build_tool,
            p.package_manager   = r.package_manager,
            p.confidence        = r.confidence
    """, rows)
    stats.packages = len(rows)


def _write_belongs_to(session, files, stats: LoadStats) -> None:
    """MERGE ``(f:File)-[:BELONGS_TO]->(p:Package)`` for every file.

    The edge is redundant with :attr:`FileNode.package` (which stays for the
    existing ``file_package`` index) but makes Cypher patterns one hop cleaner,
    e.g. ``MATCH (f:File)-[:BELONGS_TO]->(p:Package {framework:'Next.js'})``.
    """
    rows = [dict(file_id=f.id, pkg_id=f"package:{f.repo}:{f.package}")
            for f in files if f.package]
    _run(session, """
        UNWIND $rows AS r
        MATCH (f:File {id: r.file_id})
        MATCH (p:Package {id: r.pkg_id})
        MERGE (f)-[rel:BELONGS_TO]->(p)
        SET rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0
    """, rows)
    stats.belongs_to_edges = len(rows)


def _write_edges(session, edges: list[Edge], stats: LoadStats) -> None:
    # Partition
    buckets: dict[str, list] = {}
    dec_class: list = []
    dec_func: list = []
    dec_method: list = []

    for e in edges:
        if e.kind == "__STATS__":
            continue

        if e.kind == DECORATED_BY:
            dname = e.dst_id[len("dec:"):]
            _conf = dict(confidence=e.confidence, confidence_score=e.confidence_score)
            if e.src_id.startswith("class:"):
                dec_class.append(dict(src=e.src_id, name=dname, **_conf))
            elif e.src_id.startswith("func:"):
                dec_func.append(dict(src=e.src_id, name=dname, **_conf))
            elif e.src_id.startswith("method:"):
                dec_method.append(dict(src=e.src_id, name=dname, **_conf))
            else:
                log.debug("DECORATED_BY edge with unknown src prefix dropped: %r", e.src_id)
            continue

        _conf = dict(confidence=e.confidence, confidence_score=e.confidence_score)

        if e.kind == IMPORTS:
            if e.props.get("external"):
                buckets.setdefault("IMPORTS_EXT", []).append(dict(
                    src=e.src_id,
                    spec=e.dst_id[len("external:"):],
                    specifier=e.props.get("specifier", ""),
                    type_only=e.props.get("type_only", False),
                    **_conf,
                ))
            else:
                buckets.setdefault("IMPORTS", []).append(dict(
                    src=e.src_id,
                    dst=e.dst_id,
                    specifier=e.props.get("specifier", ""),
                    type_only=e.props.get("type_only", False),
                    **_conf,
                ))
            continue

        if e.kind == IMPORTS_SYMBOL:
            buckets.setdefault("IMPORTS_SYMBOL", []).append(dict(
                src=e.src_id,
                dst=e.dst_id,
                symbol=e.props.get("symbol", ""),
                type_only=e.props.get("type_only", False),
                **_conf,
            ))
            continue

        if e.kind in (EXTENDS, IMPLEMENTS, INJECTS, REPOSITORY_OF,
                       PROVIDES, EXPORTS_PROVIDER, IMPORTS_MODULE, DECLARES_CONTROLLER):
            buckets.setdefault(e.kind, []).append(dict(src=e.src_id, dst=e.dst_id, **_conf))
            continue

        if e.kind == RELATES_TO:
            buckets.setdefault(RELATES_TO, []).append(dict(
                src=e.src_id, dst=e.dst_id,
                kind=e.props.get("kind", ""),
                field=e.props.get("field", ""),
                **_conf,
            ))
            continue

        if e.kind == RENDERS:
            buckets.setdefault(RENDERS, []).append(dict(src=e.src_id, dst=e.dst_id, **_conf))
            continue

        if e.kind == USES_HOOK:
            buckets.setdefault(USES_HOOK, []).append(dict(
                src=e.src_id, hook=e.props.get("hook", ""),
                **_conf,
            ))
            continue

        if e.kind == RETURNS:
            buckets.setdefault(RETURNS, []).append(dict(src=e.src_id, dst=e.dst_id, **_conf))
            continue

        if e.kind == CALLS_ENDPOINT:
            buckets.setdefault(CALLS_ENDPOINT, []).append(dict(
                src=e.src_id, dst=e.dst_id, url=e.props.get("url", ""),
                **_conf,
            ))
            continue

        if e.kind == USES_OPERATION:
            buckets.setdefault(USES_OPERATION, []).append(dict(
                src=e.src_id, dst=e.dst_id, op_name=e.props.get("op_name", ""),
                **_conf,
            ))
            continue

        if e.kind == CALLS:
            buckets.setdefault(CALLS, []).append(dict(
                src=e.src_id, dst=e.dst_id,
                resolution=e.props.get("resolution", "name"),
                **_conf,
            ))
            continue

        if e.kind == HANDLES:
            buckets.setdefault(HANDLES, []).append(dict(src=e.src_id, dst=e.dst_id, **_conf))
            continue

    # Confidence SET fragment shared by all Cypher below
    _CONF_SET = ", rel.confidence = r.confidence, rel.confidence_score = r.confidence_score"

    # Write each bucket with its specific Cypher
    _run(session, f"""
        UNWIND $rows AS r
        MATCH (a:File {{id: r.src}}) MATCH (b:File {{id: r.dst}})
        MERGE (a)-[rel:IMPORTS]->(b)
        SET rel.specifier = r.specifier, rel.type_only = r.type_only{_CONF_SET}
    """, buckets.get("IMPORTS", []))
    stats.edges[IMPORTS] = len(buckets.get("IMPORTS", []))

    _run(session, f"""
        UNWIND $rows AS r
        MATCH (a:File {{id: r.src}}) MATCH (b:External {{specifier: r.spec}})
        MERGE (a)-[rel:IMPORTS_EXTERNAL]->(b)
        SET rel.specifier = r.specifier, rel.type_only = r.type_only{_CONF_SET}
    """, buckets.get("IMPORTS_EXT", []))
    stats.edges[IMPORTS_EXTERNAL] = len(buckets.get("IMPORTS_EXT", []))

    _run(session, f"""
        UNWIND $rows AS r
        MATCH (a:File {{id: r.src}}) MATCH (b:File {{id: r.dst}})
        MERGE (a)-[rel:IMPORTS_SYMBOL {{symbol: r.symbol}}]->(b)
        SET rel.type_only = r.type_only{_CONF_SET}
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
            MERGE (a)-[rel:{kind}]->(b)
            SET rel.confidence = r.confidence, rel.confidence_score = r.confidence_score
        """, rows)
        stats.edges[kind] = len(rows)

    _run(session, f"""
        UNWIND $rows AS r
        MATCH (a:Class {{id: r.src}})
        MATCH (b:Class {{id: r.dst}})
        MERGE (a)-[rel:RELATES_TO {{kind: r.kind, field: r.field}}]->(b)
        SET rel.confidence = r.confidence, rel.confidence_score = r.confidence_score
    """, buckets.get(RELATES_TO, []))
    stats.edges[RELATES_TO] = len(buckets.get(RELATES_TO, []))

    _run(session, f"""
        UNWIND $rows AS r
        MATCH (a:Function {{id: r.src}})
        MATCH (b:Function {{id: r.dst}})
        MERGE (a)-[rel:RENDERS]->(b)
        SET rel.confidence = r.confidence, rel.confidence_score = r.confidence_score
    """, buckets.get(RENDERS, []))
    stats.edges[RENDERS] = len(buckets.get(RENDERS, []))

    _run(session, f"""
        UNWIND $rows AS r
        MATCH (a:Function {{id: r.src}})
        MATCH (h:Hook {{name: r.hook}})
        MERGE (a)-[rel:USES_HOOK]->(h)
        SET rel.confidence = r.confidence, rel.confidence_score = r.confidence_score
    """, buckets.get(USES_HOOK, []))
    stats.edges[USES_HOOK] = len(buckets.get(USES_HOOK, []))

    _run(session, f"""
        UNWIND $rows AS r
        MATCH (o:GraphQLOperation {{id: r.src}})
        MATCH (c:Class {{id: r.dst}})
        MERGE (o)-[rel:RETURNS]->(c)
        SET rel.confidence = r.confidence, rel.confidence_score = r.confidence_score
    """, buckets.get(RETURNS, []))
    stats.edges[RETURNS] = len(buckets.get(RETURNS, []))

    _run(session, f"""
        UNWIND $rows AS r
        MATCH (a) WHERE a.id = r.src
        MATCH (e:Endpoint {{id: r.dst}})
        MERGE (a)-[rel:CALLS_ENDPOINT]->(e)
        SET rel.url = r.url{_CONF_SET}
    """, buckets.get(CALLS_ENDPOINT, []))
    stats.edges[CALLS_ENDPOINT] = len(buckets.get(CALLS_ENDPOINT, []))

    _run(session, f"""
        UNWIND $rows AS r
        MATCH (a) WHERE a.id = r.src
        MATCH (o:GraphQLOperation {{id: r.dst}})
        MERGE (a)-[rel:USES_OPERATION]->(o)
        SET rel.op_name = r.op_name{_CONF_SET}
    """, buckets.get(USES_OPERATION, []))
    stats.edges[USES_OPERATION] = len(buckets.get(USES_OPERATION, []))

    _run(session, f"""
        UNWIND $rows AS r
        MATCH (a:Method {{id: r.src}})
        MATCH (b:Method {{id: r.dst}})
        MERGE (a)-[rel:CALLS]->(b)
        SET rel.resolution = r.resolution{_CONF_SET}
    """, buckets.get(CALLS, []))
    stats.edges[CALLS] = len(buckets.get(CALLS, []))

    handles_endpoint = [r for r in buckets.get(HANDLES, []) if r["dst"].startswith("endpoint:")]
    handles_gqlop = [r for r in buckets.get(HANDLES, []) if r["dst"].startswith("gqlop:")]
    _run(session, f"""
        UNWIND $rows AS r
        MATCH (m:Method {{id: r.src}})
        MATCH (e:Endpoint {{id: r.dst}})
        MERGE (m)-[rel:HANDLES]->(e)
        SET rel.confidence = r.confidence, rel.confidence_score = r.confidence_score
    """, handles_endpoint)
    _run(session, f"""
        UNWIND $rows AS r
        MATCH (m:Method {{id: r.src}})
        MATCH (o:GraphQLOperation {{id: r.dst}})
        MERGE (m)-[rel:HANDLES]->(o)
        SET rel.confidence = r.confidence, rel.confidence_score = r.confidence_score
    """, handles_gqlop)
    stats.edges[HANDLES] = len(handles_endpoint) + len(handles_gqlop)

    # Decorator edges
    _run(session, f"""
        UNWIND $rows AS r
        MATCH (a:Class {{id: r.src}})
        MATCH (d:Decorator {{name: r.name}})
        MERGE (a)-[rel:DECORATED_BY]->(d)
        SET rel.confidence = r.confidence, rel.confidence_score = r.confidence_score
    """, dec_class)
    _run(session, f"""
        UNWIND $rows AS r
        MATCH (a:Function {{id: r.src}})
        MATCH (d:Decorator {{name: r.name}})
        MERGE (a)-[rel:DECORATED_BY]->(d)
        SET rel.confidence = r.confidence, rel.confidence_score = r.confidence_score
    """, dec_func)
    _run(session, f"""
        UNWIND $rows AS r
        MATCH (a:Method {{id: r.src}})
        MATCH (d:Decorator {{name: r.name}})
        MERGE (a)-[rel:DECORATED_BY]->(d)
        SET rel.confidence = r.confidence, rel.confidence_score = r.confidence_score
    """, dec_method)
    stats.edges[DECORATED_BY] = len(dec_class) + len(dec_func) + len(dec_method)


def _write_per_file_extras(session, index: Index, stats: LoadStats, touched_files: set[str] | None = None) -> None:
    """Atom reads/writes, env reads, events — sourced from ParseResult per-file lists."""
    atom_reads: list = []
    atom_writes: list = []
    env_reads: list = []
    event_handlers: list = []
    event_emitters: list = []

    for rel, result in index.files_by_path.items():
        if touched_files is not None and rel not in touched_files:
            continue
        repo = result.file.repo
        # Atom reads/writes: (component_name, atom_name) — lookup atom by name across files
        for comp, atom_name in result.atom_reads:
            atom_reads.append(dict(
                fn_id=f"func:{repo}:{rel}#{comp}",
                atom_name=atom_name,
            ))
        for comp, atom_name in result.atom_writes:
            atom_writes.append(dict(
                fn_id=f"func:{repo}:{rel}#{comp}",
                atom_name=atom_name,
            ))
        for env_name in set(result.env_reads):
            env_reads.append(dict(
                file_id=f"file:{repo}:{rel}",
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
        MERGE (fn)-[rel:READS_ATOM]->(a)
        SET rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0
    """, atom_reads)
    stats.edges[READS_ATOM] = len(atom_reads)

    _run(session, """
        UNWIND $rows AS r
        MATCH (fn:Function {id: r.fn_id})
        MATCH (a:Atom {name: r.atom_name})
        MERGE (fn)-[rel:WRITES_ATOM]->(a)
        SET rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0
    """, atom_writes)
    stats.edges[WRITES_ATOM] = len(atom_writes)

    _run(session, """
        UNWIND $rows AS r
        MATCH (f:File {id: r.file_id})
        MATCH (e:EnvVar {name: r.env})
        MERGE (f)-[rel:READS_ENV]->(e)
        SET rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0
    """, env_reads)
    stats.edges[READS_ENV] = len(env_reads)

    _run(session, """
        UNWIND $rows AS r
        MATCH (m:Method {id: r.method})
        MATCH (e:Event {name: r.event})
        MERGE (m)-[rel:HANDLES_EVENT]->(e)
        SET rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0
    """, event_handlers)
    stats.edges[HANDLES_EVENT] = len(event_handlers)

    _run(session, """
        UNWIND $rows AS r
        MATCH (m:Method {id: r.method})
        MATCH (e:Event {name: r.event})
        MERGE (m)-[rel:EMITS_EVENT]->(e)
        SET rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0
    """, event_emitters)
    stats.edges[EMITS_EVENT] = len(event_emitters)


def _write_test_edges(session, index: Index, stats: LoadStats) -> None:
    """Link test files to their production peer by filename.

    TS: ``foo.spec.ts`` / ``foo.test.tsx`` → ``foo.ts`` / ``foo.tsx`` (same dir).
    Python: ``test_foo.py`` / ``foo_test.py`` → ``foo.py`` (same dir only —
    cross-directory pairing is ambiguous, deferred to Stage 2). ``conftest.py``
    never pairs.
    """
    import posixpath

    rows: list = []
    rows_class: list = []
    files = index.files_by_path

    for rel, r in files.items():
        if not r.file.is_test:
            continue
        peer = None

        # TS pairing
        if rel.endswith(TS_TEST_SUFFIXES):
            for suf in TS_TEST_SUFFIXES:
                if rel.endswith(suf):
                    base = rel[: -len(suf)]
                    for ext in (".ts", ".tsx"):
                        cand = base + ext
                        if cand in files:
                            peer = cand
                            break
                    break
        # Python pairing — same directory only
        elif rel.endswith(".py"):
            dirpath, basename = posixpath.split(rel)
            if basename == PY_CONFTEST_FILENAME:
                continue
            cand = None
            if basename.endswith(PY_TEST_SUFFIX_TRAILING):
                cand = posixpath.join(dirpath, basename[: -len(PY_TEST_SUFFIX_TRAILING)] + ".py")
            elif basename.startswith(PY_TEST_PREFIX):
                cand = posixpath.join(dirpath, basename[len(PY_TEST_PREFIX):])
            if cand and cand in files:
                peer = cand

        if peer:
            repo = r.file.repo
            rows.append(dict(test_id=f"file:{repo}:{rel}",
                             peer_id=f"file:{repo}:{peer}"))
        # Also link by described subject
        for subj in r.described_subjects:
            repo = r.file.repo
            rows_class.append(dict(test_id=f"file:{repo}:{rel}", name=subj))

    _run(session, """
        UNWIND $rows AS r
        MATCH (t:File {id: r.test_id})
        MATCH (p:File {id: r.peer_id})
        MERGE (t)-[rel:TESTS]->(p)
        SET rel.confidence = 'INFERRED', rel.confidence_score = 0.5
    """, rows)
    stats.edges[TESTS] = len(rows)

    _run(session, """
        UNWIND $rows AS r
        MATCH (t:File {id: r.test_id})
        MATCH (c:Class {name: r.name})
        MERGE (t)-[rel:TESTS_CLASS]->(c)
        SET rel.confidence = 'INFERRED', rel.confidence_score = 0.6
    """, rows_class)
    stats.edges[TESTS_CLASS] = len(rows_class)


def _write_ownership(session, ownership: dict, stats: LoadStats, repo_name: str = "default") -> None:
    """Phase 7: git log + CODEOWNERS ingestion."""
    authors = ownership.get("authors", [])
    teams = ownership.get("teams", [])
    last_mod = ownership.get("last_modified", [])
    contribs = ownership.get("contributors", [])
    owned = ownership.get("owned_by", [])

    _run(session, """
        UNWIND $rows AS r
        MERGE (a:Author {email: r.email})
        SET a.name = r.name
    """, [dict(email=a["email"], name=a.get("name", "")) for a in authors])
    _run(session, "UNWIND $rows AS r MERGE (:Team {name: r.name})",
         [dict(name=t) for t in teams])

    # Ownership dicts contain {path: ...} — enrich with file_id for id-based MATCH.
    def _enrich(rows):
        return [{**r, "file_id": f"file:{repo_name}:{r['path']}"} for r in rows]

    _run(session, """
        UNWIND $rows AS r
        MATCH (f:File {id: r.file_id})
        MATCH (a:Author {email: r.email})
        MERGE (f)-[rel:LAST_MODIFIED_BY]->(a)
        SET rel.at = r.at, rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0
    """, _enrich(last_mod))
    stats.edges[LAST_MODIFIED_BY] = len(last_mod)

    _run(session, """
        UNWIND $rows AS r
        MATCH (f:File {id: r.file_id})
        MATCH (a:Author {email: r.email})
        MERGE (f)-[rel:CONTRIBUTED_BY]->(a)
        SET rel.commits = r.commits, rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0
    """, _enrich(contribs))
    stats.edges[CONTRIBUTED_BY] = len(contribs)

    _run(session, """
        UNWIND $rows AS r
        MATCH (f:File {id: r.file_id})
        MATCH (t:Team {name: r.team})
        MERGE (f)-[rel:OWNED_BY]->(t)
        SET rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0
    """, _enrich(owned))
    stats.edges[OWNED_BY] = len(owned)


def _write_edge_groups(
    session, edge_groups: list[EdgeGroupNode], edges: list[Edge], stats: LoadStats,
) -> None:
    """Phase 10: persist EdgeGroup nodes + MEMBER_OF edges from resolver."""
    # Clean stale protocol-implementer groups (community groups are managed by analyze.py)
    session.run("MATCH (eg:EdgeGroup {kind: 'protocol_implementers'}) DETACH DELETE eg")

    # Batch MERGE EdgeGroup nodes
    eg_rows = [
        dict(id=eg.id, name=eg.name, kind=eg.kind,
             node_count=eg.node_count, confidence=eg.confidence)
        for eg in edge_groups
    ]
    _run(session, """
        UNWIND $rows AS r
        MERGE (eg:EdgeGroup {id: r.id})
        SET eg.name = r.name, eg.kind = r.kind,
            eg.node_count = r.node_count, eg.confidence = r.confidence
    """, eg_rows)
    stats.edge_groups = len(edge_groups)

    # Batch MERGE MEMBER_OF edges
    member_rows = [
        dict(src_id=e.src_id, dst_id=e.dst_id)
        for e in edges if e.kind == MEMBER_OF
    ]
    _run(session, """
        UNWIND $rows AS r
        MATCH (n) WHERE n.id = r.src_id
        MATCH (eg:EdgeGroup {id: r.dst_id})
        MERGE (n)-[rel:MEMBER_OF]->(eg)
        SET rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0
    """, member_rows)
    stats.member_of_edges = len(member_rows)
    stats.edges[MEMBER_OF] = len(member_rows)
