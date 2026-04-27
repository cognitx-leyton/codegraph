"""Tests for the pre-load extraction validator (parse_validator)."""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.parse_validator import (
    VALID_CONFIDENCE_LABELS,
    VALID_EDGE_KINDS,
    assert_valid,
    validate_cross_file_edges,
    validate_parse_result,
)
from codegraph.resolver import Index
from codegraph.schema import (
    ClassNode,
    Edge,
    FileNode,
    ParseResult,
    DEFINES_CLASS,
    CALLS,
)


# ── Fixture helpers ──────────────────────────────────────────────


def _make_valid_result(path: str = "a.py", pkg: str = "p") -> ParseResult:
    """Build a minimal valid ParseResult (FileNode + one class + one edge)."""
    fn = FileNode(path=path, package=pkg, language="py", loc=10, is_test=False)
    cls = ClassNode(name="Foo", file=path)
    edge = Edge(kind=DEFINES_CLASS, src_id=fn.id, dst_id=cls.id)
    return ParseResult(file=fn, classes=[cls], edges=[edge])


# ── Constants sanity ─────────────────────────────────────────────


def test_edge_kinds_includes_stats():
    assert "__STATS__" in VALID_EDGE_KINDS


def test_confidence_labels():
    assert VALID_CONFIDENCE_LABELS == frozenset({"EXTRACTED", "INFERRED", "AMBIGUOUS"})


# ── validate_parse_result ────────────────────────────────────────


def test_valid_result_zero_errors():
    result = _make_valid_result()
    assert validate_parse_result(result) == []


def test_duplicate_node_id():
    fn = FileNode(path="a.py", package="p", language="py", loc=10, is_test=False)
    cls1 = ClassNode(name="Foo", file="a.py")
    cls2 = ClassNode(name="Foo", file="a.py")  # same name+file → same id
    result = ParseResult(file=fn, classes=[cls1, cls2], edges=[])
    errors = validate_parse_result(result)
    assert any("duplicate node id" in e for e in errors)


def test_dangling_src_id():
    fn = FileNode(path="a.py", package="p", language="py", loc=10, is_test=False)
    edge = Edge(kind=CALLS, src_id="func:default:a.py#nonexistent", dst_id=fn.id)
    result = ParseResult(file=fn, edges=[edge])
    errors = validate_parse_result(result)
    assert any("dangling src_id" in e for e in errors)


def test_dangling_dst_id():
    fn = FileNode(path="a.py", package="p", language="py", loc=10, is_test=False)
    edge = Edge(kind=CALLS, src_id=fn.id, dst_id="func:default:a.py#nonexistent")
    result = ParseResult(file=fn, edges=[edge])
    errors = validate_parse_result(result)
    assert any("dangling dst_id" in e for e in errors)


def test_synthetic_dst_id_accepted():
    fn = FileNode(path="a.py", package="p", language="py", loc=10, is_test=False)
    edge = Edge(kind="DECORATED_BY", src_id=fn.id, dst_id="dec:foo")
    result = ParseResult(file=fn, edges=[edge])
    errors = validate_parse_result(result)
    # No dangling error for the synthetic dst
    assert not any("dangling dst_id" in e for e in errors)


def test_synthetic_external_accepted():
    fn = FileNode(path="a.py", package="p", language="py", loc=10, is_test=False)
    edge = Edge(kind="IMPORTS", src_id=fn.id, dst_id="external:os")
    result = ParseResult(file=fn, edges=[edge])
    errors = validate_parse_result(result)
    assert not any("dangling" in e for e in errors)


def test_synthetic_hook_accepted():
    fn = FileNode(path="a.py", package="p", language="py", loc=10, is_test=False)
    edge = Edge(kind="USES_HOOK", src_id=fn.id, dst_id="hook:useState")
    result = ParseResult(file=fn, edges=[edge])
    errors = validate_parse_result(result)
    assert not any("dangling" in e for e in errors)


def test_synthetic_edgegroup_accepted():
    fn = FileNode(path="a.py", package="p", language="py", loc=10, is_test=False)
    edge = Edge(kind="MEMBER_OF", src_id=fn.id, dst_id="edgegroup:community:c1")
    result = ParseResult(file=fn, edges=[edge])
    errors = validate_parse_result(result)
    assert not any("dangling" in e for e in errors)


def test_unknown_edge_kind():
    fn = FileNode(path="a.py", package="p", language="py", loc=10, is_test=False)
    edge = Edge(kind="BOGUS", src_id=fn.id, dst_id=fn.id)
    result = ParseResult(file=fn, edges=[edge])
    errors = validate_parse_result(result)
    assert any("unknown kind" in e for e in errors)


def test_invalid_confidence_label():
    fn = FileNode(path="a.py", package="p", language="py", loc=10, is_test=False)
    edge = Edge(kind=CALLS, src_id=fn.id, dst_id=fn.id, confidence="MAYBE")
    result = ParseResult(file=fn, edges=[edge])
    errors = validate_parse_result(result)
    assert any("invalid confidence" in e for e in errors)


def test_confidence_score_below_zero():
    fn = FileNode(path="a.py", package="p", language="py", loc=10, is_test=False)
    edge = Edge(kind=CALLS, src_id=fn.id, dst_id=fn.id, confidence_score=-0.1)
    result = ParseResult(file=fn, edges=[edge])
    errors = validate_parse_result(result)
    assert any("confidence_score" in e and "out of range" in e for e in errors)


def test_confidence_score_above_one():
    fn = FileNode(path="a.py", package="p", language="py", loc=10, is_test=False)
    edge = Edge(kind=CALLS, src_id=fn.id, dst_id=fn.id, confidence_score=1.5)
    result = ParseResult(file=fn, edges=[edge])
    errors = validate_parse_result(result)
    assert any("confidence_score" in e and "out of range" in e for e in errors)


def test_valid_confidence_values():
    fn = FileNode(path="a.py", package="p", language="py", loc=10, is_test=False)
    edges = [
        Edge(kind=CALLS, src_id=fn.id, dst_id=fn.id,
             confidence="EXTRACTED", confidence_score=1.0),
        Edge(kind=CALLS, src_id=fn.id, dst_id=fn.id,
             confidence="INFERRED", confidence_score=0.5),
        Edge(kind=CALLS, src_id=fn.id, dst_id=fn.id,
             confidence="AMBIGUOUS", confidence_score=0.0),
    ]
    result = ParseResult(file=fn, edges=edges)
    errors = validate_parse_result(result)
    assert errors == []


# ── assert_valid ─────────────────────────────────────────────────


def test_assert_valid_raises():
    fn = FileNode(path="a.py", package="p", language="py", loc=10, is_test=False)
    edge = Edge(kind="BOGUS", src_id=fn.id, dst_id=fn.id, confidence="MAYBE")
    result = ParseResult(file=fn, edges=[edge])
    with pytest.raises(ValueError, match=r"2 validation error"):
        assert_valid(result)


def test_assert_valid_passes():
    result = _make_valid_result()
    assert_valid(result)  # should not raise


# ── validate_cross_file_edges ────────────────────────────────────


def test_cross_file_validation():
    r1 = _make_valid_result("a.py")
    r2 = _make_valid_result("b.py")
    idx = Index()
    idx.add(r1)
    idx.add(r2)

    # Cross-file edge referencing real nodes in both files → no error
    good_edge = Edge(kind=CALLS, src_id=r1.file.id, dst_id=r2.file.id)
    assert validate_cross_file_edges([good_edge], idx) == []

    # Edge with dangling dst → error
    bad_edge = Edge(kind=CALLS, src_id=r1.file.id, dst_id="func:default:z.py#ghost")
    errors = validate_cross_file_edges([bad_edge], idx)
    assert any("dangling dst_id" in e for e in errors)


def test_stats_edge_skipped():
    idx = Index()
    idx.add(_make_valid_result())
    stats = Edge(kind="__STATS__", src_id="", dst_id="", props={"total_imports": 5})
    errors = validate_cross_file_edges([stats], idx)
    assert errors == []


# ── Integration: self-parse ──────────────────────────────────────


def test_self_parse_zero_errors():
    """Parse real Python source files from codegraph and validate."""
    from codegraph.py_parser import PyParser

    parser = PyParser()
    pkg_dir = Path(__file__).resolve().parent.parent / "codegraph"
    repo_root = pkg_dir.parent

    # Pick a few known-good source files
    targets = ["schema.py", "cli.py", "parse_validator.py"]
    for name in targets:
        src = pkg_dir / name
        if not src.exists():
            continue
        rel = str(src.relative_to(repo_root)).replace("\\", "/")
        result = parser.parse_file(src, rel, "codegraph", is_test=False)
        assert result is not None, f"parse returned None for {name}"
        errors = validate_parse_result(result)
        assert errors == [], f"{name}: {errors}"
