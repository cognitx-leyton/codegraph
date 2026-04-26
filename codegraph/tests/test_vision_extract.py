"""Tests for :mod:`codegraph.vision_extract` with mocked Anthropic client."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from codegraph import vision_extract
from codegraph.schema import ConceptNode, ILLUSTRATES_CONCEPT, Edge
from codegraph.vision_extract import (
    IMAGE_EXTENSIONS,
    _MAX_IMAGE_SIZE,
    _file_content_hash,
    _parse_vision_response,
    _vision_cache_key,
    extract_vision,
)
from codegraph.semantic_extract import SemanticCache, SemanticResult

# ── Fixture path ────────────────────────────────────────────────────

FIXTURE_PNG = Path(__file__).parent / "fixtures" / "images" / "sample.png"

# ── Mock Anthropic client ───────────────────────────────────────────

_MOCK_RESPONSE_JSON = json.dumps({
    "concepts": [
        {
            "name": "Microservice Architecture",
            "description": "A diagram showing service boundaries.",
            "confidence_score": 0.6,
        },
        {
            "name": "Load Balancer",
            "description": "Distributes traffic across service instances.",
            "confidence_score": 0.5,
        },
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


# ── extract_vision tests ───────────────────────────────────────────


def test_extract_vision_basic():
    client = MockAnthropicClient()
    result = extract_vision(FIXTURE_PNG, "docs/arch.png", client=client)
    assert len(result.concepts) >= 1
    assert all(isinstance(c, ConceptNode) for c in result.concepts)


def test_extract_vision_illustrates_concept_edge():
    client = MockAnthropicClient()
    result = extract_vision(FIXTURE_PNG, "docs/arch.png", client=client)
    illustrates = [e for e in result.edges if e.kind == ILLUSTRATES_CONCEPT]
    assert len(illustrates) >= 1


def test_extract_vision_edge_confidence():
    client = MockAnthropicClient()
    result = extract_vision(FIXTURE_PNG, "docs/arch.png", client=client)
    for edge in result.edges:
        assert edge.confidence == "INFERRED"
        assert 0.0 <= edge.confidence_score <= 1.0


def test_extract_vision_document_source_id():
    client = MockAnthropicClient()
    result = extract_vision(FIXTURE_PNG, "docs/arch.png", repo_name="myrepo", client=client)
    for edge in result.edges:
        assert edge.src_id == "doc:myrepo:docs/arch.png"


def test_extract_vision_concept_extracted_by():
    client = MockAnthropicClient()
    result = extract_vision(FIXTURE_PNG, "docs/arch.png", client=client)
    for concept in result.concepts:
        assert concept.extracted_by == "claude"


def test_extract_vision_cache_roundtrip(tmp_path):
    cache = SemanticCache(tmp_path)
    client = MockAnthropicClient()
    result = extract_vision(FIXTURE_PNG, "docs/arch.png", client=client)

    fhash = _file_content_hash(FIXTURE_PNG)
    key = _vision_cache_key(fhash, "docs/arch.png", "default")
    cache.put(key, result)

    cached = cache.get(key)
    assert cached is not None
    assert len(cached.concepts) == len(result.concepts)
    assert len(cached.edges) == len(result.edges)


def test_extract_vision_cache_miss_on_content_change(tmp_path):
    k1 = _vision_cache_key("hash_a", "docs/arch.png", "default")
    k2 = _vision_cache_key("hash_b", "docs/arch.png", "default")
    assert k1 != k2


def test_extract_vision_missing_anthropic(monkeypatch):
    monkeypatch.setattr(vision_extract, "anthropic", None)
    with pytest.raises(ImportError, match="Install the .semantic. extra"):
        extract_vision(FIXTURE_PNG, "docs/arch.png")


def test_extract_vision_empty_response():
    empty_json = json.dumps({"concepts": []})
    client = MockAnthropicClient(response_text=empty_json)
    result = extract_vision(FIXTURE_PNG, "docs/arch.png", client=client)
    assert result.concepts == []
    assert result.edges == []


def test_extract_vision_malformed_response(caplog):
    client = MockAnthropicClient(response_text="not json at all")
    with caplog.at_level(logging.WARNING):
        result = extract_vision(FIXTURE_PNG, "docs/arch.png", client=client)
    assert result.concepts == []
    assert result.edges == []
    assert "Malformed JSON" in caplog.text


def test_extract_vision_file_too_large(tmp_path):
    big_file = tmp_path / "huge.png"
    # Write a file header that looks like PNG but is over the size limit.
    # We just need it to exist and be big; vision_extract checks size before reading.
    big_file.write_bytes(b"\x89PNG" + b"\x00" * (_MAX_IMAGE_SIZE + 1))
    with pytest.raises(ValueError, match="exceeds"):
        extract_vision(big_file, "huge.png")


def test_vision_cache_key_includes_rel_and_repo():
    k1 = _vision_cache_key("samehash", "a.png", "repo1")
    k2 = _vision_cache_key("samehash", "b.png", "repo1")
    k3 = _vision_cache_key("samehash", "a.png", "repo2")
    assert k1 != k2
    assert k1 != k3


def test_file_content_hash_deterministic():
    h1 = _file_content_hash(FIXTURE_PNG)
    h2 = _file_content_hash(FIXTURE_PNG)
    assert h1 == h2
    assert len(h1) == 64  # SHA256 hex digest


def test_extract_vision_media_type_detection():
    """Verify correct media type mapping for supported extensions."""
    from codegraph.vision_extract import _MEDIA_TYPES
    assert _MEDIA_TYPES[".png"] == "image/png"
    assert _MEDIA_TYPES[".jpg"] == "image/jpeg"
    assert _MEDIA_TYPES[".jpeg"] == "image/jpeg"
    assert _MEDIA_TYPES[".webp"] == "image/webp"


# ── _parse_vision_response tests ────────────────────────────────────


def test_parse_vision_response_concepts():
    result = _parse_vision_response(_MOCK_RESPONSE_JSON, "docs/arch.png", "default")
    assert len(result.concepts) == 2
    assert result.concepts[0].name == "Microservice Architecture"
    assert result.concepts[0].source_file == "docs/arch.png"
    assert result.concepts[0].repo == "default"


def test_parse_vision_response_edges():
    result = _parse_vision_response(_MOCK_RESPONSE_JSON, "docs/arch.png", "default")
    assert len(result.edges) == 2
    for edge in result.edges:
        assert edge.kind == ILLUSTRATES_CONCEPT
        assert edge.src_id == "doc:default:docs/arch.png"


def test_parse_vision_response_empty_name():
    """Concepts with blank names are skipped."""
    data = json.dumps({"concepts": [{"name": "", "description": "empty"}]})
    result = _parse_vision_response(data, "docs/arch.png", "default")
    assert result.concepts == []
    assert result.edges == []


def test_parse_vision_response_fenced():
    """Response wrapped in markdown fences is handled."""
    fenced = "```json\n" + _MOCK_RESPONSE_JSON + "\n```"
    result = _parse_vision_response(fenced, "docs/arch.png", "default")
    assert len(result.concepts) == 2
