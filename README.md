# 🕸️ graphrag-code

***A Neo4j code knowledge graph for TypeScript codebases — index NestJS and React code, then answer architecture questions with Cypher.***

![License](https://img.shields.io/badge/license-Apache%202.0-D22128?style=flat-square)
![Python](https://img.shields.io/badge/python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)
![Neo4j](https://img.shields.io/badge/neo4j-5.24-008CC1?style=flat-square&logo=neo4j&logoColor=white)
![TypeScript](https://img.shields.io/badge/typescript-ready-3178C6?style=flat-square&logo=typescript&logoColor=white)
![NestJS](https://img.shields.io/badge/nestjs-aware-E0234E?style=flat-square&logo=nestjs&logoColor=white)
![React](https://img.shields.io/badge/react-aware-61DAFB?style=flat-square&logo=react&logoColor=black)

`graphrag-code` turns a TypeScript/TSX repository into a queryable **code knowledge graph** — a structured retrieval backend for **[Claude Code](https://www.anthropic.com/claude-code)**, **Claude**, and other **AI coding agents**. It walks the AST, recognises framework constructs (NestJS controllers, modules, DI; React components and hooks), and loads the result into Neo4j. Your agent can then ask *architectural* questions — dependency chains, endpoint inventories, component usage, hubs of DI — in Cypher, instead of fuzzy-matching code chunks with embeddings.

Built at **[Leyton CognitX](https://cognitx.leyton.com/)** to make large TypeScript monorepos legible to humans, to Claude, and to LLM agents alike.

## 🚀 Quickstart: use in your repo

```bash
pipx install cognitx-codegraph
cd /path/to/your-repo
codegraph init
```

`codegraph init` asks 4-5 short questions (which packages to index, which package boundaries to enforce, whether to install the Claude Code surface + GitHub Actions gate + local Neo4j) and then:

1. Writes `.claude/commands/` (7 slash commands), `.github/workflows/arch-check.yml`, `.arch-policies.toml`, `docker-compose.yml`, and a `CLAUDE.md` snippet.
2. Starts a local Neo4j container via `docker compose up -d`.
3. Runs the first index.
4. Prints what to query next.

You're fully set up in ~2 minutes. Want everything without prompts? `codegraph init --yes`. Want just the files and no Docker? `codegraph init --yes --skip-docker --skip-index`.

Full walkthrough: [codegraph/docs/init.md](./codegraph/docs/init.md). Policy reference: [codegraph/docs/arch-policies.md](./codegraph/docs/arch-policies.md).

## ✨ Highlights

- **Framework-aware parsing** — not just imports: NestJS controllers / injectables / modules, React components and hooks, TypeORM entities, GraphQL operations, FastAPI / Flask / Django routes, SQLAlchemy models, plus generic Python classes and decorators are all first-class nodes.
- **Neo4j-backed** — every relationship is a Cypher query away. Dependency walks, shortest paths, DI chains, blast-radius, orphan detection, all out of the box.
- **Claude Code & AI agent native** — first-class MCP server with 16 tools, plus `codegraph install <platform>` for Claude Code, Codex, Cursor, Gemini CLI, Aider, Copilot, and 8 more.
- **Confidence-scored edges** — every relationship carries an `EXTRACTED` / `INFERRED` / `AMBIGUOUS` label and a numeric score; filter to a high-trust subgraph for strict checks.
- **Incremental indexing** — SHA256 content-addressed cache (`--update`), git-diff mode (`--since`), filesystem watcher (`codegraph watch`), git hooks (`codegraph hook install`).
- **Architecture conformance gate** — 5 built-in policies (cycles, cross-package, layer bypass, coupling ceiling, orphans) plus custom Cypher; ships with a GitHub Actions workflow scaffolded by `codegraph init`.
- **Monorepo-friendly** — scope indexing to specific packages, exclude build/test artefacts by default, redact confidential routes/components from the graph via `.codegraphignore`.
- **No LLM in the pipeline** — indexing is fully deterministic (AST + heuristic resolution). Predictable, reproducible, no cost-per-index.

## 📑 Table of Contents

- [Why a code knowledge graph?](#-why-a-code-knowledge-graph)
- [Using with Claude Code & AI agents](#-using-with-claude-code--ai-agents)
- [Architecture](#-architecture)
- [CLI cheat sheet](#-cli-cheat-sheet)
- [Graph schema](#-graph-schema)
- [Example queries](#-example-queries)
- [Configuration](#-configuration)
- [Documentation](#-documentation)
- [Roadmap](#-roadmap)
- [Contributing](#-contributing)
- [Contributors](#-contributors)
- [Star history](#-star-history)
- [License](#-license)

## 🧠 Why a code knowledge graph?

Vector search over raw code chunks is a blunt instrument. It finds lexically similar snippets, not *architecturally relevant* ones. Questions like *"which services does this controller transitively depend on?"*, *"who injects `AuthService`?"*, or *"which React components use this hook?"* are graph queries, not similarity queries.

`graphrag-code` gives an LLM (or a human) the structured backbone it needs:

- **Retrieval-augmented generation (RAG)** over a TypeScript codebase with typed traversals instead of opaque embeddings.
- **Architecture audits** — find hubs, cycles, orphans, tangled modules.
- **Safer refactors** — understand the blast radius of a change before you make it.
- **Onboarding** — let new engineers query the codebase in plain Cypher instead of reading files top-to-bottom.

## 🤖 Using with Claude Code & AI agents

`graphrag-code` is designed as a drop-in retrieval backend for agentic coding workflows. The typical pattern for [Claude Code](https://www.anthropic.com/claude-code) (and any other LLM coding agent — Cursor, Aider, Continue, custom MCP clients):

1. **Index your repo once** (see [Quickstart](#-quickstart)) — `codegraph.cli index` walks the AST and loads the graph into Neo4j.
2. **Expose the graph to your agent** — either via a thin MCP server, a CLI wrapper the agent can shell out to, or direct Bolt queries from tool-call handlers.
3. **Let the agent ask architectural questions** in Cypher *before* editing code.

### Why this beats embedding-only RAG for coding agents

Claude Code and other coding agents work best with **structured, low-noise context**. Vector search over code chunks pulls back things that *look* similar; a typed graph answers the question the agent is *actually* asking:

| Agent question | Graph query |
| --- | --- |
| *"What would break if I rename `AuthService`?"* | Reverse `INJECTS` + `IMPORTS*` traversal |
| *"What endpoints does `UserController` expose?"* | `EXPOSES` direct lookup |
| *"Which React components call `useAuth`?"* | `USES_HOOK` lookup |
| *"How is this file reached from the auth entrypoint?"* | `shortestPath` on `IMPORTS` |
| *"Which services are DI hubs I should treat as core?"* | `INJECTS` aggregation |

All answered in single-digit milliseconds, with zero tokens spent on retrieving irrelevant snippets.

### Exposing the graph to Claude via MCP

codegraph ships a first-class **[Model Context Protocol](https://modelcontextprotocol.io/)** stdio server. Install the optional extra, add one block to Claude Code's config, and five typed tools appear in the agent's tool menu — no more shelling out to `codegraph query`.

```bash
pip install "codegraph[mcp]"
```

In `~/.claude.json` (or your Claude Desktop config):

```json
{
  "mcpServers": {
    "codegraph": {
      "command": "codegraph-mcp",
      "type": "stdio",
      "env": {
        "CODEGRAPH_NEO4J_URI":  "bolt://localhost:7688",
        "CODEGRAPH_NEO4J_USER": "neo4j",
        "CODEGRAPH_NEO4J_PASS": "codegraph123"
      }
    }
  }
}
```

Restart Claude Code. 16 tools become available:

| Tool | Purpose |
| --- | --- |
| `query_graph(cypher, limit)` | Read-only Cypher escape hatch. Writes are rejected at the session level, so an LLM-generated `DROP`/`DELETE` can't mutate the graph. |
| `describe_schema()` | Labels, relationship types, and per-label node counts — cheap way for an agent to learn what's in the graph at session start. |
| `list_packages()` | Every indexed monorepo package with its detected framework, version, TypeScript flag, package manager, and detection confidence. |
| `callers_of_class(class_name, file, max_depth, limit)` | Blast-radius traversal over `INJECTS` / `EXTENDS` / `IMPLEMENTS`. The canonical "what breaks if I rename X" query. |
| `endpoints_for_controller(controller_name)` | HTTP routes exposed by a NestJS controller class (method + path + handler). |
| `files_in_package(name, limit)` | List files belonging to a `:Package` by name. |
| `hook_usage(hook_name, limit)` | Which components / functions use a given React hook. |
| `gql_operation_callers(op_name, op_type, limit)` | Who calls a GraphQL query / mutation / subscription, optionally narrowed by type. |
| `most_injected_services(limit)` | Rank `@Injectable` classes by number of unique callers — the classic "DI hub detection" query. |
| `find_class(name_pattern, limit)` | Case-sensitive substring search over class names, backed by the `class_name` index. |
| `find_function(name_pattern, limit)` | Case-sensitive substring search over function and method names, backed by the `func_name` and `method_name` indexes. |
| `describe_function(name, file, limit)` | Signature details (docstring, params, return type, decorators) for a function or method — answer "what does X do" in one call. |
| `calls_from(name, file, max_depth, limit)` | What a function/method calls, optionally transitive up to 5 hops via `:CALLS` edges. |
| `callers_of(name, file, max_depth, limit)` | Who calls a function/method, optionally transitive up to 5 hops (reverse `:CALLS`). |
| `reindex_file(path, package)` | Re-index a single file (delete old subgraph, parse, reload). Requires `--allow-write`. |
| `wipe_graph(confirm)` | Delete every node and relationship from the graph. Requires `--allow-write`. |

All 16 tools share a single long-lived Neo4j driver and open sessions in `READ_ACCESS` mode. Configuration is env-var only (the same `CODEGRAPH_NEO4J_*` vars the CLI uses). The server is stdio-only — no network exposure.

## 🏗️ Architecture

```
  TS / Python repo               Parser                Graph loader          Neo4j
 ┌────────────────┐      ┌──────────────────┐      ┌──────────────┐     ┌──────────┐
 │ *.ts / *.tsx   │ ───► │ tree-sitter walk  │ ───► │ Typed nodes  │───► │ Property │
 │ *.py           │      │ + framework       │      │ + edges      │     │ graph    │
 │ packages/*/src │      │ detection         │      │ + ownership  │     │          │
 └────────────────┘      │ (NestJS / React / │      └──────────────┘     └────┬─────┘
                         │  FastAPI / Django)│                                │
                         └──────────────────┘                                 ▼
                                                                         Cypher / RAG
                                                                         + MCP tools
```

All indexing is local: your code never leaves the machine, and Neo4j runs in a Docker container alongside the CLI. The pipeline is fully deterministic — no LLM in the indexing path. Edges carry a `confidence` label (`EXTRACTED` / `INFERRED` / `AMBIGUOUS`) and a numeric score so consumers can filter the noisy parts of the graph out of strict checks.

## 🛠️ CLI cheat sheet

`codegraph` is a Typer app; every subcommand supports `--json` for agent-native output.

| Command | Purpose |
| --- | --- |
| `codegraph init` | Scaffold codegraph into a repo (interactive). `--yes`, `--bolt-port`, `--http-port`, `--skip-docker`, `--skip-index`. |
| `codegraph index <repo>` | Walk source, parse, write the graph. `-p/--package`, `--update` (SHA256 cache), `--since <ref>` (git diff), `--no-wipe`, `--skip-ownership`, `--ignore-file`, `--json`. |
| `codegraph query <cypher>` | Run a Cypher query. `-n/--limit`, `--json`. |
| `codegraph arch-check` | Run architecture-conformance policies. Exits 1 on violations, 2 on config errors. |
| `codegraph validate` | Sanity-check the loaded graph (counts, orphans, schema). |
| `codegraph wipe` | `MATCH (n) DETACH DELETE n`. |
| `codegraph stats` | Quick node / edge counts. Updates the `codegraph:stats-*` block in `CLAUDE.md` with `--update`. |
| `codegraph export` | Produce `graph.html` (interactive), `graph.json`, and optional `graph.graphml` / `graph.cypher`. |
| `codegraph benchmark` | Token-reduction benchmark vs. raw source. `--min-reduction` for CI gating. |
| `codegraph report` | Generate `GRAPH_REPORT.md` from Leiden community detection. |
| `codegraph watch` | Debounced filesystem watcher; rebuilds on save. Requires `[watch]` extra. |
| `codegraph hook install` / `status` / `uninstall` | Manage post-commit + post-checkout git hooks that re-index automatically. |
| `codegraph install <platform>` | Wire codegraph into one of 14 AI agent platforms (writes rules file, registers MCP server). |
| `codegraph uninstall <platform>` | Remove integration; preserves shared rules sections still in use. |
| `codegraph repl` | Interactive Cypher REPL. Same as `codegraph` with no args. |

Full reference with every flag and `--json` shape: [`codegraph/docs/cli.md`](./codegraph/docs/cli.md).

## 🧩 Graph schema

**Nodes** — 15 typed labels with rich properties:

| Kind | What it is |
| --- | --- |
| `Package` | One per configured monorepo package. Carries detected `framework` (React / Next.js / Vue / Angular / Svelte / SvelteKit / **NestJS** / Fastify / Odoo / **FastAPI** / Flask / Django), version, TS/JS flag, styling, router, state management, UI library, build tool, package manager, confidence. |
| `File` | A `.ts` / `.tsx` / `.py` file. Properties: language, LOC, framework flags (`is_controller`, `is_injectable`, `is_module`, `is_component`, `is_entity`, `is_resolver`, `is_test`). |
| `Class` | NestJS controllers / injectables / modules, TypeORM entities, GraphQL resolvers, Python classes. Carries `is_controller`, `is_injectable`, `base_path`, `table_name`, etc. |
| `Method` | Class methods with visibility, async flag, return type, params, docstring. |
| `Function` | Module-level functions, React components, FastAPI route handlers. Same metadata. |
| `Interface` | TypeScript interfaces. |
| `Endpoint` | HTTP route exposed by a controller (method + path + handler). NestJS, FastAPI, Flask, Django. |
| `Column` | TypeORM / SQLAlchemy column with type, nullability, primary, generated. |
| `GraphQLOperation` | Query / mutation / subscription with return type, resolver class, handler. |
| `Event` | Event-bus events emitted or handled. |
| `Atom` | Jotai / Recoil state atom. |
| `EnvVar` | `process.env.X` / `os.environ['X']` reference. |
| `Route` | React Router / Next.js / file-system route with target component. |
| `External` | Symbol imported from `node_modules` / unresolved. |
| `EdgeGroup` | Hyperedge — protocol implementer set or Leiden community. Members link via `MEMBER_OF`. |

**Edges** — ~30 typed relationships, each with `confidence` + `confidence_score`. A representative slice:

`IMPORTS`, `IMPORTS_SYMBOL`, `IMPORTS_EXTERNAL`, `DEFINES_CLASS`, `DEFINES_FUNC`, `DEFINES_IFACE`, `HAS_METHOD`, `HAS_COLUMN`, `EXPOSES`, `INJECTS`, `PROVIDES`, `EXPORTS_PROVIDER`, `EXTENDS`, `IMPLEMENTS`, `RENDERS`, `USES_HOOK`, `DECORATED_BY`, `CALLS`, `CALLS_ENDPOINT`, `RESOLVES`, `HANDLES`, `HANDLES_EVENT`, `EMITS_EVENT`, `READS_ATOM`, `WRITES_ATOM`, `READS_ENV`, `BELONGS_TO`, `MEMBER_OF`, `OWNED_BY`, `LAST_MODIFIED_BY`, `CONTRIBUTED_BY`, `TESTS`, `TESTS_CLASS`.

Full catalogue with property details and example queries: [`codegraph/docs/schema.md`](./codegraph/docs/schema.md). Edge confidence model: [`codegraph/docs/confidence.md`](./codegraph/docs/confidence.md). Hyperedges: [`codegraph/docs/hyperedges.md`](./codegraph/docs/hyperedges.md).

## 🔎 Example queries

A handful of the queries in [`codegraph/queries.md`](codegraph/queries.md):

```cypher
// 1. Every HTTP endpoint with its controller
MATCH (c:Class {is_controller:true})-[:EXPOSES]->(e:Endpoint)
RETURN c.name, e.method, e.path, e.handler
ORDER BY c.name, e.path;

// 2. Most-injected services (DI hubs)
MATCH (svc:Class {is_injectable:true})<-[:INJECTS]-(caller:Class)
RETURN svc.name, count(caller) AS injections
ORDER BY injections DESC LIMIT 20;

// 3. Which React components use a given hook?
MATCH (:Hook {name:'useAuth'})<-[:USES_HOOK]-(c:Function)
RETURN c.name, c.file;

// 4. Transitive dependencies of a file
MATCH (:File {path:$start})-[:IMPORTS*1..3]->(d:File)
RETURN DISTINCT d.path;
```

See [`codegraph/queries.md`](codegraph/queries.md) for the full catalogue.

## ⚙️ Configuration

### Project config — `codegraph.toml`

`codegraph` has **no hardcoded packages**. You tell it which packages to index via a `codegraph.toml` at the repo root, a `[tool.codegraph]` block in your existing `pyproject.toml`, or `--package` flags on the CLI. Config file values are loaded first; CLI flags override them.

**`codegraph.toml`** (preferred — a standalone file, no interference with Python tooling):

```toml
# Paths are relative to the repo root. Each entry should be a TypeScript
# package directory (i.e. contain a package.json / tsconfig.json so path
# aliases can be resolved).
packages = [
  "packages/server",
  "packages/web",
]

# Optional — these extend the built-in defaults, they don't replace them.
exclude_dirs     = ["custom-build", "fixtures"]
exclude_suffixes = [".gen.ts"]
```

**`pyproject.toml`** (if you already have one and want everything in one place):

```toml
[tool.codegraph]
packages = ["packages/server", "packages/web"]
```

**CLI override** — wins over either file:

```bash
codegraph index . --package packages/server --package packages/web
```

If no config file exists and no `--package` flags are passed, `index` stops with a clear error. There are no Twenty-specific or other defaults.

### Python support (`.py` indexing)

codegraph indexes Python codebases with the same fidelity as TypeScript. The detector auto-picks the language based on the package directory: if the directory contains `__init__.py`, `pyproject.toml`, or `setup.py`, it's parsed as Python; otherwise it's parsed as TypeScript.

Install the optional `[python]` extra to enable the Python frontend:

```bash
pip install "codegraph[python]"
```

Then point `--package` at a Python package root:

```bash
codegraph index . --package src/my_package
```

What's indexed:

- **AST surface** — modules, classes, functions, methods, decorators, imports (relative + absolute + aliased), class inheritance, docstrings, type hints (`return_type`, `params_json`).
- **Method call graph** — `:CALLS` edges between methods/functions with confidence-scored resolution.
- **Framework detection** — FastAPI, Flask, Django, Odoo. Detection runs per package via `pyproject.toml` / requirements / source-pattern signals.
- **Endpoints** — `@app.get/post/...` (FastAPI), `@app.route` (Flask), Django URL config → `:Endpoint` nodes with method + path + handler.
- **ORM** — SQLAlchemy `Column(...)` and Django `models.Field()` → `:Column` nodes; relationships → `RELATES_TO` edges.
- **Tests** — `test_*.py` / `*_test.py` are paired back to their production peer via `:TESTS` and `:TESTS_CLASS` edges.

### Neo4j connection

Controlled via environment variables (defaults match the bundled `docker-compose.yml`):

| Variable | Default |
| --- | --- |
| `CODEGRAPH_NEO4J_URI` | `bolt://localhost:7688` |
| `CODEGRAPH_NEO4J_USER` | `neo4j` |
| `CODEGRAPH_NEO4J_PASS` | `codegraph123` |

### File walk exclusions

Indexing always skips `node_modules`, `dist`, `build`, `.next`, `.turbo`, `.nuxt`, `.svelte-kit`, `.vercel`, `coverage`, `generated`, `__generated__`, `.cache`, `.parcel-cache`, plus `*.d.ts` and `*.stories.{ts,tsx}`. Add to these via `exclude_dirs` / `exclude_suffixes` in your config — those keys **extend** the defaults, they don't replace them.

### `.codegraphignore`

For **confidential routes, components, or files** that shouldn't reach the graph (and therefore shouldn't reach any LLM agent querying it), drop a `.codegraphignore` file at the repo root. Syntax is gitignore-style, plus two codegraph extensions:

```gitignore
# Standard gitignore — file paths
**/admin/**
**/*.secret.ts
!**/admin/public/**         # negation — re-include a subtree

# Route patterns — match RouteNode.path
@route:/admin/*
@route:/settings/system/*

# Component patterns — match React component / NestJS class names
@component:*Admin*
@component:*UserManagement*
```

Override the default location with `--ignore-file PATH` on the CLI or `ignore_file = "custom/.ignore"` in `codegraph.toml`. `.codegraphignore` is **additive** on top of `BASE_EXCLUDE_DIRS` — it doesn't replace them.

## 📚 Documentation

Deep dives, organised by topic:

| Topic | Doc |
| --- | --- |
| Inner package overview, all 16 CLI commands at a glance | [`codegraph/README.md`](./codegraph/README.md) |
| Per-command reference (every flag, every `--json` shape) | [`codegraph/docs/cli.md`](./codegraph/docs/cli.md) |
| Per-tool reference for the MCP server | [`codegraph/docs/mcp.md`](./codegraph/docs/mcp.md) |
| Full graph schema — nodes, edges, properties, indexing phases | [`codegraph/docs/schema.md`](./codegraph/docs/schema.md) |
| Edge confidence labels and scores | [`codegraph/docs/confidence.md`](./codegraph/docs/confidence.md) |
| `:EdgeGroup` hyperedges (protocol implementers, communities) | [`codegraph/docs/hyperedges.md`](./codegraph/docs/hyperedges.md) |
| Incremental indexing — `--update`, `--since`, `watch`, `hook` | [`codegraph/docs/incremental.md`](./codegraph/docs/incremental.md) |
| AI platform integrations (14 platforms) | [`codegraph/docs/platforms.md`](./codegraph/docs/platforms.md) |
| Architecture-conformance policies | [`codegraph/docs/arch-policies.md`](./codegraph/docs/arch-policies.md) |
| `codegraph init` walkthrough | [`codegraph/docs/init.md`](./codegraph/docs/init.md) |
| Canonical Cypher query catalogue | [`codegraph/queries.md`](./codegraph/queries.md) |
| Version-by-version changelog | [`CHANGELOG.md`](./CHANGELOG.md) |

## 🛣️ Roadmap

Recent shipped highlights — full per-version detail in [`CHANGELOG.md`](./CHANGELOG.md):

- ~~First-class MCP server exposing the graph to LLM agents~~ — **shipped** (16 tools, see [Exposing the graph to Claude via MCP](#exposing-the-graph-to-claude-via-mcp))
- ~~Python language frontend~~ — **shipped** (Stage 1 parsing + Stage 2 framework detection / endpoints / ORM)
- ~~Incremental re-indexing on file changes~~ — **shipped** (`--update` SHA256 cache, `--since <ref>`, `codegraph watch`, `codegraph hook install`)
- ~~Multi-platform AI agent integrations~~ — **shipped** (`codegraph install <platform>` for 14 platforms: Claude Code, Codex, Cursor, Gemini CLI, Copilot, Aider, …)
- ~~Edge-level confidence labels~~ — **shipped** (`EXTRACTED` / `INFERRED` / `AMBIGUOUS` with numeric scores)
- ~~Hyperedge model for protocol implementers + communities~~ — **shipped** (`:EdgeGroup` nodes)
- ~~Architecture-conformance policies~~ — **shipped** (5 built-in: import cycles, cross-package, layer bypass, coupling ceiling, orphan detection — plus custom Cypher policies)

Up next:

- Go and Rust language frontends
- Pre-built RAG retrievers for common architecture questions
- Auto-generated graph visualisations as PR comments

## 🤝 Contributing

PRs welcome. The repository uses protected branches:

- **`main`** — production-ready code. All changes land here via PR.
- **`release`** — release-candidate branch. Stabilisation before tagging.
- **`hotfix`** — urgent fixes that need to skip the normal cycle.

Every PR into `main`, `release`, or `hotfix` requires a Code Owner review (see [`CODEOWNERS`](CODEOWNERS)). Please open an issue before a large refactor so we can align on direction.

## 👥 Contributors

Thanks to everyone who has helped shape `graphrag-code`:

<a href="https://github.com/cognitx-leyton/graphrag-code/graphs/contributors">
  <img alt="Avatar grid of graphrag-code contributors" src="https://contrib.rocks/image?repo=cognitx-leyton/graphrag-code" />
</a>

*Made with [contrib.rocks](https://contrib.rocks).*

## ⭐ Star history

If `graphrag-code` helps you make sense of a TypeScript monorepo, a star helps others find it too.

<a href="https://www.star-history.com/?repos=cognitx-leyton%2Fgraphrag-code&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=cognitx-leyton/graphrag-code&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=cognitx-leyton/graphrag-code&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=cognitx-leyton/graphrag-code&type=date&legend=top-left" />
 </picture>
</a>

## 📄 License

Licensed under the [Apache License 2.0](LICENSE). Copyright © [Leyton CognitX](https://cognitx.leyton.com/) and contributors.
