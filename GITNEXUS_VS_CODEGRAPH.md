# GitNexus vs Codegraph — Detailed Comparison Report

**Date:** 2026-05-08
**GitNexus version:** v1.6.3 (`abhigyanpatwari/GitNexus` @ HEAD)
**Codegraph version:** v0.1.112 (`cognitx-leyton/codegraph` @ HEAD)

---

## 1. Executive Summary

**GitNexus** and **codegraph** both index source codebases into a queryable knowledge graph, then expose that graph to AI coding agents via the Model Context Protocol (MCP). They are direct competitors in the "code-graph-for-LLM-agents" niche, but they have made very different bets:

| Dimension | GitNexus | Codegraph |
|---|---|---|
| **Implementation language** | TypeScript / Node.js (~242k LOC) | Python 3.10+ (~18k LOC) |
| **Source-code languages parsed** | **14** (TS, JS, Py, Java, Kotlin, C#, Go, Rust, PHP, Ruby, Swift, C, C++, Dart, COBOL) | **2** (TypeScript/TSX + Python) |
| **Database** | LadybugDB (KuzuDB-compatible, embedded native) | Neo4j 5.x (Docker container, Bolt) |
| **Ships a Web UI** | Yes — React + Sigma.js graph explorer + AI chat | No — static HTML export only |
| **Type-resolution system** | 14-phase fixpoint loop, cross-file propagation | Resolver only (path aliases, barrels, name fallback) |
| **Hybrid search (BM25 + embeddings)** | Yes — Reciprocal Rank Fusion with `arctic-embed-xs` | No — Cypher-only |
| **Multi-repo "groups"** | Yes — contract bridge, cross-repo impact | Per-repo namespacing only |
| **Architecture-conformance policies** | Not yet — planned | Yes — 5 built-in policies + CI gate |
| **Hyperedges / EdgeGroups** | Communities only (Leiden) | Protocol implementers + Leiden |
| **Confidence on every edge** | Yes — 0.5/0.9/0.95 tiers + reason field | Yes — EXTRACTED/INFERRED/AMBIGUOUS + numeric score |
| **MCP server** | Yes — 16 tools + 6 resources + 2 prompts | Yes — 17 tools (15 read + 2 write) |
| **Architectural focus** | **Breadth + retrieval** (multi-language, embeddings, web UI, evals) | **Depth + governance** (framework-aware schema, arch-check CI, ownership, dogfooding) |

**One-sentence summary:** GitNexus is a polyglot, retrieval-augmented, browser-renderable graph platform optimised for AI agents in heterogeneous monorepos. Codegraph is a TS/Python-focused, framework-aware, governance-oriented graph indexer optimised for architecture conformance and tight integration with multiple AI agent platforms.

---

## 2. Side-by-Side Comparison Table

### 2.1 Project metadata

| Attribute | GitNexus | Codegraph |
|---|---|---|
| Repository | `abhigyanpatwari/GitNexus` | `cognitx-leyton/codegraph` |
| First commit | Older — 1,371+ commits | 2026-04-14 — 49 commits (~5 weeks) |
| Current version | 1.6.3 | 0.1.112 |
| License | (per repo LICENSE) | (per repo LICENSE) |
| Maintainer | Akonlabs (founders offer SaaS + self-hosted enterprise) | Leyton CognitX (`@egouilliard-leyton`) |
| Distribution | npm (`gitnexus`), Docker (GHCR + Docker Hub, signed via Cosign) | PyPI (`cognitx-codegraph`), Docker Compose template |
| LOC (source) | ~242,000 TS + ~20–30k Python (eval) | ~18,400 Python |
| Top-level docs | README, ARCHITECTURE, AGENTS, CLAUDE, CHANGELOG, MIGRATION, RUNBOOK, GUARDRAILS, SECURITY, TESTING, type-resolution-system, type-resolution-roadmap, swift-ingestion-gaps, llms.txt | README, CLAUDE, CHANGELOG, ROADMAP, CODEOWNERS + 9 docs in `docs/` |
| Test count | 1,146+ tests in 53 (Vitest) | ~1,000+ tests in 43 files (pytest) |

### 2.2 Languages parsed

| Language | GitNexus | Codegraph |
|---|---|---|
| TypeScript | First-class | First-class (Stage 1) |
| TSX / JSX | First-class | First-class |
| JavaScript | First-class | Bundled into TS parser |
| Python | First-class | First-class (Stage 1 + Stage 2) |
| Java | First-class | — |
| Kotlin | First-class | — |
| C# | First-class | — |
| Go | First-class | Roadmap |
| Rust | First-class | Roadmap |
| PHP | First-class | — |
| Ruby | Partial (no named bindings) | — |
| Swift | Partial (Phase S blocked on tree-sitter-swift Node 22) | — |
| C / C++ | Partial (no imports/named bindings) | — |
| Dart | Partial (vendored grammar) | — |
| COBOL | Lexical / regex only | — |
| **Total** | **14** | **2** |

### 2.3 Pipeline architecture

| Aspect | GitNexus | Codegraph |
|---|---|---|
| Pipeline model | 12-phase DAG with explicit deps + topological sort | Sequential walk → parse → resolve → load |
| Named phases | scan → structure → markdown → cobol → parse → routes → tools → orm → crossFile → mro → communities → processes | walk → ts/py parse → cross-file resolve → load + ownership → analyze (Leiden) → export → benchmark |
| Parallelism | Node `worker_threads` pool (CPU-count workers, ~1500-file/8-MB sub-batches, exponential backoff) | Single-process sequential by default |
| Parser tech | tree-sitter native + WASM port (single capture-tag vocabulary across 14 langs) | tree-sitter native only (two concrete `Parser` classes — `TsParser`, `PyParser` — sharing `ParseResult` shape) |
| Language abstraction | Unified capture tags (`@definition.class`, `@call.name`, `@import.source`) downstream of every grammar | Two separate parsers; intentional non-abstraction (commit `154954c` rationale) |
| Optional native grammars | Skippable via `GITNEXUS_SKIP_OPTIONAL_GRAMMARS=1` | All grammars Python-pip-installed |

### 2.4 Storage / database

| Aspect | GitNexus | Codegraph |
|---|---|---|
| Database engine | LadybugDB (formerly KuzuDB) — embedded native graph DB with built-in vector support | Neo4j 5.24-community (Docker container) |
| Storage location | `<repo>/.gitnexus/lbug/` (binary), `lbug.wal`, `lbug.lock`, `meta.json` | Inside Neo4j data volume; default Bolt port `7688` |
| Query language | Cypher | Cypher (OpenCypher dialect) |
| Multi-repo scoping | Global registry `~/.gitnexus/registry.json`, MCP server discovers all | Single Neo4j; node IDs namespaced per-repo via `--repo-name` (v0.1.103+); shared `codegraph-neo4j` container (v0.1.100+) |
| Vector / embedding column | Yes — separate `Embedding` node table (FLOAT32[384]) | No |
| Single-writer locking | Yes — `lbug.lock` file | Neo4j handles concurrency itself |
| WASM build | Yes — but web UI talks to backend, no in-browser persistence | N/A |

### 2.5 Schema

| Aspect | GitNexus | Codegraph |
|---|---|---|
| Node types | 35–44 (incl. type-system nodes, framework, embedding, process, route, tool, section, community) | 20 first-class labels (+ stacked labels like `:File:TestFile`, `:Class:Controller`) |
| Edge types | 21 (CONTAINS, DEFINES, CALLS, IMPORTS, EXTENDS, IMPLEMENTS, HAS_METHOD, HAS_PROPERTY, ACCESSES r/w, METHOD_OVERRIDES, METHOD_IMPLEMENTS, MEMBER_OF, STEP_IN_PROCESS, HANDLES_ROUTE, FETCHES, HANDLES_TOOL, ENTRY_POINT_OF, …) | ~33 (BELONGS_TO, DEFINES_CLASS/FUNC/IFACE, HAS_METHOD/COLUMN, IMPORTS, IMPORTS_SYMBOL, EXTENDS, IMPLEMENTS, INJECTS, PROVIDES, EXPORTS_PROVIDER, CALLS, CALLS_ENDPOINT, RENDERS, USES_HOOK, RESOLVES, HANDLES_EVENT, EMITS_EVENT, READS/WRITES_ATOM, READS_ENV, DECORATED_BY, OWNED_BY, LAST_MODIFIED_BY, CONTRIBUTED_BY, TESTS, RELATES_TO, MEMBER_OF, …) |
| Per-edge confidence | `confidence: float` + `reason: string` (e.g., `'import-resolved'`, `'global'`, `'same-file'`) | `confidence: 'EXTRACTED'/'INFERRED'/'AMBIGUOUS'` + `confidence_score: 0.0–1.0` |
| Confidence tiers | T1 = 0.95 (same-file symbol table); T2 = 0.9 (import-scoped); T3 = 0.5 (global fallback) | Direct=1.0, alias=0.9, workspace=0.85, barrel=0.8, name-fallback=0.5; CALLS: self=1.0, super=0.7, DI=0.6, bare=0.5 |
| Hyperedges | `Community` nodes with `MEMBER_OF` edges; cohesion score | `:EdgeGroup` nodes with `MEMBER_OF` (kinds: `protocol_implementers`, `community`) |
| Framework-specific node types | `Route`, `Tool` (MCP/RPC), `Section` (markdown) | `:Endpoint`, `:Column`, `:GraphQLOperation`, `:Atom`, `:Hook`, `:EnvVar`, `:Route`, `:External`, `:Decorator`, `:Author`, `:Team`, `:Document`, `:DocumentSection`, `:Concept`, `:Decision`, `:Rationale` |

### 2.6 Framework awareness

| Framework | GitNexus | Codegraph |
|---|---|---|
| NestJS | — (decorator-aware via heuristics) | First-class — `@Controller`/`@Injectable`/`@Module`/`@Resolver`, DI, module graph |
| React | JSX detected via `_jsx` calls | First-class — components, hooks (`USES_HOOK`), JSX RENDERS edges |
| Next.js | First-class entry-point scoring (pages/app/API) | Detected at package level |
| Expo Router | First-class entry-point scoring | — |
| TypeORM | — | First-class — `@Entity`/`@Column`/`@Relation` → `:Entity`, `:Column` |
| GraphQL | — | First-class — `@Resolver`, `@Query`/`@Mutation`/`@Subscription` → `:GraphQLOperation` |
| Prisma | First-class (schema + ORM) | — |
| Supabase | First-class (client multiplier) | — |
| Express / Node MVC | First-class entry-point scoring | — |
| FastAPI / Flask / Django | Heuristic decorator detection | First-class (Stage 2) — `@app.get`/`route()` → `:Endpoint`; SQLAlchemy/Django models → `:Column` |
| Odoo | — | Stage 2 |
| State management | — | Jotai/Recoil/Zustand/Redux/Xstate detected |
| UI / styling | — | Tailwind, Emotion, styled-components, shadcn, MUI, Chakra |

### 2.7 CLI surface

| Command theme | GitNexus | Codegraph |
|---|---|---|
| One-time setup | `gitnexus setup` (auto-write MCP config) | `codegraph init` (scaffold .claude, arch-policies, docker-compose) |
| Indexing | `analyze [path]` (incremental by default; `--force`, `--embeddings`, `--skills`, `--skip-git`, `--worker-timeout`) | `index <repo>` (`-p`, `--update`, `--since`, `--no-wipe`, `--skip-ownership`, `--repo-name`, `--extract-docs`, `--extract-markdown`) |
| Direct query | `query`, `cypher`, `context`, `impact`, `detect_changes`, `rename` | `query`, `repl` (interactive Cypher) |
| Validation / governance | (none built-in; planned) | `validate`, `arch-check`, `audit` (agent-driven self-check) |
| Stats / insight | `list`, `status` | `stats`, `report` (Leiden communities), `benchmark` (token reduction) |
| Visualization | `serve` (HTTP API for web UI) | `export` (HTML vis-network + GraphML/Cypher dump) |
| Watchers / hooks | (PostToolUse hooks via Claude Code only) | `watch`, `hook install/status/uninstall` |
| Multi-repo | `group create/add/remove/list/sync/contracts/query/status` (8 group subcommands) | `index --repo-name` only |
| Cleanup | `clean`, `clean --all` | `wipe` |
| Wiki / agent prompt gen | `wiki` (LLM-generated AGENTS.md/CLAUDE.md/skills) | (no equivalent) |
| Remote repo | (relies on local checkout) | `clone <git-url>` (v0.1.102+) |
| Platform install | `setup` covers Cursor + Claude Code + Codex | `install <platform>` covers **14 platforms** + matching `uninstall` |
| MCP server | `mcp` | `codegraph-mcp` |
| Total commands | ~16 (incl. group subcommands) | 16 top-level subcommands |

### 2.8 MCP server tools

| MCP capability | GitNexus | Codegraph |
|---|---|---|
| Tools | 16 — `list_repos`, `query` (hybrid), `cypher`, `context` (360°), `impact`, `detect_changes`, `rename`, `api_impact`, `route_map`, `tool_map`, `shape_check`, group_* | 17 — `query_graph`, `describe_schema`, `list_packages`, `callers_of_class`, `endpoints_for_controller`, `files_in_package`, `hook_usage`, `gql_operation_callers`, `most_injected_services`, `find_class`, `find_function`, `describe_function`, `calls_from`, `callers_of`, `describe_group` (read-only) + `reindex_file`, `wipe_graph` (write, gated by `--allow-write`) |
| Resources | 6 — `gitnexus://repos`, `repo/{name}/context`, `clusters`, `processes`, `schema`, plus group resources | None |
| Prompts | 2 — `detect_impact`, `generate_map` | 29 — auto-loaded from `queries.md` (e.g., "find React hook usage", "list NestJS endpoints", etc.) |
| Transport | stdio | stdio only (no HTTP exposed) |
| Multi-repo discovery | Via `~/.gitnexus/registry.json` | Single Neo4j; queries optionally scope by repo name property |
| Read-only by default | Yes (annotations) | Yes (write tools require `--allow-write`) |
| Agent integrations | Claude Code (full + hooks + skills), Cursor, Codex, Windsurf, OpenCode | 14 platforms — Claude Code, Codex, Cursor, Gemini CLI, Copilot, VS Code Copilot Chat, Aider, OpenCode, OpenClaw, Factory Droid, Trae, Kiro IDE, Google Antigravity, Hermes |
| Auto-installed skills | 4 (Exploring, Debugging, Impact Analysis, Refactoring) + per-community `--skills` | Slash commands installed by `init` (graph, graph-refresh, blast-radius, dead-code, who-owns, trace-endpoint, arch-check) |

### 2.9 Type resolution

| Aspect | GitNexus | Codegraph |
|---|---|---|
| System | 14-phase explicit type-resolution roadmap (Phases 7–14, plus P.5 / S still open) | None — only import resolution + name-fallback |
| Per-file env | Per-file `TypeEnvironment`; bindings collected in single AST walk; fixpoint resolves chains | None — tree-sitter capture only |
| Tier 0 | Explicit annotations (declarations + parameters) | n/a |
| Tier 0b/0c | For-loop element types, pattern bindings (if-let/match) | n/a |
| Tier 1 | Constructor / initialiser inference | n/a |
| Tier 2 | Assignment-chain propagation (fixpoint, max 10 iterations) | n/a |
| Phase 9C | Unified fixpoint over `callResult`, `copy`, `fieldAccess`, `methodCallResult` | n/a |
| Phase 14 | Cross-file binding propagation (named imports for TS/JS/Py/Kotlin/Rust/PHP/Java/C#; wildcard for Go/Ruby/C/C++/Swift) | Not implemented |
| Container descriptors | Map/Dict K/V, List/Set element type | n/a |
| Comment-based fallbacks | JSDoc (TS/JS), PHPDoc, YARD (Ruby) | n/a |
| Effect on call resolution | `user.save()` resolves to `User#save` over `Repo#save` because `user: User` propagates | Calls resolved by class context + import scope only |

### 2.10 Search

| Aspect | GitNexus | Codegraph |
|---|---|---|
| Keyword search | Yes — LadybugDB FTS BM25 (Files, Functions, Classes, Methods, Interfaces, Properties, Routes, Tools, Sections) | No (Cypher `CONTAINS` substring on name properties) |
| Embeddings | Yes — `Snowflake/snowflake-arctic-embed-xs` (384D, 22M params, ~90 MB), HuggingFace transformers.js | No |
| Fusion | Reciprocal Rank Fusion, K = 60 | n/a |
| Embedding incremental | SHA1 content-hash cached across re-indexes; skipped if >50k nodes | n/a |
| Embedding storage | `Embedding` node table, FLOAT32[384] | n/a |
| Process-grouped results | Yes — `query` returns `processes` + `process_symbols` + `definitions` | n/a |

### 2.11 Incremental / watch

| Mechanism | GitNexus | Codegraph |
|---|---|---|
| Index staleness detection | `meta.json.lastCommit` vs `HEAD` early-exit | n/a (re-runs always wipe unless `--no-wipe`) |
| Per-file content hash | (planned) | Yes — `--update` with SHA-256 cache (`.codegraph-cache/`) |
| Git diff incremental | (planned) | Yes — `--since <ref>` re-indexes only changed files, cascade-deletes stale subgraphs |
| Filesystem watcher | (no built-in `watch`; staleness detected via PostToolUse hook on commit) | Yes — `codegraph watch` (watchdog), debounced 3.0s |
| Git hooks | `post-commit` trigger via Claude Code PostToolUse | `hook install` (post-commit + post-checkout) |
| Cross-phase tree cache | Yes — Python, C#: parse phase writes Trees, scope-resolution reads | n/a |
| Embedding cache | Yes — restored from prior index | n/a |

### 2.12 Architecture-conformance

| Aspect | GitNexus | Codegraph |
|---|---|---|
| Built-in policies | None (planned framework) | 5 — `import_cycles`, `cross_package`, `layer_bypass`, `coupling_ceiling`, `orphan_detection` |
| Custom Cypher policies | Possible via raw Cypher | Yes — `[[policies.custom]]` in `.arch-policies.toml` |
| Suppression syntax | n/a | `[[policies.<name>.suppress]]` blocks (sample, reason) |
| CI integration | Manual via `gitnexus query/cypher` | First-class — scaffolded `.github/workflows/arch-check.yml` running `neo4j:5.24-community` service container, exit-code gating, JSON report artifact |
| Operational guardrails | `GUARDRAILS.md` — operational "Signs" (audit rules) | `arch-policies.md` per-policy false-positive guidance |

### 2.13 Ownership / blame

| Aspect | GitNexus | Codegraph |
|---|---|---|
| Git blame integration | No | Yes — `:Author` nodes; `:OWNED_BY`, `:LAST_MODIFIED_BY`, `:CONTRIBUTED_BY` edges |
| CODEOWNERS parsing | No | Yes — `:Team` nodes from CODEOWNERS file |
| Slash command | n/a | `/who-owns <path>` — latest author + top-5 contributors + CODEOWNERS team |
| Cost | n/a | ~30–50% of total index time (skip via `--skip-ownership`) |

### 2.14 Endpoint / route tracing

| Aspect | GitNexus | Codegraph |
|---|---|---|
| Route extraction | Next.js, Expo, PHP frameworks, decorator-based | NestJS, FastAPI, Flask, Django |
| Edge type | `HANDLES_ROUTE` | `HANDLES`, `CALLS_ENDPOINT` |
| Tracing tool | `route_map`, `api_impact`, `shape_check` (response-shape vs consumer property mismatch detection) | `/trace-endpoint <substr>` slash command (4-hop transitive `CALLS` from handler) |
| Pre-change impact | `api_impact` — pre-analyse breakage from API handler change | `arch-check` cross-package or `query_graph` Cypher |

### 2.15 Visualization & UI

| Aspect | GitNexus | Codegraph |
|---|---|---|
| Browser UI | **Yes** — React 18 + Vite + Tailwind v4; Sigma.js + Graphology WebGL graph; AI chat (LangChain ReAct embedded) | No browser server |
| Static export | Output via `serve` HTTP API | `codegraph export` → `graph.html` (vis-network), `graph.json`, `graph.graphml`, `graph.cypher` |
| Community visualisation | Convex hulls per Leiden cluster | Convex hulls per Leiden cluster (v0.1.105+) |
| In-browser parsing | WASM tree-sitter for upload mode (limited to ~5k files) | n/a |
| Backend mode | Auto-detects running `gitnexus serve`, browses CLI-indexed repos | n/a |

### 2.16 Multi-repo

| Aspect | GitNexus | Codegraph |
|---|---|---|
| Cross-repo modelling | First-class "groups" — bridge DB at `.gitnexus/group-bridge.lbug` storing contracts + cross-repo edges | Single Neo4j with namespaced node IDs |
| Contract registry | Yes — `contracts.json` per group, computed via `group sync` (`{provider_repo, symbol, consumer_repo, consumer_symbol, confidence}`) | None |
| Cross-repo impact analysis | Yes — `cross-impact.ts` walks local CALLS, then traverses contract edges | No |
| Group RRF fusion | `query repo: "@groupName"` merges per-repo results via RRF | n/a |
| Group MCP resources | `gitnexus://group/{name}/contracts`, `…/status` | n/a |

### 2.17 Security & deployment

| Aspect | GitNexus | Codegraph |
|---|---|---|
| Container distribution | Cosign-signed multi-image (`ghcr.io/abhigyanpatwari/gitnexus`, `…/gitnexus-web`, Docker Hub mirror), Web 4173, API 4747 | Docker Compose template (Neo4j 5.24-community), default Bolt 7688 |
| SBOM / SLSA | SLSA v1 build-provenance attestations on every release tag | None advertised |
| Kubernetes | Bundled `ClusterImagePolicy` for Sigstore enforcement | No |
| CI security scanning | CodeQL + dependency-review + Gitleaks + zizmor + Trivy + OpenSSF Scorecard | `arch-check` workflow + `audit-prompt-integrity` workflow |
| Secrets posture | `SECURITY.md`, `GUARDRAILS.md` ("Signs"), automated weekly scans | CODEOWNERS for privileged surfaces |
| MCP transport | stdio only — no HTTP/network exposure | stdio only |

### 2.18 Testing

| Aspect | GitNexus | Codegraph |
|---|---|---|
| Framework | Vitest | pytest 8.0+ |
| Test files | 53 (308 total `.test.ts`/`.spec.ts` files counting both packages) | 43 |
| Test cases | 1,146+ | ~1,000+ |
| Integration tests | 178+ resolver tests across 9 langs; `--pool=forks` for isolated LadybugDB instances | Fixture-based end-to-end indexing tests |
| Eval harness | **Yes** — `eval/` Python SWE-bench harness with `baseline` / `native` / `native_augment` modes; eval-server daemon; per-(repo, commit) cache | **Yes (different shape)** — `codegraph audit` agent-driven extraction self-check; `codegraph benchmark` token-reduction measurement |

### 2.19 Configuration & ignore

| Aspect | GitNexus | Codegraph |
|---|---|---|
| Config file | `.gitnexus/meta.json` (auto), `~/.gitnexus/registry.json` (global) | `codegraph.toml` or `[tool.codegraph]` in `pyproject.toml` |
| Env vars | `GITNEXUS_SKIP_OPTIONAL_GRAMMARS`, `GITNEXUS_WORKER_*`, `HF_ENDPOINT`/`HF_TOKEN`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `PROF_SCOPE_RESOLUTION` | `CODEGRAPH_NEO4J_URI`, `CODEGRAPH_NEO4J_USER`, `CODEGRAPH_NEO4J_PASS`, `ANTHROPIC_API_KEY` (for `--extract-markdown`) |
| Ignore mechanism | `.gitignore` (via `ignore` npm package) + tsconfig/go.mod/composer.json/.csproj exclusions | `.codegraphignore` (gitignore-style) **plus** built-in defaults (`node_modules`, `dist`, `.next`, `*.d.ts`, `*.stories.*`) and route-pattern syntax (`@route:/admin/*`, `@component:*Admin*`) |
| Custom ignore file | No (only `.gitignore`) | Yes (`.codegraphignore`) |

### 2.20 Notable / unique features

| Feature | GitNexus | Codegraph |
|---|---|---|
| Browser-renderable graph + AI chat | ✓ | — |
| Hybrid BM25 + semantic search with RRF | ✓ | — |
| Multi-repo groups + contract registry | ✓ | — |
| Cross-file type-resolution fixpoint (14 phases) | ✓ | — |
| LLM-generated wiki / AGENTS.md from communities | ✓ | — |
| Cosign-signed Docker, SLSA attestations | ✓ | — |
| 14-language parser breadth | ✓ | — |
| SWE-bench-style eval harness | ✓ | — |
| Worker-thread pool with sub-batching | ✓ | — |
| Architecture-conformance CI gate (5 policies) | — | ✓ |
| Git blame + CODEOWNERS in graph | — | ✓ |
| 14-platform AI agent installer | — | ✓ |
| Framework-aware schema (NestJS DI, React hooks, TypeORM, GraphQL) | — | ✓ |
| Architecture self-audit via agent (`codegraph audit`) | — | ✓ |
| `:EdgeGroup` for protocol implementers (not just communities) | — | ✓ |
| Token-reduction benchmark with CI threshold | — | ✓ |
| `.codegraphignore` with route/component patterns | — | ✓ |
| 29 MCP prompt templates auto-loaded from `queries.md` | — | ✓ |
| Semantic Markdown extraction (Concepts/Decisions/Rationale) | — | ✓ |
| Audio/video transcription + PDF ingestion | — | ✓ |
| Slash-command power tools (`/blast-radius`, `/dead-code`, `/who-owns`, `/trace-endpoint`, `/arch-check`, `/graph`, `/graph-refresh`) | — | ✓ |
| Dogfoods itself (CLAUDE.md guides agents to query the live graph) | — | ✓ |

---

## 3. Detailed Comparison by Dimension

### 3.1 Project purpose & positioning

**GitNexus** positions itself as a "nervous system for agent context" — the substrate that lets every AI editor (Cursor, Claude Code, Codex, Windsurf, OpenCode, Cline, Roo Code) reach into a codebase and pull pre-computed *relational* intelligence (clusters, processes, blast radius) instead of forcing the LLM to explore. Tagline: "Like DeepWiki, but deeper." Marketed as enabling **analysis** rather than just **understanding**. Akonlabs offers SaaS + self-hosted enterprise around it.

**Codegraph** positions itself as a "code knowledge graph for AI coding agents" — explicitly framing the alternative as vector embeddings ("vector search finds lexically similar snippets, not architecturally relevant ones") and arguing for *structural* questions answered in single-digit milliseconds via Cypher. Built by Leyton CognitX. Strong governance angle: architecture-conformance policies enforced in CI, ownership tracked in graph, audit pipeline for self-validation.

The pitches overlap heavily but differ in centre-of-gravity. GitNexus reads like a retrieval-system pitch (find the right code for the LLM); codegraph reads like a static-analysis-meets-agent pitch (govern the codebase + make agents architecturally aware).

### 3.2 Architecture & engineering scale

GitNexus is roughly **13× larger** than codegraph by lines of code (~242k TS vs ~18k Py). It also predates codegraph by a substantial margin (1,371 commits vs 49). This is visible in:

- A formalised **12-phase DAG** ingestion pipeline with explicit dependency declaration and topological-sort validation (`/tmp/GitNexus/gitnexus/src/core/ingestion/pipeline-phases/runner.ts`).
- A **worker-thread pool** with sub-batching, exponential backoff, sequential fallback (~1500-file/8 MB batches).
- Two parallel resolution paths (legacy Call-Resolution DAG vs Scope-Resolution Pipeline RFC #909 Ring 3) running side-by-side with a CI parity gate during migration.
- **Embedded native database** (LadybugDB) with a WAL, single-writer lock, vector tables, and FTS indexes.
- **WASM port** of the entire stack for the in-browser upload mode.

Codegraph's pipeline is **straightforward sequential** (walk → ts/py parse → resolver → loader → optional ownership/analyze/export/benchmark). It explicitly rejected language-agnostic abstraction (commit `154954c` rationale: two concrete parsers sharing a `ParseResult` shape is the chosen design). It runs in a single Python process and connects to Neo4j via Bolt — no native database, no worker pool, no WASM.

The trade-off is clean: GitNexus's complexity buys polyglot breadth + parallelism + browser distribution. Codegraph's simplicity buys faster iteration on framework awareness + governance + tighter Python/TS focus.

### 3.3 Language coverage

GitNexus parses **14 languages** with a unified tree-sitter capture-tag vocabulary (`@definition.class`, `@call.name`, `@import.source`, `@heritage.extends`, `@property.access`, `@pattern.binding`). Each language's grammar maps its AST nodes to these tags so downstream extraction is language-agnostic. Coverage matrix (per `type-resolution-system.md`) is granular: TS/JS/Py/Java/Kotlin/C# are full first-class; Swift has gaps blocked on tree-sitter-swift Node 22; C/C++ are partial; COBOL is regex-only.

Codegraph parses **2 languages** (TypeScript/TSX/JS via one parser, Python via another). It deliberately chose depth over breadth — the README/ROADMAP/CLAUDE.md all emphasise this. Go and Rust are roadmap items but not yet shipped.

For a polyglot monorepo (e.g., a Java backend + TypeScript frontend + Python data pipeline), only GitNexus is currently viable. For a Python-or-TypeScript-only shop (e.g., a NestJS + React monorepo, or a FastAPI + Next.js stack), codegraph's framework awareness arguably gives **more** structural insight per language.

### 3.4 Type resolution

This is GitNexus's clearest technical lead. It has a documented **14-phase type-resolution roadmap** (`type-resolution-system.md`, `type-resolution-roadmap.md`), with delivered phases including:

- **Phase 7**: For-each element types (extract T from `for x in List[T]`)
- **Phase 8**: Constructor/initialiser inference (`new User()` → `User`)
- **Phase 9**: Call-result variable binding (`const u = getUser()` → `u: User`)
- **Phase 9C**: Unified fixpoint loop over `callResult` / `copy` / `fieldAccess` / `methodCallResult` chains, max 10 iterations, handles arbitrary-depth mixed chains and reverse declaration order
- **Phase 14**: Cross-file binding propagation (named imports for 8 langs, wildcard for 5)

The practical effect (quoted from `type-resolution-system.md`): when code contains `user.save()`, the resolver determines that `user: User` and prefers `User#save` over `Repo#save`. This dramatically improves CALLS-edge precision.

**Codegraph has no type-resolution system.** Its `resolver.py` only handles import resolution (path aliases, barrels, workspace, name-fallback). Call resolution falls back to receiver-type guessing (self/this=1.0, super=0.7, DI field=0.6, bare=0.5). For Python and TypeScript codebases that lean heavily on type annotations, this leaves accuracy on the table.

### 3.5 Search

GitNexus shipped **hybrid BM25 + semantic search** with Reciprocal Rank Fusion (K=60), backed by the `Snowflake/snowflake-arctic-embed-xs` embedding model (384-dim, 22M params, ~90 MB). BM25 indexes are LadybugDB FTS (always fresh); embeddings live in a separate `Embedding` node table and are SHA1-cached across re-indexes. The `query` MCP tool returns process-grouped results with `sources: ['bm25', 'semantic']` provenance.

Codegraph **rejects embeddings** as a design stance — the README explicitly contrasts itself against vector search and proposes Cypher as the alternative. Search inside codegraph means: open-ended `query_graph(cypher)`, or use one of the 15 typed read tools (`find_class`, `find_function`, etc.) which essentially are pre-baked Cypher with `CONTAINS` substring matching. There are 29 MCP prompt templates auto-loaded from `queries.md` to lower the bar.

Whether this is a feature or a bug is philosophical. For "find me code semantically similar to X" GitNexus wins; for "show me every controller that calls a repository without going through a service" codegraph wins.

### 3.6 Governance / architecture conformance

This is codegraph's clearest lead. **5 built-in policies**, scaffolded `.arch-policies.toml`, scaffolded GitHub Actions workflow (`arch-check.yml`) that spins up `neo4j:5.24-community` as a service container, runs `codegraph index` then `codegraph arch-check`, exit-code gates the merge:

1. **`import_cycles`** — File-level import cycles (length 2–6). Cypher: `MATCH path = (a:File)-[:IMPORTS*2..6]->(a) RETURN ...`
2. **`cross_package`** — Forbidden cross-package imports (configured pairs).
3. **`layer_bypass`** — Controllers reaching Repositories without a Service intermediary.
4. **`coupling_ceiling`** — Files with > N imports.
5. **`orphan_detection`** — Unused functions/classes/atoms/endpoints, with framework-entry-point exclusions (`@app.command`, `@pytest.fixture`, `@mcp.tool`).

Suppression is first-class via `[[policies.<name>.suppress]]` blocks with `sample` and `reason` fields. Custom Cypher policies are first-class via `[[policies.custom]]` blocks.

GitNexus does **not** have an equivalent today. `GUARDRAILS.md` describes operational "Signs" (audit rules in prose, not code-enforced). The infrastructure exists (cycle detection via Tarjan SCCs, Cypher-queryable schema) but no opinionated framework or CI gate ships out of the box.

### 3.7 Ownership / git integration

Codegraph integrates **git blame** and **CODEOWNERS** directly into the graph: `:Author` nodes (one per unique commit author email), `:Team` nodes (from CODEOWNERS), edges `:OWNED_BY`, `:LAST_MODIFIED_BY`, `:CONTRIBUTED_BY` on every `:File` node. The `/who-owns <path>` slash command answers in one query: latest author + top-5 contributors + CODEOWNERS team. Cost: ~30–50% of total index time (skip via `--skip-ownership`).

GitNexus tracks `lastCommit` for staleness detection only; no per-file blame, no CODEOWNERS, no contributor graph. The infrastructure for staleness post-commit hooks exists (Claude Code PostToolUse hooks), but ownership is out of scope.

### 3.8 Multi-repo

GitNexus has first-class **groups**: a bridge DB at `.gitnexus/group-bridge.lbug`, a contracts registry computed by `group sync` (each row: `{provider_repo, symbol, consumer_repo, consumer_symbol, confidence}`), cross-repo impact walks via `cross-impact.ts`, and group-aware querying (`query repo: "@groupName"` merges per-repo results via RRF). Eight group subcommands (`create/add/remove/list/sync/contracts/query/status`).

Codegraph's multi-repo story is namespace-only: `codegraph index --repo-name=foo` namespaces node IDs to prevent collisions when multiple repos write to one Neo4j (v0.1.103+); the shared `codegraph-neo4j` container (v0.1.100+) makes this ergonomic. There's no contract layer, no cross-repo impact tool. For a service-oriented monorepo or a federation of services that share a Neo4j instance, GitNexus's groups model is significantly more powerful.

### 3.9 Web UI / visualization

GitNexus ships **a real browser UI**: `gitnexus-web/` (React 18 + Vite + Tailwind v4 + Sigma.js + Graphology WebGL + LangChain ReAct embedded chat). Users can either drag-drop a repo (WASM tree-sitter parses in-browser, limited to ~5k files) or connect to a local `gitnexus serve` daemon and browse all CLI-indexed repos.

Codegraph's visualization is **static HTML export** only: `codegraph export` produces `graph.html` (vis-network force-directed, with sidebar toggle, search, filter, convex hulls per Leiden community), plus `graph.json`/`graph.graphml`/`graph.cypher` dumps for downstream tooling (Gephi, yEd, custom React app). Interactive querying happens via `codegraph query` CLI or `codegraph repl` (Cypher shell with prompt_toolkit history + tab-complete).

For demos and onboarding, GitNexus's browser UI is a meaningful differentiator. For everyday agent work, the difference is mostly cosmetic — both projects expect the user's editor (Claude Code, Cursor) to drive interaction via MCP.

### 3.10 Incremental indexing

Codegraph has the more flexible incremental story:

- **`--update`** SHA-256 content-addressed cache (`.codegraph-cache/`). Hashes each file; cache hits skip parse; cache misses parse + write back. Manifest tracks per-file hash; stale entries pruned on save. Implies `--no-wipe` and `--skip-ownership`.
- **`--since <git-ref>`** Git-diff incremental. `git diff --name-status <ref>` → modified/deleted file sets → re-indexes only touched files → cascade-deletes stale subgraphs before upsert.
- **`codegraph watch`** Recursive filesystem watcher (watchdog, debounced 3.0s default), filters to `.py`/`.ts`/`.tsx`, skips dotfiles and `node_modules`/`.venv`. Rebuilds via `codegraph index --since HEAD`.
- **`codegraph hook install`** Git `post-commit` and `post-checkout` hooks for auto-reindexing.

GitNexus's incremental story is currently **commit-level**: `meta.json.lastCommit` vs `HEAD` early-exit (skip the whole index if nothing's changed); embedding cache restored across re-indexes; cross-phase tree cache (Python, C#) writes Trees in parse phase for scope-resolution to skip re-parse. Per-file incremental re-parsing is tracked as future work. Staleness detection happens post-commit via Claude Code PostToolUse hook.

### 3.11 MCP server

The two MCP surfaces are roughly comparable in size (16 vs 17 tools) but optimised for different things:

GitNexus tools lean toward **end-to-end agent workflows**: `query` (hybrid search + process grouping), `context` (360° symbol view), `impact` (blast radius with risk tiering), `detect_changes` (git diff → graph), `rename` (multi-file coordinated rename, dry-run mode), `route_map` (API → handler → consumer), `api_impact` (pre-change breakage), `shape_check` (response shape vs consumer property mismatch). Plus 6 resources (`gitnexus://repos`, `…/clusters`, `…/processes`, `…/schema`, group resources) and 2 prompts (`detect_impact`, `generate_map`).

Codegraph tools lean toward **graph primitives**: `query_graph` (raw Cypher escape hatch), `describe_schema`, `list_packages`, `callers_of`/`calls_from`/`callers_of_class` (typed graph walks), `endpoints_for_controller`, `hook_usage`, `gql_operation_callers`, `most_injected_services`, `find_class`/`find_function`, `describe_function`, `describe_group` (introspect EdgeGroups). Plus two write tools (`reindex_file`, `wipe_graph`) gated by `--allow-write`. **29 prompt templates** are auto-loaded from `queries.md` and surface as Claude Desktop slash commands.

Roughly: GitNexus's tools feel like a higher-level API ("show me what to worry about"); codegraph's tools feel like a lower-level kit ("answer this query, then this query, then this query").

### 3.12 Platform integrations

Codegraph has a clear lead here. `codegraph install <platform>` supports **14** platforms (Claude Code, Codex, Cursor, Gemini CLI, Copilot, VS Code Copilot Chat, Aider, OpenCode, OpenClaw, Factory Droid, Trae, Kiro IDE, Google Antigravity, Hermes), with manifest-aware uninstall that preserves shared rules still in use by other platforms.

GitNexus's `setup` covers Claude Code (full + skills + hooks), Cursor (MCP + skills, no hooks), Codex (full), Windsurf (MCP only), OpenCode (MCP + skills) — 5 platforms. The Claude Code integration is **deeper** (PreToolUse hooks inject graph context into searches; PostToolUse hooks detect staleness post-commit), but the breadth is narrower.

### 3.13 Documentation

Both projects are well-documented. GitNexus has the larger documentation surface (15+ top-level docs including comprehensive ARCHITECTURE.md, AGENTS.md, GUARDRAILS.md, MIGRATION.md, RUNBOOK.md, SECURITY.md, TESTING.md, type-resolution-roadmap.md, type-resolution-system.md, swift-ingestion-gaps.md, llms.txt). Codegraph has a smaller but tightly organised set (README + CLAUDE + CHANGELOG + ROADMAP + 9 reference docs in `codegraph/docs/`: cli, mcp, schema, confidence, hyperedges, arch-policies, incremental, platforms, init).

GitNexus docs read like a mature open-source project (engineering RFCs, decision rationale, weekly cadence). Codegraph docs read like a fast-moving startup (per-wave changelog, ROADMAP as session handoff, dogfooding-first slash command guides).

### 3.14 Maturity & sustainability

GitNexus is the more mature project: 1,371 commits, weekly release cadence, signed Docker images with SLSA attestations, OpenSSF Scorecard, weekly Trivy/CodeQL scans, secret scanning in CI, Sigstore policy bundle for Kubernetes, community Discord, third-party integrations (`pi-gitnexus`, `gitnexus-stable-ops`), trending on Trendshift, founder commercial offering (akonlabs.com). **Production-ready signals are clear.**

Codegraph is younger: 49 commits over ~24 days, currently v0.1.112 with `Development Status :: 3 - Alpha` in the package classifiers. The pace is rapid (~15–20 minor versions per week) and the iteration loop is tight (CLAUDE.md instructs agents to use the slash commands and dogfood the graph), but production signals are nascent.

---

## 4. Strengths & Weaknesses

### 4.1 GitNexus — Strengths

1. **14-language polyglot coverage** with unified capture-tag vocabulary.
2. **14-phase type resolution** with cross-file fixpoint propagation — substantially improves call-edge accuracy.
3. **Hybrid BM25 + semantic search** via RRF and arctic-embed-xs.
4. **Browser-renderable graph** + AI chat via React + Sigma.js + LangChain.
5. **First-class multi-repo groups** with contract registry and cross-repo impact.
6. **Embedded LadybugDB** with vector + FTS — single binary, no external Neo4j.
7. **Signed Docker images, SBOM, SLSA attestations, Sigstore K8s policy.**
8. **Worker-thread parallelism** with sub-batching and backoff.
9. **SWE-bench-style eval harness** with `baseline`/`native`/`native_augment` modes.
10. **Mature codebase** (242k LOC, 1,371 commits, 1,146+ tests, weekly cadence, commercial backer).

### 4.2 GitNexus — Weaknesses / gaps

1. **No architecture-conformance policies** or CI gate (planned).
2. **No git blame / CODEOWNERS integration** in graph.
3. **Per-file incremental re-parsing not yet shipped** — rebuilds whole index on commit.
4. **Smaller platform installer surface** (5 vs 14).
5. **No `.gitnexusignore` equivalent** — only `.gitignore` is respected.
6. **Swift parity blocked** on tree-sitter-swift Node 22 compatibility.
7. **C/C++/COBOL coverage is shallow** (no imports, no named bindings; COBOL is regex-only).
8. **No semantic Markdown extraction** (Concepts/Decisions/Rationale).
9. **No audio/video/PDF ingestion** in core (eval harness only).
10. **Heavy dependency on `node-gyp`/native modules** for grammars (mitigatable with `GITNEXUS_SKIP_OPTIONAL_GRAMMARS`).

### 4.3 Codegraph — Strengths

1. **Architecture-conformance CI gate** with 5 built-in policies, scaffolded GitHub Actions workflow, suppression syntax, custom Cypher policies.
2. **Framework-aware schema** — NestJS DI, React hooks, TypeORM entities, GraphQL resolvers, FastAPI/Flask/Django routes are first-class graph nodes (not just heuristics).
3. **Git blame + CODEOWNERS** in graph (`:Author`, `:Team`, `:OWNED_BY`, `:LAST_MODIFIED_BY`, `:CONTRIBUTED_BY`).
4. **14-platform installer** with manifest-aware uninstall.
5. **3-axis incremental indexing** (`--update` content cache + `--since` git-diff + `watch` watchdog + git hooks).
6. **`codegraph audit` agent-driven extraction self-check** — novel feature, no equivalent in GitNexus.
7. **`:EdgeGroup` for protocol implementers**, not just communities.
8. **29 MCP prompt templates** auto-loaded from `queries.md` (Claude Desktop slash commands).
9. **Token-reduction benchmark** (`codegraph benchmark`) with CI threshold.
10. **Semantic Markdown extraction** (Concepts/Decisions/Rationale) + audio/video transcription (Whisper) + PDF ingestion.
11. **`.codegraphignore` with route/component patterns** (`@route:/admin/*`, `@component:*Admin*`).
12. **Power-tool slash commands** (`/blast-radius`, `/dead-code`, `/who-owns`, `/trace-endpoint`, `/arch-check`, `/graph`, `/graph-refresh`).
13. **Dogfoods itself** — CLAUDE.md instructs agents to query the live graph during development.
14. **Smaller, more focused codebase** (~18k LOC) — easier to read, modify, fork.
15. **Read-only by default MCP** with explicit `--allow-write` opt-in.

### 4.4 Codegraph — Weaknesses / gaps

1. **Only 2 source languages** (TS/TSX/JS + Python) — Go and Rust are roadmap.
2. **No type resolution** beyond import resolution + name fallback.
3. **No hybrid search / no embeddings** — Cypher-only.
4. **No browser UI** — static HTML export only.
5. **No multi-repo groups** beyond ID namespacing.
6. **No worker-thread parallelism** — single-process sequential.
7. **Neo4j as external dependency** — Docker required (vs GitNexus's embedded LadybugDB).
8. **Younger / smaller** — 49 commits, alpha status, no SLSA/SBOM, no signed Docker images.
9. **No SWE-bench eval harness** (though `audit` and `benchmark` partially overlap).
10. **No commercial backer / paid offering** advertised.

---

## 5. When to Choose Which

### Choose **GitNexus** if:

- Your monorepo is **polyglot** (Java + TS + Python, Kotlin + Swift + Go, etc.).
- You need **semantic search** ("find code similar to X") in addition to structural queries.
- You want a **browser UI** for demos, onboarding, or non-developer stakeholders.
- You're operating across **multiple repos** and need a contract registry / cross-repo impact analysis.
- You care about **supply-chain security** (signed images, SBOM, SLSA, Sigstore K8s policy) out of the box.
- You want **call-edge precision** that requires cross-file type propagation (a sophisticated TypeScript or Python codebase with deep call chains).
- You want a **mature, production-tested** project with a commercial backer.
- You're running an **SWE-bench-style benchmark** for agent tool usage.

### Choose **Codegraph** if:

- Your codebase is **TypeScript and/or Python** (with strong framework usage — NestJS, React, TypeORM, GraphQL, FastAPI, Flask, Django).
- You need **architecture-conformance enforcement** in CI (block PRs that introduce import cycles, layer bypasses, cross-package imports, or coupling-ceiling violations).
- You want **ownership and CODEOWNERS in the graph** for impact-by-team analysis.
- You want **fine-grained incremental indexing** (per-file content cache, git-diff mode, filesystem watcher, git hooks).
- You're integrating with **a wide range of AI agent platforms** (14 supported with manifest-aware uninstall).
- You want a **smaller, simpler codebase** that's easy to read, modify, fork.
- You want **read-only-by-default MCP** with explicit `--allow-write` gating.
- You want to **dogfood architectural awareness** in your AI agent prompts via slash commands.
- You want **semantic Markdown extraction** (Concepts/Decisions/Rationale), audio/video transcription, or PDF ingestion in your graph.

### Could you use both?

In principle, yes — they don't conflict. GitNexus could index the codebase for semantic search and impact analysis; codegraph could enforce architecture policies in CI. Both expose MCP servers with non-overlapping tool names. The friction would be (a) two indexing pipelines to keep fresh, (b) two databases (LadybugDB + Neo4j) running, (c) two MCP servers connected to your editor. For most teams that's overkill; pick one based on the strengths above.

---

## 6. Forward-Looking Notes

- **GitNexus's roadmap signals**: per-file incremental re-parsing, Phase P.5 (covariant return types), Phase S (Swift parity once tree-sitter-swift unblocks), architecture-conformance framework, expanded supply-chain attestations.
- **Codegraph's roadmap signals**: Go and Rust frontends (Stage 2/3 of Python frontend lands first), expanded `audit` automation, deeper retrieval-augmented PR comments, more arch-check policies.
- **Convergence vectors**: codegraph could plausibly add embeddings (its `[analyze]` extra already pulls `networkx` + `graspologic`) and a typed type-resolver for TS/Python. GitNexus could plausibly add an arch-check framework on top of its existing Cypher infrastructure and integrate git blame.

---

## 7. Numbers Snapshot

| Metric | GitNexus | Codegraph |
|---|---|---|
| Source LOC | ~242,000 (TS) | ~18,400 (Py) |
| Source files | 1,069 TS + 59 TSX + 225 Py | ~83 Py |
| Tests | 1,146+ in 53 files (Vitest) | ~1,000+ in 43 files (pytest) |
| Commits since inception | 1,371+ | 49 |
| Days in development | (years) | ~24 |
| Current version | 1.6.3 | 0.1.112 |
| Languages parsed | 14 | 2 |
| Node types | 35–44 | 20 first-class + stacked labels |
| Edge types | 21 | ~33 |
| MCP tools | 16 | 17 (15 read + 2 write) |
| MCP resources | 6 | 0 |
| MCP prompts | 2 | 29 |
| CLI commands | ~16 (incl. group subcommands) | 16 top-level |
| AI platform integrations | 5 | 14 |
| Built-in arch policies | 0 | 5 |
| Reference docs | 15+ top-level | 9 in `docs/` + 4 top-level |
| Embedding model | `Snowflake/snowflake-arctic-embed-xs` (384D) | none |
| Database engine | LadybugDB (embedded native) | Neo4j 5.24 (Docker) |
| Distribution | npm + signed Docker (GHCR + Docker Hub) | PyPI + Docker Compose template |

---

## 8. Closing Assessment

**GitNexus and codegraph are not yet drop-in substitutes.** They overlap in the abstract category ("graph the code, expose to LLMs via MCP") but they have made meaningfully different bets that produce meaningfully different tools.

- GitNexus is a **polyglot retrieval platform**: it parses 14 languages, maintains an embedded native graph DB with vectors, ships a browser UI, runs precomputed clustering and process-tracing at index time so that AI agents can ask one question and get a complete answer. It's mature, security-hardened, and commercially backed.

- Codegraph is a **framework-aware governance layer**: it parses two languages but with deep schema modelling for the frameworks those languages actually use (NestJS, React, TypeORM, GraphQL, FastAPI, Django). It enforces architecture in CI, models ownership in the graph, integrates with 14 agent platforms, and dogfoods itself in development.

For a heterogeneous monorepo or a team that values retrieval breadth, GitNexus is the obvious pick. For a TS/Python monorepo where architecture conformance, ownership, and tight agent-platform coverage matter more than raw search, codegraph offers a sharper tool. Choose based on which problem you actually have.
