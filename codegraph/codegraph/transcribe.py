"""Audio/video transcription via faster-whisper.

Transcribes media files (WAV, MP3, MP4, etc.) via Whisper and produces
:class:`DocumentNode` instances with ``file_type="transcript"`` for loading
into Neo4j.  The transcript text can then feed into the semantic extraction
pipeline for concept/decision/rationale extraction.

URL-based downloads via ``yt-dlp`` are supported for YouTube and similar
sources.

Requires the ``[transcribe]`` extra:
``pip install "codegraph[transcribe]"``.
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from .schema import DocumentNode

try:
    import faster_whisper
except ImportError:  # pragma: no cover
    faster_whisper = None  # type: ignore[assignment]

try:
    import yt_dlp
except ImportError:  # pragma: no cover
    yt_dlp = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

_MAX_MEDIA_SIZE = 500_000_000  # 500 MB

AUDIO_EXTENSIONS = frozenset({
    ".wav", ".mp3", ".flac", ".ogg", ".m4a", ".wma", ".aac",
})

VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv",
})

MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS

_DEFAULT_MODEL = "base"


# ── Hashing / caching ─────────────────────────────────────────────

def _file_content_hash(path: Path) -> str:
    """Return the SHA256 hex digest of a file's raw bytes (chunked)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):  # 1 MB chunks
            h.update(chunk)
    return h.hexdigest()


def _transcript_cache_path(repo: Path, file_hash: str) -> Path:
    """Return the cache file path for a transcript."""
    return repo / ".codegraph-cache" / "transcripts" / f"{file_hash}.txt"


def _get_cached_transcript(repo: Path, file_hash: str) -> str | None:
    """Read cached transcript text, or *None* if not cached."""
    cache = _transcript_cache_path(repo, file_hash)
    if cache.is_file():
        return cache.read_text(encoding="utf-8")
    return None


def _put_cached_transcript(repo: Path, file_hash: str, text: str) -> None:
    """Write transcript text to cache (atomic via os.replace)."""
    cache = _transcript_cache_path(repo, file_hash)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, cache)


# ── Transcription ──────────────────────────────────────────────────

def load_model(model_size: str = _DEFAULT_MODEL):
    """Load a WhisperModel, auto-detecting the best device.

    Call once and pass the result to :func:`transcribe` via its *model*
    parameter to avoid reloading the model for every file.

    Raises
    ------
    ImportError
        If ``faster_whisper`` is not installed.
    """
    if faster_whisper is None:
        raise ImportError(
            "Install the [transcribe] extra: "
            "pip install 'codegraph[transcribe]'"
        )

    device = "cpu"
    compute_type = "int8"
    try:
        import ctranslate2
        if "cuda" in ctranslate2.get_supported_compute_types("cuda"):
            device = "cuda"
            compute_type = "float16"
    except Exception:
        log.debug("CUDA not available, falling back to CPU", exc_info=True)

    return faster_whisper.WhisperModel(
        model_size, device=device, compute_type=compute_type,
    )


def transcribe(
    path: Path,
    rel: str,
    repo_name: str = "default",
    *,
    initial_prompt: str = "",
    model_size: str = _DEFAULT_MODEL,
    model: object | None = None,
) -> tuple[DocumentNode, str]:
    """Transcribe *path* and return a document node + transcript text.

    Parameters
    ----------
    path:
        Absolute path to the media file on disk.
    rel:
        Repo-relative path (used as the node ``path`` field).
    repo_name:
        Repository namespace for multi-repo indexing.
    initial_prompt:
        Optional domain-aware prompt to improve Whisper accuracy.
    model_size:
        Whisper model size (``tiny``, ``base``, ``small``, ``medium``,
        ``large-v3``).  Ignored when *model* is provided.
    model:
        Pre-loaded :class:`faster_whisper.WhisperModel`.  When ``None``
        (the default), a new model is created — prefer passing one from
        :func:`load_model` when transcribing multiple files.

    Returns
    -------
    tuple
        ``(DocumentNode, str)`` — the document node and transcript text.

    Raises
    ------
    ImportError
        If ``faster_whisper`` is not installed.
    ValueError
        If the file exceeds the 500 MB size guard.
    """
    if faster_whisper is None:
        raise ImportError(
            "Install the [transcribe] extra: "
            "pip install 'codegraph[transcribe]'"
        )

    if path.stat().st_size > _MAX_MEDIA_SIZE:
        raise ValueError(
            f"{rel}: file exceeds 500 MB size limit "
            f"({path.stat().st_size / 1_000_000:.1f} MB)"
        )

    if model is None:
        model = load_model(model_size)

    segments, _info = model.transcribe(
        str(path),
        language="en",
        beam_size=5,
        vad_filter=True,
        initial_prompt=initial_prompt or None,
    )

    text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())

    doc = DocumentNode(
        path=rel,
        file_type="transcript",
        loc=len(text),
        extracted_at=datetime.now(timezone.utc).isoformat(),
        repo=repo_name,
    )
    return doc, text


# ── URL download ───────────────────────────────────────────────────

def download_audio(url: str, output_dir: Path) -> Path:
    """Download audio from *url* via yt-dlp and return the output path.

    Parameters
    ----------
    url:
        Video/audio URL (YouTube, etc.).
    output_dir:
        Directory where the downloaded WAV will be written.

    Returns
    -------
    Path
        Path to the downloaded audio file.

    Raises
    ------
    ImportError
        If ``yt_dlp`` is not installed.
    """
    if yt_dlp is None:
        raise ImportError(
            "Install the [transcribe] extra: "
            "pip install 'codegraph[transcribe]'"
        )

    outtmpl = str(output_dir / "%(id)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
        }],
        "outtmpl": outtmpl,
        "quiet": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        video_id = info["id"]

    result = output_dir / f"{video_id}.wav"
    if result.is_file():
        return result

    # yt-dlp may use a different extension; find the downloaded file.
    for candidate in output_dir.iterdir():
        if candidate.stem == video_id:
            return candidate

    raise FileNotFoundError(
        f"Downloaded audio not found for {url} in {output_dir}"
    )
