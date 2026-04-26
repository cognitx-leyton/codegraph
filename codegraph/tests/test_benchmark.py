"""Tests for :mod:`codegraph.benchmark`.

All tests use a fake Neo4j driver — no live Neo4j instance required.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable
from typer.testing import CliRunner

from codegraph.benchmark import (
    BenchmarkResult,
    _estimate_tokens,
    _format_context_block,
    _TOKENIZER,
    count_corpus_tokens,
    run_benchmark,
    write_benchmark_json,
)
from codegraph.cli import app

_USING_TIKTOKEN = _TOKENIZER.startswith("tiktoken")


# ── Fake Neo4j driver ───────────────────────────────────────────────


class _FakeResult:
    """Stand-in for a Neo4j result; supports iteration."""

    def __init__(self, rows: list[dict]):
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)


class _FakeSession:
    """Routes ``run(cypher, **params)`` to a caller-supplied resolver."""

    def __init__(self, resolver):
        self._resolver = resolver

    def run(self, cypher: str, **params: Any) -> _FakeResult:
        return _FakeResult(self._resolver(cypher, **params))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeDriver:
    def __init__(self, resolver):
        self._resolver = resolver
        self.closed = False

    def verify_connectivity(self):
        pass

    def session(self):
        return _FakeSession(self._resolver)

    def close(self):
        self.closed = True


def _constant_driver(answers: dict[str, list[dict]]) -> _FakeDriver:
    """Build a driver whose session.run returns rows matching a key in the query."""

    def resolver(cypher: str, **_params):
        for key, rows in answers.items():
            if key in cypher:
                return rows
        return []

    return _FakeDriver(resolver)


class _FakeGD:
    """Stand-in for ``neo4j.GraphDatabase`` with a ``.driver()`` factory."""
    def __init__(self, fake_driver):
        self._fake = fake_driver

    def driver(self, *args, **kwargs):
        return self._fake


runner = CliRunner()


# ── Token estimator tests ──────────────────────────────────────────


@pytest.mark.skipif(_USING_TIKTOKEN, reason="chars/4 test; tiktoken installed")
def test_estimate_tokens_nonempty():
    assert _estimate_tokens("abcdefgh") == 2  # 8 chars // 4


def test_estimate_tokens_empty():
    assert _estimate_tokens("") == 1  # minimum floor (both tokenizers)


@pytest.mark.skipif(_USING_TIKTOKEN, reason="chars/4 test; tiktoken installed")
def test_estimate_tokens_short():
    assert _estimate_tokens("abc") == 1  # 3 chars // 4 = 0 -> clamped to 1


def test_estimate_tokens_positive():
    """Token count is always >= 1 regardless of tokenizer."""
    assert _estimate_tokens("hello world") >= 1


# ── Context formatter tests ────────────────────────────────────────


def test_format_context_block_multiple_rows():
    rows = [
        {"name": "Foo", "file": "a.py"},
        {"name": "Bar", "file": "b.py"},
    ]
    result = _format_context_block(rows)
    assert "name=Foo" in result
    assert "name=Bar" in result
    assert "file=a.py" in result
    assert result.count("\n") == 1  # two rows, one newline


def test_format_context_block_empty():
    assert _format_context_block([]) == ""


# ── Corpus counter tests ───────────────────────────────────────────


@pytest.mark.skipif(_USING_TIKTOKEN, reason="chars/4 test; tiktoken installed")
def test_count_corpus_tokens_fixture(tmp_path):
    """Known content → expected token count (chars/4)."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    # 100 chars → 25 tokens (chars/4)
    (pkg / "a.py").write_text("x" * 100)
    # 40 chars → 10 tokens
    (pkg / "b.py").write_text("y" * 40)

    result = count_corpus_tokens(tmp_path, ["mypkg"])
    assert result == 35  # 25 + 10


def test_count_corpus_tokens_positive(tmp_path):
    """Non-empty files produce a positive token count regardless of tokenizer."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "a.py").write_text("x" * 100)
    assert count_corpus_tokens(tmp_path, ["mypkg"]) > 0


def test_count_corpus_tokens_skips_large_files(tmp_path):
    """Files > 1.5 MB are excluded."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "small.py").write_text("x" * 100)
    (pkg / "huge.py").write_text("z" * 2_000_000)

    # Only the small file contributes tokens
    result_with_both = count_corpus_tokens(tmp_path, ["mypkg"])
    result_small_only = _estimate_tokens("x" * 100)
    assert result_with_both == result_small_only


# ── run_benchmark tests ────────────────────────────────────────────


def test_run_benchmark_happy_path(tmp_path, monkeypatch):
    """Fake driver returns rows for some queries → valid BenchmarkResult."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "code.py").write_text("x" * 400)

    answers = {
        "IMPORTS_SYMBOL": [
            {"f.path": "a.py", "r.symbol": "Foo", "g.path": "b.py"},
        ],
        "IMPORTS": [
            {"f.path": "c.py", "importers": 5},
        ],
    }
    fake = _constant_driver(answers)
    monkeypatch.setattr(
        "codegraph.benchmark.GraphDatabase", _FakeGD(fake),
    )

    result = run_benchmark(
        uri="bolt://fake:7688", user="neo4j", password="test",
        repo=tmp_path, packages=["mypkg"],
    )
    assert result.corpus_tokens > 0
    assert result.queries_evaluated >= 1
    assert result.queries_skipped >= 1
    assert result.reduction_ratio > 0
    assert result.ok is True


def test_run_benchmark_empty_graph(tmp_path, monkeypatch):
    """Empty graph → queries_evaluated == 0, reduction_ratio == 0."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "code.py").write_text("x" * 100)

    fake = _constant_driver({})
    monkeypatch.setattr(
        "codegraph.benchmark.GraphDatabase", _FakeGD(fake),
    )

    result = run_benchmark(
        uri="bolt://fake:7688", user="neo4j", password="test",
        repo=tmp_path, packages=["mypkg"],
    )
    assert result.queries_evaluated == 0
    assert result.reduction_ratio == 0.0


def test_run_benchmark_partial_queries(tmp_path, monkeypatch):
    """Some queries return rows, others empty → correct skipped count."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "code.py").write_text("x" * 100)

    # Only match callers-of-class query
    answers = {
        "IMPORTS_SYMBOL": [
            {"f.path": "a.py", "r.symbol": "Foo", "g.path": "b.py"},
        ],
    }
    fake = _constant_driver(answers)
    monkeypatch.setattr(
        "codegraph.benchmark.GraphDatabase", _FakeGD(fake),
    )

    result = run_benchmark(
        uri="bolt://fake:7688", user="neo4j", password="test",
        repo=tmp_path, packages=["mypkg"],
    )
    assert result.queries_evaluated == 1
    assert result.queries_skipped == 7  # 8 total - 1 matched


def test_benchmark_result_to_json():
    """BenchmarkResult.to_json() produces valid JSON with expected keys."""
    result = BenchmarkResult(
        corpus_tokens=1000,
        queries_evaluated=5,
        queries_skipped=3,
        avg_query_tokens=50,
        reduction_ratio=20.0,
        tokenizer="chars/4",
        per_query=[{"name": "test", "rows": 10, "context_tokens": 50, "skipped": False}],
        timestamp="2026-04-24T00:00:00+00:00",
    )
    parsed = json.loads(result.to_json())
    for key in (
        "corpus_tokens", "queries_evaluated", "queries_skipped",
        "avg_query_tokens", "reduction_ratio", "tokenizer",
        "per_query", "timestamp",
    ):
        assert key in parsed
    assert parsed["corpus_tokens"] == 1000
    assert parsed["reduction_ratio"] == 20.0
    assert parsed["ok"] is True


# ── CLI subcommand tests ───────────────────────────────────────────


def test_benchmark_cli_json_output(tmp_path, monkeypatch):
    """CLI --json produces valid JSON output."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "code.py").write_text("x" * 400)

    answers = {
        "IMPORTS_SYMBOL": [
            {"f.path": "a.py", "r.symbol": "Foo", "g.path": "b.py"},
        ],
    }
    fake = _constant_driver(answers)
    monkeypatch.setattr(GraphDatabase, "driver", lambda *a, **kw: fake)

    result = runner.invoke(app, ["benchmark", str(tmp_path), "--json", "--scope", "mypkg"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert "corpus_tokens" in parsed
    assert "reduction_ratio" in parsed


def test_benchmark_cli_min_reduction_pass(tmp_path, monkeypatch):
    """Ratio above threshold → exit 0."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "code.py").write_text("x" * 4000)

    answers = {
        "IMPORTS_SYMBOL": [
            {"f.path": "a.py", "r.symbol": "X", "g.path": "b.py"},
        ],
    }
    fake = _constant_driver(answers)
    monkeypatch.setattr(GraphDatabase, "driver", lambda *a, **kw: fake)

    result = runner.invoke(app, [
        "benchmark", str(tmp_path), "--min-reduction", "1", "--scope", "mypkg",
    ])
    assert result.exit_code == 0, result.output


def test_benchmark_cli_min_reduction_fail(tmp_path, monkeypatch):
    """Ratio below threshold → exit 1."""
    pkg = tmp_path / "mypkg"
    pkg.mkdir()
    (pkg / "code.py").write_text("x" * 100)

    answers = {
        "IMPORTS_SYMBOL": [
            {"f.path": "a.py", "r.symbol": "X", "g.path": "b.py"},
        ],
    }
    fake = _constant_driver(answers)
    monkeypatch.setattr(GraphDatabase, "driver", lambda *a, **kw: fake)

    result = runner.invoke(app, [
        "benchmark", str(tmp_path), "--min-reduction", "99999", "--scope", "mypkg",
    ])
    assert result.exit_code == 1


def test_benchmark_cli_service_unavailable(tmp_path, monkeypatch):
    """Connection error → exit 2, clean JSON error."""
    err = ServiceUnavailable("Connection refused")

    class _ErrorDriver:
        def verify_connectivity(self):
            raise err
        def session(self):
            raise err
        def close(self):
            pass

    monkeypatch.setattr(GraphDatabase, "driver", lambda *a, **kw: _ErrorDriver())

    result = runner.invoke(app, [
        "benchmark", str(tmp_path), "--json", "--no-scope",
    ])
    assert result.exit_code == 2
    parsed = json.loads(result.output)
    assert parsed["ok"] is False
    assert parsed["error"] == "connection"


# ── Integration + write tests ─────────────────────────────────────


def test_index_no_benchmark_flag():
    """--no-benchmark appears in index help."""
    result = runner.invoke(app, ["index", "--help"])
    assert "--no-benchmark" in result.output


def test_benchmark_json_written(tmp_path):
    """write_benchmark_json writes valid JSON file."""
    result = BenchmarkResult(
        corpus_tokens=500,
        queries_evaluated=3,
        queries_skipped=5,
        avg_query_tokens=25,
        reduction_ratio=20.0,
        tokenizer="chars/4",
        per_query=[],
        timestamp="2026-04-24T00:00:00+00:00",
    )
    path = write_benchmark_json(result, tmp_path)
    assert path.exists()
    parsed = json.loads(path.read_text())
    assert parsed["corpus_tokens"] == 500
    assert parsed["reduction_ratio"] == 20.0
