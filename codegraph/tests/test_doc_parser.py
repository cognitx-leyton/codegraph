"""Tests for :mod:`codegraph.doc_parser`.

Uses the 3-page PDF fixture at ``tests/fixtures/docs/sample.pdf`` which has
an outline with three chapter bookmarks.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

pypdf = pytest.importorskip("pypdf")

from codegraph import doc_parser
from codegraph.doc_parser import extract_pdf
from codegraph.schema import DocumentNode, DocumentSectionNode

FIXTURE = Path(__file__).parent / "fixtures" / "docs" / "sample.pdf"


# ── Basic extraction ──────────────────────────────────────────────────


def test_extract_pdf_basic():
    doc, sections = extract_pdf(FIXTURE, "docs/sample.pdf")
    assert isinstance(doc, DocumentNode)
    assert doc.file_type == "pdf"
    assert doc.path == "docs/sample.pdf"
    assert doc.loc > 0


def test_extract_pdf_sections():
    doc, sections = extract_pdf(FIXTURE, "docs/sample.pdf")
    assert len(sections) >= 3
    for sec in sections:
        assert isinstance(sec, DocumentSectionNode)
        assert sec.heading
        assert len(sec.text_sample) <= 500


def test_extract_pdf_section_index_sequential():
    _, sections = extract_pdf(FIXTURE, "docs/sample.pdf")
    indices = [s.section_index for s in sections]
    assert indices == list(range(len(sections)))


# ── ID format ─────────────────────────────────────────────────────────


def test_extract_pdf_id_format():
    doc, sections = extract_pdf(FIXTURE, "docs/sample.pdf")
    assert doc.id.startswith("doc:default:")
    for sec in sections:
        assert sec.id.startswith("docsec:default:")


def test_extract_pdf_repo_name():
    doc, sections = extract_pdf(FIXTURE, "docs/sample.pdf", repo_name="myrepo")
    assert "myrepo" in doc.id
    for sec in sections:
        assert "myrepo" in sec.id


# ── Edge cases ────────────────────────────────────────────────────────


def test_extract_pdf_missing_pypdf(monkeypatch):
    monkeypatch.setattr(doc_parser, "pypdf", None)
    with pytest.raises(ImportError, match="Install the .docs. extra"):
        extract_pdf(FIXTURE, "docs/sample.pdf")


def test_extract_pdf_extracted_at_is_iso():
    doc, _ = extract_pdf(FIXTURE, "docs/sample.pdf")
    # Should parse without error as ISO 8601
    dt = datetime.fromisoformat(doc.extracted_at)
    assert dt.year >= 2025


def test_extract_pdf_size_guard(tmp_path):
    big = tmp_path / "big.pdf"
    big.write_bytes(b"\x00" * (50_000_001))
    with pytest.raises(ValueError, match="exceeds 50 MB"):
        extract_pdf(big, "big.pdf")


def test_extract_pdf_section_paths_match_doc():
    doc, sections = extract_pdf(FIXTURE, "docs/sample.pdf")
    for sec in sections:
        assert sec.path == doc.path
