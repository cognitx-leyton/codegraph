"""LLM-powered semantic extraction of concepts, decisions, and rationale.

Uses the Anthropic Python SDK to call Claude for document analysis.
All extracted nodes are tagged ``extracted_by="claude"`` and edges carry
``confidence="INFERRED"`` to distinguish them from deterministic AST
extraction.

Requires the ``[semantic]`` extra: ``pip install "codegraph[semantic]"``.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from .schema import (
    DOCUMENTS_CONCEPT,
    DECIDES,
    JUSTIFIES,
    ConceptNode,
    DecisionNode,
    Edge,
    RationaleNode,
)

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

PROMPT_VERSION = "1"

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "semantic" / "extract.md"

_MAX_CONTENT_CHARS = 100_000


# ── Result dataclass ─────────────────────────────────────────────────

@dataclass
class SemanticResult:
    concepts: list[ConceptNode] = field(default_factory=list)
    decisions: list[DecisionNode] = field(default_factory=list)
    rationales: list[RationaleNode] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


# ── Cache ────────────────────────────────────────────────────────────

def _semantic_cache_key(content: str, rel: str = "", repo_name: str = "") -> str:
    """SHA256 of content + NUL + rel + NUL + repo_name + NUL + PROMPT_VERSION.

    Including ``rel`` and ``repo_name`` prevents cache hits when the same
    content appears at different paths or in different repos (the extracted
    nodes embed these in their IDs).
    """
    h = hashlib.sha256()
    h.update(content.encode("utf-8"))
    h.update(b"\x00")
    h.update(rel.encode("utf-8"))
    h.update(b"\x00")
    h.update(repo_name.encode("utf-8"))
    h.update(b"\x00")
    h.update(PROMPT_VERSION.encode("utf-8"))
    return h.hexdigest()


class SemanticCache:
    """Disk cache at ``.codegraph-cache/semantic/`` for semantic results."""

    def __init__(self, repo: Path) -> None:
        self.cache_dir = repo / ".codegraph-cache" / "semantic"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def cache_key(content: str, rel: str, repo_name: str) -> str:
        """Compute the cache key for a given content + path + repo."""
        return _semantic_cache_key(content, rel, repo_name)

    def get(self, key: str) -> SemanticResult | None:
        entry = self.cache_dir / f"{key}.json"
        if not entry.exists():
            return None
        try:
            d = json.loads(entry.read_text(encoding="utf-8"))
            return _result_from_dict(d)
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            return None

    def put(self, key: str, result: SemanticResult) -> None:
        entry = self.cache_dir / f"{key}.json"
        tmp = entry.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(_result_to_dict(result)), encoding="utf-8")
            os.replace(tmp, entry)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise


# ── Serialisation ────────────────────────────────────────────────────

def _result_to_dict(result: SemanticResult) -> dict:
    return {
        "concepts": [
            dict(name=c.name, description=c.description,
                 source_file=c.source_file, extracted_by=c.extracted_by,
                 repo=c.repo)
            for c in result.concepts
        ],
        "decisions": [
            dict(title=d.title, context=d.context, status=d.status,
                 source_file=d.source_file, markdown_line=d.markdown_line,
                 extracted_by=d.extracted_by, repo=d.repo)
            for d in result.decisions
        ],
        "rationales": [
            dict(text=r.text, decision_title=r.decision_title,
                 source_file=r.source_file, rationale_index=r.rationale_index,
                 extracted_by=r.extracted_by, repo=r.repo)
            for r in result.rationales
        ],
        "edges": [
            dict(kind=e.kind, src_id=e.src_id, dst_id=e.dst_id,
                 props=e.props, confidence=e.confidence,
                 confidence_score=e.confidence_score)
            for e in result.edges
        ],
    }


def _result_from_dict(d: dict) -> SemanticResult:
    concepts = [ConceptNode(**c) for c in d.get("concepts", [])]
    decisions = [DecisionNode(**dec) for dec in d.get("decisions", [])]
    rationales = [RationaleNode(**r) for r in d.get("rationales", [])]
    edges = [Edge(**e) for e in d.get("edges", [])]
    return SemanticResult(
        concepts=concepts, decisions=decisions,
        rationales=rationales, edges=edges,
    )


# ── Extraction ───────────────────────────────────────────────────────

def extract_semantic(
    md_text: str,
    rel: str,
    repo_name: str = "default",
    *,
    client: object | None = None,
) -> SemanticResult:
    """Extract concepts, decisions, and rationale from markdown text.

    Parameters
    ----------
    md_text:
        Raw markdown content.
    rel:
        Repo-relative path of the source file.
    repo_name:
        Repository namespace.
    client:
        Optional pre-built ``anthropic.Anthropic`` instance (for testing).

    Raises
    ------
    ImportError
        If the ``anthropic`` package is not installed.
    """
    if anthropic is None:
        raise ImportError(
            "Install the [semantic] extra: pip install 'codegraph[semantic]'"
        )

    if client is None:
        client = anthropic.Anthropic()

    prompt_template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    truncated = md_text[:_MAX_CONTENT_CHARS]
    prompt = prompt_template.replace("$CONTENT", truncated)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
    except Exception as exc:
        log.warning("Claude API call failed for %s: %s", rel, exc)
        return SemanticResult()

    return _parse_response(text, rel, repo_name)


def _parse_response(text: str, rel: str, repo_name: str) -> SemanticResult:
    """Parse Claude's JSON response into typed nodes and edges."""
    # Strip markdown fences if present.
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # Remove opening fence (with optional language tag).
        nl_pos = cleaned.find("\n")
        if nl_pos == -1:
            # Degenerate: just "```" with no newline — nothing useful inside.
            return SemanticResult()
        cleaned = cleaned[nl_pos + 1:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        log.warning("Malformed JSON from Claude for %s: %s", rel, exc)
        return SemanticResult()

    if not isinstance(data, dict):
        log.warning("Expected dict from Claude for %s, got %s", rel, type(data).__name__)
        return SemanticResult()

    concepts: list[ConceptNode] = []
    for c in data.get("concepts", []):
        if not isinstance(c, dict) or "name" not in c:
            continue
        if not str(c["name"]).strip():
            continue
        concepts.append(ConceptNode(
            name=c["name"],
            description=c.get("description", ""),
            source_file=rel,
            repo=repo_name,
        ))

    decisions: list[DecisionNode] = []
    for d in data.get("decisions", []):
        if not isinstance(d, dict) or "title" not in d:
            continue
        if not str(d["title"]).strip():
            continue
        decisions.append(DecisionNode(
            title=d["title"],
            context=d.get("context", ""),
            status=d.get("status", "proposed"),
            source_file=rel,
            repo=repo_name,
        ))

    rationales: list[RationaleNode] = []
    _rationale_counts: dict[str, int] = {}  # decision_title -> next index
    for r in data.get("rationales", []):
        if not isinstance(r, dict) or "text" not in r or "decision_title" not in r:
            continue
        dt = r["decision_title"]
        idx = _rationale_counts.get(dt, 0)
        _rationale_counts[dt] = idx + 1
        rationales.append(RationaleNode(
            text=r["text"],
            decision_title=dt,
            source_file=rel,
            rationale_index=idx,
            repo=repo_name,
        ))

    # Build edges.
    edges: list[Edge] = []

    # DOCUMENTS_CONCEPT: Document -> Concept
    doc_id = f"doc:{repo_name}:{rel}"
    for concept in concepts:
        score = _get_score(data, "concepts", concept.name)
        edges.append(Edge(
            kind=DOCUMENTS_CONCEPT,
            src_id=doc_id,
            dst_id=concept.id,
            confidence="INFERRED",
            confidence_score=score,
        ))

    # DECIDES: Document -> Decision
    for decision in decisions:
        score = _get_score(data, "decisions", decision.title)
        edges.append(Edge(
            kind=DECIDES,
            src_id=doc_id,
            dst_id=decision.id,
            confidence="INFERRED",
            confidence_score=score,
        ))

    # JUSTIFIES: Rationale -> Decision
    decision_by_title = {d.title: d for d in decisions}
    raw_rationales = [r for r in data.get("rationales", [])
                      if isinstance(r, dict) and "text" in r and "decision_title" in r]
    for i, rationale in enumerate(rationales):
        target = decision_by_title.get(rationale.decision_title)
        if target is None:
            continue
        score = _get_score_by_index(raw_rationales, i)
        edges.append(Edge(
            kind=JUSTIFIES,
            src_id=rationale.id,
            dst_id=target.id,
            confidence="INFERRED",
            confidence_score=score,
        ))

    return SemanticResult(
        concepts=concepts, decisions=decisions,
        rationales=rationales, edges=edges,
    )


def _get_score(data: dict, category: str, name: str) -> float:
    """Look up the confidence_score from the raw Claude response, default 0.7."""
    key = "name" if category == "concepts" else "title"
    for item in data.get(category, []):
        if isinstance(item, dict) and item.get(key) == name:
            return _clamp_score(item.get("confidence_score", 0.7))
    return 0.7


def _get_score_by_index(raw_items: list[dict], index: int) -> float:
    """Look up confidence_score by position in the raw list, default 0.7."""
    if 0 <= index < len(raw_items):
        return _clamp_score(raw_items[index].get("confidence_score", 0.7))
    return 0.7


def _clamp_score(value: object) -> float:
    """Clamp a value to [0.0, 1.0], defaulting to 0.7 on bad input."""
    import math
    try:
        score = float(value)  # type: ignore[arg-type]
        if math.isnan(score) or math.isinf(score):
            return 0.7
        return max(0.0, min(1.0, score))
    except (ValueError, TypeError):
        return 0.7
