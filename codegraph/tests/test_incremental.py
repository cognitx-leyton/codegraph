"""Tests for incremental re-indexing (``--since`` flag).

Covers:
- ``_git_changed_files`` — subprocess parsing of ``git diff --name-status``
- ``Neo4jLoader.delete_file_subgraph`` — scoped cleanup Cypher
- ``Neo4jLoader.load(touched_files=...)`` — selective node/edge loading
- ``_file_from_id`` — node-ID → file-path extraction
"""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from codegraph import loader
from codegraph.cli import _git_changed_files
from codegraph.config import ConfigError
from codegraph.loader import Neo4jLoader, _file_from_id
from codegraph.resolver import Index
from codegraph.schema import (
    ClassNode,
    ColumnNode,
    Edge,
    FileNode,
    FunctionNode,
    IMPORTS,
    IMPORTS_SYMBOL,
    ParseResult,
    READS_ATOM,
    WRITES_ATOM,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _fake_index(files: dict[str, bool]) -> Index:
    """Build an Index with files keyed by path; value = is_test flag."""
    idx = Index()
    for path, is_test in files.items():
        language = "py" if path.endswith(".py") else "ts"
        fn = FileNode(path=path, package="p", language=language, loc=1, is_test=is_test)
        idx.files_by_path[path] = ParseResult(file=fn)
    return idx


class _Stats:
    def __init__(self):
        self.edges: dict = {}


# ── Test group 1: _git_changed_files ──────────────────────────────────


def test_git_diff_parses_modified_and_deleted(monkeypatch):
    """Modified → modified set, deleted → deleted set."""
    fake_output = "M\tsrc/foo.py\nA\tsrc/bar.py\nD\tsrc/old.py\n"
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout=fake_output, stderr=""),
    )
    modified, deleted = _git_changed_files("/repo", "HEAD~3")
    assert modified == {"src/foo.py", "src/bar.py"}
    assert deleted == {"src/old.py"}


def test_git_diff_handles_renames(monkeypatch):
    """Rename → old in deleted, new in modified."""
    fake_output = "R100\tsrc/old_name.py\tsrc/new_name.py\n"
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout=fake_output, stderr=""),
    )
    modified, deleted = _git_changed_files("/repo", "HEAD~1")
    assert "src/old_name.py" in deleted
    assert "src/new_name.py" in modified


def test_git_diff_bad_ref_raises_config_error(monkeypatch):
    """Non-zero returncode from git → ConfigError."""
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: MagicMock(returncode=128, stdout="", stderr="fatal: bad ref"),
    )
    with pytest.raises(ConfigError, match="bad ref"):
        _git_changed_files("/repo", "NOTAREF")


def test_git_diff_empty_diff_returns_empty_sets(monkeypatch):
    """No changes → both sets empty."""
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout="", stderr=""),
    )
    modified, deleted = _git_changed_files("/repo", "HEAD")
    assert modified == set()
    assert deleted == set()


def test_git_diff_filters_non_code_extensions(monkeypatch):
    """Non-code files (md, yml, json, txt) are excluded; .py/.ts/.tsx pass through."""
    fake_output = (
        "M\tsrc/foo.py\n"
        "A\tsrc/bar.ts\n"
        "M\tsrc/app.tsx\n"
        "M\tREADME.md\n"
        "A\t.github/ci.yml\n"
        "D\tdocs/notes.txt\n"
        "D\tsrc/old.ts\n"
    )
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: MagicMock(returncode=0, stdout=fake_output, stderr=""),
    )
    modified, deleted = _git_changed_files("/repo", "HEAD~1")
    assert modified == {"src/foo.py", "src/bar.ts", "src/app.tsx"}
    assert deleted == {"src/old.ts"}


# ── Test group 2: delete_file_subgraph ────────────────────────────────


def test_delete_subgraph_emits_correct_cypher():
    """Verify all expected Cypher statements are emitted for the given paths."""
    session_mock = MagicMock()
    # Build a minimal loader with a fake driver
    ldr = Neo4jLoader.__new__(Neo4jLoader)
    ldr.database = "neo4j"

    class FakeCtx:
        def __enter__(self):
            return session_mock
        def __exit__(self, *a):
            pass

    ldr.driver = MagicMock()
    ldr.driver.session.return_value = FakeCtx()

    count = ldr.delete_file_subgraph(["a.py", "b.py"])
    assert count == 2

    # Should have been called 3 times (class grandchildren, owned children,
    # file node)
    calls = session_mock.run.call_args_list
    assert len(calls) == 3

    # Verify all calls received rows with both paths
    for call in calls:
        rows = call.kwargs.get("rows") or call[1].get("rows", [])
        paths = {r["path"] for r in rows}
        assert paths == {"a.py", "b.py"}


def test_delete_subgraph_empty_paths_is_noop():
    """Empty list → no session opened, returns 0."""
    ldr = Neo4jLoader.__new__(Neo4jLoader)
    ldr.database = "neo4j"
    ldr.driver = MagicMock()
    assert ldr.delete_file_subgraph([]) == 0
    ldr.driver.session.assert_not_called()


# ── Test group 3: load() with touched_files filter ────────────────────


@pytest.fixture
def captured_runs(monkeypatch):
    """Monkeypatch ``loader._run`` to record every (cypher, rows) pair."""
    calls: list[tuple[str, list]] = []

    def fake_run(session, cypher, rows):
        calls.append((cypher, list(rows)))

    monkeypatch.setattr(loader, "_run", fake_run)
    return calls


def test_load_touched_files_filters_nodes(captured_runs):
    """Only nodes from touched files appear in MERGE rows."""
    idx = Index()
    for path in ("a.py", "b.py", "c.py"):
        fn = FileNode(path=path, package="p", language="py", loc=10)
        pr = ParseResult(file=fn)
        pr.classes.append(ClassNode(name=f"Cls_{path[0]}", file=path))
        pr.functions.append(FunctionNode(name=f"fn_{path[0]}", file=path))
        idx.add(pr)

    ldr = Neo4jLoader.__new__(Neo4jLoader)
    ldr.database = "neo4j"

    class FakeCtx:
        def __enter__(self):
            return MagicMock()
        def __exit__(self, *a):
            pass

    ldr.driver = MagicMock()
    ldr.driver.session.return_value = FakeCtx()

    ldr.load(idx, [], touched_files={"a.py"})

    # Find the File MERGE call — only a.py should be in the rows
    file_merges = [
        (cy, rows) for cy, rows in captured_runs
        if "MERGE (n:File {path: r.path})" in cy
    ]
    assert len(file_merges) == 1
    file_paths = {r["path"] for r in file_merges[0][1]}
    assert file_paths == {"a.py"}

    # Class MERGE — only a.py's class
    class_merges = [
        (cy, rows) for cy, rows in captured_runs
        if "MERGE (n:Class {id: r.id})" in cy
    ]
    assert len(class_merges) == 1
    class_files = {r["file"] for r in class_merges[0][1]}
    assert class_files == {"a.py"}


def test_load_touched_files_none_loads_all(captured_runs):
    """touched_files=None → all files loaded (backwards compat)."""
    idx = Index()
    for path in ("a.py", "b.py"):
        fn = FileNode(path=path, package="p", language="py", loc=10)
        idx.add(ParseResult(file=fn))

    ldr = Neo4jLoader.__new__(Neo4jLoader)
    ldr.database = "neo4j"

    class FakeCtx:
        def __enter__(self):
            return MagicMock()
        def __exit__(self, *a):
            pass

    ldr.driver = MagicMock()
    ldr.driver.session.return_value = FakeCtx()

    ldr.load(idx, [], touched_files=None)

    file_merges = [
        (cy, rows) for cy, rows in captured_runs
        if "MERGE (n:File {path: r.path})" in cy
    ]
    assert len(file_merges) == 1
    file_paths = {r["path"] for r in file_merges[0][1]}
    assert file_paths == {"a.py", "b.py"}


def test_load_touched_files_filters_edges(captured_runs):
    """Edges between untouched files are excluded; edges involving touched files pass."""
    idx = Index()
    for path in ("a.py", "b.py", "c.py"):
        fn = FileNode(path=path, package="p", language="py", loc=10)
        idx.add(ParseResult(file=fn))

    edges = [
        # a.py → b.py — a.py is touched, should be included
        Edge(kind=IMPORTS, src_id="file:a.py", dst_id="file:b.py",
             props={"specifier": "b", "type_only": False}),
        # b.py → c.py — neither is touched, should be excluded
        Edge(kind=IMPORTS, src_id="file:b.py", dst_id="file:c.py",
             props={"specifier": "c", "type_only": False}),
        # c.py → a.py — a.py is touched (dst), should be included
        Edge(kind=IMPORTS_SYMBOL, src_id="file:c.py", dst_id="file:a.py",
             props={"symbol": "X", "type_only": False}),
    ]

    ldr = Neo4jLoader.__new__(Neo4jLoader)
    ldr.database = "neo4j"

    class FakeCtx:
        def __enter__(self):
            return MagicMock()
        def __exit__(self, *a):
            pass

    ldr.driver = MagicMock()
    ldr.driver.session.return_value = FakeCtx()

    ldr.load(idx, edges, touched_files={"a.py"})

    # Find IMPORTS MERGE calls
    import_merges = [
        (cy, rows) for cy, rows in captured_runs
        if "MERGE (a)-[rel:IMPORTS]->(b)" in cy
    ]
    assert len(import_merges) == 1
    # Only the a.py → b.py edge, NOT b.py → c.py
    assert len(import_merges[0][1]) == 1
    assert import_merges[0][1][0]["src"] == "a.py"

    # IMPORTS_SYMBOL — c.py → a.py should be included
    sym_merges = [
        (cy, rows) for cy, rows in captured_runs
        if "MERGE (a)-[rel:IMPORTS_SYMBOL" in cy
    ]
    assert len(sym_merges) == 1
    assert len(sym_merges[0][1]) == 1
    assert sym_merges[0][1][0]["dst"] == "a.py"


def test_load_touched_files_always_writes_packages(captured_runs):
    """Packages are written regardless of touched_files."""
    from codegraph.schema import PackageNode

    idx = Index()
    fn = FileNode(path="a.py", package="mypkg", language="py", loc=10)
    idx.add(ParseResult(file=fn))
    idx.packages.append(PackageNode(name="mypkg", framework="Unknown", confidence=0.0))

    ldr = Neo4jLoader.__new__(Neo4jLoader)
    ldr.database = "neo4j"

    class FakeCtx:
        def __enter__(self):
            return MagicMock()
        def __exit__(self, *a):
            pass

    ldr.driver = MagicMock()
    ldr.driver.session.return_value = FakeCtx()

    ldr.load(idx, [], touched_files={"a.py"})

    # Package MERGE should have been called
    pkg_merges = [
        (cy, rows) for cy, rows in captured_runs
        if "MERGE (p:Package {name: r.name})" in cy
    ]
    assert len(pkg_merges) == 1
    assert pkg_merges[0][1][0]["name"] == "mypkg"


def test_load_touched_files_filters_per_file_extras(captured_runs):
    """Per-file extras (env_reads) from untouched files are skipped."""
    idx = Index()
    for path, envs in (("a.py", ["DB_URL"]), ("b.py", ["API_KEY"])):
        fn = FileNode(path=path, package="p", language="py", loc=10)
        pr = ParseResult(file=fn)
        pr.env_reads = envs
        idx.add(pr)

    ldr = Neo4jLoader.__new__(Neo4jLoader)
    ldr.database = "neo4j"

    class FakeCtx:
        def __enter__(self):
            return MagicMock()
        def __exit__(self, *a):
            pass

    ldr.driver = MagicMock()
    ldr.driver.session.return_value = FakeCtx()

    ldr.load(idx, [], touched_files={"a.py"})

    # Find the READS_ENV MERGE call
    env_merges = [
        (cy, rows) for cy, rows in captured_runs
        if "READS_ENV" in cy
    ]
    assert len(env_merges) == 1
    env_files = {r["file"] for r in env_merges[0][1]}
    env_names = {r["env"] for r in env_merges[0][1]}
    assert env_files == {"a.py"}
    assert env_names == {"DB_URL"}


def test_per_file_extras_atom_stats_use_len_not_db_count(captured_runs):
    """READS_ATOM / WRITES_ATOM stats must count the local batch, not DB-wide.

    Regression test for #220: in incremental mode only touched files' atoms
    are MERGEd, so stats must reflect the batch size, not a global count.
    """
    idx = Index()
    for path, reads, writes in (
        ("a.py", [("CompA", "countAtom")], [("CompA", "userAtom")]),
        ("b.py", [("CompB", "themeAtom")], []),
    ):
        fn = FileNode(path=path, package="p", language="py", loc=10)
        pr = ParseResult(file=fn)
        pr.atom_reads = reads
        pr.atom_writes = writes
        idx.add(pr)

    ldr = Neo4jLoader.__new__(Neo4jLoader)
    ldr.database = "neo4j"

    class FakeCtx:
        def __enter__(self):
            return MagicMock()
        def __exit__(self, *a):
            pass

    ldr.driver = MagicMock()
    ldr.driver.session.return_value = FakeCtx()

    stats = ldr.load(idx, [], touched_files={"a.py"})

    # Only a.py's atoms should be in the MERGE calls
    atom_read_merges = [
        (cy, rows) for cy, rows in captured_runs
        if "READS_ATOM" in cy
    ]
    assert len(atom_read_merges) == 1
    assert len(atom_read_merges[0][1]) == 1  # only CompA→countAtom

    # Stats must equal the batch length (1), not a DB-wide count
    assert stats.edges[READS_ATOM] == 1
    assert stats.edges[WRITES_ATOM] == 1


# ── Test group 4: _file_from_id ───────────────────────────────────────


@pytest.mark.parametrize("node_id,expected", [
    ("file:codegraph/cli.py", "codegraph/cli.py"),
    ("class:codegraph/cli.py#Foo", "codegraph/cli.py"),
    ("func:codegraph/cli.py#bar", "codegraph/cli.py"),
    ("method:class:codegraph/cli.py#Cls#run", "codegraph/cli.py"),
    ("atom:codegraph/cli.py#myAtom", "codegraph/cli.py"),
    ("endpoint:GET:/api@codegraph/cli.py#handler", "codegraph/cli.py"),
    ("gqlop:query:Users@codegraph/cli.py#resolve", "codegraph/cli.py"),
])
def test_file_from_id_extracts_path(node_id, expected):
    assert _file_from_id(node_id) == expected


@pytest.mark.parametrize("node_id", [
    "hook:useState",
    "external:react",
    "dec:dataclass",
    "__STATS__",
])
def test_file_from_id_unknown_prefix_returns_none(node_id):
    assert _file_from_id(node_id) is None


# ── Test group 5: column filter with malformed entity_id ─────────────


def test_load_touched_files_filters_columns(captured_runs):
    """Column filter handles valid, untouched, and malformed entity_ids without crashing."""
    idx = Index()
    fn = FileNode(path="a.py", package="p", language="py", loc=10)
    pr = ParseResult(file=fn)
    # Valid column in a touched file
    pr.columns.append(ColumnNode(entity_id="class:a.py#Foo", name="id", type="int"))
    # Valid column in an untouched file
    pr.columns.append(ColumnNode(entity_id="class:b.py#Bar", name="id", type="int"))
    # Malformed entity_id (no colon prefix) — should be excluded, not crash
    pr.columns.append(ColumnNode(entity_id="malformed_no_colon", name="bad", type="str"))
    idx.add(pr)

    ldr = Neo4jLoader.__new__(Neo4jLoader)
    ldr.database = "neo4j"

    class FakeCtx:
        def __enter__(self):
            return MagicMock()
        def __exit__(self, *a):
            pass

    ldr.driver = MagicMock()
    ldr.driver.session.return_value = FakeCtx()

    # Should not raise IndexError
    ldr.load(idx, [], touched_files={"a.py"})

    # Find the Column MERGE call — only a.py's column should appear
    col_merges = [
        (cy, rows) for cy, rows in captured_runs
        if "MERGE (c:Column {id: r.id})" in cy
    ]
    assert len(col_merges) == 1
    col_ids = {r["entity_id"] for r in col_merges[0][1]}
    assert col_ids == {"class:a.py#Foo"}
