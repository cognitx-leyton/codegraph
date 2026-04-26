"""Image content extraction via Claude vision API.

Sends PNG/JPG/WEBP images to Claude and extracts :Concept nodes with
ILLUSTRATES_CONCEPT edges.  All extracted nodes are tagged
``extracted_by="claude"`` and edges carry ``confidence="INFERRED"``.

Requires the ``[semantic]`` extra: ``pip install "codegraph[semantic]"``.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from pathlib import Path

from .schema import ConceptNode, Edge, ILLUSTRATES_CONCEPT
from .semantic_extract import SemanticResult

try:
    import anthropic
except ImportError:  # pragma: no cover
    anthropic = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

PROMPT_VERSION = "1"

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "semantic" / "vision.md"

_MAX_IMAGE_SIZE = 20_000_000  # 20 MB

IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp"})

_MEDIA_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


# ── Hashing ─────────────────────────────────────────────────────────

def _file_content_hash(path: Path) -> str:
    """Return the SHA256 hex digest of a file's raw bytes."""
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _vision_cache_key(file_hash: str, rel: str, repo_name: str) -> str:
    """SHA256 of file_hash + NUL + rel + NUL + repo_name + NUL + PROMPT_VERSION."""
    h = hashlib.sha256()
    h.update(file_hash.encode("utf-8"))
    h.update(b"\x00")
    h.update(rel.encode("utf-8"))
    h.update(b"\x00")
    h.update(repo_name.encode("utf-8"))
    h.update(b"\x00")
    h.update(PROMPT_VERSION.encode("utf-8"))
    return h.hexdigest()


# ── Extraction ──────────────────────────────────────────────────────

def extract_vision(
    image_path: Path,
    rel: str,
    repo_name: str = "default",
    *,
    client: object | None = None,
    context: str = "",
) -> SemanticResult:
    """Extract concepts from an image via Claude vision API.

    Parameters
    ----------
    image_path:
        Absolute path to the image file.
    rel:
        Repo-relative path of the image.
    repo_name:
        Repository namespace.
    client:
        Optional pre-built ``anthropic.Anthropic`` instance (for testing).
    context:
        Optional corpus context injected into the prompt template.

    Raises
    ------
    ImportError
        If the ``anthropic`` package is not installed.
    ValueError
        If the image exceeds ``_MAX_IMAGE_SIZE``.
    """
    if anthropic is None:
        raise ImportError(
            "Install the [semantic] extra: pip install 'codegraph[semantic]'"
        )

    file_size = image_path.stat().st_size
    if file_size > _MAX_IMAGE_SIZE:
        raise ValueError(
            f"Image {rel} is {file_size} bytes, exceeds {_MAX_IMAGE_SIZE} byte limit"
        )

    if client is None:
        client = anthropic.Anthropic()

    raw_bytes = image_path.read_bytes()
    b64_data = base64.b64encode(raw_bytes).decode("ascii")
    suffix = image_path.suffix.lower()
    media_type = _MEDIA_TYPES.get(suffix, "image/png")

    prompt_template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    prompt = prompt_template.replace("$CONTEXT", context)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }],
        )
        text = response.content[0].text
    except Exception as exc:
        log.warning("Claude vision API call failed for %s: %s", rel, exc)
        return SemanticResult()

    return _parse_vision_response(text, rel, repo_name)


def _parse_vision_response(
    text: str, rel: str, repo_name: str,
) -> SemanticResult:
    """Parse Claude's JSON response into ConceptNodes and ILLUSTRATES_CONCEPT edges."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        nl_pos = cleaned.find("\n")
        if nl_pos == -1:
            return SemanticResult()
        cleaned = cleaned[nl_pos + 1:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        log.warning("Malformed JSON from Claude vision for %s: %s", rel, exc)
        return SemanticResult()

    if not isinstance(data, dict):
        log.warning("Expected dict from Claude vision for %s, got %s", rel, type(data).__name__)
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

    edges: list[Edge] = []
    doc_id = f"doc:{repo_name}:{rel}"
    for concept in concepts:
        score = _get_vision_score(data, concept.name)
        edges.append(Edge(
            kind=ILLUSTRATES_CONCEPT,
            src_id=doc_id,
            dst_id=concept.id,
            confidence="INFERRED",
            confidence_score=score,
        ))

    return SemanticResult(concepts=concepts, edges=edges)


def _get_vision_score(data: dict, name: str) -> float:
    """Look up confidence_score from the raw response, default 0.5 for vision."""
    for item in data.get("concepts", []):
        if isinstance(item, dict) and item.get("name") == name:
            return _clamp_score(item.get("confidence_score", 0.5))
    return 0.5


def _clamp_score(value: object) -> float:
    """Clamp a value to [0.0, 1.0], defaulting to 0.5 on bad input."""
    import math
    try:
        score = float(value)  # type: ignore[arg-type]
        if math.isnan(score) or math.isinf(score):
            return 0.5
        return max(0.0, min(1.0, score))
    except (ValueError, TypeError):
        return 0.5
