"""Graph schema: typed node + edge dataclasses shared across parser → loader."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .framework import FrameworkInfo


# ── Nodes ────────────────────────────────────────────────────

@dataclass
class PackageNode:
    """A monorepo package with per-package framework detection.

    Mirrors :class:`codegraph.framework.FrameworkInfo` as a flat set of
    properties so every field is queryable directly in Cypher without a join.
    The ``name`` matches the ``package`` string already stored on
    :class:`FileNode`, and :class:`FileNode` → :class:`PackageNode` is wired
    via ``BELONGS_TO`` at load time (see :mod:`codegraph.loader`).
    """
    name: str
    framework: str                                  # display name: "React", "Next.js", "Odoo", ...
    framework_version: Optional[str] = None
    typescript: bool = False
    styling: list[str] = field(default_factory=list)
    router: Optional[str] = None
    state_management: list[str] = field(default_factory=list)
    ui_library: Optional[str] = None
    build_tool: Optional[str] = None
    package_manager: Optional[str] = None
    confidence: float = 0.0

    @property
    def id(self) -> str:
        return f"package:{self.name}"

    @classmethod
    def from_framework_info(cls, name: str, info: "FrameworkInfo") -> "PackageNode":
        return cls(
            name=name,
            framework=info.display_name,
            framework_version=info.version,
            typescript=info.typescript,
            styling=list(info.styling),
            router=info.router,
            state_management=list(info.state_management),
            ui_library=info.ui_library,
            build_tool=info.build_tool,
            package_manager=info.package_manager,
            confidence=info.confidence,
        )


@dataclass
class FileNode:
    path: str
    package: str
    language: str
    loc: int
    is_controller: bool = False
    is_injectable: bool = False
    is_module: bool = False
    is_component: bool = False
    is_entity: bool = False
    is_resolver: bool = False
    is_test: bool = False

    @property
    def id(self) -> str:
        return f"file:{self.path}"


@dataclass
class ClassNode:
    name: str
    file: str
    is_controller: bool = False
    is_injectable: bool = False
    is_module: bool = False
    is_entity: bool = False
    is_resolver: bool = False
    is_abstract: bool = False
    base_path: str = ""
    table_name: str = ""  # for entities

    @property
    def id(self) -> str:
        return f"class:{self.file}#{self.name}"


@dataclass
class FunctionNode:
    name: str
    file: str
    is_component: bool = False
    exported: bool = False
    docstring: str = ""
    return_type: str = ""
    params_json: str = "[]"

    @property
    def id(self) -> str:
        return f"func:{self.file}#{self.name}"


@dataclass
class InterfaceNode:
    name: str
    file: str

    @property
    def id(self) -> str:
        return f"interface:{self.file}#{self.name}"


@dataclass
class MethodNode:
    name: str
    class_id: str
    file: str
    is_static: bool = False
    is_async: bool = False
    is_constructor: bool = False
    visibility: str = "public"   # public | private | protected
    return_type: str = ""
    params_json: str = "[]"
    docstring: str = ""

    @property
    def id(self) -> str:
        return f"method:{self.class_id}#{self.name}"


@dataclass
class EndpointNode:
    method: str
    path: str
    controller_class: str
    file: str
    handler: str

    @property
    def id(self) -> str:
        return f"endpoint:{self.method}:{self.path}@{self.file}#{self.handler}"


@dataclass
class ColumnNode:
    entity_id: str
    name: str
    type: str = ""
    nullable: bool = False
    unique: bool = False
    primary: bool = False
    generated: bool = False

    @property
    def id(self) -> str:
        return f"column:{self.entity_id}#{self.name}"


@dataclass
class GraphQLOperationNode:
    op_type: str          # query | mutation | subscription
    name: str
    return_type: str      # best-effort
    file: str
    resolver_class: str   # class id
    handler: str          # method name

    @property
    def id(self) -> str:
        return f"gqlop:{self.op_type}:{self.name}@{self.file}#{self.handler}"


@dataclass
class EventNode:
    name: str

    @property
    def id(self) -> str:
        return f"event:{self.name}"


@dataclass
class AtomNode:
    name: str
    file: str
    family: bool = False

    @property
    def id(self) -> str:
        return f"atom:{self.file}#{self.name}"


@dataclass
class EnvVarNode:
    name: str

    @property
    def id(self) -> str:
        return f"env:{self.name}"


@dataclass
class RouteNode:
    path: str
    component_name: str
    file: str

    @property
    def id(self) -> str:
        return f"route:{self.path}@{self.file}"


@dataclass
class ExternalNode:
    specifier: str

    @property
    def id(self) -> str:
        return f"external:{self.specifier}"


@dataclass
class EdgeGroupNode:
    name: str
    kind: str          # 'protocol_implementers', 'community', etc.
    node_count: int = 0
    confidence: float = 1.0

    @property
    def id(self) -> str:
        return f"edgegroup:{self.kind}:{self.name}"


# ── Edges ────────────────────────────────────────────────────

@dataclass
class Edge:
    kind: str
    src_id: str
    dst_id: str
    props: dict = field(default_factory=dict)
    confidence: str = "EXTRACTED"
    confidence_score: float = 1.0


# Edge kind constants
IMPORTS           = "IMPORTS"
IMPORTS_SYMBOL    = "IMPORTS_SYMBOL"
IMPORTS_EXTERNAL  = "IMPORTS_EXTERNAL"
DEFINES_CLASS     = "DEFINES_CLASS"
DEFINES_FUNC      = "DEFINES_FUNC"
DEFINES_IFACE     = "DEFINES_IFACE"
HAS_METHOD        = "HAS_METHOD"
EXPOSES           = "EXPOSES"
HANDLES           = "HANDLES"
INJECTS           = "INJECTS"
EXTENDS           = "EXTENDS"
IMPLEMENTS        = "IMPLEMENTS"
DECORATED_BY      = "DECORATED_BY"
RENDERS           = "RENDERS"
USES_HOOK         = "USES_HOOK"

# Phase 2 — TypeORM
HAS_COLUMN        = "HAS_COLUMN"
RELATES_TO        = "RELATES_TO"
REPOSITORY_OF     = "REPOSITORY_OF"

# Phase 3 — GraphQL + cross-layer
RESOLVES          = "RESOLVES"
RETURNS           = "RETURNS"
CALLS_ENDPOINT    = "CALLS_ENDPOINT"
USES_OPERATION    = "USES_OPERATION"

# Phase 4 — method call graph
CALLS             = "CALLS"

# Phase 5 — NestJS module
PROVIDES          = "PROVIDES"
EXPORTS_PROVIDER  = "EXPORTS_PROVIDER"
IMPORTS_MODULE    = "IMPORTS_MODULE"
DECLARES_CONTROLLER = "DECLARES_CONTROLLER"

# Phase 6 — tests + events
TESTS             = "TESTS"
TESTS_CLASS       = "TESTS_CLASS"
HANDLES_EVENT     = "HANDLES_EVENT"
EMITS_EVENT       = "EMITS_EVENT"

# Phase 7 — git
LAST_MODIFIED_BY  = "LAST_MODIFIED_BY"
CONTRIBUTED_BY    = "CONTRIBUTED_BY"
OWNED_BY          = "OWNED_BY"

# Phase 8 — frontend targeted
DEFINES_ATOM      = "DEFINES_ATOM"
READS_ATOM        = "READS_ATOM"
WRITES_ATOM       = "WRITES_ATOM"
READS_ENV         = "READS_ENV"

# Phase 9 — package / framework detection
BELONGS_TO        = "BELONGS_TO"

# Phase 10 — hyperedges / group relationships
MEMBER_OF         = "MEMBER_OF"


# ── Test-file pairing conventions ────────────────────────────
TS_TEST_SUFFIXES = (".spec.ts", ".spec.tsx", ".test.ts", ".test.tsx")
PY_TEST_SUFFIX_TRAILING = "_test.py"       # foo_test.py ↔ foo.py
PY_TEST_PREFIX = "test_"                   # test_foo.py ↔ foo.py
PY_CONFTEST_FILENAME = "conftest.py"       # no pairing


# ── Import spec (Phase 1) ────────────────────────────────────

@dataclass
class ImportSpec:
    specifier: str
    type_only: bool = False
    symbols: list[str] = field(default_factory=list)   # named imports
    default: Optional[str] = None                      # default import name
    namespace: Optional[str] = None                    # import * as X


# ── ParseResult ─────────────────────────────────────────────

@dataclass
class ParseResult:
    file: FileNode
    classes: list[ClassNode] = field(default_factory=list)
    functions: list[FunctionNode] = field(default_factory=list)
    interfaces: list[InterfaceNode] = field(default_factory=list)
    endpoints: list[EndpointNode] = field(default_factory=list)

    # Phase 1
    imports: list[ImportSpec] = field(default_factory=list)

    # Phase 2 — TypeORM
    columns: list[ColumnNode] = field(default_factory=list)
    relations: list[tuple[str, str, str, str]] = field(default_factory=list)
        # (entity_class_name, kind, field_name, target_type_name)
    repository_refs: list[tuple[str, str]] = field(default_factory=list)
        # (class_name, repo_target_type_name)

    # Phase 3 — GraphQL
    gql_operations: list[GraphQLOperationNode] = field(default_factory=list)
    rest_calls: list[tuple[str, str, str]] = field(default_factory=list)
        # (containing_function_name, http_method_or_None, url_template)
    gql_literals: list[tuple[str, str, str]] = field(default_factory=list)
        # (containing_function_name, op_type, op_name)

    # Phase 4 — methods
    methods: list[MethodNode] = field(default_factory=list)
    method_calls: list[tuple[str, str, str, str]] = field(default_factory=list)
        # (caller_method_id, receiver_kind, receiver_name, method_name)
        # receiver_kind in {'this','this.<field>','name'}

    # Phase 6 — tests + events
    described_subjects: list[str] = field(default_factory=list)
    event_handlers: list[tuple[str, str]] = field(default_factory=list)   # (method_id, event_name)
    event_emitters: list[tuple[str, str]] = field(default_factory=list)   # (method_id, event_name)

    # Phase 8 — frontend
    atoms: list[AtomNode] = field(default_factory=list)
    atom_reads: list[tuple[str, str]] = field(default_factory=list)       # (component_name, atom_name)
    atom_writes: list[tuple[str, str]] = field(default_factory=list)      # (component_name, atom_name)
    env_reads: list[str] = field(default_factory=list)                    # env var names
    routes: list[RouteNode] = field(default_factory=list)

    # Intra-file edges (emitted immediately)
    edges: list[Edge] = field(default_factory=list)

    # Name-based references resolved in second pass
    class_extends: list[tuple[str, str]] = field(default_factory=list)
    class_implements: list[tuple[str, str]] = field(default_factory=list)
    di_refs: list[tuple[str, str]] = field(default_factory=list)
    jsx_renders: list[tuple[str, str]] = field(default_factory=list)
    hook_calls: list[tuple[str, str]] = field(default_factory=list)

    # Phase 5 — module graph name refs
    module_providers: list[tuple[str, str]] = field(default_factory=list)      # (module, provider_name)
    module_exports: list[tuple[str, str]] = field(default_factory=list)        # (module, exported_name)
    module_imports: list[tuple[str, str]] = field(default_factory=list)        # (module, imported_module_name)
    module_controllers: list[tuple[str, str]] = field(default_factory=list)    # (module, controller_name)


# ── ParseResult serialisation ──────────────────────────────

def parse_result_to_dict(result: ParseResult) -> dict:
    """Serialise a *ParseResult* to a plain dict suitable for ``json.dumps``."""
    return dataclasses.asdict(result)


def parse_result_from_dict(d: dict) -> ParseResult:
    """Reconstruct a *ParseResult* from the dict produced by :func:`parse_result_to_dict`.

    Uses ``.get()`` with defaults so older cache entries missing newly-added
    fields still load without error.
    """
    # --- node-list fields (need dataclass reconstruction) ---
    file = FileNode(**d["file"])
    classes = [ClassNode(**c) for c in d.get("classes", [])]
    functions = [FunctionNode(**f) for f in d.get("functions", [])]
    interfaces = [InterfaceNode(**i) for i in d.get("interfaces", [])]
    endpoints = [EndpointNode(**e) for e in d.get("endpoints", [])]
    imports = [ImportSpec(**s) for s in d.get("imports", [])]
    columns = [ColumnNode(**c) for c in d.get("columns", [])]
    gql_operations = [GraphQLOperationNode(**o) for o in d.get("gql_operations", [])]
    methods = [MethodNode(**m) for m in d.get("methods", [])]
    atoms = [AtomNode(**a) for a in d.get("atoms", [])]
    routes = [RouteNode(**r) for r in d.get("routes", [])]
    edges = [Edge(**e) for e in d.get("edges", [])]

    # --- tuple-list fields (JSON lists-of-lists → lists-of-tuples) ---
    _tup = lambda key: [tuple(x) for x in d.get(key, [])]  # noqa: E731

    return ParseResult(
        file=file,
        classes=classes,
        functions=functions,
        interfaces=interfaces,
        endpoints=endpoints,
        imports=imports,
        columns=columns,
        gql_operations=gql_operations,
        methods=methods,
        atoms=atoms,
        routes=routes,
        edges=edges,
        relations=_tup("relations"),
        repository_refs=_tup("repository_refs"),
        rest_calls=_tup("rest_calls"),
        gql_literals=_tup("gql_literals"),
        method_calls=_tup("method_calls"),
        event_handlers=_tup("event_handlers"),
        event_emitters=_tup("event_emitters"),
        atom_reads=_tup("atom_reads"),
        atom_writes=_tup("atom_writes"),
        class_extends=_tup("class_extends"),
        class_implements=_tup("class_implements"),
        di_refs=_tup("di_refs"),
        jsx_renders=_tup("jsx_renders"),
        hook_calls=_tup("hook_calls"),
        module_providers=_tup("module_providers"),
        module_exports=_tup("module_exports"),
        module_imports=_tup("module_imports"),
        module_controllers=_tup("module_controllers"),
        # plain list[str] fields
        described_subjects=d.get("described_subjects", []),
        env_reads=d.get("env_reads", []),
    )
