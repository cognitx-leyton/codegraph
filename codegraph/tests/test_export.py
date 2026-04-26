"""Tests for :mod:`codegraph.export` — HTML, JSON, GraphML, Cypher exports."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from codegraph.export import (
    LABEL_COLORS,
    MAX_NODES_FOR_VIZ,
    _cypher_escape,
    _sanitize_label,
    to_cypher,
    to_graphml,
    to_html,
    to_json,
)


# ── fixtures ──────────────────────────────────────────────────────

_FIXTURE_NODES: list[dict] = [
    {
        "id": "n1",
        "labels": ["Class"],
        "properties": {"name": "UserService", "file": "src/app.ts"},
    },
    {
        "id": "n2",
        "labels": ["Function"],
        "properties": {"name": "getUser", "file": "src/app.ts"},
    },
    {
        "id": "n3",
        "labels": ["File"],
        "properties": {"path": "src/app.ts"},
    },
    {
        "id": "n4",
        "labels": ["Endpoint"],
        "properties": {"name": "/users", "file": "src/app.ts"},
    },
]

_FIXTURE_EDGES: list[dict] = [
    {"src": "n3", "dst": "n1", "type": "DEFINES_CLASS", "properties": {}},
    {"src": "n3", "dst": "n2", "type": "DEFINES_FUNCTION", "properties": {}},
    {"src": "n1", "dst": "n2", "type": "CALLS", "properties": {}},
]


# ── HTML tests ────────────────────────────────────────────────────


def test_to_html_contains_vis_js(tmp_path: Path) -> None:
    out = tmp_path / "graph.html"
    to_html(_FIXTURE_NODES, _FIXTURE_EDGES, out)
    content = out.read_text()
    assert "vis.Network" in content


def test_to_html_contains_node_labels(tmp_path: Path) -> None:
    out = tmp_path / "graph.html"
    to_html(_FIXTURE_NODES, _FIXTURE_EDGES, out)
    content = out.read_text()
    assert "UserService" in content
    assert "getUser" in content
    assert "src/app.ts" in content


def test_to_html_self_contained(tmp_path: Path) -> None:
    """No external <script src=...> tags — everything is inline."""
    out = tmp_path / "graph.html"
    to_html(_FIXTURE_NODES, _FIXTURE_EDGES, out)
    content = out.read_text()
    assert '<script src=' not in content


def test_to_html_xss_safety(tmp_path: Path) -> None:
    nodes = [
        {
            "id": "xss1",
            "labels": ["Class"],
            "properties": {"name": "<script>alert(1)</script>", "file": "x.ts"},
        },
    ]
    out = tmp_path / "graph.html"
    to_html(nodes, [], out)
    content = out.read_text()
    # Raw <script>alert should NOT appear — must be escaped
    assert "<script>alert" not in content
    # The name should appear somewhere (escaped in JSON as \u003c or in HTML as &lt;)
    assert "alert(1)" in content


def test_to_html_max_nodes_guard(tmp_path: Path) -> None:
    nodes = [{"id": f"n{i}", "labels": ["Class"], "properties": {}} for i in range(MAX_NODES_FOR_VIZ + 1)]
    out = tmp_path / "graph.html"
    with pytest.raises(ValueError, match="too large"):
        to_html(nodes, [], out)


def test_to_html_empty_graph(tmp_path: Path) -> None:
    out = tmp_path / "graph.html"
    to_html([], [], out)
    content = out.read_text()
    assert "<!DOCTYPE html>" in content
    assert "0 nodes" in content


def test_to_html_has_sidebar_elements(tmp_path: Path) -> None:
    out = tmp_path / "graph.html"
    to_html(_FIXTURE_NODES, _FIXTURE_EDGES, out)
    content = out.read_text()
    assert 'id="search"' in content
    assert 'id="info-panel"' in content
    assert 'id="legend"' in content
    assert 'id="stats"' in content


# ── JSON tests ────────────────────────────────────────────────────


def test_to_json_roundtrip(tmp_path: Path) -> None:
    out = tmp_path / "graph.json"
    to_json(_FIXTURE_NODES, _FIXTURE_EDGES, out)
    doc = json.loads(out.read_text())
    assert len(doc["nodes"]) == len(_FIXTURE_NODES)
    assert len(doc["edges"]) == len(_FIXTURE_EDGES)


def test_to_json_has_meta(tmp_path: Path) -> None:
    out = tmp_path / "graph.json"
    to_json(_FIXTURE_NODES, _FIXTURE_EDGES, out)
    doc = json.loads(out.read_text())
    meta = doc["meta"]
    assert meta["node_count"] == len(_FIXTURE_NODES)
    assert meta["edge_count"] == len(_FIXTURE_EDGES)
    assert "exported_at" in meta
    # Verify ISO 8601 format
    from datetime import datetime
    datetime.fromisoformat(meta["exported_at"])


# ── GraphML tests ─────────────────────────────────────────────────


def test_to_graphml_valid_xml(tmp_path: Path) -> None:
    out = tmp_path / "graph.graphml"
    to_graphml(_FIXTURE_NODES, _FIXTURE_EDGES, out)
    # Should parse without error
    ET.parse(out)


def test_to_graphml_node_count(tmp_path: Path) -> None:
    out = tmp_path / "graph.graphml"
    to_graphml(_FIXTURE_NODES, _FIXTURE_EDGES, out)
    tree = ET.parse(out)
    ns = {"g": "http://graphml.graphstruct.org/xmlns"}
    node_elements = tree.findall(".//g:node", ns)
    assert len(node_elements) == len(_FIXTURE_NODES)


def test_to_graphml_edge_count(tmp_path: Path) -> None:
    out = tmp_path / "graph.graphml"
    to_graphml(_FIXTURE_NODES, _FIXTURE_EDGES, out)
    tree = ET.parse(out)
    ns = {"g": "http://graphml.graphstruct.org/xmlns"}
    edge_elements = tree.findall(".//g:edge", ns)
    assert len(edge_elements) == len(_FIXTURE_EDGES)


# ── Cypher tests ──────────────────────────────────────────────────


def test_to_cypher_merge_statements(tmp_path: Path) -> None:
    out = tmp_path / "graph.cypher"
    to_cypher(_FIXTURE_NODES, _FIXTURE_EDGES, out)
    content = out.read_text()
    assert "MERGE (n:Class" in content
    assert "MERGE (n:Function" in content
    assert "MERGE (n:File" in content
    assert "MERGE (n:Endpoint" in content


def test_to_cypher_edge_statements(tmp_path: Path) -> None:
    out = tmp_path / "graph.cypher"
    to_cypher(_FIXTURE_NODES, _FIXTURE_EDGES, out)
    content = out.read_text()
    assert "MERGE (a)-[:DEFINES_CLASS]->(b)" in content
    assert "MERGE (a)-[:CALLS]->(b)" in content


def test_to_cypher_escapes_quotes(tmp_path: Path) -> None:
    nodes = [
        {
            "id": "q1",
            "labels": ["Class"],
            "properties": {"name": "it's", "file": "x.ts"},
        },
    ]
    out = tmp_path / "graph.cypher"
    to_cypher(nodes, [], out)
    content = out.read_text()
    assert "it\\'s" in content


# ── Utility tests ─────────────────────────────────────────────────


def test_label_colors_complete() -> None:
    """Every label used in fixtures gets a real color, not fallback."""
    for node in _FIXTURE_NODES:
        for lbl in node["labels"]:
            assert lbl in LABEL_COLORS, f"Missing color for label {lbl!r}"


def test_cypher_escape() -> None:
    assert _cypher_escape("it's") == "it\\'s"
    assert _cypher_escape("a\\b") == "a\\\\b"


def test_to_graphml_quotes_in_id(tmp_path: Path) -> None:
    """Node IDs containing quotes must not break XML attribute values."""
    nodes = [{"id": 'n"1', "labels": ["Class"], "properties": {"name": "Foo"}}]
    out = tmp_path / "graph.graphml"
    to_graphml(nodes, [], out)
    tree = ET.parse(out)  # Would fail if quote breaks XML
    ns = {"g": "http://graphml.graphstruct.org/xmlns"}
    assert len(tree.findall(".//g:node", ns)) == 1


def test_sanitize_label() -> None:
    assert _sanitize_label("Class") == "Class"
    assert _sanitize_label("My-Label!") == "MyLabel"
    assert _sanitize_label("!!!") == "Node"
