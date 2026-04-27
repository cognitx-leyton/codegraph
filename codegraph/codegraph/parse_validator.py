"""Pre-load validation for ParseResult objects.

Catches malformed nodes and edges *before* they reach the Neo4j loader.
The post-load validator lives in ``validate.py``; this module is its
pre-load counterpart.
"""

from __future__ import annotations

from .schema import (
    Edge,
    ParseResult,
    # Phase 1
    IMPORTS,
    IMPORTS_SYMBOL,
    IMPORTS_EXTERNAL,
    DEFINES_CLASS,
    DEFINES_FUNC,
    DEFINES_IFACE,
    HAS_METHOD,
    EXPOSES,
    HANDLES,
    INJECTS,
    EXTENDS,
    IMPLEMENTS,
    DECORATED_BY,
    RENDERS,
    USES_HOOK,
    # Phase 2 — TypeORM
    HAS_COLUMN,
    RELATES_TO,
    REPOSITORY_OF,
    # Phase 3 — GraphQL + cross-layer
    RESOLVES,
    RETURNS,
    CALLS_ENDPOINT,
    USES_OPERATION,
    # Phase 4 — method call graph
    CALLS,
    # Phase 5 — NestJS module
    PROVIDES,
    EXPORTS_PROVIDER,
    IMPORTS_MODULE,
    DECLARES_CONTROLLER,
    # Phase 6 — tests + events
    TESTS,
    TESTS_CLASS,
    HANDLES_EVENT,
    EMITS_EVENT,
    # Phase 7 — git
    LAST_MODIFIED_BY,
    CONTRIBUTED_BY,
    OWNED_BY,
    # Phase 8 — frontend
    DEFINES_ATOM,
    READS_ATOM,
    WRITES_ATOM,
    READS_ENV,
    # Phase 9 — package / framework detection
    BELONGS_TO,
    # Phase 10 — hyperedges
    MEMBER_OF,
    # Phase 11 — documents
    HAS_SECTION,
    REFERENCES_DOCUMENT,
    # Phase 12 — semantic extraction
    DOCUMENTS_CONCEPT,
    DECIDES,
    JUSTIFIES,
    SEMANTICALLY_SIMILAR_TO,
    # Phase 13 — vision extraction
    ILLUSTRATES_CONCEPT,
    SHOWS_ARCHITECTURE,
)

# ── Constants ─────────────────────────────────────────────────

VALID_EDGE_KINDS: frozenset[str] = frozenset({
    IMPORTS, IMPORTS_SYMBOL, IMPORTS_EXTERNAL,
    DEFINES_CLASS, DEFINES_FUNC, DEFINES_IFACE,
    HAS_METHOD, EXPOSES, HANDLES, INJECTS,
    EXTENDS, IMPLEMENTS, DECORATED_BY, RENDERS, USES_HOOK,
    HAS_COLUMN, RELATES_TO, REPOSITORY_OF,
    RESOLVES, RETURNS, CALLS_ENDPOINT, USES_OPERATION,
    CALLS,
    PROVIDES, EXPORTS_PROVIDER, IMPORTS_MODULE, DECLARES_CONTROLLER,
    TESTS, TESTS_CLASS, HANDLES_EVENT, EMITS_EVENT,
    LAST_MODIFIED_BY, CONTRIBUTED_BY, OWNED_BY,
    DEFINES_ATOM, READS_ATOM, WRITES_ATOM, READS_ENV,
    BELONGS_TO,
    MEMBER_OF,
    HAS_SECTION, REFERENCES_DOCUMENT,
    DOCUMENTS_CONCEPT, DECIDES, JUSTIFIES, SEMANTICALLY_SIMILAR_TO,
    ILLUSTRATES_CONCEPT, SHOWS_ARCHITECTURE,
    "__STATS__",
})

VALID_CONFIDENCE_LABELS: frozenset[str] = frozenset({
    "EXTRACTED", "INFERRED", "AMBIGUOUS",
})

SYNTHETIC_ID_PREFIXES: tuple[str, ...] = (
    "external:", "dec:", "hook:", "edgegroup:",
)


# ── Helpers ───────────────────────────────────────────────────

def _collect_node_ids(result: ParseResult) -> set[str]:
    """Return the set of all node ``.id`` values in *result*."""
    ids: set[str] = set()
    ids.add(result.file.id)
    for lst in (
        result.classes, result.functions, result.interfaces,
        result.endpoints, result.methods, result.columns,
        result.gql_operations, result.atoms, result.routes,
    ):
        for node in lst:
            ids.add(node.id)
    return ids


def _is_synthetic(node_id: str) -> bool:
    """Return *True* if *node_id* starts with a known synthetic prefix."""
    return any(node_id.startswith(p) for p in SYNTHETIC_ID_PREFIXES)


# ── Per-file validation ──────────────────────────────────────

def validate_parse_result(result: ParseResult) -> list[str]:
    """Validate a single file's *ParseResult*.

    Returns a list of human-readable error strings (empty == valid).
    """
    errors: list[str] = []
    node_ids = _collect_node_ids(result)

    # 1. Duplicate node IDs
    seen: set[str] = set()
    seen.add(result.file.id)
    for lst in (
        result.classes, result.functions, result.interfaces,
        result.endpoints, result.methods, result.columns,
        result.gql_operations, result.atoms, result.routes,
    ):
        for node in lst:
            if node.id in seen:
                errors.append(f"duplicate node id: {node.id}")
            seen.add(node.id)

    # 2. Edge validation
    for edge in result.edges:
        _validate_edge(edge, node_ids, errors)

    return errors


def _validate_edge(edge: Edge, valid_ids: set[str], errors: list[str]) -> None:
    """Check a single edge's referential integrity, kind, and confidence."""
    # Referential integrity
    if edge.src_id not in valid_ids and not _is_synthetic(edge.src_id):
        errors.append(f"edge {edge.kind}: dangling src_id {edge.src_id}")
    if edge.dst_id not in valid_ids and not _is_synthetic(edge.dst_id):
        errors.append(f"edge {edge.kind}: dangling dst_id {edge.dst_id}")
    # Kind allowlist
    if edge.kind not in VALID_EDGE_KINDS:
        errors.append(f"edge: unknown kind '{edge.kind}'")
    # Confidence label
    if edge.confidence not in VALID_CONFIDENCE_LABELS:
        errors.append(f"edge {edge.kind}: invalid confidence '{edge.confidence}'")
    # Confidence score range
    if not (0.0 <= edge.confidence_score <= 1.0):
        errors.append(
            f"edge {edge.kind}: confidence_score {edge.confidence_score} "
            f"out of range [0.0, 1.0]"
        )


# ── Cross-file validation ────────────────────────────────────

def validate_cross_file_edges(
    edges: list[Edge],
    index: "Index",  # noqa: F821 — forward ref to resolver.Index
) -> list[str]:
    """Validate cross-file edges against the global node-ID pool.

    *index* is a :class:`~codegraph.resolver.Index` whose
    ``files_by_path`` holds every parsed file's result.
    """
    # Build the global set of all node IDs across files
    all_ids: set[str] = set()
    for result in index.files_by_path.values():
        all_ids.update(_collect_node_ids(result))

    errors: list[str] = []
    for edge in edges:
        # __STATS__ sentinel has empty src/dst — skip it
        if edge.kind == "__STATS__":
            continue
        _validate_edge(edge, all_ids, errors)
    return errors


# ── Strict-mode helper ────────────────────────────────────────

def assert_valid(result: ParseResult) -> None:
    """Raise :class:`ValueError` if *result* has any validation errors."""
    errors = validate_parse_result(result)
    if errors:
        bullet_list = "\n".join(f"  - {e}" for e in errors)
        raise ValueError(
            f"{len(errors)} validation error(s):\n{bullet_list}"
        )
