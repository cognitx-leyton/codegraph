"""Token-reduction benchmark.

Compares "reading every raw file" vs "querying the graph for a focused
context block" across a set of canonical Cypher queries.  The ratio
shows how many fewer tokens an agent needs when it uses codegraph.

Integrated into ``codegraph index`` (one-line summary) and available
standalone via ``codegraph benchmark``.  Uses ``len(text) // 4`` as the
default tokeniser (zero deps).  Install the ``benchmark`` extra for
precise BPE counting via tiktoken.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from neo4j import GraphDatabase
from rich.console import Console
from rich.table import Table

# ── Token estimator ────────────────────────────────────────────

_TOKENIZER: str = "chars/4"

try:
    import tiktoken as _tiktoken  # type: ignore[import-untyped]

    _enc = _tiktoken.get_encoding("cl100k_base")
    _TOKENIZER = "tiktoken/cl100k_base"

    def _estimate_tokens(text: str) -> int:
        return max(1, len(_enc.encode(text)))

except Exception:  # ImportError or encoding download failure

    def _estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)


# ── Corpus counter ─────────────────────────────────────────────

_DEFAULT_EXCLUDE_DIRS: frozenset[str] = frozenset({
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".nuxt",
})

_DEFAULT_EXCLUDE_SUFFIXES: tuple[str, ...] = (
    ".pyc", ".pyo", ".so", ".dll", ".dylib", ".whl",
    ".tar", ".gz", ".zip", ".jar",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".lock",
)

_MAX_FILE_SIZE = 1_500_000  # 1.5 MB


def count_corpus_tokens(
    repo: Path,
    packages: list[str],
    exclude_dirs: frozenset[str] | None = None,
    exclude_suffixes: tuple[str, ...] | None = None,
) -> int:
    """Walk files under *packages* and sum token estimates."""
    if exclude_dirs is None:
        exclude_dirs = _DEFAULT_EXCLUDE_DIRS
    if exclude_suffixes is None:
        exclude_suffixes = _DEFAULT_EXCLUDE_SUFFIXES

    total = 0
    for pkg in packages:
        pkg_dir = repo / pkg
        if not pkg_dir.is_dir():
            continue
        for root, dirs, files in os.walk(pkg_dir):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for fname in files:
                if fname.endswith(exclude_suffixes):
                    continue
                fpath = Path(root) / fname
                try:
                    size = fpath.stat().st_size
                except OSError:
                    continue
                if size > _MAX_FILE_SIZE or size == 0:
                    continue
                try:
                    text = fpath.read_text(errors="replace")
                except OSError:
                    continue
                total += _estimate_tokens(text)
    return total


# ── Benchmark queries ──────────────────────────────────────────

_BENCHMARK_QUERIES: list[tuple[str, str, str]] = [
    (
        "endpoints-for-controller",
        "Controllers and the endpoints they expose",
        "MATCH (c:Controller)-[:EXPOSES]->(e:Endpoint) "
        "RETURN c.name, e.method, e.path, e.handler, c.file LIMIT 50",
    ),
    (
        "callers-of-class",
        "Cross-file import relationships",
        "MATCH (f:File)-[r:IMPORTS_SYMBOL]->(g:File) "
        "RETURN f.path, r.symbol, g.path LIMIT 50",
    ),
    (
        "method-call-chain",
        "Transitive method call chains (1-3 hops)",
        "MATCH (m:Method)-[:CALLS*1..3]->(callee:Method) "
        "RETURN DISTINCT m.name, callee.name, callee.file LIMIT 50",
    ),
    (
        "entity-columns",
        "ORM entities and their columns",
        "MATCH (e:Entity)-[:HAS_COLUMN]->(col:Column) "
        "RETURN e.name, col.name, col.type LIMIT 50",
    ),
    (
        "di-graph",
        "Dependency injection graph (1-2 hops)",
        "MATCH (c:Class)-[:INJECTS*1..2]->(dep:Class) "
        "RETURN DISTINCT c.name, dep.name, dep.file LIMIT 50",
    ),
    (
        "test-coverage-gaps",
        "Classes without a corresponding test file",
        "MATCH (c:Class) "
        "WHERE NOT EXISTS { (:TestFile)-[:TESTS_CLASS]->(c) } "
        "RETURN c.name, c.file LIMIT 50",
    ),
    (
        "hub-files",
        "Most-imported files (hub nodes)",
        "MATCH (f:File)<-[:IMPORTS]-(src:File) "
        "RETURN f.path, count(src) AS importers "
        "ORDER BY importers DESC LIMIT 20",
    ),
    (
        "feature-slice",
        "Files with their defined symbols",
        "MATCH (f:File)-[:DEFINES_CLASS|DEFINES_FUNC]->(n) "
        "WITH f, collect(n.name) AS symbols "
        "RETURN f.path, symbols LIMIT 30",
    ),
]


# ── Context formatter ──────────────────────────────────────────

def _format_context_block(rows: list[dict]) -> str:
    """Join each row as ``key=value`` pairs, one line per row."""
    if not rows:
        return ""
    lines: list[str] = []
    for row in rows:
        parts = [f"{k}={v}" for k, v in row.items()]
        lines.append("  ".join(parts))
    return "\n".join(lines)


# ── Result dataclass ───────────────────────────────────────────

@dataclass
class BenchmarkResult:
    """Aggregate benchmark result."""
    corpus_tokens: int = 0
    queries_evaluated: int = 0
    queries_skipped: int = 0
    avg_query_tokens: int = 0
    reduction_ratio: float = 0.0
    tokenizer: str = "chars/4"
    per_query: list[dict] = field(default_factory=list)
    timestamp: str = ""

    @property
    def ok(self) -> bool:
        return True

    def to_json(self) -> str:
        d = asdict(self)
        d["ok"] = self.ok
        return json.dumps(d, indent=2, default=str)


# ── Orchestrator ───────────────────────────────────────────────

def run_benchmark(
    uri: str,
    user: str,
    password: str,
    repo: Path,
    packages: list[str],
    exclude_dirs: frozenset[str] | None = None,
    exclude_suffixes: tuple[str, ...] | None = None,
) -> BenchmarkResult:
    """Open a driver, count corpus tokens, run benchmark queries, return result."""
    corpus_tokens = count_corpus_tokens(
        repo, packages,
        exclude_dirs=exclude_dirs,
        exclude_suffixes=exclude_suffixes,
    )

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        per_query: list[dict] = []
        total_query_tokens = 0
        queries_evaluated = 0
        queries_skipped = 0

        with driver.session() as s:
            for name, description, cypher in _BENCHMARK_QUERIES:
                rows = [dict(r) for r in s.run(cypher)]
                if not rows:
                    queries_skipped += 1
                    per_query.append({
                        "name": name,
                        "description": description,
                        "rows": 0,
                        "context_tokens": 0,
                        "skipped": True,
                    })
                    continue
                context = _format_context_block(rows)
                context_tokens = _estimate_tokens(context)
                total_query_tokens += context_tokens
                queries_evaluated += 1
                per_query.append({
                    "name": name,
                    "description": description,
                    "rows": len(rows),
                    "context_tokens": context_tokens,
                    "skipped": False,
                })
    finally:
        driver.close()

    avg_query_tokens = (
        total_query_tokens // queries_evaluated if queries_evaluated else 0
    )
    reduction_ratio = (
        round(corpus_tokens / avg_query_tokens, 1)
        if avg_query_tokens > 0 else 0.0
    )

    return BenchmarkResult(
        corpus_tokens=corpus_tokens,
        queries_evaluated=queries_evaluated,
        queries_skipped=queries_skipped,
        avg_query_tokens=avg_query_tokens,
        reduction_ratio=reduction_ratio,
        tokenizer=_TOKENIZER,
        per_query=per_query,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ── Printers ───────────────────────────────────────────────────

def print_benchmark_summary(result: BenchmarkResult, console: Console) -> None:
    """One-line Rich summary suitable for post-index output."""
    if result.queries_evaluated == 0:
        console.print(
            "[yellow]Token reduction:[/] no benchmark queries matched "
            "(graph may be empty)"
        )
        return
    console.print(
        f"[green]Token reduction:[/] {result.reduction_ratio}x "
        f"({result.corpus_tokens:,} corpus tokens → "
        f"{result.avg_query_tokens:,} avg query tokens, "
        f"{result.queries_evaluated}/{result.queries_evaluated + result.queries_skipped} queries matched)"
    )


def print_benchmark_verbose(result: BenchmarkResult, console: Console) -> None:
    """Rich table with per-query breakdown."""
    print_benchmark_summary(result, console)
    if not result.per_query:
        return
    t = Table(
        title="Benchmark per-query breakdown",
        show_header=True,
        header_style="bold magenta",
    )
    t.add_column("query")
    t.add_column("rows", justify="right")
    t.add_column("context tokens", justify="right")
    t.add_column("status")
    for q in result.per_query:
        status = "[dim]skipped[/]" if q["skipped"] else "[green]matched[/]"
        t.add_row(
            q["name"],
            str(q["rows"]),
            str(q["context_tokens"]),
            status,
        )
    console.print(t)


# ── Writer ─────────────────────────────────────────────────────

def write_benchmark_json(result: BenchmarkResult, out_dir: Path) -> Path:
    """Write ``benchmark.json`` to *out_dir*. Returns the written path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "benchmark.json"
    path.write_text(result.to_json())
    return path
