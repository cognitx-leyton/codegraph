"""Graph export: interactive HTML (vis.js), JSON, GraphML, and Cypher.

Each ``to_*`` function takes pre-fetched node/edge dicts so it works
without a live Neo4j connection (and is therefore testable with plain
fixtures).  The ``*_from_driver`` wrappers handle the Neo4j query.
"""
from __future__ import annotations

import datetime
import html
import json
import re
from importlib.resources import files as _pkg_files
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape, quoteattr as xml_quoteattr


# ── constants ──────────────────────────────────────────────────────

MAX_NODES_FOR_VIZ = 5_000

LABEL_COLORS: dict[str, dict[str, str]] = {
    "File":      {"background": "#BAB0AC", "border": "#9E9691"},
    "Class":     {"background": "#E15759", "border": "#C43E40"},
    "Function":  {"background": "#4E79A7", "border": "#3A6291"},
    "Method":    {"background": "#76B7B2", "border": "#5DA09B"},
    "Interface": {"background": "#EDC948", "border": "#D4B230"},
    "Endpoint":  {"background": "#F28E2B", "border": "#D97812"},
    "Component": {"background": "#59A14F", "border": "#438739"},
    "Hook":      {"background": "#9C755F", "border": "#7F5D49"},
    "External":  {"background": "#888888", "border": "#6E6E6E"},
    "Package":   {"background": "#B07AA1", "border": "#96618A"},
    "TestFile":  {"background": "#FF9DA7", "border": "#E6838D"},
    "Decorator": {"background": "#C4A35A", "border": "#AB8A42"},
    "EnvVar":    {"background": "#7B8794", "border": "#636F7B"},
    "Event":     {"background": "#FF6B6B", "border": "#E65252"},
}
_DEFAULT_COLOR: dict[str, str] = {"background": "#AAAAAA", "border": "#888888"}


# ── Neo4j dump ────────────────────────────────────────────────────


def dump_graph(
    driver: Any,
    *,
    scope: list[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Query all nodes and edges from Neo4j, optionally filtered by scope.

    Returns ``(nodes, edges)`` where each node is::

        {"id": eid, "labels": [...], "properties": {...}}

    and each edge is::

        {"src": src_eid, "dst": dst_eid, "type": rel, "properties": {...}}
    """
    if scope:
        node_cypher = (
            "MATCH (n) "
            "WITH n, labels(n) AS lbls, elementId(n) AS eid, "
            "coalesce(n.file, n.path) AS loc "
            "WHERE loc IS NOT NULL "
            "AND any(s IN $scopes WHERE loc STARTS WITH s) "
            "RETURN n, lbls, eid"
        )
        edge_cypher = (
            "MATCH (a)-[r]->(b) "
            "WITH a, r, b, "
            "coalesce(a.file, a.path) AS aloc, "
            "coalesce(b.file, b.path) AS bloc "
            "WHERE (aloc IS NOT NULL AND any(s IN $scopes WHERE aloc STARTS WITH s)) "
            "AND (bloc IS NOT NULL AND any(s IN $scopes WHERE bloc STARTS WITH s)) "
            "RETURN elementId(a) AS src_eid, type(r) AS rel, "
            "properties(r) AS props, elementId(b) AS dst_eid"
        )
        params: dict[str, Any] = {"scopes": scope}
    else:
        node_cypher = (
            "MATCH (n) "
            "RETURN n, labels(n) AS lbls, elementId(n) AS eid"
        )
        edge_cypher = (
            "MATCH (a)-[r]->(b) "
            "RETURN elementId(a) AS src_eid, type(r) AS rel, "
            "properties(r) AS props, elementId(b) AS dst_eid"
        )
        params = {}

    with driver.session() as s:
        raw_nodes = list(s.run(node_cypher, **params))
        raw_edges = list(s.run(edge_cypher, **params))

    nodes: list[dict] = []
    for row in raw_nodes:
        n = row["n"]
        props = dict(n.items()) if hasattr(n, "items") else {}
        nodes.append({
            "id": row["eid"],
            "labels": list(row["lbls"]),
            "properties": props,
        })

    edges: list[dict] = []
    for row in raw_edges:
        props = dict(row["props"]) if row["props"] else {}
        edges.append({
            "src": row["src_eid"],
            "dst": row["dst_eid"],
            "type": row["rel"],
            "properties": props,
        })

    return nodes, edges


# ── HTML export ───────────────────────────────────────────────────


def _js_safe(obj: Any) -> str:
    """JSON-encode *obj* and escape for safe HTML ``<script>`` embedding.

    Replaces ``<`` with ``\\u003c`` so that no HTML tag (including
    ``<script>`` or ``</script>``) can appear literally inside the
    JSON blob.
    """
    return json.dumps(obj).replace("<", "\\u003c")


def _html_styles() -> str:
    return """\
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: #1a1a2e; color: #e0e0e0; display: flex; height: 100vh; overflow: hidden; }
#sidebar { width: 320px; min-width: 320px; background: #16213e; display: flex; flex-direction: column; border-right: 1px solid #0f3460; overflow-y: auto; }
#sidebar h2 { padding: 16px; font-size: 18px; border-bottom: 1px solid #0f3460; }
#search-box { padding: 8px 16px; }
#search { width: 100%; padding: 8px 12px; border: 1px solid #0f3460; border-radius: 4px; background: #1a1a2e; color: #e0e0e0; font-size: 14px; }
#stats { padding: 8px 16px; font-size: 13px; color: #a0a0c0; border-bottom: 1px solid #0f3460; }
#legend { padding: 8px 16px; border-bottom: 1px solid #0f3460; }
#legend h3 { font-size: 14px; margin-bottom: 8px; }
.legend-item { display: flex; align-items: center; margin-bottom: 4px; cursor: pointer; font-size: 13px; }
.legend-color { width: 14px; height: 14px; border-radius: 3px; margin-right: 8px; flex-shrink: 0; }
.legend-item.hidden { opacity: 0.35; text-decoration: line-through; }
#communities { padding: 8px 16px; border-bottom: 1px solid #0f3460; }
#communities:empty { display: none; }
#communities h3 { font-size: 14px; margin-bottom: 8px; }
.community-item { display: flex; align-items: center; margin-bottom: 4px; cursor: pointer; font-size: 13px; }
.community-item input { margin-right: 6px; }
.community-color { width: 14px; height: 14px; border-radius: 3px; margin-right: 8px; flex-shrink: 0; }
.community-item.hidden { opacity: 0.35; text-decoration: line-through; }
#info-panel { padding: 16px; flex: 1; overflow-y: auto; font-size: 13px; }
#info-panel h3 { margin-bottom: 8px; }
.prop-row { margin-bottom: 4px; }
.prop-key { color: #a0a0c0; }
.prop-val { color: #e0e0e0; word-break: break-all; }
#graph { flex: 1; }
"""


def _html_script(
    nodes_json: str,
    edges_json: str,
    legend_json: str,
    community_json: str,
) -> str:
    return (
        "var nodesArray = " + nodes_json + ";\n"
        "var edgesArray = " + edges_json + ";\n"
        "var legendData = " + legend_json + ";\n"
        "var communityData = " + community_json + ";\n"
        """
var nodes = new vis.DataSet(nodesArray);
var edges = new vis.DataSet(edgesArray);
var container = document.getElementById('graph');
var data = { nodes: nodes, edges: edges };
var options = {
    physics: {
        solver: 'forceAtlas2Based',
        forceAtlas2Based: { gravitationalConstant: -30, centralGravity: 0.005, springLength: 100, springConstant: 0.02 },
        stabilization: { iterations: 150, updateInterval: 25 }
    },
    edges: { arrows: { to: { enabled: true, scaleFactor: 0.5 } }, color: { color: '#404060', highlight: '#7070a0' }, smooth: { type: 'continuous' } },
    interaction: { hover: true, tooltipDelay: 100 },
    nodes: { shape: 'dot', font: { color: '#e0e0e0' } }
};
var network = new vis.Network(container, data, options);

function escapeHtml(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function stripDiacritics(s) { return s.normalize('NFD').replace(/[\\u0300-\\u036f]/g, ''); }

// Visibility coordination — each control adds/removes its own reason.
// A node is hidden iff it has any reason.
var hiddenReasons = {};
function setHidden(nodeId, reason, hide) {
    if (!hiddenReasons[nodeId]) hiddenReasons[nodeId] = {};
    if (hide) hiddenReasons[nodeId][reason] = true;
    else delete hiddenReasons[nodeId][reason];
    var keys = Object.keys(hiddenReasons[nodeId]);
    nodes.update({id: nodeId, hidden: keys.length > 0});
}

// Search (diacritic-insensitive)
document.getElementById('search').addEventListener('input', function(e) {
    var q = stripDiacritics(e.target.value.toLowerCase());
    nodes.forEach(function(n) {
        if (!q) { setHidden(n.id, 'search', false); return; }
        var match = stripDiacritics((n.label || '').toLowerCase()).indexOf(q) >= 0
                 || stripDiacritics((n.title || '').toLowerCase()).indexOf(q) >= 0;
        setHidden(n.id, 'search', !match);
    });
});

// Click to inspect
network.on('click', function(params) {
    var panel = document.getElementById('info-panel');
    if (params.nodes.length === 0) { panel.innerHTML = '<em>Click a node to inspect</em>'; return; }
    var nid = params.nodes[0];
    var n = nodes.get(nid);
    var h = '<h3>' + escapeHtml(n.label || n.id) + '</h3>';
    h += '<div class="prop-row"><span class="prop-key">labels:</span> <span class="prop-val">' + escapeHtml((n._labels || []).join(', ')) + '</span></div>';
    var props = n._props || {};
    for (var k in props) { h += '<div class="prop-row"><span class="prop-key">' + escapeHtml(k) + ':</span> <span class="prop-val">' + escapeHtml(String(props[k])) + '</span></div>'; }
    var conns = network.getConnectedNodes(nid);
    h += '<div class="prop-row" style="margin-top:8px"><span class="prop-key">connections:</span> <span class="prop-val">' + conns.length + '</span></div>';
    for (var i = 0; i < Math.min(conns.length, 20); i++) {
        var cn = nodes.get(conns[i]);
        if (cn) h += '<div class="prop-row" style="padding-left:12px">→ ' + escapeHtml(cn.label || cn.id) + '</div>';
    }
    panel.innerHTML = h;
});

// Legend toggle
var hiddenLabels = {};
document.querySelectorAll('.legend-item').forEach(function(el) {
    el.addEventListener('click', function() {
        var lbl = this.dataset.label;
        hiddenLabels[lbl] = !hiddenLabels[lbl];
        this.classList.toggle('hidden');
        nodes.forEach(function(n) {
            if ((n._labels || []).indexOf(lbl) >= 0) {
                setHidden(n.id, 'legend:' + lbl, !!hiddenLabels[lbl]);
            }
        });
    });
});

// Community toggle
var hiddenCommunities = {};
document.querySelectorAll('.community-item input').forEach(function(cb) {
    cb.addEventListener('change', function() {
        var cid = cb.dataset.community;
        hiddenCommunities[cid] = !cb.checked;
        cb.parentElement.classList.toggle('hidden', !cb.checked);
        nodes.forEach(function(n) {
            if (n._communityId === cid) {
                setHidden(n.id, 'community:' + cid, !cb.checked);
            }
        });
    });
});

// Convex hull (Graham scan)
function convexHull(points) {
    if (points.length < 3) return points.slice();
    points.sort(function(a, b) { return a.x - b.x || a.y - b.y; });
    var lower = [];
    for (var i = 0; i < points.length; i++) {
        while (lower.length >= 2 && cross(lower[lower.length-2], lower[lower.length-1], points[i]) <= 0) lower.pop();
        lower.push(points[i]);
    }
    var upper = [];
    for (var i = points.length - 1; i >= 0; i--) {
        while (upper.length >= 2 && cross(upper[upper.length-2], upper[upper.length-1], points[i]) <= 0) upper.pop();
        upper.push(points[i]);
    }
    upper.pop(); lower.pop();
    return lower.concat(upper);
}
function cross(O, A, B) { return (A.x - O.x) * (B.y - O.y) - (A.y - O.y) * (B.x - O.x); }

// Draw community hulls
if (communityData.length > 0) {
    network.on('afterDrawing', function(ctx) {
        var positions = network.getPositions();
        communityData.forEach(function(comm) {
            if (hiddenCommunities[comm.id]) return;
            var pts = [];
            nodes.forEach(function(n) {
                if (n._communityId === comm.id && !n.hidden && positions[n.id]) {
                    var p = positions[n.id];
                    pts.push({x: p.x, y: p.y});
                }
            });
            if (pts.length < 3) return;
            var hull = convexHull(pts);
            var cx = 0, cy = 0;
            hull.forEach(function(p) { cx += p.x; cy += p.y; });
            cx /= hull.length; cy /= hull.length;
            var padded = hull.map(function(p) {
                var dx = p.x - cx, dy = p.y - cy;
                var d = Math.sqrt(dx*dx + dy*dy) || 1;
                return {x: p.x + dx/d * 20, y: p.y + dy/d * 20};
            });
            ctx.beginPath();
            ctx.moveTo(padded[0].x, padded[0].y);
            for (var i = 1; i < padded.length; i++) ctx.lineTo(padded[i].x, padded[i].y);
            ctx.closePath();
            ctx.fillStyle = comm.color.replace('hsl', 'hsla').replace(')', ', 0.12)');
            ctx.fill();
            ctx.strokeStyle = comm.color.replace('hsl', 'hsla').replace(')', ', 0.3)');
            ctx.lineWidth = 1;
            ctx.stroke();
        });
    });
}
"""
    )


def to_html(
    nodes: list[dict],
    edges: list[dict],
    out_path: Path,
    *,
    max_nodes: int | None = None,
) -> None:
    """Write a self-contained interactive HTML visualisation.

    Raises :class:`ValueError` if *nodes* exceeds *max_nodes*
    (defaults to :data:`MAX_NODES_FOR_VIZ`).
    """
    limit = max_nodes if max_nodes is not None else MAX_NODES_FOR_VIZ
    if len(nodes) > limit:
        raise ValueError(
            f"Graph too large for HTML visualisation ({len(nodes)} nodes, "
            f"max {limit}). Use --max-nodes to override or "
            f"export to JSON/GraphML instead."
        )

    # Partition: separate EdgeGroup community nodes and MEMBER_OF edges
    regular_nodes: list[dict] = []
    community_nodes: list[dict] = []
    for n in nodes:
        if "EdgeGroup" in n.get("labels", []):
            community_nodes.append(n)
        else:
            regular_nodes.append(n)

    regular_edges: list[dict] = []
    member_edges: list[dict] = []
    for e in edges:
        if e["type"] == "MEMBER_OF":
            member_edges.append(e)
        else:
            regular_edges.append(e)

    # Build community structures
    n_comms = len(community_nodes)
    community_map: dict[str, dict] = {}
    for i, cn in enumerate(community_nodes):
        props = cn.get("properties", {})
        color = f"hsl({i * 360 // n_comms if n_comms else 0}, 60%, 45%)"
        community_map[cn["id"]] = {
            "label": props.get("label", cn["id"]),
            "kind": props.get("kind", "community"),
            "node_count": props.get("node_count", 0),
            "color": color,
        }

    node_to_community: dict[str, str] = {}
    for me in member_edges:
        node_to_community[me["src"]] = me["dst"]

    # Compute degree for sizing (regular edges only)
    degree: dict[str, int] = {}
    for e in regular_edges:
        degree[e["src"]] = degree.get(e["src"], 0) + 1
        degree[e["dst"]] = degree.get(e["dst"], 0) + 1
    max_deg = max(degree.values()) if degree else 1

    # Build vis nodes (regular only — EdgeGroup nodes are not rendered)
    vis_nodes: list[dict] = []
    label_counts: dict[str, int] = {}
    for n in regular_nodes:
        labels = n.get("labels", [])
        primary = labels[0] if labels else "Unknown"
        label_counts[primary] = label_counts.get(primary, 0) + 1
        color = LABEL_COLORS.get(primary, _DEFAULT_COLOR)
        props = n.get("properties", {})
        display_name = props.get("name") or props.get("path") or n["id"]
        deg = degree.get(n["id"], 0)
        size = 10 + 30 * (deg / max_deg) if max_deg else 10
        vis_nodes.append({
            "id": n["id"],
            "label": display_name,
            "title": html.escape(f"{primary}: {display_name}"),
            "color": color,
            "size": round(size, 1),
            "font": {"size": 12 if deg > max_deg * 0.3 else 0},
            "_labels": labels,
            "_props": {k: str(v) for k, v in props.items()},
            "_communityId": node_to_community.get(n["id"]),
        })

    # Build vis edges (regular only — MEMBER_OF edges are not rendered)
    vis_edges: list[dict] = []
    for e in regular_edges:
        vis_edges.append({
            "from": e["src"],
            "to": e["dst"],
            "title": html.escape(e["type"]),
        })

    # Build legend
    legend_data: list[dict] = []
    for lbl, count in sorted(label_counts.items(), key=lambda x: -x[1]):
        color = LABEL_COLORS.get(lbl, _DEFAULT_COLOR)
        legend_data.append({"label": lbl, "count": count, "color": color["background"]})

    # Build community data for JS
    community_data: list[dict] = []
    for cid, cinfo in community_map.items():
        member_count = sum(1 for v in node_to_community.values() if v == cid)
        community_data.append({
            "id": cid,
            "label": cinfo["label"],
            "color": cinfo["color"],
            "memberCount": member_count,
        })

    # Read vendored vis.js
    vis_js = (_pkg_files("codegraph") / "templates" / "vis-network.min.js").read_text()

    # Build legend HTML
    legend_html_parts: list[str] = []
    for item in legend_data:
        legend_html_parts.append(
            f'<div class="legend-item" data-label="{html.escape(item["label"])}">'
            f'<span class="legend-color" style="background:{html.escape(item["color"])}"></span>'
            f'{html.escape(item["label"])} ({item["count"]})</div>'
        )
    legend_html = "\n".join(legend_html_parts)

    # Build community sidebar HTML
    community_html = ""
    if community_data:
        comm_parts: list[str] = ["<h3>Communities</h3>"]
        for cd in community_data:
            comm_parts.append(
                f'<label class="community-item" data-community="{html.escape(cd["id"])}">'
                f'<input type="checkbox" checked data-community="{html.escape(cd["id"])}">'
                f'<span class="community-color" style="background:{html.escape(cd["color"])}"></span>'
                f'{html.escape(cd["label"])} ({cd["memberCount"]})</label>'
            )
        community_html = "\n".join(comm_parts)

    nodes_json = _js_safe(vis_nodes)
    edges_json = _js_safe(vis_edges)
    legend_json_str = _js_safe(legend_data)
    community_json = _js_safe(community_data)
    script = _html_script(nodes_json, edges_json, legend_json_str, community_json)
    styles = _html_styles()

    page = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        "<title>codegraph — interactive graph</title>\n"
        f"<style>\n{styles}</style>\n"
        f"<script>\n{vis_js}\n</"
        "script>\n"
        "</head>\n<body>\n"
        '<div id="sidebar">\n'
        "  <h2>codegraph</h2>\n"
        f'  <div id="stats">{len(regular_nodes)} nodes, {len(regular_edges)} edges</div>\n'
        '  <div id="search-box"><input id="search" placeholder="Search nodes\u2026" type="text"></div>\n'
        f'  <div id="legend"><h3>Labels</h3>\n{legend_html}\n  </div>\n'
        f'  <div id="communities">{community_html}</div>\n'
        '  <div id="info-panel"><em>Click a node to inspect</em></div>\n'
        "</div>\n"
        '<div id="graph"></div>\n'
        f"<script>\n{script}\n</"
        "script>\n"
        "</body>\n</html>"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")


def to_html_from_driver(
    driver: Any,
    out_path: Path,
    *,
    scope: list[str] | None = None,
    max_nodes: int = MAX_NODES_FOR_VIZ,
) -> int:
    """Dump graph from Neo4j and write interactive HTML. Returns node count."""
    nodes, edges = dump_graph(driver, scope=scope)
    to_html(nodes, edges, out_path, max_nodes=max_nodes)
    return len(nodes)


# ── JSON export ───────────────────────────────────────────────────


def to_json(
    nodes: list[dict],
    edges: list[dict],
    out_path: Path,
) -> None:
    """Write nodes and edges as a JSON document."""
    doc = {
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")


def to_json_from_driver(
    driver: Any,
    out_path: Path,
    *,
    scope: list[str] | None = None,
) -> int:
    """Dump graph from Neo4j and write JSON. Returns node count."""
    nodes, edges = dump_graph(driver, scope=scope)
    to_json(nodes, edges, out_path)
    return len(nodes)


# ── GraphML export ────────────────────────────────────────────────


def to_graphml(
    nodes: list[dict],
    edges: list[dict],
    out_path: Path,
) -> None:
    """Write nodes and edges as a GraphML XML document."""
    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphstruct.org/xmlns">',
        '  <key id="labels" for="node" attr.name="labels" attr.type="string"/>',
        '  <key id="name" for="node" attr.name="name" attr.type="string"/>',
        '  <key id="file" for="node" attr.name="file" attr.type="string"/>',
        '  <key id="path" for="node" attr.name="path" attr.type="string"/>',
        '  <key id="reltype" for="edge" attr.name="type" attr.type="string"/>',
        '  <graph edgedefault="directed">',
    ]
    for n in nodes:
        nid = xml_quoteattr(str(n["id"]))
        labels = xml_escape(",".join(n.get("labels", [])))
        props = n.get("properties", {})
        name = xml_escape(str(props.get("name", "")))
        file_val = xml_escape(str(props.get("file", "")))
        path_val = xml_escape(str(props.get("path", "")))
        lines.append(f"    <node id={nid}>")
        lines.append(f'      <data key="labels">{labels}</data>')
        if name:
            lines.append(f'      <data key="name">{name}</data>')
        if file_val:
            lines.append(f'      <data key="file">{file_val}</data>')
        if path_val:
            lines.append(f'      <data key="path">{path_val}</data>')
        lines.append("    </node>")

    for i, e in enumerate(edges):
        src = xml_quoteattr(str(e["src"]))
        dst = xml_quoteattr(str(e["dst"]))
        rel = xml_escape(str(e["type"]))
        lines.append(f'    <edge id="e{i}" source={src} target={dst}>')
        lines.append(f'      <data key="reltype">{rel}</data>')
        lines.append("    </edge>")

    lines.append("  </graph>")
    lines.append("</graphml>")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def to_graphml_from_driver(
    driver: Any,
    out_path: Path,
    *,
    scope: list[str] | None = None,
) -> int:
    """Dump graph from Neo4j and write GraphML. Returns node count."""
    nodes, edges = dump_graph(driver, scope=scope)
    to_graphml(nodes, edges, out_path)
    return len(nodes)


# ── Cypher export ─────────────────────────────────────────────────


def _cypher_escape(s: str) -> str:
    """Escape a string for use inside Cypher single-quoted literals."""
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _sanitize_label(label: str) -> str:
    """Strip non-alphanumeric chars from a Neo4j label for Cypher output."""
    return re.sub(r"[^a-zA-Z0-9_]", "", label) or "Node"


def to_cypher(
    nodes: list[dict],
    edges: list[dict],
    out_path: Path,
) -> None:
    """Write CREATE/MERGE Cypher statements that recreate the graph."""
    lines: list[str] = ["// Cypher export -- generated by codegraph"]

    for n in nodes:
        labels = n.get("labels", [])
        primary = _sanitize_label(labels[0]) if labels else "Node"
        props = n.get("properties", {})
        nid = _cypher_escape(str(n["id"]))
        name = _cypher_escape(str(props.get("name", "")))
        file_val = _cypher_escape(str(props.get("file", "")))
        prop_parts = [f"id: '{nid}'"]
        if name:
            prop_parts.append(f"name: '{name}'")
        if file_val:
            prop_parts.append(f"file: '{file_val}'")
        prop_str = ", ".join(prop_parts)
        lines.append(f"MERGE (n:{primary} {{{prop_str}}});")

    for e in edges:
        src = _cypher_escape(str(e["src"]))
        dst = _cypher_escape(str(e["dst"]))
        rel = _sanitize_label(e["type"])
        lines.append(f"MATCH (a {{id: '{src}'}}), (b {{id: '{dst}'}}) MERGE (a)-[:{rel}]->(b);")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


def to_cypher_from_driver(
    driver: Any,
    out_path: Path,
    *,
    scope: list[str] | None = None,
) -> int:
    """Dump graph from Neo4j and write Cypher. Returns node count."""
    nodes, edges = dump_graph(driver, scope=scope)
    to_cypher(nodes, edges, out_path)
    return len(nodes)
