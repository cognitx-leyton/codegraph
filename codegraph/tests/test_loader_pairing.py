"""Tests for :func:`codegraph.loader._write_test_edges`.

Builds a synthetic :class:`~codegraph.resolver.Index` with a handful of
``ParseResult`` entries and verifies the test-to-production pairing rules
(TS + Python, same-directory only for Python MVP). Monkeypatches
``loader._run`` so no Neo4j is needed.
"""
from __future__ import annotations

import pytest

from codegraph import loader
from codegraph.resolver import Index
from codegraph.schema import FileNode, ParseResult


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


@pytest.fixture
def captured_runs(monkeypatch):
    calls: list[tuple[str, list]] = []

    def fake_run(session, cypher, rows):
        calls.append((cypher, list(rows)))

    monkeypatch.setattr(loader, "_run", fake_run)
    return calls


def _tests_rows(captured_runs):
    """Extract the rows passed to the TESTS (file→file) MERGE."""
    for cypher, rows in captured_runs:
        if "MERGE (t)-[:TESTS]->(p)" in cypher:
            return rows
    return []


def test_python_test_prefix_pairs(captured_runs):
    """``pkg/test_foo.py`` pairs to ``pkg/foo.py`` (same directory)."""
    idx = _fake_index({
        "pkg/test_foo.py": True,
        "pkg/foo.py": False,
    })
    loader._write_test_edges(session=None, index=idx, stats=_Stats())
    rows = _tests_rows(captured_runs)
    assert rows == [{"test": "pkg/test_foo.py", "peer": "pkg/foo.py"}]


def test_python_test_trailing_pairs(captured_runs):
    """``pkg/foo_test.py`` pairs to ``pkg/foo.py``."""
    idx = _fake_index({
        "pkg/foo_test.py": True,
        "pkg/foo.py": False,
    })
    loader._write_test_edges(session=None, index=idx, stats=_Stats())
    rows = _tests_rows(captured_runs)
    assert rows == [{"test": "pkg/foo_test.py", "peer": "pkg/foo.py"}]


def test_conftest_does_not_pair(captured_runs):
    """``conftest.py`` is a pytest fixture collector — no production peer."""
    idx = _fake_index({
        "pkg/conftest.py": True,
        "pkg/context.py": False,    # ``conf``-prefixed near-match, must not pair
    })
    loader._write_test_edges(session=None, index=idx, stats=_Stats())
    assert _tests_rows(captured_runs) == []


def test_test_without_peer_does_not_pair(captured_runs):
    """``test_orphan.py`` with no sibling ``orphan.py`` → no edge."""
    idx = _fake_index({
        "pkg/test_orphan.py": True,
    })
    loader._write_test_edges(session=None, index=idx, stats=_Stats())
    assert _tests_rows(captured_runs) == []


def test_cross_directory_python_does_not_pair(captured_runs):
    """Same-directory rule: ``tests/test_foo.py`` does NOT pair to ``pkg/foo.py``."""
    idx = _fake_index({
        "tests/test_foo.py": True,
        "pkg/foo.py": False,
    })
    loader._write_test_edges(session=None, index=idx, stats=_Stats())
    assert _tests_rows(captured_runs) == []


def test_ts_pairing_still_works(captured_runs):
    """TS pairing must not regress: ``foo.spec.ts`` → ``foo.ts``."""
    idx = _fake_index({
        "pkg/foo.spec.ts": True,
        "pkg/foo.ts": False,
    })
    loader._write_test_edges(session=None, index=idx, stats=_Stats())
    rows = _tests_rows(captured_runs)
    assert rows == [{"test": "pkg/foo.spec.ts", "peer": "pkg/foo.ts"}]
