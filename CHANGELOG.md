# Changelog

All notable changes to **codegraph** (`cognitx-codegraph` on PyPI). The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [semantic versioning](https://semver.org/) — although while we're in `0.1.x` the public API is still considered evolving.

Versions are grouped into **waves** rather than listed one-by-one — the project ships small atomic versions (`0.1.0` → `0.1.99` over twelve days). Per-commit detail is in `git log`; this file is the human-readable narrative.

For the session-by-session engineering handoff (open questions, what's next, environment setup), see [`ROADMAP.md`](./ROADMAP.md).

---

## [Unreleased]

### Added

- **`codegraph audit`** — agent-driven extraction self-check. Launches an external coding agent (`claude` / `codex` / `gemini` / `aider` / `opencode` / `droid`, with a `cursor` rules-file fallback) in headless + permission-bypass mode against the live graph, with a tightly-scoped prompt that flags only places where codegraph claims to extract X but missed it on this repo. Output is `codegraph-out/audit-report.md` plus an optional `gh issue create --label codegraph-audit`. The prompt templates are protected by three layers (CODEOWNERS, a CI workflow that posts a sticky reviewer warning + runs static-diff lint, and a SHA-256 lock file the runtime verifies before launch). See [`codegraph/docs/cli.md#audit`](./codegraph/docs/cli.md#audit).
- **Shared `codegraph-neo4j` container** — every repo on the machine now indexes into one Neo4j instead of one container per repo. `codegraph init` auto-detects the existing `codegraph-neo4j`, reuses it if running, starts it if stopped, or creates it on first run. Reuse path reads the running container's host-side port mapping via `docker inspect` and threads those ports through, so existing `CODEGRAPH_NEO4J_URI` env vars stay accurate. Documented in [`codegraph/docs/init.md`](./codegraph/docs/init.md#shared-codegraph-neo4j-container).
- **Docker presence + version preflight** in `codegraph init`. Detects whether `docker` is on PATH, whether the daemon is answering, and whether the installed version is older than the recommended `20.10` baseline. On miss, prints an OS-aware install / start / upgrade command (Debian/Ubuntu / Fedora/RHEL / Arch / openSUSE / macOS / Windows) sourced from a new `codegraph.docker_setup` module. Never executes install commands automatically — sudo is too risky to automate.
- **`Neo4jLoader.wipe_scoped(packages)`** — package-scoped graph wipe. Reuses the existing 3-step delete cascade in `delete_file_subgraph`, plus drops orphaned `:Package` nodes for the wiped packages.

### Changed

- **`codegraph index --wipe` is now scoped to configured packages**. Previous behaviour (`MATCH (n) DETACH DELETE n`) would have nuked every other repo's data on a shared `codegraph-neo4j`. The standalone `codegraph wipe` command keeps its global semantics for an explicit clean slate.
- **Default container name** in scaffolded `docker-compose.yml` switched from per-repo `cognitx-codegraph-<repo>-<8hex>` to the shared `codegraph-neo4j`. The per-repo derivation function (`derive_container_name`) is still exported for callers that want isolated containers; it's just not the default.

### Migration

If you upgrade and have legacy per-repo containers from earlier versions:

```bash
docker ps -a --filter "name=cognitx-codegraph-" --format "table {{.Names}}\t{{.Status}}"
docker rm -f $(docker ps -a -q --filter "name=cognitx-codegraph-")
docker volume prune
```

Init does not migrate data automatically — re-running `codegraph index .` against the new `codegraph-neo4j` is the supported path. Fresh indexes are cheap (~30s for a 1k-file repo).

### Planned next

- Go and Rust language frontends.
- Pre-built RAG retrievers for common architecture questions (callers-of, blast-radius, layer reachability).
- Auto-generated graph visualisations as PR comments via the GitHub Actions workflow.

---

## [0.1.93 – 0.1.99] — 2026-04-24 → 2026-04-25

### Added

- **Multi-platform AI agent integrations** (#258): `codegraph install <platform>` and `codegraph uninstall <platform>` for **14 platforms** — Claude Code, Codex, OpenCode, Cursor, Gemini CLI, GitHub Copilot CLI, VS Code Copilot Chat, Aider, OpenClaw, Factory Droid, Trae, Kiro IDE, Google Antigravity, Hermes. Each platform install writes the appropriate rules file (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursor/rules/codegraph.mdc`, `.github/copilot-instructions.md`, …) and registers the MCP server. Manifest-aware uninstall preserves shared `AGENTS.md` sections still in use by other platforms (#261). Template variables (`$NEO4J_BOLT_PORT`, `$PACKAGE_PATHS_FLAGS`, `$CONTAINER_NAME`, …) resolve per-repo (#260).
- **Edge-level confidence labels** (#255): every relationship now carries `confidence` (`EXTRACTED` / `INFERRED` / `AMBIGUOUS`) and `confidence_score` (`0.0`–`1.0`). Strict checks can filter to a high-trust subgraph; exploratory queries get the full picture. Reference: [`codegraph/docs/confidence.md`](./codegraph/docs/confidence.md).
- **Hyperedge model** (#254): `:EdgeGroup` nodes model N-ary relationships (protocol implementer sets, Leiden communities). Members link via `:MEMBER_OF`. New MCP tool `describe_group` for inspection. Reference: [`codegraph/docs/hyperedges.md`](./codegraph/docs/hyperedges.md).

### Changed

- **Comprehensive docs sweep** (0.1.99): synchronised top-level `README.md`, inner `codegraph/README.md`, `CLAUDE.md` snippets, and `codegraph/docs/init.md` with the post-250-issue codebase. Added per-topic deep dives under `codegraph/docs/`.
- **Template-var deduplication** (#262): `derive_container_name(root)` and `build_template_vars(...)` extracted into `init.py` as public helpers; `_build_install_vars` in `cli.py` now delegates.

---

## [0.1.88 – 0.1.92] — 2026-04-24

### Added

- **SHA-256 incremental cache** (#46, #248): `codegraph index --update` skips unchanged files using a content-addressed cache in `.codegraph-cache/`. Stale entries are pruned on save (#250). `codegraph init` auto-appends `.codegraph-cache/` to `.gitignore` (#249).
- **Filesystem watcher** (#47, #245): `codegraph watch` rebuilds the graph on save with debounced events. Requires the `[watch]` extra (`watchdog`).
- **Git hooks** (#47, #245): `codegraph hook install` / `status` / `uninstall` manages `post-commit` and `post-checkout` hooks that re-index automatically on commit and branch switch.
- **Interactive HTML + GraphML export** (#251): `codegraph export` produces `graph.html` (vis-network), `graph.json`, optionally `graph.graphml` and `graph.cypher`. Runs after `codegraph index` unless `--no-export`.
- **Token-reduction benchmark** (#252): `codegraph benchmark` measures graph size vs. raw source token count. Optional `--min-reduction` for CI gating. Uses `tiktoken` if the `[benchmark]` extra is installed; otherwise falls back to `chars/4`.
- **Leiden community detection** (#253): `codegraph report` runs Leiden clustering and writes `GRAPH_REPORT.md`. Communities materialise as `:EdgeGroup` nodes with `kind = "community"`. Requires the `[analyze]` extra (`networkx`, `graspologic`). Runs after `codegraph index` unless `--no-analyze`.

---

## [0.1.84 – 0.1.87] — 2026-04-24

### Added

- **MCP tool: `find_function`** (#238): substring search over `:Function` and `:Method` names; returns the containing class for methods (#243).
- **MCP tool: `describe_function`** — signature, file, callers/callees summary. Now bounded by `--limit` (#240).
- **MCP tool: `calls_from`** — outgoing `:CALLS` graph from a method, transitive up to 5 hops.
- **MCP tool: `callers_of`** — reverse `:CALLS` graph.
- **MCP tool: `describe_group`** — inspect `:EdgeGroup` hyperedges.

### Changed

- **`callers_of_class` parameters** (#242): added `file` filter and `limit` for narrowing on namespace-collision class names.
- **`query_graph` limit pushdown** (#235): the `limit` argument is now spliced into the Cypher itself rather than slicing rows client-side. Avoids fetching thousands of rows just to discard them.

---

## [0.1.73 – 0.1.83] — 2026-04-22 → 2026-04-23

### Added

- **Custom Neo4j ports during init** (#232): `codegraph init --bolt-port` / `--http-port` for repos that already use the defaults. Compose file and rules templates resolve `$NEO4J_BOLT_PORT` / `$NEO4J_HTTP_PORT`.
- **Container-name derivation**: container names now derive from `<sanitised-repo-dir>-<8-char-sha1>`, eliminating collisions when multiple repos run codegraph side-by-side. Init warns when orphaned containers from the old naming scheme are found (#233).
- **Python module-level call tracking** (#228): `:CALLS` edges are emitted from module top-level statements (not just inside functions/methods). Walks `for`, `while`, and `match` statements (#229).
- **Orphan-detection scoping** (#231): `arch-check` orphan policy gained `exclude_prefixes` and `exclude_names` for repository-specific test-framework conventions (`pytest_*`, `conftest`, …).

### Fixed

- **Special characters in directory names** (#234): container-name sanitiser now handles dots, spaces, and uppercase before hashing.
- **Suppression policy validation** (#224): unknown policy names in `[[suppress]]` blocks now raise with a "did you mean…" suggestion.
- **Exact suppression counts** (#93, fix #225): `arch-check` now counts suppressed violations in Cypher rather than approximating client-side.

---

## [0.1.50 – 0.1.72] — 2026-04-19 → 2026-04-22

### Added

- **`codegraph stats` subcommand**: quick node and edge counts. Supports `--scope` flags and a `--update` mode that rewrites the `<!-- codegraph:stats-begin -->` block in `CLAUDE.md`.
- **MCP tool: `reindex_file`**: re-parse a single file and upsert its subgraph (cascade delete + reload). Requires `--allow-write`.

### Fixed

- **Neo4j error surfacing**: connection and auth errors are no longer swallowed by `index` and `wipe` (#0.1.57, #0.1.59). `validate` now wraps the driver in `try/finally` to prevent leaks on error (#0.1.59).
- **Loader correctness**: endpoint `:EXPOSES` batch split by class-level vs file-level (`#0.1.52`); `READS_ATOM`/`WRITES_ATOM` stats use batch lengths instead of DB-wide counts (`#0.1.69`); `interface:` prefix added to `_FILE_BEARING_PREFIXES` (`#0.1.70`).
- **Resolver**: npm `tsconfig` presets now resolved from `node_modules` (`#0.1.65`).
- **Incremental mode**: skip per-file extras for untouched files (`#0.1.68`); filter non-code files from git diff (`#0.1.67`).
- **`arch-check` UX**: render violations when `sample` is empty (`#0.1.62`); respect custom `sample_limit` in user policies (`#0.1.61`); explicit `disabled` field in `PolicyResult` (`#0.1.64`).
- **`stats`**: prevent multi-label nodes from inflating counts (`#0.1.60`).

---

## [0.1.30 – 0.1.49] — 2026-04-18 → 2026-04-19

### Added

- **`codegraph stats`** initial release (`#0.1.34`): scope-aware node and edge counts.
- **CRLF normalisation** (`#0.1.40`): file-read paths normalise CRLF endings to LF before parsing — fixes Windows-checkout indexing parity.
- **Scoped edge counts** (`#0.1.36`): `stats` filters edges to AND-logic across endpoints, with `--include-cross-scope-edges` opt-out.

### Changed

- **`DEFINES_INTERFACE` → `DEFINES_IFACE`** (`#0.1.49`): consistency with `DEFINES_CLASS` / `DEFINES_FUNC`. Removed duplicate edge writes in `reindex_file`.

### Fixed

- **Ownership hardening**: `_parse_codeowners` catches `OSError` (`#0.1.41`); contract guarantees never returns `None` (`#0.1.45`); rooted-pattern false positives on sibling dirs (`#0.1.46`); unit separator (`0x1f`) replaces pipe in git-log delimiter (`#0.1.47`).
- **Loader cascade**: simplified delete cascade to avoid stale child nodes (`#0.1.48`).

---

## [0.1.20 – 0.1.29] — 2026-04-18

### Added

- **Architecture-conformance CI gate**: `.github/workflows/arch-check.yml` scaffolded by `codegraph init`. Spins up `neo4j:5.24-community` as a service container, indexes the repo, runs `codegraph arch-check`, uploads the JSON report. Any violation blocks the merge.

### Fixed

- **Auto-scope alignment** (`#0.1.25`): `arch-check` workflow paths now match `pyproject.toml`-declared package roots.
- **Validation messages** (`#0.1.24`): policy validation errors use fully-qualified policy paths.

---

## [0.1.10 – 0.1.19] — 2026-04-17

### Added

- **Python Stage 2** (`6493224`): framework detection (FastAPI, Flask, Django, Odoo); endpoint extraction from `@app.get/post/...`; SQLAlchemy / Django `models.Field` → `:Column` nodes; resolver fixes for Python aliased imports.

---

## [0.1.5 – 0.1.9] — 2026-04-16 → 2026-04-17

### Added

- **Python Stage 1** (`154954c`): tree-sitter-python parser. Indexes modules, classes, functions, methods, imports (relative + absolute + aliased), class inheritance, decorators, docstrings, type hints. Auto-detected from `__init__.py` / `pyproject.toml` / `setup.py` at the package root.
- **Architecture policies documentation**: comprehensive [`codegraph/docs/arch-policies.md`](./codegraph/docs/arch-policies.md) covering all 5 built-in policies with worked examples and false-positive guidance.

---

## [0.1.1 – 0.1.4] — 2026-04-14 → 2026-04-15

### Added

- **Initial public release** on PyPI as `cognitx-codegraph`.
- **Core indexing pipeline**: TypeScript / TSX parser via tree-sitter; cross-file resolver; Neo4j batch loader with constraints.
- **Framework detection**: NestJS controllers / injectables / modules / resolvers, React components and hooks, TypeORM entities, GraphQL operations.
- **CLI**: `codegraph init`, `index`, `query`, `validate`, `arch-check`, `wipe`.
- **MCP server**: `codegraph-mcp` stdio server with the initial 10 read-only tools (`query_graph`, `describe_schema`, `list_packages`, `callers_of_class`, `endpoints_for_controller`, `files_in_package`, `hook_usage`, `gql_operation_callers`, `most_injected_services`, `find_class`).
- **`.codegraphignore`**: gitignore-style file-path patterns plus `@route:` and `@component:` extensions for keeping confidential surfaces out of the graph.
- **`codegraph init`**: scaffolds `.claude/commands/`, `.github/workflows/arch-check.yml`, `.arch-policies.toml`, `docker-compose.yml`, and a `CLAUDE.md` snippet. Starts Neo4j and runs the first index.
- **Architecture-conformance policies**: 5 built-in (`import_cycles`, `cross_package`, `layer_bypass`, `coupling_ceiling`, `orphan_detection`) plus `[[policies.custom]]` Cypher policies in `.arch-policies.toml`.

---

## Pre-release

The repo's first commit is dated 2026-04-14. Anything before that is a private prototype.
