"""Markdown renderer for GRAPH_REPORT.md.

Takes the analysis dict from :func:`codegraph.analyze.run_analysis` and
produces a plain-text Markdown report with god nodes, surprising connections,
communities, and suggested questions.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path


def generate_report(analysis: dict) -> str:
    """Render the analysis dict as a Markdown report."""
    lines: list[str] = []

    # Header
    lines.append(f"# Graph Report \u2014 {date.today().isoformat()}")
    lines.append("")

    # Summary
    node_count = analysis.get("node_count", 0)
    edge_count = analysis.get("edge_count", 0)
    community_count = analysis.get("community_count", 0)
    lines.append(
        f"**{node_count}** nodes, **{edge_count}** edges, "
        f"**{community_count}** communities detected."
    )
    lines.append("")

    # God Nodes
    lines.append("## God Nodes")
    lines.append("")
    gods = analysis.get("god_nodes", [])
    if gods:
        for i, g in enumerate(gods, 1):
            name = g.get("name", "?")
            degree = g.get("degree", 0)
            file_ = g.get("file", "")
            lines.append(f"{i}. `{name}` \u2014 {degree} connections ({file_})")
    else:
        lines.append("_No god nodes detected._")
    lines.append("")

    # Surprising Connections
    lines.append("## Surprising Connections")
    lines.append("")
    surprises = analysis.get("surprising_connections", [])
    if surprises:
        for s in surprises:
            src = s.get("source_name", "?")
            dst = s.get("target_name", "?")
            etype = s.get("edge_type", "?")
            why = s.get("why", "")
            lines.append(f"- `{src}` --{etype}--> `{dst}`: {why}")
    else:
        lines.append("_No surprising connections detected._")
    lines.append("")

    # Communities
    lines.append("## Communities")
    lines.append("")
    communities = analysis.get("communities", [])
    if communities:
        for comm in communities[:20]:
            label = comm.get("label", f"Community {comm.get('id', '?')}")
            count = comm.get("node_count", 0)
            coh = comm.get("cohesion", 0.0)
            members = comm.get("members", [])
            lines.append(f"### {label}")
            lines.append(f"_{count} nodes, cohesion {coh:.2f}_")
            lines.append("")
            shown = members[:8]
            names = ", ".join(f"`{m}`" for m in shown)
            if len(members) > 8:
                names += f" (+{len(members) - 8} more)"
            lines.append(names)
            lines.append("")
    else:
        lines.append("_No communities detected._")
    lines.append("")

    # Suggested Questions
    lines.append("## Suggested Questions")
    lines.append("")
    questions = analysis.get("suggested_questions", [])
    if questions:
        for q in questions:
            question = q.get("question", "?")
            why = q.get("why", "")
            lines.append(f"- {question} _{why}_")
    else:
        lines.append("_No questions suggested._")
    lines.append("")

    return "\n".join(lines)


def write_report(report_text: str, path: Path) -> None:
    """Write *report_text* to *path*, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_text, encoding="utf-8")
