"""Tests for :mod:`codegraph.schema` — _slug helper and node ID generation."""
from __future__ import annotations

import hashlib
import unicodedata

from codegraph.schema import ConceptNode, DecisionNode, RationaleNode, _slug


# ── _slug: ASCII passthrough ────────────────────────────────────────


def test_slug_ascii_passthrough():
    assert _slug("hello world") == "hello_world"


def test_slug_preserves_dots_and_dashes():
    assert _slug("file-name.v2") == "file-name.v2"


# ── _slug: accented transliteration ─────────────────────────────────


def test_slug_accented_transliteration():
    assert _slug("café") == "cafe"
    assert _slug("naïve résumé") == "naive_resume"


def test_slug_n_tilde():
    assert _slug("Ñoño") == "nono"


# ── _slug: hash fallback for purely non-ASCII ───────────────────────


def test_slug_cjk_hash_fallback():
    result = _slug("日本語のコンセプト")
    assert len(result) == 8
    assert all(c in "0123456789abcdef" for c in result)


def test_slug_empty_string_hash():
    result = _slug("")
    assert len(result) == 8
    assert all(c in "0123456789abcdef" for c in result)


def test_slug_whitespace_only_hash():
    result = _slug("   ")
    assert len(result) == 8
    assert all(c in "0123456789abcdef" for c in result)


# ── _slug: uniqueness and determinism ────────────────────────────────


def test_slug_different_cjk_inputs_differ():
    assert _slug("日本語") != _slug("中文")


def test_slug_deterministic():
    assert _slug("日本語") == _slug("日本語")


def test_slug_hash_matches_sha256_of_normalised():
    text = "日本語"
    normalised = unicodedata.normalize("NFKD", text)
    expected = hashlib.sha256(normalised.encode()).hexdigest()[:8]
    assert _slug(text) == expected


def test_slug_canonical_equivalence():
    """Precomposed and decomposed forms of the same character produce the same slug."""
    precomposed = "\u304C"  # が (single code point)
    decomposed = "\u304B\u3099"  # か + combining dakuten
    assert _slug(precomposed) == _slug(decomposed)


# ── _slug: no forbidden characters ──────────────────────────────────


def test_slug_no_forbidden_chars():
    inputs = [
        "hello world",
        "café",
        "日本語のコンセプト",
        "",
        "   ",
        "foo#bar:baz qux",
    ]
    for text in inputs:
        slug = _slug(text)
        assert "#" not in slug, f"slug({text!r}) = {slug!r} contains #"
        assert ":" not in slug, f"slug({text!r}) = {slug!r} contains :"
        assert " " not in slug, f"slug({text!r}) = {slug!r} contains space"


# ── Node ID integration ─────────────────────────────────────────────


def test_concept_node_id_accented():
    node = ConceptNode(name="café", description="x", source_file="f.md")
    assert "#cafe" in node.id


def test_concept_node_id_cjk():
    node = ConceptNode(name="日本語", description="x", source_file="f.md")
    normalised = unicodedata.normalize("NFKD", "日本語")
    expected_hash = hashlib.sha256(normalised.encode()).hexdigest()[:8]
    assert f"#{expected_hash}" in node.id


def test_decision_node_id_accented():
    node = DecisionNode(
        title="café decision", context="x", status="accepted", source_file="f.md"
    )
    assert "#cafe_decision" in node.id


def test_rationale_node_id_cjk():
    node = RationaleNode(text="x", decision_title="日本語", source_file="f.md")
    normalised = unicodedata.normalize("NFKD", "日本語")
    expected_hash = hashlib.sha256(normalised.encode()).hexdigest()[:8]
    assert f"#{expected_hash}_0" in node.id
