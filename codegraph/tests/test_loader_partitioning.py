"""Tests for :mod:`codegraph.loader`'s edge partitioner.

These don't touch Neo4j — they monkeypatch ``loader._run`` to capture the
``(cypher, rows)`` tuples the partitioner produces. That lets us assert the
routing logic directly without a live session.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph import loader
from codegraph.py_parser import PyParser
from codegraph.schema import DECORATED_BY, Edge


REPO_ROOT = Path(__file__).resolve().parents[2]
CODEGRAPH_PKG = REPO_ROOT / "codegraph" / "codegraph"


class _Stats:
    """Minimal LoadStats stand-in for partitioner tests."""

    def __init__(self):
        self.edges: dict = {}


@pytest.fixture
def captured_runs(monkeypatch):
    """Monkeypatch ``loader._run`` to record every (cypher, rows) pair."""
    calls: list[tuple[str, list]] = []

    def fake_run(session, cypher, rows):
        calls.append((cypher, list(rows)))

    monkeypatch.setattr(loader, "_run", fake_run)
    return calls


def test_decorated_by_partitions_function_src_ids(captured_runs):
    """func:-prefixed DECORATED_BY edges must reach a Function MERGE."""
    edges = [
        Edge(kind=DECORATED_BY, src_id="class:a.py#A", dst_id="dec:dataclass"),
        Edge(kind=DECORATED_BY, src_id="func:b.py#helper", dst_id="dec:staticmethod"),
        Edge(kind=DECORATED_BY, src_id="func:c.py#main", dst_id="dec:app.command()"),
        Edge(kind=DECORATED_BY, src_id="method:class:d.py#D#run", dst_id="dec:property"),
    ]
    stats = _Stats()

    loader._write_edges(session=None, edges=edges, stats=stats)

    # Find the Function MERGE call and check the rows it got.
    func_runs = [
        (cypher, rows) for cypher, rows in captured_runs
        if "MATCH (a:Function {id: r.src})" in cypher
        and "MERGE (a)-[:DECORATED_BY]->(d)" in cypher
    ]
    assert len(func_runs) == 1, "expected exactly one Function DECORATED_BY MERGE"
    rows = func_runs[0][1]
    assert len(rows) == 2
    src_ids = {r["src"] for r in rows}
    assert src_ids == {"func:b.py#helper", "func:c.py#main"}

    # Stats total covers all three buckets (class=1, func=2, method=1).
    assert stats.edges[DECORATED_BY] == 4


def test_decorated_by_func_smoke_from_parser():
    """Parsing ``mcp.py`` must yield exactly 13 function-level decorators.

    All are ``@mcp.tool()`` on module-level tool functions. If this count
    changes, ``mcp.py`` grew a new tool — update this assertion and ROADMAP.
    """
    parser = PyParser()
    rel = "codegraph/codegraph/mcp.py"
    result = parser.parse_file(CODEGRAPH_PKG / "mcp.py", rel, "codegraph")
    assert result is not None
    func_decs = [
        e for e in result.edges
        if e.kind == DECORATED_BY and e.src_id.startswith("func:")
    ]
    assert len(func_decs) == 13
    assert all(e.dst_id == "dec:mcp.tool()" for e in func_decs)


def test_unknown_prefix_logs_debug(captured_runs, caplog):
    """Unknown src_id prefixes drop through with a debug-log breadcrumb."""
    import logging
    caplog.set_level(logging.DEBUG, logger="codegraph.loader")

    edges = [
        Edge(kind=DECORATED_BY, src_id="garbage:x#y", dst_id="dec:whatever"),
    ]
    loader._write_edges(session=None, edges=edges, stats=_Stats())

    assert any(
        "unknown src prefix" in rec.message and "garbage:x#y" in rec.message
        for rec in caplog.records
    ), "expected a debug log about the unknown prefix"
