"""Tests for EdgeGroup (hyperedge) support.

Covers: schema dataclass, protocol-implementer group emission in resolver,
loader persistence, and the MCP ``describe_group`` tool.
"""
from __future__ import annotations

from typing import Any

import codegraph.mcp as mcp_mod
from codegraph.loader import LoadStats, MEMBER_OF, _write_edge_groups
from codegraph.schema import (
    IMPLEMENTS,
    Edge,
    EdgeGroupNode,
    MEMBER_OF as MEMBER_OF_CONST,
)


# ── Schema tests ──────────────────────────────────────────────────────


def test_edge_group_node_id():
    eg = EdgeGroupNode("Foo implementers", "protocol_implementers", 3)
    assert eg.id == "edgegroup:protocol_implementers:Foo implementers"


def test_edge_group_node_defaults():
    eg = EdgeGroupNode("test", "community")
    assert eg.node_count == 0
    assert eg.confidence == 1.0


def test_member_of_constant():
    assert MEMBER_OF_CONST == "MEMBER_OF"


# ── Resolver protocol-grouping tests ─────────────────────────────────


def _make_implements_edges(iface_id: str, impl_ids: list[str]) -> list[Edge]:
    """Build IMPLEMENTS edges from a list of implementer IDs to one interface."""
    return [Edge(kind=IMPLEMENTS, src_id=sid, dst_id=iface_id) for sid in impl_ids]


def _run_protocol_grouping(edges: list[Edge]):
    """Replicate the protocol-grouping logic from link_cross_file.

    We test the algorithm in isolation rather than building a full Index,
    since that logic is a self-contained post-pass over the edge list.
    """
    from codegraph.schema import MEMBER_OF as MO

    iface_to_implementers: dict[str, list[str]] = {}
    for e in edges:
        if e.kind == IMPLEMENTS:
            iface_to_implementers.setdefault(e.dst_id, []).append(e.src_id)

    edge_groups: list[EdgeGroupNode] = []
    for iface_id, implementers in iface_to_implementers.items():
        if len(implementers) < 2:
            continue
        eg = EdgeGroupNode(
            name=f"{iface_id} implementers",
            kind="protocol_implementers",
            node_count=len(implementers),
        )
        edge_groups.append(eg)
        for impl_id in implementers:
            edges.append(Edge(kind=MO, src_id=impl_id, dst_id=eg.id))

    return edges, edge_groups


def test_protocol_group_three_implementers():
    """3 classes implementing the same interface → 1 group + 3 MEMBER_OF edges."""
    iface = "class:pkg/base.py#IHandler"
    impls = [
        "class:pkg/a.py#HandlerA",
        "class:pkg/b.py#HandlerB",
        "class:pkg/c.py#HandlerC",
    ]
    edges = _make_implements_edges(iface, impls)
    edges, groups = _run_protocol_grouping(edges)

    assert len(groups) == 1
    eg = groups[0]
    assert eg.kind == "protocol_implementers"
    assert eg.name == "class:pkg/base.py#IHandler implementers"
    assert eg.node_count == 3

    member_of = [e for e in edges if e.kind == MEMBER_OF_CONST]
    assert len(member_of) == 3
    assert all(e.dst_id == eg.id for e in member_of)
    assert {e.src_id for e in member_of} == set(impls)


def test_no_group_for_single_implementer():
    """An interface with only 1 implementer should not produce a group."""
    edges = _make_implements_edges("class:pkg/base.py#IFoo", ["class:pkg/a.py#FooImpl"])
    edges, groups = _run_protocol_grouping(edges)
    assert len(groups) == 0
    assert not any(e.kind == MEMBER_OF_CONST for e in edges)


def test_multiple_interfaces_multiple_groups():
    """Two interfaces with 2+ implementers each → 2 groups."""
    edges = (
        _make_implements_edges("class:pkg/base.py#IA", [
            "class:pkg/a1.py#A1", "class:pkg/a2.py#A2",
        ])
        + _make_implements_edges("class:pkg/base.py#IB", [
            "class:pkg/b1.py#B1", "class:pkg/b2.py#B2", "class:pkg/b3.py#B3",
        ])
    )
    edges, groups = _run_protocol_grouping(edges)
    assert len(groups) == 2
    names = {g.name for g in groups}
    assert "class:pkg/base.py#IA implementers" in names
    assert "class:pkg/base.py#IB implementers" in names


# ── Loader tests ─────────────────────────────────────────────────────


def test_write_edge_groups_cypher_patterns():
    """Mock session verifies the correct Cypher patterns are executed."""
    calls: list[str] = []

    class FakeSession:
        def run(self, cypher: str, **params):
            calls.append(cypher)

    eg = EdgeGroupNode("IHandler implementers", "protocol_implementers", 2)
    edges = [
        Edge(kind=MEMBER_OF_CONST, src_id="class:a.py#A", dst_id=eg.id),
        Edge(kind=MEMBER_OF_CONST, src_id="class:b.py#B", dst_id=eg.id),
    ]
    stats = LoadStats()
    _write_edge_groups(FakeSession(), [eg], edges, stats)

    all_cypher = " ".join(calls)
    assert "DETACH DELETE" in all_cypher
    assert "protocol_implementers" in all_cypher
    assert "MERGE (eg:EdgeGroup" in all_cypher
    assert "MERGE (n)-[:MEMBER_OF]" in all_cypher
    assert stats.edge_groups == 1
    assert stats.member_of_edges == 2


def test_loader_cleans_stale_groups():
    """The first Cypher statement should DETACH DELETE protocol_implementers groups."""
    calls: list[str] = []

    class FakeSession:
        def run(self, cypher: str, **params):
            calls.append(cypher)

    _write_edge_groups(FakeSession(), [], [], LoadStats())
    # The very first call should be the cleanup
    assert len(calls) >= 1
    assert "DETACH DELETE" in calls[0]
    assert "protocol_implementers" in calls[0]


# ── MCP tool tests ───────────────────────────────────────────────────


class _FakeRecord:
    def __init__(self, data: dict) -> None:
        self._data = data

    def items(self):
        return self._data.items()

    def __getitem__(self, key):
        return self._data[key]

    def __iter__(self):
        return iter(self._data)


class _FakeSession:
    def __init__(self, responses: list[list[dict]] | Exception) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc: Any) -> None:
        pass

    def run(self, cypher: str, **params: Any):
        self.calls.append((cypher, params))
        if isinstance(self._responses, Exception):
            raise self._responses
        if not self._responses:
            return iter([])
        rows = self._responses.pop(0)
        return iter([_FakeRecord(r) for r in rows])


class _FakeDriver:
    def __init__(self, responses: list[list[dict]] | Exception) -> None:
        self.session_obj = _FakeSession(responses)

    def session(self, **kwargs: Any):
        return self.session_obj

    def close(self) -> None:
        pass


def _patch(monkeypatch, responses):
    driver = _FakeDriver(responses)
    monkeypatch.setattr(mcp_mod, "_driver", driver)
    return driver


def test_describe_group_empty_name():
    result = mcp_mod.describe_group("")
    assert result == [{"error": "name_or_id must be non-empty"}]


def test_describe_group_bad_limit():
    result = mcp_mod.describe_group("foo", limit=0)
    assert len(result) == 1
    assert "error" in result[0]
    assert "limit" in result[0]["error"]


def test_describe_group_happy_path(monkeypatch):
    rows = [
        {
            "group_id": "edgegroup:protocol_implementers:IHandler implementers",
            "group_name": "IHandler implementers",
            "group_kind": "protocol_implementers",
            "group_size": 2,
            "confidence": 1.0,
            "cohesion": None,
            "member_kind": "Class",
            "member_name": "HandlerA",
            "member_file": "pkg/a.py",
        },
    ]
    driver = _patch(monkeypatch, [rows])
    result = mcp_mod.describe_group("IHandler")

    assert len(result) == 1
    assert result[0]["group_name"] == "IHandler implementers"
    assert result[0]["member_name"] == "HandlerA"
    # Verify query used correct parameter
    cypher, params = driver.session_obj.calls[0]
    assert params["q"] == "IHandler"


def test_describe_group_with_kind_filter(monkeypatch):
    driver = _patch(monkeypatch, [[]])
    mcp_mod.describe_group("test", kind="community")
    cypher, params = driver.session_obj.calls[0]
    assert "eg.kind = $kind" in cypher
    assert params["kind"] == "community"
