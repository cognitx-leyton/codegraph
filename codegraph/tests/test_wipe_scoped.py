"""Tests for :meth:`codegraph.loader.Neo4jLoader.wipe_scoped`.

The 3-step delete cascade is already covered by ``test_loader_pairing.py``
via :meth:`delete_file_subgraph`. These tests focus on the new behaviour:

- Empty package list → no-op, no driver session opened.
- Selects file paths by ``f.package IN $packages``.
- Delegates path deletion to :meth:`delete_file_subgraph`.
- Drops orphaned ``:Package`` nodes for the wiped packages.

Driver / session / Cypher are all mocked so no Neo4j is required.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from codegraph import loader as loader_module


class _FakeRecord(dict):
    """dict subclass that implements both .get and __getitem__ like a Neo4j record."""

    def __getitem__(self, key):
        return super().__getitem__(key)


@pytest.fixture
def loader_with_fake_driver(monkeypatch):
    """Return a Neo4jLoader whose driver / session / run are all mocks.

    The MagicMock chain captures every Cypher call so tests can assert on it.
    """
    fake_session = MagicMock()
    fake_driver = MagicMock()
    fake_driver.session.return_value.__enter__ = lambda self: fake_session
    fake_driver.session.return_value.__exit__ = lambda *a: False

    monkeypatch.setattr(
        loader_module.GraphDatabase, "driver",
        lambda *args, **kwargs: fake_driver,
    )

    instance = loader_module.Neo4jLoader("bolt://test:7687", "neo4j", "x")
    return instance, fake_session


def test_wipe_scoped_empty_packages_is_noop(loader_with_fake_driver):
    """Calling with [] doesn't open a session or run any Cypher."""
    loader, session = loader_with_fake_driver
    assert loader.wipe_scoped([]) == 0
    session.run.assert_not_called()


def test_wipe_scoped_no_matching_files_drops_packages(loader_with_fake_driver):
    """No matching files but the package node still gets cleaned up."""
    loader, session = loader_with_fake_driver

    # First session.run() returns an empty paths list (no files matched).
    # Second session.run() drops the orphaned :Package nodes.
    session.run.return_value = iter([])

    deleted = loader.wipe_scoped(["nonexistent_pkg"])

    assert deleted == 0
    # Two run() calls: the SELECT and the Package cleanup.
    assert session.run.call_count >= 1
    # The last call should be the :Package cleanup.
    last_cypher = session.run.call_args_list[-1].args[0]
    assert "MATCH (p:Package)" in last_cypher
    assert "DETACH DELETE p" in last_cypher


def test_wipe_scoped_collects_paths_and_delegates(monkeypatch, loader_with_fake_driver):
    """The first session.run() is the path-collection query; results feed delete_file_subgraph()."""
    loader, session = loader_with_fake_driver

    paths = ["packages/server/src/a.ts", "packages/server/src/b.ts"]
    session.run.side_effect = [
        iter([_FakeRecord(path=p) for p in paths]),
        iter([]),  # Package cleanup
    ]

    delegate_calls: list[list[str]] = []
    monkeypatch.setattr(
        loader_module.Neo4jLoader, "delete_file_subgraph",
        lambda self, p: delegate_calls.append(list(p)) or len(p),
    )

    deleted = loader.wipe_scoped(["server"])
    assert deleted == 2
    assert delegate_calls == [paths]


def test_wipe_scoped_select_uses_in_clause(loader_with_fake_driver):
    """The path-collection Cypher uses `f.package IN $packages` and passes packages."""
    loader, session = loader_with_fake_driver
    session.run.return_value = iter([])
    loader.wipe_scoped(["a", "b"])

    # First call is the SELECT; verify the Cypher and parameters.
    first_call = session.run.call_args_list[0]
    cypher = first_call.args[0]
    assert "f.package IN $packages" in cypher
    assert first_call.kwargs.get("packages") == ["a", "b"]


def test_wipe_scoped_drops_packages_after_delete(monkeypatch, loader_with_fake_driver):
    """After deleting files, the :Package nodes for those names are also removed."""
    loader, session = loader_with_fake_driver

    session.run.side_effect = [
        iter([_FakeRecord(path="x.ts")]),
        iter([]),
    ]
    monkeypatch.setattr(
        loader_module.Neo4jLoader, "delete_file_subgraph",
        lambda self, p: 1,
    )

    loader.wipe_scoped(["pkg-a", "pkg-b"])

    # Last session.run() is the Package cleanup with the original package names.
    last_call = session.run.call_args_list[-1]
    assert "p.name IN $packages" in last_call.args[0]
    assert last_call.kwargs.get("packages") == ["pkg-a", "pkg-b"]
