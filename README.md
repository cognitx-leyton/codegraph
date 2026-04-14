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

## ✨ Highlights

- **Framework-aware parsing** — not just imports: controllers, injectables, modules, entities, React components and hooks are first-class nodes.
- **Neo4j-backed** — every relationship is a Cypher query away. Dependency walks, shortest paths, DI chains, orphan detection, all out of the box.
- **Claude Code & AI agent native** — the typed graph is a structured retrieval backend for Claude Code, Claude, and other coding agents that need architectural context, not just nearest-neighbour code chunks.
- **Monorepo-friendly** — scope indexing to specific packages (`twenty-server`, `twenty-front`, …) and exclude build/test artefacts by default.
- **Batteries included** — a Typer CLI (`index`, `query`, `validate`), Docker Compose for Neo4j, and a library of example Cypher queries.

## 📑 Table of Contents

- [Why a code knowledge graph?](#-why-a-code-knowledge-graph)
- [Using with Claude Code & AI agents](#-using-with-claude-code--ai-agents)
- [Architecture](#-architecture)
- [Quickstart](#-quickstart)
- [Graph schema](#-graph-schema)
- [Example queries](#-example-queries)
- [Configuration](#-configuration)
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

A first-class **[Model Context Protocol](https://modelcontextprotocol.io/)** server wrapping the graph is on the [Roadmap](#-roadmap). In the meantime, you can:

- Let Claude Code shell out to `codegraph query "<cypher>"` via its bash tool.
- Write a small MCP server that exposes a `query_graph` tool backed by the Neo4j driver.
- Query Bolt directly from any agent framework that supports custom tools.

## 🏗️ Architecture

```
  TypeScript repo                Parser                Graph loader          Neo4j
 ┌────────────────┐      ┌──────────────────┐      ┌──────────────┐     ┌──────────┐
 │ *.ts / *.tsx   │ ───► │ AST walk          │ ───► │ Typed nodes  │───► │ Property │
 │ packages/*/src │      │ + framework       │      │ + edges      │     │ graph    │
 └────────────────┘      │ detection         │      └──────────────┘     └────┬─────┘
                         │ (NestJS / React)  │                                │
                         └──────────────────┘                                 ▼
                                                                         Cypher / RAG
```

All indexing is local: your code never leaves the machine, and Neo4j runs in a Docker container alongside the CLI.

## 🚀 Quickstart

```bash
cd codegraph

# 1. Python environment
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Neo4j (Docker)
docker compose up -d
# Browser UI:  http://localhost:7475   (neo4j / codegraph123)
# Bolt:        bolt://localhost:7688

# 3. Tell codegraph which packages in your monorepo to index.
#    Either drop a codegraph.toml at the repo root (see Configuration below)
#    or pass --package flags:
.venv/bin/python -m codegraph.cli index /path/to/your-monorepo \
  --package packages/server --package packages/web

# 4. Sanity-check the load
.venv/bin/python -m codegraph.cli validate /path/to/your-monorepo

# 5. Ask a question
.venv/bin/python -m codegraph.cli query \
  "MATCH (e:Endpoint) RETURN e.method, e.path LIMIT 10"
```

## 🧩 Graph schema

**Nodes**

| Kind | Examples / notes |
| --- | --- |
| `File` | TS/TSX files with language, LOC, and framework flags (`is_controller`, `is_component`, …) |
| `Class` | NestJS controllers, injectables, modules, entities, resolvers |
| `Function` | Exported functions and React components |
| `Interface` | TypeScript interfaces |
| `Endpoint` | HTTP routes exposed by controllers (method + path + handler) |
| `Hook` | React hooks (custom and built-in usage sites) |
| `Decorator` | Framework decorators applied to classes/methods |
| `External` | Symbols imported from `node_modules` |

**Edges**

`IMPORTS`, `IMPORTS_EXTERNAL`, `DEFINES_CLASS`, `DEFINES_FUNC`, `DEFINES_IFACE`, `EXPOSES`, `INJECTS`, `EXTENDS`, `IMPLEMENTS`, `RENDERS`, `USES_HOOK`, `DECORATED_BY`.

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

## 🛣️ Roadmap

- Incremental re-indexing on file changes
- Python and Go language frontends
- First-class MCP server exposing the graph to LLM agents
- Pre-built RAG retrievers for common architecture questions

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

<a href="https://star-history.com/#cognitx-leyton/graphrag-code&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=cognitx-leyton/graphrag-code&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=cognitx-leyton/graphrag-code&type=Date" />
    <img alt="Star history chart for cognitx-leyton/graphrag-code" src="https://api.star-history.com/svg?repos=cognitx-leyton/graphrag-code&type=Date" />
  </picture>
</a>

## 📄 License

Licensed under the [Apache License 2.0](LICENSE). Copyright © [Leyton CognitX](https://cognitx.leyton.com/) and contributors.
