# CLAUDE.md

Guidance for Claude Code (and similar coding agents) working on this repo.

## Project summary

**codegraph** (package: `codegraph`) is a Python tool that indexes TypeScript and Python codebases into a Neo4j property graph. It walks source with tree-sitter, recognises framework constructs (NestJS controllers / injectables / modules, React components and hooks, TypeORM entities, GraphQL operations, Python classes and decorators), and loads typed nodes + edges into Neo4j. Downstream consumers:

- **CLI**: `codegraph index`, `codegraph query`, `codegraph validate`, `codegraph wipe` — Typer app.
- **MCP server**: `codegraph-mcp` stdio server with 10 read-only tools. Optional extra (`pip install "codegraph[mcp]"`).
- **REPL**: interactive Cypher shell at `codegraph repl`.

This repo is itself **Python**, and codegraph parses Python since Stage 1 shipped. So we can dogfood: Claude Code can query the graph of codegraph-the-codebase while implementing codegraph-the-tool.

## Using the graph during development

Two slash commands wire the local Neo4j graph into your Claude Code workflow. **Use them** — they exist to catch mistakes the language server can't.

### `/graph <cypher>` — query the live graph

Read-only Cypher against `bolt://localhost:7688`. Prefer this over manual `codegraph query` in Bash because the slash command has the permissions pre-approved and a body of canonical query patterns. See `.claude/commands/graph.md` for examples.

**When to run `/graph`**:

- **Before renaming** a class, function, or file → check blast radius with `MATCH (f:File)-[r:IMPORTS_SYMBOL]->(g:File) WHERE r.symbol = 'X' RETURN f.path, g.path`.
- **Before deleting** a function or method → confirm nothing depends on it.
- **Before moving** a module → count incoming IMPORTS edges; you'll need to update every caller.
- **When asked "who calls X?" or "where is Y used?"** — almost always a one-query answer.
- **When in doubt about what exists** — `/graph "MATCH (c:Class) WHERE c.name CONTAINS 'Foo' RETURN c.name, c.file"` is faster and more exhaustive than grep.

### `/graph-refresh` — update the graph

Re-indexes this repo's Python package + its tests (`codegraph/codegraph/` + `codegraph/tests/`) so `/graph` queries reflect the latest on-disk state. **Run it after any structural edit** — adding, removing, renaming, or moving classes / functions / methods / imports / decorators. Cosmetic edits don't need a refresh.

Takes ~5 seconds. Uses `--no-wipe` so other indexed graphs (e.g. Twenty) survive. See `.claude/commands/graph-refresh.md`.

### Daily power-tool commands

Five purpose-built wrappers over `/graph` for the patterns you'll reach for most often. Each is a thin shell around a canonical Cypher query — run them before changing code, not after.

| Command | Use case |
|---|---|
| `/blast-radius <Symbol>` | Before renaming / deleting / moving a class, function, or method — see every caller, subclass, DI consumer, and importer |
| `/dead-code [path_prefix]` | Sweep for orphan functions, classes, atoms, endpoints. Framework entry points (`@mcp.tool()`, `@app.command()`, `@pytest.fixture`) are excluded automatically |
| `/who-owns <path>` | Latest author + top-5 contributors + CODEOWNERS team for a file. Requires an ownership-aware index pass (not `--skip-ownership`) |
| `/trace-endpoint <url_substring>` | Endpoint → handler method → every method reachable within 4 `CALLS` hops. Good for impact analysis + security review |
| `/arch-check` | Built-in conformance policies: import cycles, cross-package violations, Controller→Repository bypass. Fork the command to add project-specific policies |

### Architecture drift (CI gate)

`codegraph arch-check` is a first-class CLI subcommand that runs the same three built-in policies as `/arch-check` and exits non-zero on any violation. `.github/workflows/arch-check.yml` wires it into CI: on every PR to `main`, GitHub Actions spins up `neo4j:5.24-community` as a service container, indexes the repo with `codegraph index`, runs the check, and uploads the JSON report as a build artifact. Any violation blocks the merge.

**Configuring the trigger scope**: edit the `on:` block at the top of `.github/workflows/arch-check.yml`. The shipped default is `pull_request: branches: [main]` (strictest, lowest-noise). Two commented-out alternatives sit right below it: `push: branches: [dev]` to catch drift the moment it lands, and `workflow_dispatch` for manual runs from the Actions UI. Uncomment what you need.

**Reproducing a failing check locally**: `cd codegraph && codegraph index . -p codegraph -p tests --skip-ownership && codegraph arch-check`. Exit code mirrors CI.

Policy reference + false-positive guidance: `codegraph/docs/arch-policies.md`.

### What's indexed (and what isn't)

The slash commands point at `codegraph/codegraph/` (the Python package) and `codegraph/tests/` (its test suite). The package is ~20 files, 56 classes, 134 module functions, ~180 methods; tests add another ~17 files that pair back via `TESTS` edges where they share a directory with their production peer. **Not indexed**: the root-level `dependency_slicer.py`, `.venv`, the repo root's config files.
<!-- Stats updated 2026-04-18. Refresh: codegraph query "MATCH (n) WHERE n.file STARTS WITH 'codegraph/' RETURN labels(n)[0], count(*)" -->

If you want a query against other paths, re-run `codegraph/.venv/bin/codegraph index . -p <path>` with the package scope you want.

### Prerequisites

The slash commands silently assume:
1. Neo4j is running: `docker ps | grep codegraph-neo4j` should show a healthy container. If not, `cd codegraph && docker compose up -d`.
2. The `.venv` is installed with the `[python]` extra: `codegraph/.venv/bin/codegraph --help` should work. If not, `cd codegraph && python3 -m venv .venv && .venv/bin/pip install -e ".[python,mcp]"`.
3. The graph has been indexed at least once. Run `/graph-refresh` if `/graph` returns zero for queries you expect to match.

## Repo conventions

- **Branches**: `dev` is where work lands. `main` / `release` / `hotfix` are protected; PRs from `dev` to `main`.
- **Atomic commits** with detailed bodies. See `git log` for the style. Subjects follow conventional commits (`feat(scope)`, `fix(scope)`, `docs(scope)`, `test(scope)`).
- **Tests**: `.venv/bin/python -m pytest tests/ -q` from `codegraph/`. Target 100% passing, zero warnings. The suite runs in ~15s.
- **Type checking**: none configured today; we rely on the tests + `python -m compileall` for basic integrity.
- **Linting**: none configured today either.
- **Planning**: non-trivial changes go through `/plan_local` (or manual plan-mode) before implementation. Plans live at `~/.claude/plans/`.
- **`.claude/` layout**: `.claude/commands/` contains repo-shared slash commands (committed). `.claude/settings.json` holds repo-shared permissions (committed). `.claude/settings.local.json`, `.claude/agents/`, and `.claude/skills/` are user-local (gitignored).

## Architecture at a glance

Read `ROADMAP.md` at the repo root for the session-to-session handoff and the full state of the codebase (shipped features per commit, open questions, what's next, environment setup, tests, architectural decisions). It's the authoritative pointer.

Key source files:

| File | Purpose |
|---|---|
| `codegraph/codegraph/cli.py` | Typer CLI + file-walk dispatch (TS ↔ Python) |
| `codegraph/codegraph/parser.py` | TypeScript / TSX tree-sitter walker |
| `codegraph/codegraph/py_parser.py` | Python tree-sitter walker |
| `codegraph/codegraph/resolver.py` | Cross-file import resolution (TS + Python) |
| `codegraph/codegraph/loader.py` | Neo4j batch writer + constraints |
| `codegraph/codegraph/schema.py` | Node + edge dataclasses (language-agnostic) |
| `codegraph/codegraph/mcp.py` | FastMCP stdio server (10 tools) |
| `codegraph/codegraph/framework.py` | Per-package framework detection (TS only in Stage 1) |
| `codegraph/codegraph/ignore.py` | `.codegraphignore` parser |
| `codegraph/codegraph/config.py` | `codegraph.toml` / `pyproject.toml` config loader |

## Non-goals to remember

- Don't refactor `TsParser` to be "language-agnostic" — two concrete parsers with the same `ParseResult` interface is the chosen design. See commit `154954c` for the rationale.
- Don't commit `.claude/settings.local.json`, `.claude/agents/`, or `.claude/skills/`. They're user-local agent config.
- Don't add per-file framework flags to Python FileNodes beyond what Stage 1 emits. Framework detection for Python lands in Stage 2 as a separate piece.
- Don't work on Go / Rust frontends until Stage 2/3 of the Python frontend has landed — priority is depth over breadth for now.
