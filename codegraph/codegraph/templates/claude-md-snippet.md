## Using the codegraph knowledge graph

This repo is indexed into a local Neo4j via **codegraph** (`pipx install cognitx-codegraph`). Run `codegraph init` if you haven't yet. The graph is reachable at `bolt://localhost:$NEO4J_BOLT_PORT`. Claude Code has slash commands wired to it — use them.

### `/graph <cypher>` — read-only Cypher queries

Run any MATCH query against the live graph. See `.claude/commands/graph.md` for canonical query patterns (blast radius, callers, class census, etc.).

### `/graph-refresh` — re-index after structural edits

Run after adding / removing / renaming classes, functions, methods, imports, decorators. Cosmetic edits don't need a refresh. Takes ~5 seconds.

### Daily power-tool commands

| Command | Use case |
|---|---|
| `/blast-radius <Symbol>` | Before renaming / deleting / moving a class, function, or method |
| `/dead-code [path_prefix]` | Sweep for orphan functions, classes, atoms, endpoints |
| `/who-owns <path>` | Latest author + top-5 contributors + CODEOWNERS team for a file |
| `/trace-endpoint <url_substring>` | Endpoint → handler method → every method reachable within 4 CALLS hops |
| `/arch-check` | Built-in conformance policies + custom Cypher policies from `.arch-policies.toml` |

### Architecture drift (CI gate)

`codegraph arch-check` also runs on every PR to `main` via `.github/workflows/arch-check.yml`. Any policy violation blocks the merge. Tune policies in `.arch-policies.toml`; reproduce a failing check locally with `codegraph index . $PACKAGE_PATHS_FLAGS --skip-ownership && codegraph arch-check`.

### Prerequisites

1. Neo4j running: `docker compose ps` shows `$CONTAINER_NAME` up. If not: `docker compose up -d`.
2. `codegraph --help` works (install with `pipx install cognitx-codegraph`).
3. Graph indexed at least once — `codegraph init` does this the first time; `/graph-refresh` re-runs it later.
