"""Tests for :mod:`codegraph.transcribe` with mocked WhisperModel.

Uses the 1-second silence WAV fixture at ``tests/fixtures/audio/sample.wav``.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

faster_whisper = pytest.importorskip("faster_whisper")

from codegraph import transcribe as transcribe_mod
from codegraph.transcribe import (
    AUDIO_EXTENSIONS,
    MEDIA_EXTENSIONS,
    VIDEO_EXTENSIONS,
    _MAX_MEDIA_SIZE,
    _file_content_hash,
    _get_cached_transcript,
    _put_cached_transcript,
    download_audio,
    transcribe,
)
from codegraph.schema import DocumentNode

FIXTURE = Path(__file__).parent / "fixtures" / "audio" / "sample.wav"


# ── Mock WhisperModel ────────────────────────────────────────────────


class _MockSegment:
    def __init__(self, text: str, start: float = 0.0, end: float = 1.0):
        self.text = text
        self.start = start
        self.end = end


class _MockInfo:
    language = "en"
    language_probability = 0.99
    duration = 1.0


class _MockWhisperModel:
    call_count = 0

    def __init__(self, *args, **kwargs):
        pass

    def transcribe(self, audio, **kwargs):
        _MockWhisperModel.call_count += 1
        return iter([_MockSegment("hello world")]), _MockInfo()


class _CapturingWhisperModel:
    """Records kwargs passed to ``transcribe()`` for assertion."""
    last_kwargs: dict = {}

    def __init__(self, *args, **kwargs):
        pass

    def transcribe(self, audio, **kwargs):
        _CapturingWhisperModel.last_kwargs = dict(kwargs)
        return iter([_MockSegment("bonjour")]), _MockInfo()


# ── Basic transcription ──────────────────────────────────────────────


def test_transcribe_returns_document_node(monkeypatch):
    monkeypatch.setattr(transcribe_mod, "faster_whisper", type("M", (), {"WhisperModel": _MockWhisperModel})())
    doc, text = transcribe(FIXTURE, "audio/sample.wav")
    assert isinstance(doc, DocumentNode)
    assert doc.file_type == "transcript"


def test_transcribe_returns_text(monkeypatch):
    monkeypatch.setattr(transcribe_mod, "faster_whisper", type("M", (), {"WhisperModel": _MockWhisperModel})())
    doc, text = transcribe(FIXTURE, "audio/sample.wav")
    assert isinstance(text, str)
    assert len(text) > 0
    assert "hello world" in text


def test_transcribe_document_path(monkeypatch):
    monkeypatch.setattr(transcribe_mod, "faster_whisper", type("M", (), {"WhisperModel": _MockWhisperModel})())
    doc, _ = transcribe(FIXTURE, "audio/sample.wav")
    assert doc.path == "audio/sample.wav"


def test_transcribe_document_id_format(monkeypatch):
    monkeypatch.setattr(transcribe_mod, "faster_whisper", type("M", (), {"WhisperModel": _MockWhisperModel})())
    doc, _ = transcribe(FIXTURE, "audio/sample.wav")
    assert doc.id.startswith("doc:default:")


def test_transcribe_with_repo_name(monkeypatch):
    monkeypatch.setattr(transcribe_mod, "faster_whisper", type("M", (), {"WhisperModel": _MockWhisperModel})())
    doc, _ = transcribe(FIXTURE, "audio/sample.wav", repo_name="myrepo")
    assert "myrepo" in doc.id


def test_transcribe_loc_matches_text_length(monkeypatch):
    monkeypatch.setattr(transcribe_mod, "faster_whisper", type("M", (), {"WhisperModel": _MockWhisperModel})())
    doc, text = transcribe(FIXTURE, "audio/sample.wav")
    assert doc.loc == len(text)


def test_transcribe_extracted_at_is_iso(monkeypatch):
    monkeypatch.setattr(transcribe_mod, "faster_whisper", type("M", (), {"WhisperModel": _MockWhisperModel})())
    doc, _ = transcribe(FIXTURE, "audio/sample.wav")
    # Should not raise
    datetime.fromisoformat(doc.extracted_at)


# ── Guards ───────────────────────────────────────────────────────────


def test_transcribe_size_guard(monkeypatch, tmp_path):
    monkeypatch.setattr(transcribe_mod, "faster_whisper", type("M", (), {"WhisperModel": _MockWhisperModel})())
    big = tmp_path / "big.wav"
    big.write_bytes(b"\x00" * 100)
    # Lower the limit so even our tiny file exceeds it
    monkeypatch.setattr(transcribe_mod, "_MAX_MEDIA_SIZE", 10)
    with pytest.raises(ValueError, match="size limit"):
        transcribe(big, "big.wav")


def test_transcribe_missing_faster_whisper(monkeypatch):
    monkeypatch.setattr(transcribe_mod, "faster_whisper", None)
    with pytest.raises(ImportError, match=r"\[transcribe\]"):
        transcribe(FIXTURE, "audio/sample.wav")


def test_download_audio_missing_ytdlp(monkeypatch):
    monkeypatch.setattr(transcribe_mod, "yt_dlp", None)
    with pytest.raises(ImportError, match=r"\[transcribe\]"):
        download_audio("https://example.com/video", Path("/tmp"))


def _mock_yt_dlp(video_id: str):
    class _MockYoutubeDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=True):
            return {"id": video_id}

    return type("M", (), {"YoutubeDL": _MockYoutubeDL})()


@pytest.mark.parametrize("video_id", ["abc123", "a-b_c.d"])
def test_download_audio_returns_wav_for_plain_video_id(monkeypatch, tmp_path, video_id):
    (tmp_path / f"{video_id}.wav").write_bytes(b"RIFF")
    monkeypatch.setattr(transcribe_mod, "yt_dlp", _mock_yt_dlp(video_id))
    assert download_audio("https://example.com/v", tmp_path) == tmp_path / f"{video_id}.wav"


@pytest.mark.parametrize("video_id", ["../escape", "sub/clip"])
def test_download_audio_rejects_video_id_with_path_parts(monkeypatch, tmp_path, video_id):
    out = tmp_path / "out"
    (out / "sub").mkdir(parents=True)
    (out / "sub" / "clip.wav").write_bytes(b"RIFF")
    (tmp_path / "escape.wav").write_bytes(b"RIFF")
    monkeypatch.setattr(transcribe_mod, "yt_dlp", _mock_yt_dlp(video_id))
    with pytest.raises(ValueError, match="video id"):
        download_audio("https://example.com/v", out)


def test_download_audio_rejects_absolute_video_id(monkeypatch, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (tmp_path / "escape.wav").write_bytes(b"RIFF")
    monkeypatch.setattr(transcribe_mod, "yt_dlp", _mock_yt_dlp(str(tmp_path / "escape")))
    with pytest.raises(ValueError, match="video id"):
        download_audio("https://example.com/v", out)


def test_download_audio_rejects_symlink_leaving_output_dir(monkeypatch, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    target = tmp_path / "elsewhere.wav"
    target.write_bytes(b"RIFF")
    try:
        (out / "link.wav").symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks here")
    monkeypatch.setattr(transcribe_mod, "yt_dlp", _mock_yt_dlp("link"))
    with pytest.raises(ValueError, match="video id"):
        download_audio("https://example.com/v", out)


def test_download_audio_returns_other_extension_inside_output_dir(monkeypatch, tmp_path):
    (tmp_path / "clip.m4a").write_bytes(b"x")
    monkeypatch.setattr(transcribe_mod, "yt_dlp", _mock_yt_dlp("clip"))
    assert download_audio("https://example.com/v", tmp_path) == tmp_path / "clip.m4a"


def test_download_audio_skips_other_extension_that_leaves_output_dir(monkeypatch, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    target = tmp_path / "elsewhere.m4a"
    target.write_bytes(b"x")
    try:
        (out / "clip.m4a").symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks here")
    monkeypatch.setattr(transcribe_mod, "yt_dlp", _mock_yt_dlp("clip"))
    with pytest.raises(FileNotFoundError):
        download_audio("https://example.com/v", out)


# ── Caching ──────────────────────────────────────────────────────────


def test_transcript_cache_roundtrip(tmp_path):
    text = "this is a test transcript"
    _put_cached_transcript(tmp_path, "abc123", text)
    result = _get_cached_transcript(tmp_path, "abc123")
    assert result == text


def test_cache_miss_returns_none(tmp_path):
    result = _get_cached_transcript(tmp_path, "nonexistent")
    assert result is None


# ── Language forwarding (#281) ───────────────────────────────────────


def test_transcribe_forwards_language(monkeypatch):
    monkeypatch.setattr(transcribe_mod, "faster_whisper", type("M", (), {"WhisperModel": _CapturingWhisperModel})())
    _doc, _text = transcribe(FIXTURE, "audio/sample.wav", language="fr")
    assert _CapturingWhisperModel.last_kwargs["language"] == "fr"


def test_transcribe_default_language_is_none(monkeypatch):
    monkeypatch.setattr(transcribe_mod, "faster_whisper", type("M", (), {"WhisperModel": _CapturingWhisperModel})())
    _doc, _text = transcribe(FIXTURE, "audio/sample.wav")
    assert _CapturingWhisperModel.last_kwargs["language"] is None


# ── Cache isolation (#281, #292) ─────────────────────────────────────


def test_cache_key_includes_language(tmp_path):
    _put_cached_transcript(tmp_path, "abc", "english text", language="en")
    assert _get_cached_transcript(tmp_path, "abc", language="en") == "english text"
    assert _get_cached_transcript(tmp_path, "abc", language="fr") is None


def test_cache_key_auto_language(tmp_path):
    _put_cached_transcript(tmp_path, "abc", "auto text")
    assert _get_cached_transcript(tmp_path, "abc") == "auto text"
    assert _get_cached_transcript(tmp_path, "abc", language="en") is None


def test_cache_key_includes_model_size(tmp_path):
    _put_cached_transcript(tmp_path, "abc", "base text", model_size="base")
    assert _get_cached_transcript(tmp_path, "abc", model_size="base") == "base text"
    assert _get_cached_transcript(tmp_path, "abc", model_size="large-v3") is None


# ── Extension sets ───────────────────────────────────────────────────


def test_media_extensions_complete():
    for ext in (".wav", ".mp3", ".mp4", ".mkv", ".flac"):
        assert ext in MEDIA_EXTENSIONS


def test_audio_video_partition():
    assert ".wav" in AUDIO_EXTENSIONS
    assert ".mp4" in VIDEO_EXTENSIONS
    assert MEDIA_EXTENSIONS == AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
