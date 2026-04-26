"""Leiden community detection + graph analysis for codegraph.

Reads the Neo4j graph into a NetworkX DiGraph, clusters with Leiden (or
Louvain fallback), and computes god nodes, surprising connections, and
suggested questions — all from pure graph topology, no LLM calls.

Requires the ``[analyze]`` extra: ``pip install "codegraph[analyze]"``.
"""
from __future__ import annotations

import io
import sys
from collections import Counter
from typing import Any, Optional

import networkx as nx  # type: ignore[import-untyped]


# ── Constants ────────────────────────────────────────────────────────

# Labels that represent structural/infra hubs — exclude from god nodes and
# surprising-connections scoring because their high degree is expected.
_HUB_LABELS = frozenset({
    "File", "Package", "External", "Hook", "Decorator",
    "EnvVar", "Event", "TestFile", "Author", "Team",
})

# Decorators that mark a function as a framework entry point (not dead code).
_ENTRY_DECORATORS = frozenset({
    "app.command", "app.get", "app.post", "app.put", "app.delete",
    "app.patch", "mcp.tool", "pytest.fixture", "pytest.mark",
})


# ── Neo4j → NetworkX ────────────────────────────────────────────────


def read_graph(
    driver: Any,
    *,
    scope: Optional[list[str]] = None,
) -> nx.DiGraph:
    """Query all nodes + edges from Neo4j into a NetworkX DiGraph.

    Each node gets attributes: ``labels``, ``name``, ``file``, ``package``,
    ``id``.  Each edge gets a ``type`` attribute (IMPORTS, CALLS, etc.).
    Uses ``elementId()`` as NetworkX node keys to avoid collisions.
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
            "WITH a, r, b, elementId(a) AS aeid, elementId(b) AS beid, "
            "coalesce(a.file, a.path) AS aloc, "
            "coalesce(b.file, b.path) AS bloc "
            "WHERE (aloc IS NOT NULL AND any(s IN $scopes WHERE aloc STARTS WITH s)) "
            "AND (bloc IS NOT NULL AND any(s IN $scopes WHERE bloc STARTS WITH s)) "
            "RETURN aeid, type(r) AS rel, beid"
        )
        params: dict[str, Any] = {"scopes": scope}
    else:
        node_cypher = (
            "MATCH (n) "
            "RETURN n, labels(n) AS lbls, elementId(n) AS eid"
        )
        edge_cypher = (
            "MATCH (a)-[r]->(b) "
            "RETURN elementId(a) AS aeid, type(r) AS rel, elementId(b) AS beid"
        )
        params = {}

    G = nx.DiGraph()

    with driver.session() as s:
        for row in s.run(node_cypher, **params):
            n = row["n"]
            props = dict(n.items()) if hasattr(n, "items") else {}
            eid = row["eid"]
            G.add_node(eid, **{
                "labels": list(row["lbls"]),
                "name": props.get("name", props.get("path", "")),
                "file": props.get("file", props.get("path", "")),
                "package": props.get("package", ""),
                "id": props.get("id", eid),
            })

        for row in s.run(edge_cypher, **params):
            src, dst = row["aeid"], row["beid"]
            if src in G and dst in G:
                G.add_edge(src, dst, type=row["rel"])

    return G


# ── Leiden / Louvain partitioning ────────────────────────────────────


def _partition(G: nx.Graph) -> dict[str, int]:
    """Partition *G* using Leiden (graspologic) or Louvain (networkx) fallback.

    Returns a mapping of node-key → community-id.
    """
    if G.number_of_nodes() == 0:
        return {}

    # graspologic's leiden works on undirected graphs
    undirected = G.to_undirected() if G.is_directed() else G

    # Leiden requires at least one edge; degenerate graphs get one community
    if undirected.number_of_edges() == 0:
        return {n: 0 for n in undirected.nodes}

    try:
        from graspologic.partition import leiden  # type: ignore[import-untyped]

        # Suppress graspologic stdout noise
        old_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            result = leiden(undirected)
        finally:
            sys.stdout = old_stdout
        # leiden returns dict[node, community_id]
        return dict(result)
    except ImportError:
        pass

    communities = nx.community.louvain_communities(
        undirected, seed=42, threshold=1e-4
    )
    return {node: cid for cid, nodes in enumerate(communities) for node in nodes}


def cluster(G: nx.DiGraph) -> dict[int, list[str]]:
    """Cluster *G* into communities, returning ``{community_id: [node_keys]}``.

    Handles isolates, oversized communities (>25 % of graph), and re-indexes
    by descending size.
    """
    if G.number_of_nodes() == 0:
        return {}

    node_to_cid = _partition(G)

    # Group nodes by community
    raw: dict[int, list[str]] = {}
    for node, cid in node_to_cid.items():
        raw.setdefault(cid, []).append(node)

    # Split oversized communities (>25 % of graph, minimum 6 nodes)
    threshold = max(G.number_of_nodes() // 4, 6)
    split: list[list[str]] = []
    for members in raw.values():
        if len(members) > threshold:
            sub = G.subgraph(members).copy()
            sub_partition = _partition(sub)
            sub_groups: dict[int, list[str]] = {}
            for n, cid in sub_partition.items():
                sub_groups.setdefault(cid, []).append(n)
            split.extend(sub_groups.values())
        else:
            split.append(members)

    # Re-index by descending size
    split.sort(key=len, reverse=True)
    return {i: members for i, members in enumerate(split)}


def cohesion_score(G: nx.Graph, community_nodes: list[str]) -> float:
    """Ratio of actual to maximum possible intra-community edges."""
    if len(community_nodes) < 2:
        return 1.0
    sub = G.subgraph(community_nodes)
    actual = sub.number_of_edges()
    n = len(community_nodes)
    # For directed graphs, max edges = n*(n-1); undirected = n*(n-1)/2
    if G.is_directed():
        maximum = n * (n - 1)
    else:
        maximum = n * (n - 1) // 2
    return actual / maximum if maximum > 0 else 1.0


# ── Community labeling ───────────────────────────────────────────────


def _label_community(G: nx.DiGraph, nodes: list[str]) -> str:
    """Derive a human-readable label for a community.

    Uses the most common package prefix among member nodes, combined with
    the highest-degree node's name.
    """
    if not nodes:
        return "empty"

    packages = [G.nodes[n].get("package", "") for n in nodes if G.nodes[n].get("package")]
    pkg_prefix = Counter(packages).most_common(1)[0][0] if packages else "misc"

    # Find highest-degree node within the community
    degrees = [(n, G.degree(n)) for n in nodes]
    degrees.sort(key=lambda x: x[1], reverse=True)
    top_name = G.nodes[degrees[0][0]].get("name", "?")

    return f"{pkg_prefix}: {top_name}"


# ── God nodes ────────────────────────────────────────────────────────


def god_nodes(G: nx.DiGraph, top_n: int = 10) -> list[dict]:
    """Return the *top_n* highest-degree nodes, excluding hub labels."""
    scored: list[tuple[str, int]] = []
    for n in G.nodes:
        labels = set(G.nodes[n].get("labels", []))
        if labels & _HUB_LABELS:
            continue
        scored.append((n, G.degree(n)))

    scored.sort(key=lambda x: x[1], reverse=True)
    result = []
    for nid, deg in scored[:top_n]:
        attrs = G.nodes[nid]
        result.append({
            "id": attrs.get("id", nid),
            "name": attrs.get("name", ""),
            "file": attrs.get("file", ""),
            "labels": attrs.get("labels", []),
            "degree": deg,
        })
    return result


# ── Surprising connections ───────────────────────────────────────────


def surprising_connections(
    G: nx.DiGraph,
    communities: dict[int, list[str]],
    top_n: int = 5,
) -> list[dict]:
    """Find cross-community edges, scored by structural surprise."""
    if not communities:
        return []

    node_to_cid = {}
    for cid, members in communities.items():
        for n in members:
            node_to_cid[n] = cid

    # Collect the best-scoring edge per community pair
    best_per_pair: dict[tuple[int, int], tuple[float, dict]] = {}

    for u, v, data in G.edges(data=True):
        cid_u = node_to_cid.get(u)
        cid_v = node_to_cid.get(v)
        if cid_u is None or cid_v is None or cid_u == cid_v:
            continue

        pair = (min(cid_u, cid_v), max(cid_u, cid_v))
        edge_type = data.get("type", "UNKNOWN")
        reasons = []
        score = 0.0

        # Cross-package bonus
        pkg_u = G.nodes[u].get("package", "")
        pkg_v = G.nodes[v].get("package", "")
        if pkg_u and pkg_v and pkg_u != pkg_v:
            score += 2
            reasons.append("cross-package")

        # Structural coupling bonus (EXTENDS/INJECTS are rarer than IMPORTS)
        if edge_type in ("EXTENDS", "INJECTS"):
            score += 1
            reasons.append(f"structural coupling ({edge_type})")

        # Peripheral-to-hub bonus
        deg_u, deg_v = G.degree(u), G.degree(v)
        if min(deg_u, deg_v) <= 2 and max(deg_u, deg_v) >= 5:
            score += 1
            reasons.append("peripheral-to-hub bridge")

        if score > 0:
            entry = (score, {
                "source_name": G.nodes[u].get("name", ""),
                "target_name": G.nodes[v].get("name", ""),
                "source_file": G.nodes[u].get("file", ""),
                "target_file": G.nodes[v].get("file", ""),
                "edge_type": edge_type,
                "why": "; ".join(reasons),
            })
            prev = best_per_pair.get(pair)
            if prev is None or score > prev[0]:
                best_per_pair[pair] = entry

    scored = sorted(best_per_pair.values(), key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_n]]


# ── Suggested questions ──────────────────────────────────────────────


def suggest_questions(
    G: nx.DiGraph,
    communities: dict[int, list[str]],
    top_n: int = 5,
) -> list[dict]:
    """Generate orientation questions from structural signals."""
    questions: list[dict] = []

    if G.number_of_nodes() == 0:
        return [{"type": "info", "question": "Graph is empty — nothing to analyze.", "why": "no nodes"}]

    # High fan-in classes (>10 incoming INJECTS/EXTENDS)
    for n in G.nodes:
        labels = set(G.nodes[n].get("labels", []))
        if labels & _HUB_LABELS:
            continue
        in_count = sum(
            1 for _, _, d in G.in_edges(n, data=True)
            if d.get("type") in ("INJECTS", "EXTENDS", "IMPORTS_SYMBOL", "CALLS")
        )
        if in_count > 10:
            name = G.nodes[n].get("name", "?")
            questions.append({
                "type": "god-node",
                "question": f"Is `{name}` doing too much?",
                "why": f"{in_count} incoming dependencies",
            })

    # Bridge nodes (top betweenness centrality)
    try:
        node_to_cid: dict[str, int] = {}
        for cid, members in communities.items():
            for m in members:
                node_to_cid[m] = cid

        k = min(100, G.number_of_nodes())
        bc = nx.betweenness_centrality(G, k=k, seed=42)
        bridges = sorted(bc.items(), key=lambda x: x[1], reverse=True)[:3]
        for nid, score in bridges:
            if score < 0.01:
                continue
            labels = set(G.nodes[nid].get("labels", []))
            if labels & _HUB_LABELS:
                continue
            name = G.nodes[nid].get("name", "?")
            neighbors = set(G.predecessors(nid)) | set(G.successors(nid))
            neighbor_cids = {node_to_cid[nb] for nb in neighbors if nb in node_to_cid}
            if len(neighbor_cids) >= 2:
                questions.append({
                    "type": "bridge",
                    "question": f"Why does `{name}` connect {len(neighbor_cids)} clusters?",
                    "why": f"betweenness centrality {score:.3f}",
                })
    except Exception:
        pass  # betweenness can fail on degenerate graphs

    # Low-cohesion communities
    for cid, members in communities.items():
        if len(members) < 5:
            continue
        coh = cohesion_score(G, members)
        if coh < 0.15:
            label = _label_community(G, members)
            questions.append({
                "type": "low-cohesion",
                "question": f"Should the `{label}` cluster be split?",
                "why": f"cohesion {coh:.2f} across {len(members)} nodes",
            })

    # Orphan functions (no incoming CALLS, not entry-point-decorated)
    for n in G.nodes:
        labels = set(G.nodes[n].get("labels", []))
        if "Function" not in labels:
            continue
        if labels & _HUB_LABELS:
            continue
        # Check if any incoming CALLS edges
        has_callers = any(
            d.get("type") == "CALLS" for _, _, d in G.in_edges(n, data=True)
        )
        if has_callers:
            continue
        # Check for entry-point decorators
        name = G.nodes[n].get("name", "")
        node_id = G.nodes[n].get("id", "")
        # Check if decorated by an entry-point decorator via HAS_DECORATOR edges
        is_entry = any(
            G.nodes.get(target, {}).get("name", "") in _ENTRY_DECORATORS
            for _, target, d in G.out_edges(n, data=True)
            if d.get("type") == "HAS_DECORATOR"
        )
        if is_entry:
            continue
        questions.append({
            "type": "orphan",
            "question": f"Is `{name}` dead code?",
            "why": "no incoming CALLS edges and no entry-point decorator",
        })

    return questions[:top_n] if questions else [
        {"type": "info", "question": "No structural concerns detected.", "why": "graph looks healthy"}
    ]


# ── Neo4j persistence ───────────────────────────────────────────────


def persist_communities(
    driver: Any,
    G: nx.DiGraph,
    communities: dict[int, list[str]],
    cohesion_scores: dict[int, float],
) -> dict:
    """Write community assignments back to Neo4j.

    1. SET ``community_id`` on every node.
    2. MERGE ``:EdgeGroup`` nodes with ``kind='community'``.
    3. MERGE ``:MEMBER_OF`` edges from nodes to their EdgeGroup.
    """
    # Build batch data for UNWIND-based writes
    eg_rows = []
    member_rows = []
    for cid, members in communities.items():
        label = _label_community(G, members)
        eg_id = f"community:{cid}"
        coh = cohesion_scores.get(cid, 0.0)
        eg_rows.append({
            "id": eg_id, "count": len(members),
            "cohesion": coh, "label": label,
        })
        for nid in members:
            member_rows.append({"eid": nid, "cid": cid, "egid": eg_id})

    with driver.session() as s:
        # Batch create EdgeGroup nodes
        s.run(
            "UNWIND $rows AS r "
            "MERGE (eg:EdgeGroup {id: r.id}) "
            "SET eg.kind = 'community', eg.node_count = r.count, "
            "eg.cohesion = r.cohesion, eg.label = r.label",
            rows=eg_rows,
        )
        # Batch set community_id + MEMBER_OF edges
        s.run(
            "UNWIND $rows AS r "
            "MATCH (n) WHERE elementId(n) = r.eid "
            "SET n.community_id = r.cid "
            "WITH n, r "
            "MATCH (eg:EdgeGroup {id: r.egid}) "
            "MERGE (n)-[rel:MEMBER_OF]->(eg) "
            "SET rel.confidence = 'EXTRACTED', rel.confidence_score = 1.0",
            rows=member_rows,
        )

    return {"communities": len(communities), "nodes_labeled": len(member_rows)}


# ── Orchestrator ─────────────────────────────────────────────────────


def run_analysis(
    driver: Any,
    *,
    scope: Optional[list[str]] = None,
    console: Any = None,
) -> dict:
    """Run the full analysis pipeline.

    Returns a dict with all results for the report renderer:
    ``{node_count, edge_count, community_count, communities, cohesion_scores,
    god_nodes, surprising_connections, suggested_questions}``.
    """
    def _print(msg: str) -> None:
        if console is not None:
            console.print(msg)

    _print("[dim]analyze:[/] reading graph from Neo4j...")
    G = read_graph(driver, scope=scope)
    _print(f"[dim]analyze:[/] {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")

    _print("[dim]analyze:[/] clustering...")
    comms = cluster(G)
    _print(f"[dim]analyze:[/] {len(comms)} communities detected")

    coh_scores = {cid: cohesion_score(G, members) for cid, members in comms.items()}
    gods = god_nodes(G)
    surprises = surprising_connections(G, comms)
    questions = suggest_questions(G, comms)

    _print("[dim]analyze:[/] persisting communities to Neo4j...")
    persist_stats = persist_communities(driver, G, comms, coh_scores)

    # Build community summaries for the report
    community_summaries = []
    for cid, members in comms.items():
        label = _label_community(G, members)
        member_names = [G.nodes[n].get("name", "?") for n in members]
        community_summaries.append({
            "id": cid,
            "label": label,
            "node_count": len(members),
            "cohesion": coh_scores.get(cid, 0.0),
            "members": member_names,
        })

    return {
        "node_count": G.number_of_nodes(),
        "edge_count": G.number_of_edges(),
        "community_count": len(comms),
        "communities": community_summaries,
        "cohesion_scores": coh_scores,
        "god_nodes": gods,
        "surprising_connections": surprises,
        "suggested_questions": questions,
        "persist_stats": persist_stats,
    }
