"""Tests for :mod:`codegraph.cache` — SHA256 hashing, AstCache round-trips, manifest."""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.cache import AstCache, file_content_hash
from codegraph.schema import (
    ClassNode,
    Edge,
    FileNode,
    FunctionNode,
    ImportSpec,
    MethodNode,
    ParseResult,
    parse_result_from_dict,
    parse_result_to_dict,
)


# ── file_content_hash ──────────────────────────────────────────────


def test_file_content_hash_deterministic(tmp_path: Path) -> None:
    f = tmp_path / "a.py"
    f.write_text("hello", encoding="utf-8")
    h1 = file_content_hash(f, tmp_path)
    h2 = file_content_hash(f, tmp_path)
    assert h1 == h2

    f.write_text("world", encoding="utf-8")
    h3 = file_content_hash(f, tmp_path)
    assert h3 != h1


def test_file_content_hash_includes_path(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("same", encoding="utf-8")
    b.write_text("same", encoding="utf-8")
    assert file_content_hash(a, tmp_path) != file_content_hash(b, tmp_path)


def test_file_content_hash_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        file_content_hash(tmp_path / "nonexistent.py", tmp_path)


# ── AstCache ───────────────────────────────────────────────────────


def _make_parse_result(path: str = "a.py") -> ParseResult:
    fn = FileNode(path=path, package="p", language="py", loc=10, is_test=False)
    cls = ClassNode(name="Foo", file=path, is_abstract=True)
    func = FunctionNode(name="bar", file=path, exported=True, docstring="doc")
    method = MethodNode(name="baz", class_id=f"class:{path}#Foo", file=path, is_async=True)
    imp = ImportSpec(specifier="os", symbols=["path"])
    edge = Edge(kind="CALLS", src_id="method:a.py#Foo#baz", dst_id="func:a.py#bar")
    return ParseResult(
        file=fn,
        classes=[cls],
        functions=[func],
        methods=[method],
        imports=[imp],
        edges=[edge],
        class_extends=[("Foo", "Base")],
        method_calls=[("m1", "this", "self", "do_thing")],
        described_subjects=["Foo"],
        env_reads=["HOME"],
    )


def test_cache_put_get_round_trip(tmp_path: Path) -> None:
    cache = AstCache(tmp_path)
    pr = _make_parse_result()
    cache.put("a.py", "abc123", pr)
    got = cache.get("a.py", "abc123")
    assert got is not None
    assert got.file.path == pr.file.path
    assert got.file.loc == pr.file.loc
    assert len(got.classes) == 1
    assert got.classes[0].name == "Foo"
    assert got.classes[0].is_abstract is True
    assert len(got.functions) == 1
    assert got.functions[0].docstring == "doc"
    assert len(got.methods) == 1
    assert got.methods[0].is_async is True
    assert len(got.imports) == 1
    assert got.imports[0].symbols == ["path"]
    assert len(got.edges) == 1
    assert got.edges[0].kind == "CALLS"
    assert got.class_extends == [("Foo", "Base")]
    assert got.method_calls == [("m1", "this", "self", "do_thing")]
    assert got.described_subjects == ["Foo"]
    assert got.env_reads == ["HOME"]


def test_cache_get_miss_returns_none(tmp_path: Path) -> None:
    cache = AstCache(tmp_path)
    assert cache.get("a.py", "nonexistent") is None


def test_cache_get_no_file_returns_none(tmp_path: Path) -> None:
    cache = AstCache(tmp_path)
    assert cache.get("a.py", "anything") is None


def test_cache_get_corrupt_file_returns_none(tmp_path: Path) -> None:
    cache = AstCache(tmp_path)
    corrupt = cache.cache_dir / "badhash.json"
    corrupt.write_text("NOT VALID JSON {{{", encoding="utf-8")
    assert cache.get("a.py", "badhash") is None


def test_cache_clear_removes_all(tmp_path: Path) -> None:
    cache = AstCache(tmp_path)
    cache.put("a.py", "h1", _make_parse_result("a.py"))
    cache.put("b.py", "h2", _make_parse_result("b.py"))
    cache.save_manifest({"a.py": "h1", "b.py": "h2"})
    cache.clear()
    assert cache.get("a.py", "h1") is None
    assert cache.get("b.py", "h2") is None
    assert cache.load_manifest() == {}


# ── Manifest ───────────────────────────────────────────────────────


def test_manifest_save_load_round_trip(tmp_path: Path) -> None:
    cache = AstCache(tmp_path)
    manifest = {"a.py": "abc123", "b.py": "def456"}
    cache.save_manifest(manifest)
    assert cache.load_manifest() == manifest


def test_manifest_missing_returns_empty(tmp_path: Path) -> None:
    cache = AstCache(tmp_path)
    assert cache.load_manifest() == {}


def test_manifest_version_mismatch_returns_empty(tmp_path: Path) -> None:
    """If manifest was written by a different codegraph version, treat as empty."""
    import json
    cache = AstCache(tmp_path)
    cache.manifest_path.write_text(
        json.dumps({"version": "0.0.0-fake", "files": {"a.py": "abc"}}),
        encoding="utf-8",
    )
    assert cache.load_manifest() == {}


def test_manifest_legacy_flat_dict_returns_empty(tmp_path: Path) -> None:
    """Pre-versioned manifests (flat dict) are treated as empty on load."""
    import json
    cache = AstCache(tmp_path)
    cache.manifest_path.write_text(
        json.dumps({"a.py": "abc"}),
        encoding="utf-8",
    )
    assert cache.load_manifest() == {}


# ── Pruning ───────────────────────────────────────────────────────


def test_prune_stale_removes_orphaned_entries(tmp_path: Path) -> None:
    cache = AstCache(tmp_path)
    cache.put("a.py", "h1", _make_parse_result("a.py"))
    cache.put("b.py", "h2", _make_parse_result("b.py"))
    cache.put("b.py", "h3", _make_parse_result("b.py"))

    old = {"a.py": "h1", "b.py": "h2"}
    new = {"a.py": "h1", "b.py": "h3"}
    assert cache.prune_stale(old, new) == 1
    assert (cache.cache_dir / "h1.json").exists()
    assert not (cache.cache_dir / "h2.json").exists()
    assert (cache.cache_dir / "h3.json").exists()


def test_prune_stale_no_op_when_nothing_changed(tmp_path: Path) -> None:
    cache = AstCache(tmp_path)
    cache.put("a.py", "h1", _make_parse_result("a.py"))

    manifest = {"a.py": "h1"}
    assert cache.prune_stale(manifest, manifest) == 0
    assert (cache.cache_dir / "h1.json").exists()


def test_prune_stale_tolerates_missing_file(tmp_path: Path) -> None:
    cache = AstCache(tmp_path)
    old = {"a.py": "h1"}
    new: dict[str, str] = {}
    assert cache.prune_stale(old, new) == 0


# ── ParseResult serialisation ─────────────────────────────────────


def test_parse_result_to_dict_from_dict_round_trip() -> None:
    pr = _make_parse_result()
    d = parse_result_to_dict(pr)
    reconstructed = parse_result_from_dict(d)

    assert reconstructed.file.path == pr.file.path
    assert reconstructed.file.package == pr.file.package
    assert len(reconstructed.classes) == len(pr.classes)
    assert reconstructed.classes[0].name == pr.classes[0].name
    assert len(reconstructed.functions) == len(pr.functions)
    assert len(reconstructed.methods) == len(pr.methods)
    assert len(reconstructed.imports) == len(pr.imports)
    assert len(reconstructed.edges) == len(pr.edges)
    assert reconstructed.class_extends == pr.class_extends
    assert reconstructed.method_calls == pr.method_calls
    assert reconstructed.described_subjects == pr.described_subjects
    assert reconstructed.env_reads == pr.env_reads


def test_parse_result_from_dict_missing_keys_uses_defaults() -> None:
    d = {"file": {"path": "x.py", "package": "p", "language": "py", "loc": 1}}
    pr = parse_result_from_dict(d)
    assert pr.file.path == "x.py"
    assert pr.classes == []
    assert pr.functions == []
    assert pr.methods == []
    assert pr.imports == []
    assert pr.edges == []
    assert pr.class_extends == []
    assert pr.described_subjects == []
    assert pr.env_reads == []
