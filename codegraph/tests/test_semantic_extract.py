"""Tests for :mod:`codegraph.semantic_extract` with mocked Anthropic client."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from codegraph import semantic_extract
from codegraph.schema import (
    ConceptNode,
    DECIDES,
    DecisionNode,
    DOCUMENTS_CONCEPT,
    Edge,
    JUSTIFIES,
    RationaleNode,
)
from codegraph.semantic_extract import (
    SemanticCache,
    SemanticResult,
    _parse_response,
    _semantic_cache_key,
    extract_semantic,
)

# ── Mock Anthropic client ────────────────────────────────────────────

_MOCK_RESPONSE_JSON = json.dumps({
    "concepts": [
        {"name": "Graph Indexing", "description": "Walking a codebase with tree-sitter.", "confidence_score": 0.9},
        {"name": "Incremental Update", "description": "SHA256 skip unchanged.", "confidence_score": 0.8},
    ],
    "decisions": [
        {"title": "Use Neo4j", "context": "Need Cypher support.", "status": "accepted", "confidence_score": 0.95},
    ],
    "rationales": [
        {"text": "Neo4j is the most mature property graph.", "decision_title": "Use Neo4j", "confidence_score": 0.85},
    ],
})


class _MockContent:
    def __init__(self, text: str):
        self.text = text


class _MockResponse:
    def __init__(self, text: str):
        self.content = [_MockContent(text)]


class _MockMessages:
    def __init__(self, response_text: str):
        self._text = response_text
        self.call_count = 0

    def create(self, **kwargs):
        self.call_count += 1
        return _MockResponse(self._text)


class MockAnthropicClient:
    def __init__(self, response_text: str = _MOCK_RESPONSE_JSON):
        self.messages = _MockMessages(response_text)


# ── extract_semantic tests ────────────────────────────────────────────


def test_extract_semantic_basic():
    client = MockAnthropicClient()
    result = extract_semantic("# Heading\nSome content", "docs/test.md", client=client)
    assert len(result.concepts) == 2
    assert len(result.decisions) == 1
    assert len(result.rationales) == 1
    assert all(isinstance(c, ConceptNode) for c in result.concepts)
    assert all(isinstance(d, DecisionNode) for d in result.decisions)
    assert all(isinstance(r, RationaleNode) for r in result.rationales)


def test_extract_semantic_all_edges_inferred():
    client = MockAnthropicClient()
    result = extract_semantic("# Test\nContent", "docs/test.md", client=client)
    for edge in result.edges:
        assert edge.confidence == "INFERRED"
        assert 0.0 <= edge.confidence_score <= 1.0


def test_extract_semantic_justifies_edges():
    client = MockAnthropicClient()
    result = extract_semantic("# Test\nContent", "docs/test.md", client=client)
    justifies = [e for e in result.edges if e.kind == JUSTIFIES]
    assert len(justifies) == 1
    # Rationale -> Decision
    assert justifies[0].src_id == result.rationales[0].id
    assert justifies[0].dst_id == result.decisions[0].id


def test_extract_semantic_documents_concept_edges():
    client = MockAnthropicClient()
    result = extract_semantic("# Test\nContent", "docs/test.md", client=client)
    doc_concept = [e for e in result.edges if e.kind == DOCUMENTS_CONCEPT]
    assert len(doc_concept) == 2
    for edge in doc_concept:
        assert edge.src_id == "doc:default:docs/test.md"


def test_extract_semantic_decides_edges():
    client = MockAnthropicClient()
    result = extract_semantic("# Test\nContent", "docs/test.md", client=client)
    decides = [e for e in result.edges if e.kind == DECIDES]
    assert len(decides) == 1
    assert decides[0].src_id == "doc:default:docs/test.md"
    assert decides[0].dst_id == result.decisions[0].id


def test_extract_semantic_cache_hit(tmp_path):
    cache = SemanticCache(tmp_path)
    client = MockAnthropicClient()
    content = "# Cached\nContent"
    rel = "docs/test.md"
    result1 = extract_semantic(content, rel, client=client)
    key = _semantic_cache_key(content, rel, "default")
    cache.put(key, result1)

    # Second retrieval from cache — no API call
    cached = cache.get(key)
    assert cached is not None
    assert len(cached.concepts) == len(result1.concepts)
    assert len(cached.decisions) == len(result1.decisions)
    assert client.messages.call_count == 1


def test_extract_semantic_cache_miss_on_content_change(tmp_path):
    cache = SemanticCache(tmp_path)
    client = MockAnthropicClient()
    rel = "docs/test.md"
    content1 = "# Version 1\nContent"
    content2 = "# Version 2\nDifferent"
    result1 = extract_semantic(content1, rel, client=client)
    key1 = _semantic_cache_key(content1, rel, "default")
    cache.put(key1, result1)

    key2 = _semantic_cache_key(content2, rel, "default")
    assert key1 != key2
    assert cache.get(key2) is None


def test_extract_semantic_missing_anthropic(monkeypatch):
    monkeypatch.setattr(semantic_extract, "anthropic", None)
    with pytest.raises(ImportError, match="Install the .semantic. extra"):
        extract_semantic("# Test", "docs/test.md")


def test_extract_semantic_empty_response():
    empty_json = json.dumps({"concepts": [], "decisions": [], "rationales": []})
    client = MockAnthropicClient(response_text=empty_json)
    result = extract_semantic("# Empty doc", "docs/test.md", client=client)
    assert result.concepts == []
    assert result.decisions == []
    assert result.rationales == []
    assert result.edges == []


def test_extract_semantic_malformed_response(caplog):
    client = MockAnthropicClient(response_text="not json at all")
    with caplog.at_level(logging.WARNING):
        result = extract_semantic("# Bad", "docs/test.md", client=client)
    assert result.concepts == []
    assert result.decisions == []
    assert result.rationales == []
    assert "Malformed JSON" in caplog.text


def test_extract_semantic_deterministic_rerun(tmp_path):
    cache = SemanticCache(tmp_path)
    client = MockAnthropicClient()
    rel = "docs/test.md"
    content = "# Deterministic\nSame content"
    r1 = extract_semantic(content, rel, client=client)
    key = _semantic_cache_key(content, rel, "default")
    cache.put(key, r1)
    r2 = cache.get(key)
    assert r2 is not None
    assert len(r2.concepts) == len(r1.concepts)
    assert len(r2.edges) == len(r1.edges)


def test_cache_put_concurrent_writers_do_not_share_tmp(tmp_path, monkeypatch):
    """A second writer finishing inside the first writer's window must not break it."""
    cache = SemanticCache(tmp_path)
    key = _semantic_cache_key("# Race\nContent", "docs/test.md", "default")
    first = SemanticResult(concepts=[
        ConceptNode(name="first", description="", source_file="docs/test.md"),
    ])
    second = SemanticResult(concepts=[
        ConceptNode(name="second", description="", source_file="docs/test.md"),
    ])
    real_replace = os.replace
    tmp_dirs: list[Path] = []
    competitor_ran: list[bool] = []

    def replace_after_competitor(src, dst):
        tmp_dirs.append(Path(src).parent)
        if not competitor_ran:
            competitor_ran.append(True)
            cache.put(key, second)
        real_replace(src, dst)

    monkeypatch.setattr(semantic_extract.os, "replace", replace_after_competitor)
    cache.put(key, first)

    assert tmp_dirs == [cache.cache_dir, cache.cache_dir]
    got = cache.get(key)
    assert got is not None
    assert [c.name for c in got.concepts] == ["first"]
    assert list(cache.cache_dir.glob("*.tmp")) == []


def test_cache_put_removes_tmp_when_replace_fails(tmp_path, monkeypatch):
    cache = SemanticCache(tmp_path)

    def failing_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(semantic_extract.os, "replace", failing_replace)
    with pytest.raises(OSError, match="disk full"):
        cache.put("a" * 64, SemanticResult())
    assert list(cache.cache_dir.iterdir()) == []


# ── _parse_response tests ────────────────────────────────────────────


def test_parse_response_concepts():
    result = _parse_response(_MOCK_RESPONSE_JSON, "docs/test.md", "default")
    assert len(result.concepts) == 2
    assert result.concepts[0].name == "Graph Indexing"
    assert result.concepts[0].source_file == "docs/test.md"
    assert result.concepts[0].repo == "default"


def test_parse_response_decisions():
    result = _parse_response(_MOCK_RESPONSE_JSON, "docs/test.md", "default")
    assert len(result.decisions) == 1
    assert result.decisions[0].title == "Use Neo4j"
    assert result.decisions[0].status == "accepted"


def test_parse_response_rationales():
    result = _parse_response(_MOCK_RESPONSE_JSON, "docs/test.md", "default")
    assert len(result.rationales) == 1
    assert result.rationales[0].decision_title == "Use Neo4j"
    assert "most mature" in result.rationales[0].text


def test_parse_response_rationale_index():
    """Multiple rationales for the same decision get sequential indices."""
    data = json.dumps({
        "concepts": [],
        "decisions": [{"title": "Use Neo4j", "context": "ctx", "status": "accepted", "confidence_score": 0.9}],
        "rationales": [
            {"text": "Reason A", "decision_title": "Use Neo4j", "confidence_score": 0.8},
            {"text": "Reason B", "decision_title": "Use Neo4j", "confidence_score": 0.7},
        ],
    })
    result = _parse_response(data, "docs/test.md", "default")
    assert len(result.rationales) == 2
    assert result.rationales[0].rationale_index == 0
    assert result.rationales[1].rationale_index == 1
    # IDs must differ
    assert result.rationales[0].id != result.rationales[1].id


def test_parse_response_degenerate_fence():
    """A response that is just '```' with no newline should not crash."""
    result = _parse_response("```", "docs/test.md", "default")
    assert result.concepts == []
    assert result.decisions == []


def test_cache_key_includes_rel_and_repo():
    """Same content at different paths or repos produces different cache keys."""
    k1 = _semantic_cache_key("hello", "a.md", "repo1")
    k2 = _semantic_cache_key("hello", "b.md", "repo1")
    k3 = _semantic_cache_key("hello", "a.md", "repo2")
    assert k1 != k2
    assert k1 != k3
