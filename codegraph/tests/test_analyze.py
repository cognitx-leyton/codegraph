"""Tests for codegraph.analyze + codegraph.report.

All tests use pure NetworkX fixtures — no live Neo4j required.
"""
from __future__ import annotations

from typing import Any

import pytest

nx = pytest.importorskip("networkx")

from codegraph.analyze import (  # noqa: E402
    _label_community,
    cluster,
    cohesion_score,
    god_nodes,
    persist_communities,
    read_graph,
    surprising_connections,
    suggest_questions,
)
from codegraph.report import generate_report, write_report  # noqa: E402


# ── Fixtures ─────────────────────────────────────────────────────────


def _make_two_cluster_graph() -> nx.DiGraph:
    """Two clear 4-node clusters connected by 1 bridge edge."""
    G = nx.DiGraph()
    # Cluster A
    for i in range(4):
        G.add_node(f"a{i}", labels=["Class"], name=f"ClassA{i}",
                   file=f"src/a{i}.py", package="pkg_a", id=f"class:a{i}")
    for i in range(4):
        for j in range(i + 1, 4):
            G.add_edge(f"a{i}", f"a{j}", type="CALLS")
            G.add_edge(f"a{j}", f"a{i}", type="CALLS")

    # Cluster B
    for i in range(4):
        G.add_node(f"b{i}", labels=["Class"], name=f"ClassB{i}",
                   file=f"src/b{i}.py", package="pkg_b", id=f"class:b{i}")
    for i in range(4):
        for j in range(i + 1, 4):
            G.add_edge(f"b{i}", f"b{j}", type="CALLS")
            G.add_edge(f"b{j}", f"b{i}", type="CALLS")

    # Bridge
    G.add_edge("a0", "b0", type="CALLS")
    return G


def _make_star_graph() -> nx.DiGraph:
    """1 hub Class node + 5 leaf Method nodes."""
    G = nx.DiGraph()
    G.add_node("hub", labels=["Class"], name="HubClass",
               file="src/hub.py", package="core", id="class:hub")
    for i in range(5):
        G.add_node(f"leaf{i}", labels=["Method"], name=f"method{i}",
                   file="src/hub.py", package="core", id=f"method:leaf{i}")
        G.add_edge("hub", f"leaf{i}", type="HAS_METHOD")
        G.add_edge(f"leaf{i}", "hub", type="CALLS")
    return G


def _make_empty_graph() -> nx.DiGraph:
    return nx.DiGraph()


# ── cluster tests ────────────────────────────────────────────────────


def test_cluster_finds_communities():
    G = _make_two_cluster_graph()
    comms = cluster(G)
    assert len(comms) >= 2, f"Expected >=2 communities, got {len(comms)}"


def test_cluster_empty_graph():
    G = _make_empty_graph()
    comms = cluster(G)
    assert comms == {}


def test_cluster_single_node():
    G = nx.DiGraph()
    G.add_node("only", labels=["Class"], name="Only", file="a.py",
               package="p", id="class:only")
    comms = cluster(G)
    assert len(comms) == 1
    assert len(list(comms.values())[0]) == 1


# ── cohesion tests ───────────────────────────────────────────────────


def test_cohesion_complete_graph():
    G = nx.DiGraph()
    nodes = ["x", "y", "z"]
    for n in nodes:
        G.add_node(n)
    for a in nodes:
        for b in nodes:
            if a != b:
                G.add_edge(a, b)
    assert cohesion_score(G, nodes) == pytest.approx(1.0)


def test_cohesion_single_node():
    G = nx.DiGraph()
    G.add_node("x")
    assert cohesion_score(G, ["x"]) == 1.0


# ── god_nodes tests ──────────────────────────────────────────────────


def test_god_nodes_returns_top_k():
    G = _make_star_graph()
    gods = god_nodes(G, top_n=3)
    assert len(gods) >= 1
    assert gods[0]["name"] == "HubClass"


def test_god_nodes_filters_hub_labels():
    G = nx.DiGraph()
    # High-degree File node — should be excluded
    G.add_node("file1", labels=["File"], name="big_file.py",
               file="big_file.py", package="p", id="file:big")
    for i in range(20):
        G.add_node(f"c{i}", labels=["Class"], name=f"C{i}",
                   file="c.py", package="p", id=f"class:c{i}")
        G.add_edge("file1", f"c{i}", type="DEFINES")

    # Lower-degree Class node
    G.add_node("real", labels=["Class"], name="RealClass",
               file="r.py", package="p", id="class:real")
    G.add_edge("real", "c0", type="CALLS")
    G.add_edge("real", "c1", type="CALLS")

    gods = god_nodes(G, top_n=5)
    god_names = [g["name"] for g in gods]
    assert "big_file.py" not in god_names
    assert "RealClass" in god_names


# ── surprising_connections tests ─────────────────────────────────────


def test_surprising_connections_cross_community():
    G = _make_two_cluster_graph()
    comms = {0: [f"a{i}" for i in range(4)], 1: [f"b{i}" for i in range(4)]}
    surprises = surprising_connections(G, comms, top_n=5)
    assert len(surprises) >= 1
    edge_types = [s["edge_type"] for s in surprises]
    assert "CALLS" in edge_types


def test_surprising_connections_empty():
    G = _make_empty_graph()
    surprises = surprising_connections(G, {}, top_n=5)
    assert surprises == []


# ── suggest_questions tests ──────────────────────────────────────────


def test_suggest_questions_high_fan_in():
    G = nx.DiGraph()
    G.add_node("target", labels=["Class"], name="GodService",
               file="svc.py", package="core", id="class:god")
    for i in range(15):
        G.add_node(f"dep{i}", labels=["Class"], name=f"Dep{i}",
                   file=f"d{i}.py", package="core", id=f"class:dep{i}")
        G.add_edge(f"dep{i}", "target", type="INJECTS")

    comms = {0: ["target"] + [f"dep{i}" for i in range(15)]}
    questions = suggest_questions(G, comms, top_n=5)
    q_texts = [q["question"] for q in questions]
    assert any("GodService" in q for q in q_texts)


def test_suggest_questions_empty_graph():
    G = _make_empty_graph()
    questions = suggest_questions(G, {}, top_n=5)
    assert len(questions) >= 1
    assert questions[0]["type"] == "info"


# ── report tests ─────────────────────────────────────────────────────


def _minimal_analysis() -> dict:
    return {
        "node_count": 10,
        "edge_count": 15,
        "community_count": 2,
        "god_nodes": [{"name": "Foo", "degree": 8, "file": "foo.py",
                       "labels": ["Class"], "id": "class:foo"}],
        "surprising_connections": [{"source_name": "A", "target_name": "B",
                                    "edge_type": "CALLS", "why": "cross-package",
                                    "source_file": "a.py", "target_file": "b.py"}],
        "communities": [{"id": 0, "label": "core: Foo", "node_count": 5,
                         "cohesion": 0.6, "members": ["Foo", "Bar", "Baz"]}],
        "suggested_questions": [{"type": "god-node",
                                 "question": "Is Foo doing too much?",
                                 "why": "8 deps"}],
    }


def test_generate_report_contains_sections():
    report = generate_report(_minimal_analysis())
    assert "## God Nodes" in report
    assert "## Surprising Connections" in report
    assert "## Communities" in report
    assert "## Suggested Questions" in report


def test_generate_report_empty_analysis():
    empty = {
        "node_count": 0, "edge_count": 0, "community_count": 0,
        "god_nodes": [], "surprising_connections": [],
        "communities": [], "suggested_questions": [],
    }
    report = generate_report(empty)
    assert "# Graph Report" in report
    assert "**0** nodes" in report


def test_write_report_creates_file(tmp_path):
    out = tmp_path / "sub" / "GRAPH_REPORT.md"
    write_report("# test", out)
    assert out.exists()
    assert out.read_text() == "# test"


# ── persist_communities tests ────────────────────────────────────────


def test_persist_communities_calls_neo4j():
    """Mock driver verifies the correct Cypher patterns are executed."""
    calls: list[str] = []

    class FakeSession:
        def run(self, cypher: str, **params):
            calls.append(cypher)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class FakeDriver:
        def session(self):
            return FakeSession()

    G = nx.DiGraph()
    G.add_node("n1", labels=["Class"], name="Foo", file="f.py",
               package="pkg", id="class:foo")
    comms = {0: ["n1"]}
    coh = {0: 1.0}
    result = persist_communities(FakeDriver(), G, comms, coh)
    assert result["communities"] == 1
    assert result["nodes_labeled"] == 1

    all_cypher = " ".join(calls)
    assert "UNWIND" in all_cypher
    assert "SET n.community_id" in all_cypher
    assert "MERGE (eg:EdgeGroup" in all_cypher
    assert "MERGE (n)-[rel:MEMBER_OF]" in all_cypher


# ── _label_community tests ──────────────────────────────────────────


def test_label_community():
    G = nx.DiGraph()
    G.add_node("n1", labels=["Class"], name="Loader", file="l.py",
               package="codegraph", id="class:loader")
    G.add_node("n2", labels=["Class"], name="Parser", file="p.py",
               package="codegraph", id="class:parser")
    G.add_edge("n1", "n2", type="CALLS")
    label = _label_community(G, ["n1", "n2"])
    assert "codegraph" in label


# ── read_graph tests ─────────────────────────────────────────────────


class _FakeNode:
    """Stand-in for a Neo4j node record with .items() support."""
    def __init__(self, props: dict):
        self._props = props

    def items(self):
        return self._props.items()


class _FakeResult:
    def __init__(self, rows: list[dict]):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    def __init__(self, resolver):
        self._resolver = resolver

    def run(self, cypher: str, **params):
        return _FakeResult(self._resolver(cypher, **params))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeDriver:
    def __init__(self, resolver):
        self._resolver = resolver

    def session(self):
        return _FakeSession(self._resolver)


def test_read_graph_scoped():
    """read_graph with scope passes $scopes and maps node attributes."""
    def resolver(cypher: str, **params):
        if "labels(n)" in cypher:
            return [
                {"n": _FakeNode({"name": "Foo", "file": "src/foo.py",
                                 "package": "pkg", "id": "class:foo"}),
                 "lbls": ["Class"], "eid": "e1"},
                {"n": _FakeNode({"name": "Bar", "file": "src/bar.py",
                                 "package": "pkg", "id": "class:bar"}),
                 "lbls": ["Class"], "eid": "e2"},
            ]
        if "type(r)" in cypher:
            return [{"aeid": "e1", "rel": "CALLS", "beid": "e2"}]
        return []

    driver = _FakeDriver(resolver)
    G = read_graph(driver, scope=["src/"])
    assert G.number_of_nodes() == 2
    assert G.number_of_edges() == 1
    assert G.nodes["e1"]["name"] == "Foo"
    assert G.nodes["e1"]["labels"] == ["Class"]
    assert G.edges["e1", "e2"]["type"] == "CALLS"


def test_read_graph_unscoped():
    """read_graph without scope still builds the graph correctly."""
    def resolver(cypher: str, **params):
        if "labels(n)" in cypher:
            return [
                {"n": _FakeNode({"name": "Only", "path": "a.py", "id": "f:a"}),
                 "lbls": ["File"], "eid": "e1"},
            ]
        return []

    driver = _FakeDriver(resolver)
    G = read_graph(driver)
    assert G.number_of_nodes() == 1
    assert G.nodes["e1"]["name"] == "Only"
