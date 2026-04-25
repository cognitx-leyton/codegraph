# codegraph

Index a TypeScript / Python codebase into a Neo4j property graph, then query architecture in Cypher. Designed as always-on context for Claude Code, Cursor, Codex, Aider, and other AI coding agents.

PyPI: [`cognitx-codegraph`](https://pypi.org/project/cognitx-codegraph/) — install with `pipx install cognitx-codegraph`.

Recognises NestJS controllers / injectables / modules, React components and hooks, TypeORM entities, GraphQL operations, FastAPI / Flask / Django routes, SQLAlchemy models, plus generic Python classes / decorators. Loads typed nodes + edges into Neo4j with no LLM in the pipeline — everything is AST + deterministic resolution.

## Quick start

```bash
pipx install cognitx-codegraph        # core; or `pipx install "cognitx-codegraph[python,mcp,watch,analyze]"` for all extras
cd /path/to/your/repo
codegraph init                         # scaffolds Neo4j docker-compose, slash commands, CI gate, .arch-policies.toml; runs first index
codegraph query "MATCH (c:Class) RETURN c.name LIMIT 5"
codegraph arch-check                   # exit 1 on architecture violations
```

`codegraph init` is the supported onboarding path — it asks 4-5 questions, writes everything you need, starts Neo4j, and runs the first index. See [`docs/init.md`](docs/init.md) for the full flow and flags.

## CLI

| Command | Purpose |
|---|---|
| `codegraph init` | Scaffold codegraph into a repo (interactive). Auto-detects + reuses the shared `codegraph-neo4j` container (starts it if stopped, creates it if missing). Pre-flights Docker presence + version with OS-aware install / upgrade suggestions. `--yes` for non-interactive, `--bolt-port` / `--http-port` for custom Neo4j ports, `--skip-docker`, `--skip-index`. |
| `codegraph index <repo>` | Walk the source, parse with tree-sitter, write the graph. Flags: `-p/--package` (repeatable), `--update` (SHA256 incremental), `--since <git-ref>` (diff-based), `--no-wipe`, `--no-export`, `--no-benchmark`, `--no-analyze`, `--skip-ownership`, `--max-files`, `--ignore-file`, `--json`. |
| `codegraph query <cypher>` | Run a Cypher query. `-n/--limit`, `--json`. |
| `codegraph arch-check` | Run architecture-conformance policies. Auto-scopes to configured packages; `--scope` / `--no-scope` overrides. Exits 1 on violations, 2 on config errors. |
| `codegraph validate` | Sanity-check the loaded graph (counts, orphans, schema). |
| `codegraph wipe` | `MATCH (n) DETACH DELETE n`. |
| `codegraph stats` | Quick node / edge counts. |
| `codegraph export` | Produce `graph.html` (interactive vis-network), `graph.json`, optional `graph.graphml` and `graph.cypher`. Runs after `index` unless `--no-export`. |
| `codegraph benchmark` | Token-reduction benchmark vs. raw source. Optional `--min-reduction` for CI gating. |
| `codegraph report` | Generate `GRAPH_REPORT.md` from Leiden community detection. Runs after `index` unless `--no-analyze`. |
| `codegraph watch` | File-system watcher; rebuilds on save. `--debounce`, `-p`. Requires the `[watch]` extra. |
| `codegraph hook install` / `uninstall` / `status` | Manage `post-commit` + `post-checkout` git hooks that re-index automatically. |
| `codegraph install <platform>` | Wire codegraph into an AI agent platform (writes rules file, registers MCP server, etc.). 14 platforms supported — see below. `--all` installs for every detected platform. |
| `codegraph uninstall <platform>` | Remove integration. Preserves shared rules sections (e.g. `AGENTS.md`) when other platforms still need them. |
| `codegraph repl` | Interactive Cypher REPL. Same as running `codegraph` with no args. |

## MCP server

Optional extra: `pipx install "cognitx-codegraph[mcp]"`. Console script `codegraph-mcp` runs a stdio FastMCP server with 16 tools. Read-only by default; the two write tools (`wipe_graph`, `reindex_file`) require `--allow-write`.

| Tool | Purpose |
|---|---|
| `query_graph(cypher, limit=20)` | Read-only Cypher (limit pushed into the query). |
| `describe_schema()` | Node labels, edge types, property keys. |
| `list_packages()` | All `:Package` nodes with file counts. |
| `find_class(name_pattern, limit=50)` | Substring search over `:Class.name`. |
| `find_function(name_pattern, limit=50)` | Substring search over `:Function`/`:Method`. Returns containing class for methods. |
| `describe_function(name, file=None, limit=50)` | Signature, file, callers/callees summary. |
| `callers_of_class(class_name, file=None, limit=50)` | Who instantiates / extends / injects a class. |
| `calls_from(name, max_depth=2)` | Outgoing CALLS graph from a method. |
| `callers_of(name, max_depth=2)` | Reverse CALLS graph. |
| `endpoints_for_controller(controller_name)` | NestJS / FastAPI / Flask / Django routes. |
| `files_in_package(name, limit=50)` | All files in a package. |
| `hook_usage(hook_name, limit=50)` | React components calling a hook. |
| `gql_operation_callers(operation_name, …)` | Who triggers a GraphQL query / mutation. |
| `most_injected_services(limit=20)` | Top NestJS DI providers. |
| `describe_group(name_or_id, kind=None, limit=50)` | Inspect `:EdgeGroup` hyperedges (protocol implementers, communities). |
| `wipe_graph(confirm=False)` | Destructive — requires `--allow-write` and `confirm=True`. |
| `reindex_file(path, package=None)` | Re-parse and upsert a single file. Requires `--allow-write`. |

Plus 29 prompt templates auto-registered from `queries.md` (one per Cypher example block).

## Schema

**Nodes**: `Package`, `File`, `Class`, `Method`, `Function`, `Interface`, `Endpoint`, `Column`, `GraphQLOperation`, `Event`, `Atom`, `EnvVar`, `Route`, `External`, `EdgeGroup`.

**Edges (selected)**: `IMPORTS`, `IMPORTS_SYMBOL`, `IMPORTS_EXTERNAL`, `DEFINES_CLASS`, `DEFINES_FUNC`, `DEFINES_IFACE`, `HAS_METHOD`, `HAS_COLUMN`, `EXPOSES`, `INJECTS`, `PROVIDES`, `EXPORTS_PROVIDER`, `EXTENDS`, `IMPLEMENTS`, `RENDERS`, `USES_HOOK`, `DECORATED_BY`, `CALLS`, `CALLS_ENDPOINT`, `HANDLES`, `HANDLES_EVENT`, `EMITS_EVENT`, `READS_ATOM`, `WRITES_ATOM`, `READS_ENV`, `RESOLVES`, `BELONGS_TO`, `MEMBER_OF`, `OWNED_BY`, `LAST_MODIFIED_BY`, `CONTRIBUTED_BY`, `TESTS`, `TESTS_CLASS`.

Every relationship carries `confidence` (`EXTRACTED` / `INFERRED` / `AMBIGUOUS`) and `confidence_score` (0.0-1.0). Filter low-confidence edges out of strict checks. See [`docs/confidence.md`](docs/confidence.md).

`:EdgeGroup` nodes model N-ary "hyperedges" — used for protocol implementers (auto-emitted during indexing) and Leiden communities (`codegraph report`). Members link via `MEMBER_OF`. See [`docs/hyperedges.md`](docs/hyperedges.md).

## Architecture conformance

`codegraph arch-check` runs five built-in policies plus any `[[policies.custom]]` Cypher you add to `.arch-policies.toml`:

1. **`import_cycles`** — file-level cycles of length 2-6.
2. **`cross_package`** — forbidden directional imports between packages.
3. **`layer_bypass`** — Controllers reaching Repositories without a Service in between.
4. **`coupling_ceiling`** — files importing more than N other files (default 20).
5. **`orphan_detection`** — functions / classes / atoms / endpoints with no inbound references. Configurable `exclude_prefixes` / `exclude_names` for test framework conventions.

Suppress individual violations with `[[suppress]]` entries (each requires a `reason`). Stale suppressions are flagged. CI integration: `.github/workflows/arch-check.yml` (scaffolded by `codegraph init`). Full reference in [`docs/arch-policies.md`](docs/arch-policies.md).

## AI platform integrations

`codegraph install <platform>` writes the appropriate rules file (e.g. `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursor/rules/codegraph.mdc`, `.github/copilot-instructions.md`), registers the MCP server, and tracks the install in `.codegraph/platforms.json` so partial uninstalls preserve shared sections.

| Platform | Subcommand | Rules file |
|---|---|---|
| Claude Code | `claude` | `CLAUDE.md` |
| Codex | `codex` | `AGENTS.md` |
| OpenCode | `opencode` | `AGENTS.md` |
| Cursor | `cursor` | `.cursor/rules/codegraph.mdc` |
| Gemini CLI | `gemini` | `GEMINI.md` |
| GitHub Copilot CLI | `copilot` | (MCP only) |
| VS Code Copilot Chat | `vscode` | `.github/copilot-instructions.md` |
| Aider | `aider` | `AGENTS.md` |
| OpenClaw | `claw` | `AGENTS.md` |
| Factory Droid | `droid` | `AGENTS.md` |
| Trae | `trae` | `AGENTS.md` |
| Kiro IDE | `kiro` | `AGENTS.md` |
| Google Antigravity | `antigravity` | `AGENTS.md` |
| Hermes | `hermes` | `AGENTS.md` |

Templates resolve `$NEO4J_BOLT_PORT`, `$NEO4J_HTTP_PORT`, `$PACKAGE_PATHS_FLAGS`, `$CONTAINER_NAME`, `$DEFAULT_PACKAGE_PREFIX`, `$CROSS_PAIRS_TOML`, `$PIPX_VERSION` to per-repo values.

## Incremental indexing

Two modes:

- **`--update`** — SHA256 content-addressed cache in `.codegraph-cache/` (auto-added to `.gitignore` by `init`). Files whose hash is unchanged are skipped. Stale entries are pruned on save. Cache is invalidated automatically on a package version bump.
- **`--since <git-ref>`** — re-index only files changed since the ref (`HEAD~1`, a tag, a SHA). Diffs the working tree, removes stale subgraphs for deleted/changed files, upserts the rest. Implies `--no-wipe`. Non-code files are filtered out before processing.

`codegraph watch` (debounced file-system watcher) and `codegraph hook install` (post-commit + post-checkout) both layer on top of `--update`.

## File extras

| Extra | Adds |
|---|---|
| `[python]` | `tree-sitter-python` — enables Python frontend. |
| `[mcp]` | `mcp` — enables `codegraph-mcp` stdio server. |
| `[watch]` | `watchdog` — enables `codegraph watch`. |
| `[analyze]` | `networkx`, `graspologic` — Leiden community detection for `codegraph report`. |
| `[benchmark]` | `tiktoken` — exact BPE counting for `codegraph benchmark` (otherwise chars/4 approximation). |
| `[repl]` | `prompt_toolkit` — history + tab-completion in REPL. |
| `[all]` | All of the above. |

## Configuration

`codegraph.toml` (or `[tool.codegraph]` in `pyproject.toml`) at the repo root:

```toml
[tool.codegraph]
packages       = ["packages/twenty-server", "packages/twenty-front"]
ignore_file    = ".codegraphignore"     # optional; auto-detected at repo root
neo4j_uri      = "bolt://localhost:7688"
neo4j_user     = "neo4j"
neo4j_password = "codegraph123"
```

`.codegraphignore` uses gitignore syntax with two extensions: `@route:<glob>` and `@component:<glob>` for path-based framework-feature suppression.

`.arch-policies.toml` configures `arch-check` — full schema in [`docs/arch-policies.md`](docs/arch-policies.md).

## Documentation

- [`docs/cli.md`](docs/cli.md) — full per-command reference: every flag, `--json` shape, exit codes, examples.
- [`docs/mcp.md`](docs/mcp.md) — full per-tool reference for the MCP server (17 tools).
- [`docs/schema.md`](docs/schema.md) — complete graph schema: 15 node types, 33 edge types, properties, indexing phases.
- [`docs/incremental.md`](docs/incremental.md) — `--update`, `--since`, `codegraph watch`, `codegraph hook install`.
- [`docs/platforms.md`](docs/platforms.md) — the 14 AI agent platform integrations.
- [`docs/init.md`](docs/init.md) — `codegraph init` flow, port flags, prompts, troubleshooting.
- [`docs/arch-policies.md`](docs/arch-policies.md) — policy reference, suppression syntax, custom-policy authoring.
- [`docs/confidence.md`](docs/confidence.md) — edge-level confidence labels and scores.
- [`docs/hyperedges.md`](docs/hyperedges.md) — `:EdgeGroup` model and the `describe_group` MCP tool.
- `queries.md` — canonical Cypher query catalogue (also auto-loaded as MCP prompt templates).
- `../CHANGELOG.md` — version-by-version shipped-feature log.
- `../ROADMAP.md` — session-to-session engineering handoff.

## Development

```bash
git clone https://github.com/cognitx-leyton/codegraph
cd codegraph/codegraph
python3 -m venv .venv
.venv/bin/pip install -e ".[python,mcp,watch,analyze,benchmark,repl,test]"
docker compose up -d
.venv/bin/python -m pytest tests/ -q   # 800+ tests, ~15s
```

Tests target 100% passing, zero warnings. Conventional commits (`feat(scope)`, `fix(scope)`, `docs(scope)`, `test(scope)`). Work lands on `dev`; `main` / `release` / `hotfix` are protected.

License: Apache-2.0.
