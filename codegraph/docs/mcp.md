# MCP Server Reference

Per-tool reference for `codegraph-mcp` — the stdio [Model Context Protocol](https://modelcontextprotocol.io/) server that exposes the codegraph Neo4j graph to LLM coding agents (Claude Code, Cursor, Codex, Aider, …).

This is the deep reference. For a one-liner table see [`README.md`](../README.md#mcp-server). For implementation details, the source of truth is [`codegraph/codegraph/mcp.py`](../codegraph/mcp.py).

---

## Orientation

### Install

```bash
pipx install "cognitx-codegraph[mcp]"
```

The `[mcp]` extra pulls in the `mcp` SDK and registers the `codegraph-mcp` console script.

### Wire it into Claude Code

In `~/.claude.json`:

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

Restart the agent. The 17 tools listed below appear in the tool menu.

To enable the two write tools (`wipe_graph`, `reindex_file`), add `"args": ["--allow-write"]` to the block:

```json
{
  "mcpServers": {
    "codegraph": {
      "command": "codegraph-mcp",
      "args": ["--allow-write"],
      "type": "stdio",
      "env": { "CODEGRAPH_NEO4J_URI": "bolt://localhost:7688", "...": "..." }
    }
  }
}
```

### Architecture

- **Stdio-only.** No HTTP, no socket, no port. The server speaks JSON-RPC over stdin/stdout to the spawning agent process. There is nothing to firewall.
- **One driver, shared.** A single module-scoped `neo4j.Driver` is constructed lazily on the first tool call (so `import codegraph.mcp` succeeds even when Neo4j is down — the error surfaces as a tool-call error rather than killing the server before Claude Code can see it). Read tools open `READ_ACCESS` sessions; write tools open `WRITE_ACCESS` sessions.
- **Read-only by default.** Read sessions reject `CREATE` / `MERGE` / `DELETE` / `SET` at the Neo4j layer. An LLM-generated `DROP DATABASE` or `MATCH (n) DETACH DELETE n` surfaces as a `ClientError` returned in the tool result, not a mutation.
- **Write tools are gated.** `wipe_graph` and `reindex_file` check the `_allow_write` module flag, set by the `--allow-write` CLI flag in `main()`. Without the flag they return `{"error": "Write tools require --allow-write flag on codegraph-mcp"}`.
- **Configuration is env-var only.** `CODEGRAPH_NEO4J_URI` / `_USER` / `_PASS` (defaults: `bolt://localhost:7688`, `neo4j`, `codegraph123`).
- **Errors are tool-call results, not exceptions.** `CypherSyntaxError`, `ClientError`, and `ServiceUnavailable` are caught and returned as `[{"error": "..."}]` so the agent can reason about the failure instead of seeing a generic MCP transport error.

### Prompt templates

In addition to tools, the server registers **29 prompt templates** auto-loaded from [`queries.md`](../queries.md). Each `## ` heading + ` ```cypher ` block becomes one prompt; the first `//` comment in the block is the description. Prompts surface in agents that support them (e.g. Claude Desktop's slash menu) as ready-made queries the user can run via `query_graph`.

### Limit and depth validation

Every tool that accepts a `limit` validates it against `[1, 1000]` (or `[1, 100]` for `most_injected_services`). Every tool that accepts `max_depth` validates it against `[1, 5]`. These are **interpolated** into the Cypher string rather than passed as bind parameters because Neo4j 5.x rejects `LIMIT $param` as a syntax error. Validation closes the injection surface — non-int values are rejected before any string formatting.

---

## Read tools (15)

### `query_graph`

**Purpose**: Run an arbitrary read-only Cypher query — the escape hatch for anything the typed tools don't cover.

**Signature**:

```python
query_graph(cypher: str, limit: int = 20) -> list[dict]
```

**Parameters**:

- `cypher` (string, required) — Cypher query string. Writes (`CREATE`/`MERGE`/`DELETE`/`SET`) are rejected by the Neo4j read-only session.
- `limit` (int, default `20`, range `1..1000`) — Maximum rows to return. Applied client-side after the query runs; not pushed into the Cypher.

**Returns**: `list[dict]`. Each row is a flat dict of column-name → JSON-safe value. `Node` and `Relationship` values are unwrapped to their property dicts. On failure: `[{"error": "..."}]`.

**Example call**:

```json
{
  "name": "query_graph",
  "arguments": {
    "cypher": "MATCH (c:Class {is_controller:true}) RETURN c.name, c.file LIMIT 5",
    "limit": 5
  }
}
```

**Example result**:

```json
[
  {"c.name": "AuthController",  "c.file": "src/auth/auth.controller.ts"},
  {"c.name": "UserController",  "c.file": "src/user/user.controller.ts"}
]
```

**When to use**: filtering on properties not exposed by the typed tools, ad-hoc aggregations, multi-hop joins. Prefer a typed tool when one fits — they're shorter to call and the agent gets a stable, documented return shape.

---

### `describe_schema`

**Purpose**: Return labels, relationship types, and node counts per label — the cheap way for an agent to learn what's in the graph.

**Signature**:

```python
describe_schema() -> dict
```

**Parameters**: none.

**Returns**: `dict` with three keys:

- `labels` (`list[str]`) — every node label, alphabetised.
- `rel_types` (`list[str]`) — every relationship type, alphabetised.
- `counts` (`dict[str, int]`) — node count per label.

On failure: `{"error": "..."}` (a single dict, not a list).

**Example call**:

```json
{"name": "describe_schema", "arguments": {}}
```

**Example result**:

```json
{
  "labels": ["Atom", "Class", "Decorator", "EdgeGroup", "Endpoint", "File", "Function", "GraphQLOperation", "Hook", "Method", "Package"],
  "rel_types": ["BELONGS_TO", "CALLS", "DECORATED_BY", "DEFINES_CLASS", "EXPOSES", "IMPORTS", "INJECTS", "USES_HOOK"],
  "counts": {"File": 1234, "Class": 567, "Function": 890, "Method": 2103}
}
```

**When to use**: at session start, to ground the agent before it writes Cypher. Avoid calling repeatedly — labels and rel-types don't change between tool calls.

---

### `list_packages`

**Purpose**: Return every indexed monorepo package with its detected framework.

**Signature**:

```python
list_packages() -> list[dict]
```

**Parameters**: none.

**Returns**: one dict per `:Package`, ordered by `name`:

- `name` (str) — package name (e.g. `twenty-server`, `packages/web`).
- `framework` (str | null) — detected framework (`nestjs`, `react`, `fastapi`, …).
- `framework_version` (str | null) — version string from `package.json` / `pyproject.toml`.
- `typescript` (bool | null) — true if the package uses TypeScript.
- `package_manager` (str | null) — `npm`, `pnpm`, `yarn`, `pip`, `poetry`, …
- `confidence` (float | null) — framework-detection confidence 0.0-1.0.

Empty list if no packages have been indexed yet.

**Example call**:

```json
{"name": "list_packages", "arguments": {}}
```

**Example result**:

```json
[
  {"name": "twenty-front",  "framework": "react",  "framework_version": "18.2.0", "typescript": true,  "package_manager": "yarn", "confidence": 0.95},
  {"name": "twenty-server", "framework": "nestjs", "framework_version": "10.0.0", "typescript": true,  "package_manager": "yarn", "confidence": 0.99}
]
```

**When to use**: orientation. The agent typically calls this once after `describe_schema` to learn what packages exist before querying within them.

---

### `callers_of_class`

**Purpose**: Blast-radius traversal — who reaches the given class transitively over `INJECTS` / `EXTENDS` / `IMPLEMENTS`?

**Signature**:

```python
callers_of_class(
    class_name: str,
    file: Optional[str] = None,
    max_depth: int = 1,
    limit: int = 50,
) -> list[dict]
```

**Parameters**:

- `class_name` (str, required) — exact `:Class.name` (e.g. `"AuthService"`).
- `file` (str | null, default `None`) — optional exact `:Class.file` path to disambiguate identically-named classes across modules.
- `max_depth` (int, default `1`, range `1..5`) — hops to traverse. `1` is direct; up to `5` for deep DI / inheritance chains.
- `limit` (int, default `50`, range `1..1000`).

**Returns**: distinct caller-class rows:

- `name` (str) — caller class name.
- `file` (str) — file path of caller.
- `is_injectable` (bool | null) — caller is a NestJS `@Injectable`.
- `is_controller` (bool | null) — caller is a NestJS `@Controller`.

**Example call**:

```json
{
  "name": "callers_of_class",
  "arguments": {"class_name": "AuthService", "max_depth": 2, "limit": 20}
}
```

**Example result**:

```json
[
  {"name": "UserController", "file": "src/user/user.controller.ts", "is_injectable": false, "is_controller": true},
  {"name": "PostsService",   "file": "src/posts/posts.service.ts",  "is_injectable": true,  "is_controller": false}
]
```

**When to use**: before renaming, deleting, or moving a class. Use `callers_of` instead for function/method-level blast radius (different relationship type).

---

### `endpoints_for_controller`

**Purpose**: Return the HTTP endpoints exposed by a NestJS controller class.

**Signature**:

```python
endpoints_for_controller(controller_name: str) -> list[dict]
```

**Parameters**:

- `controller_name` (str, required) — exact `:Class.name`. Must have `is_controller=true`.

**Returns**: one row per endpoint, ordered by `path`:

- `method` (str) — HTTP verb (`GET`, `POST`, …).
- `path` (str) — route path including base path.
- `handler` (str) — handler method name on the controller.

**Example call**:

```json
{"name": "endpoints_for_controller", "arguments": {"controller_name": "UserController"}}
```

**Example result**:

```json
[
  {"method": "GET",    "path": "/users",     "handler": "findAll"},
  {"method": "GET",    "path": "/users/:id", "handler": "findOne"},
  {"method": "POST",   "path": "/users",     "handler": "create"}
]
```

**When to use**: API surface inspection. Pairs well with `/trace-endpoint` (CLI side) for end-to-end "URL → handler → call graph" traversal.

---

### `files_in_package`

**Purpose**: List files belonging to a monorepo package.

**Signature**:

```python
files_in_package(name: str, limit: int = 50) -> list[dict]
```

**Parameters**:

- `name` (str, required) — exact `:Package.name` (equivalently `:File.package`).
- `limit` (int, default `50`, range `1..1000`).

**Returns**: one row per file, ordered by `path`:

- `path` (str) — file path.
- `language` (str) — `python`, `typescript`, `tsx`, …
- `loc` (int) — lines of code.
- `is_controller`, `is_component`, `is_injectable`, `is_module`, `is_entity` (bool | null) — framework flags.

Empty list for unknown package names — the empty result *is* the answer.

**Example call**:

```json
{"name": "files_in_package", "arguments": {"name": "twenty-server", "limit": 100}}
```

**Example result**:

```json
[
  {"path": "src/auth/auth.controller.ts", "language": "typescript", "loc": 142, "is_controller": true,  "is_component": false, "is_injectable": false, "is_module": false, "is_entity": false},
  {"path": "src/auth/auth.service.ts",    "language": "typescript", "loc":  89, "is_controller": false, "is_component": false, "is_injectable": true,  "is_module": false, "is_entity": false}
]
```

**When to use**: scoping a follow-up query to a single package. Backed by the `file_package` property index, so it's faster than walking `BELONGS_TO`.

---

### `hook_usage`

**Purpose**: Return functions / components that use a given React hook.

**Signature**:

```python
hook_usage(hook_name: str, limit: int = 50) -> list[dict]
```

**Parameters**:

- `hook_name` (str, required) — exact `:Hook.name` (e.g. `"useAuth"`). Only **custom** hooks codegraph detected appear as `:Hook` nodes; built-in React hooks like `useState` are imports, not nodes.
- `limit` (int, default `50`, range `1..1000`).

**Returns**: distinct caller rows, ordered by `name`:

- `name` (str) — function/component name.
- `file` (str) — file path.
- `is_component` (bool | null) — true if it's a React component vs. a helper.
- `docstring` (str | null).
- `params_json` (str | null) — JSON-encoded parameter list.
- `return_type` (str | null).

**Example call**:

```json
{"name": "hook_usage", "arguments": {"hook_name": "useAuth", "limit": 20}}
```

**Example result**:

```json
[
  {"name": "Header",       "file": "src/components/Header.tsx",      "is_component": true,  "docstring": "Page header with logout.", "params_json": "[]", "return_type": "JSX.Element"},
  {"name": "useUserMenu",  "file": "src/components/useUserMenu.ts",  "is_component": false, "docstring": null,                       "params_json": "[]", "return_type": null}
]
```

**When to use**: blast radius for refactoring a custom hook. For built-in React hooks, query `IMPORTS_SYMBOL` via `query_graph` instead.

---

### `gql_operation_callers`

**Purpose**: Return callers of a GraphQL operation (query / mutation / subscription).

**Signature**:

```python
gql_operation_callers(
    op_name: str,
    op_type: Optional[str] = None,
    limit: int = 50,
) -> list[dict]
```

**Parameters**:

- `op_name` (str, required) — exact `:GraphQLOperation.name`.
- `op_type` (str | null, default `None`) — one of `"query"`, `"mutation"`, `"subscription"`. Pass to disambiguate when the same name exists across types. Returns `[{"error": "op_type must be one of 'query' | 'mutation' | 'subscription'"}]` for invalid values.
- `limit` (int, default `50`, range `1..1000`).

**Returns**: distinct caller rows, ordered by `caller.name`:

- `caller_name` (str) — caller's `name` property.
- `caller_file` (str) — caller's file path.
- `caller_kind` (str) — `Function`, `Method`, or `Class` (the first label).
- `caller_docstring` (str | null).
- `caller_params_json` (str | null).
- `op_type` (str) — `query` / `mutation` / `subscription`.
- `return_type` (str | null) — declared return type of the operation.

**Example call**:

```json
{
  "name": "gql_operation_callers",
  "arguments": {"op_name": "findManyUsers", "op_type": "query", "limit": 10}
}
```

**Example result**:

```json
[
  {"caller_name": "UsersList", "caller_file": "src/UsersList.tsx", "caller_kind": "Function", "caller_docstring": null, "caller_params_json": "[]", "op_type": "query", "return_type": "User[]"}
]
```

**When to use**: deciding whether a mutation can be safely renamed / restructured. The `caller_kind` field distinguishes a React component caller from a service-class caller without a second query.

---

### `most_injected_services`

**Purpose**: Rank `@Injectable` classes by number of unique callers — the canonical "DI hub detection" query.

**Signature**:

```python
most_injected_services(limit: int = 20) -> list[dict]
```

**Parameters**:

- `limit` (int, default `20`, range `1..100` — *tighter cap than other tools; nobody wants 1000 hubs*).

**Returns**: ordered by `injections` descending:

- `name` (str) — service class name.
- `file` (str) — file path.
- `injections` (int) — count of *distinct* caller classes (a caller injecting the same service into multiple methods still counts once).
- `is_controller` (bool | null) — flag (most hubs aren't controllers; included for completeness).

**Example call**:

```json
{"name": "most_injected_services", "arguments": {"limit": 5}}
```

**Example result**:

```json
[
  {"name": "AuthService",     "file": "src/auth/auth.service.ts",         "injections": 42, "is_controller": false},
  {"name": "UserService",     "file": "src/user/user.service.ts",         "injections": 31, "is_controller": false},
  {"name": "DatabaseService", "file": "src/database/database.service.ts", "injections": 28, "is_controller": false}
]
```

**When to use**: identifying core architectural pieces. Hub services are the riskiest to refactor — change them last and with the most regression coverage.

---

### `describe_group`

**Purpose**: Describe an `:EdgeGroup` (hyperedge) and list its members.

**Signature**:

```python
describe_group(
    name_or_id: str,
    kind: Optional[str] = None,
    limit: int = 50,
) -> list[dict]
```

**Parameters**:

- `name_or_id` (str, required, non-empty) — matched against `id` (exact) and `name` (CONTAINS). Empty / whitespace-only strings rejected.
- `kind` (str | null, default `None`) — restrict to EdgeGroups with this `kind` (e.g. `"protocol_implementers"`, `"community"`). See [`hyperedges.md`](hyperedges.md) for the canonical list.
- `limit` (int, default `50`, range `1..1000`) — caps **member rows**, not group count.

**Returns**: one row per (group, member) pair, ordered by `group_name, member_name`:

- `group_id` (str) — EdgeGroup id.
- `group_name` (str) — EdgeGroup name.
- `group_kind` (str) — kind tag.
- `group_size` (int) — `node_count` property.
- `confidence` (float | null) — group confidence 0.0-1.0.
- `cohesion` (float | null) — cohesion metric (community detection only).
- `member_kind` (str | null) — first label of the member node.
- `member_name` (str | null) — `name` (or `id` fallback) of the member.
- `member_file` (str | null).

**Example call**:

```json
{"name": "describe_group", "arguments": {"name_or_id": "Repository", "kind": "protocol_implementers"}}
```

**Example result**:

```json
[
  {"group_id": "eg:proto:Repository", "group_name": "Repository protocol",    "group_kind": "protocol_implementers", "group_size": 12, "confidence": 1.0,  "cohesion": null, "member_kind": "Class", "member_name": "PostgresRepository", "member_file": "src/db/postgres.ts"},
  {"group_id": "eg:proto:Repository", "group_name": "Repository protocol",    "group_kind": "protocol_implementers", "group_size": 12, "confidence": 1.0,  "cohesion": null, "member_kind": "Class", "member_name": "RedisRepository",    "member_file": "src/db/redis.ts"}
]
```

**When to use**: inspecting protocol implementer sets, Leiden communities (from `codegraph report`), or any other auto-emitted hyperedge. For one-off Cypher against EdgeGroups, fall back to `query_graph`.

---

### `find_class`

**Purpose**: Case-sensitive substring search over class names.

**Signature**:

```python
find_class(name_pattern: str, limit: int = 50) -> list[dict]
```

**Parameters**:

- `name_pattern` (str, required, non-empty) — substring matched against `:Class.name` via `CONTAINS`. Empty strings are rejected (would match every class). Case-sensitive — bypassing the index via `toLower()` would turn this into a full scan.
- `limit` (int, default `50`, range `1..1000`).

**Returns**: ordered by `name`:

- `name` (str).
- `file` (str).
- `is_controller`, `is_injectable`, `is_module`, `is_entity`, `is_resolver` (bool | null) — framework flags.

**Example call**:

```json
{"name": "find_class", "arguments": {"name_pattern": "Auth", "limit": 10}}
```

**Example result**:

```json
[
  {"name": "AuthController", "file": "src/auth/auth.controller.ts", "is_controller": true,  "is_injectable": false, "is_module": false, "is_entity": false, "is_resolver": false},
  {"name": "AuthGuard",      "file": "src/auth/auth.guard.ts",      "is_controller": false, "is_injectable": true,  "is_module": false, "is_entity": false, "is_resolver": false},
  {"name": "AuthModule",     "file": "src/auth/auth.module.ts",     "is_controller": false, "is_injectable": false, "is_module": true,  "is_entity": false, "is_resolver": false}
]
```

**When to use**: discovering candidates before drilling in. If you already know the exact class name and want full info on a specific class, prefer `query_graph` with an equality match — it's O(1) on the index.

---

### `find_function`

**Purpose**: Case-sensitive substring search over function and method names.

**Signature**:

```python
find_function(name_pattern: str, limit: int = 50) -> list[dict]
```

**Parameters**:

- `name_pattern` (str, required, non-empty) — substring matched against `:Function.name` and `:Method.name` via `CONTAINS`.
- `limit` (int, default `50`, range `1..1000`).

**Returns**: distinct rows, ordered by `file, name`:

- `kind` (str) — `Function` or `Method`.
- `name` (str).
- `file` (str).
- `docstring` (str | null).
- `return_type` (str | null).
- `class_name` (str | null) — populated only for methods (via `OPTIONAL MATCH (c:Class)-[:HAS_METHOD]->(n)`).

**Example call**:

```json
{"name": "find_function", "arguments": {"name_pattern": "login"}}
```

**Example result**:

```json
[
  {"kind": "Method",   "name": "login",      "file": "src/auth/auth.controller.ts", "docstring": "Authenticate a user.",         "return_type": "Promise<Token>", "class_name": "AuthController"},
  {"kind": "Function", "name": "loginGuard", "file": "src/auth/guards.ts",          "docstring": null,                            "return_type": "boolean",        "class_name": null}
]
```

**When to use**: locating a function before calling `describe_function` or `callers_of`. Backed by the `func_name` and `method_name` indexes.

---

### `calls_from`

**Purpose**: Return what a function/method calls, optionally transitively.

**Signature**:

```python
calls_from(
    name: str,
    file: Optional[str] = None,
    max_depth: int = 1,
    limit: int = 50,
) -> list[dict]
```

**Parameters**:

- `name` (str, required) — exact `:Function.name` or `:Method.name`. Same name in multiple files yields combined results unless `file` is set.
- `file` (str | null, default `None`) — exact source file path to disambiguate.
- `max_depth` (int, default `1`, range `1..5`) — `1` for direct calls; up to `5` for transitive reach via `:CALLS*1..N`.
- `limit` (int, default `50`, range `1..1000`).

**Returns**: distinct rows, ordered by `file, name`:

- `kind` (str) — first label of the target (`Function`, `Method`, or `External` for unresolved calls — stdlib, builtins, dynamic).
- `name` (str) — target name.
- `file` (str) — target file path, empty string for `:External`.
- `docstring` (str | null) — target docstring, empty string when missing.
- `confidence` (str | null) — `"EXTRACTED"` / `"INFERRED"` / `"AMBIGUOUS"` (only present at `max_depth=1`).
- `confidence_score` (float | null) — 0.0-1.0 (only present at `max_depth=1`).

**Example call**:

```json
{
  "name": "calls_from",
  "arguments": {"name": "login", "file": "src/auth/auth.controller.ts", "max_depth": 2}
}
```

**Example result**:

```json
[
  {"kind": "Method",   "name": "validateUser", "file": "src/auth/auth.service.ts", "docstring": "Verify credentials.", "confidence": null, "confidence_score": null},
  {"kind": "Method",   "name": "signToken",    "file": "src/auth/auth.service.ts", "docstring": "JWT signing.",        "confidence": null, "confidence_score": null},
  {"kind": "External", "name": "compare",      "file": "",                          "docstring": "",                    "confidence": null, "confidence_score": null}
]
```

**When to use**: understanding what a function does without reading it. Pair with `describe_function` to get the signature first.

---

### `callers_of`

**Purpose**: Return who calls a function/method, optionally transitively.

**Signature**:

```python
callers_of(
    name: str,
    file: Optional[str] = None,
    max_depth: int = 1,
    limit: int = 50,
) -> list[dict]
```

**Parameters**: same as `calls_from`. `file` narrows the **target**, not the caller.

**Returns**: distinct rows, ordered by `src.file, src.name`. Callers are always `:Function` or `:Method` — no other label emits `:CALLS`.

- `kind` (str) — `Function` or `Method`.
- `name` (str).
- `file` (str).
- `confidence` (str | null) — only present at `max_depth=1`.
- `confidence_score` (float | null) — only present at `max_depth=1`.

**Example call**:

```json
{"name": "callers_of", "arguments": {"name": "validateUser", "max_depth": 1}}
```

**Example result**:

```json
[
  {"kind": "Method", "name": "login",  "file": "src/auth/auth.controller.ts", "confidence": "EXTRACTED", "confidence_score": 1.0},
  {"kind": "Method", "name": "signup", "file": "src/auth/auth.controller.ts", "confidence": "INFERRED",  "confidence_score": 0.8}
]
```

**When to use**: blast radius for renaming or removing a function. Filter low-confidence rows when running strict checks — see [`confidence.md`](confidence.md).

---

### `describe_function`

**Purpose**: Return rich signature info (docstring, params, return type, decorators) for functions and methods matching `name`.

**Signature**:

```python
describe_function(
    name: str,
    file: Optional[str] = None,
    limit: int = 50,
) -> list[dict]
```

**Parameters**:

- `name` (str, required) — exact `:Function.name` or `:Method.name`.
- `file` (str | null, default `None`) — exact `:File.path` to disambiguate collisions.
- `limit` (int, default `50`, range `1..1000`).

**Returns**: ordered by `file, name`:

- `kind` (str) — `Function` or `Method`.
- `name` (str).
- `file` (str).
- `docstring` (str | null).
- `params_json` (str | null) — JSON-encoded parameter list (`[{"name": ..., "type": ..., "default": ...}]`).
- `return_type` (str | null).
- `decorators` (`list[str]`) — names of decorators applied to the function/method (collected via `OPTIONAL MATCH (n)-[:DECORATED_BY]->(d:Decorator)`).

**Example call**:

```json
{"name": "describe_function", "arguments": {"name": "login"}}
```

**Example result**:

```json
[
  {
    "kind": "Method",
    "name": "login",
    "file": "src/auth/auth.controller.ts",
    "docstring": "Authenticate a user and return a JWT.",
    "params_json": "[{\"name\":\"dto\",\"type\":\"LoginDto\"}]",
    "return_type": "Promise<{access_token: string}>",
    "decorators": ["Post", "ApiOperation"]
  }
]
```

**When to use**: answering "what does X do" in one tool call instead of reading source. The `decorators` array distinguishes a route handler from a regular method, an `@Injectable` from a plain class, etc.

---

## Write tools (2)

Both write tools require `--allow-write` on the server CLI. Without the flag they return:

```json
{"error": "Write tools require --allow-write flag on codegraph-mcp"}
```

### `wipe_graph`

**Purpose**: Wipe all nodes and relationships from the Neo4j graph. **Destructive.**

**Signature**:

```python
wipe_graph(confirm: bool = False) -> dict
```

**Parameters**:

- `confirm` (bool, default `False`) — must be `True` to proceed. Safety guard against accidental invocation. Without it: `{"error": "Pass confirm=True to wipe the entire graph"}`.

**Returns**: `dict`:

- On success: `{"ok": True, "action": "wipe"}`.
- On error: `{"error": "..."}`.

**Example call**:

```json
{"name": "wipe_graph", "arguments": {"confirm": true}}
```

**Example result**:

```json
{"ok": true, "action": "wipe"}
```

**When to use**: rarely. `codegraph wipe` from the CLI is the same operation; the tool exists so an agent that's already mid-workflow can reset the graph without shelling out. After wipe, the graph is empty until the next `codegraph index`.

---

### `reindex_file`

**Purpose**: Re-index a single file — delete its old subgraph, parse it, and reload.

**Signature**:

```python
reindex_file(path: str, package: Optional[str] = None) -> dict
```

**Parameters**:

- `path` (str, required) — repo-relative file path. Must end in `.py`, `.ts`, or `.tsx`. Other extensions: `{"error": "path must end in .py, .ts, or .tsx"}`.
- `package` (str | null, default `None`) — package name to associate the file with. If omitted, looked up from the existing `:File` node in the graph; if the file isn't in the graph yet, an error is returned (`File ... not found in graph and no package specified`).

**Returns**: `dict`:

- On success: `{"ok": True, "file": <path>, "nodes": <int>, "edges": <int>}` — counts of nodes and intra-file edges written.
- On error: `{"error": "..."}` — covers missing file, parse failures, unknown package, Neo4j errors.

**Example call**:

```json
{"name": "reindex_file", "arguments": {"path": "src/auth/auth.service.ts"}}
```

**Example result**:

```json
{"ok": true, "file": "src/auth/auth.service.ts", "nodes": 14, "edges": 23}
```

**Important caveat**: `reindex_file` refreshes the file's nodes (classes, functions, methods, endpoints, GraphQL operations, columns, atoms, interfaces) and **intra-file** edges. **Cross-file edges** (`IMPORTS`, `CALLS` across files, resolver-to-class via class-id, etc.) are NOT refreshed — run a full `codegraph index` for that. Use `reindex_file` after edits to a single file when the cross-file graph is still consistent (e.g. you renamed a private method); use `codegraph index --update` when imports or external references change.

**Internal flow** (for the curious):

1. Validate extension and resolve package (from graph if not given).
2. Locate the file on disk.
3. Detect test status via `PY_TEST_PREFIX` / `PY_TEST_SUFFIX_TRAILING` / `TS_TEST_SUFFIXES`.
4. Parse with `PyParser` or `TsParser`.
5. Three-step `DETACH DELETE` of the old subgraph: grandchildren of owned classes → direct children → file node itself.
6. Re-create `:File` and all owned nodes (classes, functions, methods, interfaces, endpoints, GraphQL operations, columns, atoms).
7. Replay intra-file edges from a whitelist that covers every edge type in `schema.py` except `HAS_METHOD`/`RESOLVES`/`HAS_COLUMN`/`EXPOSES` (those are merged inline during node creation to avoid double-write).

---

## Choosing the right tool

A decision tree for picking among the typed tools. Default to the typed tool when one fits — `query_graph` is the escape hatch.

| If you want to … | Use |
| --- | --- |
| Find a class by partial name | `find_class` |
| Find a function or method by partial name | `find_function` |
| Get the full signature of a function/method | `describe_function` |
| Know what a function calls | `calls_from` |
| Know what calls a function/method | `callers_of` |
| Know what classes depend on a class (DI / inheritance) | `callers_of_class` |
| List endpoints exposed by a controller | `endpoints_for_controller` |
| List GraphQL callers of an operation | `gql_operation_callers` |
| List components using a custom React hook | `hook_usage` |
| Identify DI hub services | `most_injected_services` |
| List files in a package | `files_in_package` |
| List packages in the repo | `list_packages` |
| Inspect a hyperedge (protocol implementers, community) | `describe_group` |
| Discover labels / rel-types / counts | `describe_schema` |
| Filter on a property the typed tools don't expose | `query_graph` |
| Refresh a file after editing it | `reindex_file` (write) |
| Reset the graph entirely | `wipe_graph` (write) |

A few pointers worth internalising:

- **Class blast radius vs. function blast radius are different relationships.** `callers_of_class` walks `INJECTS` / `EXTENDS` / `IMPLEMENTS`. `callers_of` walks `:CALLS`. If you ask "who depends on `AuthService`" you almost certainly want `callers_of_class` — DI is a class-level relationship, not a method-level one.
- **`find_*` is for discovery; `describe_*` is for detail.** `find_class` returns name + file + framework flags; if you need methods of that class, follow up with `query_graph "MATCH (c:Class {name:'X'})-[:HAS_METHOD]->(m) RETURN m"`. Same for `find_function` → `describe_function`.
- **Use `file=` on `describe_function` / `calls_from` / `callers_of` when names collide.** Many codebases have multiple `init` / `validate` / `handle` methods. Without `file`, traversal merges them — you get the union of every same-named function's call graph.
- **`max_depth > 1` drops confidence fields.** Variable-length traversal can't carry per-edge properties cleanly; tools omit them when traversing >1 hop. Drop to `max_depth=1` if you need `confidence_score` on each edge.
- **The empty list is a valid answer.** `endpoints_for_controller("DoesNotExist")` returns `[]`, not an error. Distinguish "no results" from "error" by checking for the `error` key in the first row.

For everything outside this menu, write Cypher and call `query_graph`. The full schema reference lives in [`README.md`](../README.md#schema), and canonical query patterns live in [`queries.md`](../queries.md) — every block in that file is also auto-registered as a prompt template on this server.
