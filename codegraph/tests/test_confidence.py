"""Tests for edge-level confidence classification (issue #38).

Verifies that edges emitted by the resolver carry the correct
``confidence`` (EXTRACTED / INFERRED / AMBIGUOUS) and
``confidence_score`` (0.0–1.0) values, and that cache round-trips
preserve them.
"""
from __future__ import annotations

from pathlib import Path

from codegraph.py_parser import PyParser
from codegraph.resolver import (
    Index,
    Resolver,
    ResolveResult,
    link_cross_file,
    load_python_package_config,
)
from codegraph.schema import CALLS, IMPORTS, IMPORTS_SYMBOL, Edge, parse_result_from_dict, parse_result_to_dict


# ── Helpers ─────────────────────────────────────────────────────────


def _build_pkg(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)


def _run_pipeline(
    repo_root: Path, package_name: str, package_dir: Path
) -> tuple[Index, list]:
    parser = PyParser()
    index = Index()
    for p in package_dir.rglob("*.py"):
        rel = str(p.resolve().relative_to(repo_root)).replace("\\", "/")
        result = parser.parse_file(p, rel, package_name, is_test=False)
        assert result is not None
        index.add(result)
    pkg_config = load_python_package_config(repo_root, package_dir)
    resolver = Resolver(repo_root, [pkg_config])
    edges, _edge_groups = link_cross_file(index, resolver)
    return index, edges


def _calls_edges(edges):
    return [e for e in edges if e.kind == CALLS]


def _import_edges(edges):
    return [e for e in edges if e.kind == IMPORTS]


# ── Edge defaults ──────────────────────────────────────────────────


def test_edge_default_confidence():
    """A bare Edge() defaults to EXTRACTED / 1.0."""
    e = Edge("IMPORTS", "a", "b")
    assert e.confidence == "EXTRACTED"
    assert e.confidence_score == 1.0


def test_edge_explicit_confidence():
    """Confidence fields can be set explicitly."""
    e = Edge("CALLS", "a", "b", confidence="INFERRED", confidence_score=0.5)
    assert e.confidence == "INFERRED"
    assert e.confidence_score == 0.5


# ── Cache round-trip ───────────────────────────────────────────────


def test_cache_roundtrip_preserves_confidence(tmp_path: Path):
    """Confidence survives serialize → deserialize via parse_result_to_dict."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "from .b import helper\n",
        "pkg/b.py": "def helper(): pass\n",
    })
    _, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")
    # Find a file's ParseResult and round-trip it
    parser = PyParser()
    rel = "pkg/a.py"
    result = parser.parse_file(tmp_path / rel, rel, "pkg", is_test=False)
    d = parse_result_to_dict(result)
    restored = parse_result_from_dict(d)
    for edge in restored.edges:
        assert hasattr(edge, "confidence")
        assert hasattr(edge, "confidence_score")
        assert edge.confidence == "EXTRACTED"
        assert edge.confidence_score == 1.0


def test_old_cache_entry_gets_defaults():
    """An Edge dict missing confidence fields deserializes to EXTRACTED/1.0."""
    old_dict = {"kind": "IMPORTS", "src_id": "a", "dst_id": "b", "props": {}}
    e = Edge(**old_dict)
    assert e.confidence == "EXTRACTED"
    assert e.confidence_score == 1.0


# ── self.foo() → EXTRACTED ─────────────────────────────────────────


def test_self_call_is_extracted(tmp_path: Path):
    """``self.foo()`` CALLS edge has confidence=EXTRACTED, score=1.0."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": (
            "class A:\n"
            "    def run(self):\n"
            "        self.foo()\n"
            "    def foo(self):\n"
            "        pass\n"
        ),
    })
    _, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")
    calls = _calls_edges(edges)
    self_call = [
        e for e in calls
        if e.src_id == "method:class:pkg/a.py#A#run"
        and e.dst_id == "method:class:pkg/a.py#A#foo"
    ]
    assert len(self_call) == 1
    assert self_call[0].confidence == "EXTRACTED"
    assert self_call[0].confidence_score == 1.0


# ── super().foo() → INFERRED/0.7 ──────────────────────────────────


def test_super_call_is_inferred(tmp_path: Path):
    """``super().run()`` CALLS edge has confidence=INFERRED, score=0.7."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/base.py": (
            "class B:\n"
            "    def run(self):\n"
            "        pass\n"
        ),
        "pkg/child.py": (
            "from .base import B\n"
            "class A(B):\n"
            "    def run(self):\n"
            "        super().run()\n"
        ),
    })
    _, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")
    calls = _calls_edges(edges)
    super_call = [
        e for e in calls
        if e.src_id == "method:class:pkg/child.py#A#run"
        and e.dst_id == "method:class:pkg/base.py#B#run"
    ]
    assert len(super_call) == 1
    assert super_call[0].confidence == "INFERRED"
    assert super_call[0].confidence_score == 0.7


# ── Bare function call → INFERRED/0.5 ─────────────────────────────


def test_bare_function_call_is_inferred(tmp_path: Path):
    """Bare function call has confidence=INFERRED, score=0.5."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": (
            "from .b import helper\n"
            "def run():\n"
            "    helper()\n"
        ),
        "pkg/b.py": "def helper(): pass\n",
    })
    _, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")
    calls = _calls_edges(edges)
    bare_call = [
        e for e in calls
        if "helper" in e.dst_id
    ]
    assert len(bare_call) == 1
    assert bare_call[0].confidence == "INFERRED"
    assert bare_call[0].confidence_score == 0.5


# ── Barrel import → INFERRED/0.8 ──────────────────────────────────


def test_barrel_import_is_inferred(tmp_path: Path):
    """Import through __init__.py barrel has confidence=INFERRED, score=0.8."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/sub/__init__.py": "from .mod import helper\n",
        "pkg/sub/mod.py": "def helper(): pass\n",
        "pkg/a.py": "from .sub import helper\n",
    })
    _, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")
    imports = _import_edges(edges)
    barrel = [
        e for e in imports
        if e.src_id == "file:pkg/a.py"
        and "sub/__init__" in e.dst_id
    ]
    assert len(barrel) == 1
    assert barrel[0].confidence == "INFERRED"
    assert barrel[0].confidence_score == 0.8


# ── Direct relative import → EXTRACTED/1.0 ────────────────────────


def test_direct_relative_import_is_extracted(tmp_path: Path):
    """Direct relative import resolving to .py has confidence=EXTRACTED, score=1.0."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "from .b import helper\n",
        "pkg/b.py": "def helper(): pass\n",
    })
    _, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")
    imports = _import_edges(edges)
    direct = [
        e for e in imports
        if e.src_id == "file:pkg/a.py"
        and e.dst_id == "file:pkg/b.py"
    ]
    assert len(direct) == 1
    assert direct[0].confidence == "EXTRACTED"
    assert direct[0].confidence_score == 1.0


# ── ResolveResult ──────────────────────────────────────────────────


def test_resolve_result_namedtuple():
    """ResolveResult is a NamedTuple with path and strategy."""
    rr = ResolveResult("foo.py", "direct")
    assert rr.path == "foo.py"
    assert rr.strategy == "direct"
    assert rr[0] == "foo.py"
    assert rr[1] == "direct"
