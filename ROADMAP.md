# codegraph — Roadmap & Session Handoff

> **Purpose of this document.** Capture enough context for a fresh agent session (or a human returning after time away) to continue work on codegraph without re-deriving state from scratch. Separate from the user-facing roadmap bullets in `README.md`, which stay short and pitch-oriented.
>
> **Last updated:** 2026-04-15 after commit `7588522`.

---

## TL;DR — where we are

- **Branch:** `dev` (pushed to `origin/dev`). Six commits ahead of `main`, not yet PR'd.
- **Tests:** 103/103 passing, 0 warnings. Run via `.venv/bin/python -m pytest tests/` from inside `codegraph/`.
- **Graph indexed:** Twenty CRM (`/tmp/twenty`, 13460 TS/TSX files) is loaded into the local Neo4j container. Good integration target.
- **MCP server:** 10 read-only tools live. `codegraph-mcp` console script registered. End-to-end verified via JSON-RPC against the live Twenty graph.
- **Nothing pushed to `main`.** Whole session's work sits on `dev`.

---

## Shipped this session (six atomic commits on `dev`)

```
7588522 feat(mcp):   add 5 pre-built retrievers for common agent questions
39be5c2 fix(review): address code-reviewer findings across mcp, framework, tests
e7382f7 fix(framework): detect NestJS, walk up for lockfile + workspace deps
c198c5d feat(mcp):   stdio server with 5 read-only tools
9fb4d1d feat(schema): per-package framework detection + :Package nodes
b71bc45 feat(ignore): .codegraphignore for per-repo file/route/component exclusion
```

All six commits came from porting pieces of `/tmp/agent-onboarding/architect/` (a related internal repo, Apache-2.0) and then hardening them against real monorepo shapes via an end-to-end test on Twenty CRM.

### What each commit added

**`b71bc45 feat(ignore)`** — `codegraph/codegraph/ignore.py` (new, ~180 LOC).
- Parses `.codegraphignore` at repo root (or via `--ignore-file` CLI flag).
- Syntax: gitignore-style file globs + `@route:/admin/*` + `@component:*Admin*` + `!` negation.
- Hooked into `cli._run_index` at three points: file walk (skip file), `_extract_routes` (skip RouteNode), and a new `_strip_ignored_components` pass (flip `FunctionNode.is_component = False` without deleting the function — preserves IMPORTS/CALL edges).
- Stripped from the upstream: opinionated `DEFAULT_IGNORE_PATTERNS`, `save_agentignore` / `create_default_agentignore` UX helpers.
- Renamed `.agentignore` → `.codegraphignore` to match tool convention and avoid clashing if users run both projects.
- 12 unit tests in `codegraph/tests/test_ignore.py` (plus 7 more added later for `_strip_ignored_components` + `_load_ignore_filter` helpers).

**`9fb4d1d feat(schema)`** — `codegraph/codegraph/framework.py` (new, ~360 LOC originally).
- `FrameworkDetector` class with scored heuristic: file existence (30 pts) + package.json dep (25 pts) + code-regex pattern (15 pts) per framework.
- Initial frameworks: React / React-TS / Next.js / Vue / Vue3 / Angular / Svelte / SvelteKit / Odoo (+ Unknown).
- New `:Package` node in `schema.py` with all `FrameworkInfo` fields inlined: `name`, `framework`, `framework_version`, `typescript`, `styling`, `router`, `state_management`, `ui_library`, `build_tool`, `package_manager`, `confidence`.
- New `:BELONGS_TO` edge type (File → Package) + `_write_packages` / `_write_belongs_to` functions in `loader.py`.
- `LoadStats` extended with `packages` and `belongs_to_edges` counters.
- `Index.packages: list[PackageNode]` added to `resolver.py`.
- `FrameworkDetector(pkg_dir).detect()` runs once per configured package in `cli._run_index` right after `load_package_config`.
- 14 unit tests against 6 fixture apps bundled with agent-onboarding (`/tmp/agent-onboarding/tests/fixtures/{react,nextjs,vue,sveltekit,angular,odoo}-app`).
- 3 new example queries in `codegraph/queries.md`.

**`c198c5d feat(mcp)`** — `codegraph/codegraph/mcp.py` (new, ~240 LOC originally).
- FastMCP (`mcp>=1.0`) stdio server registered as `codegraph-mcp` console script via `pyproject.toml`.
- `mcp` is an **optional extra** — `pip install "codegraph[mcp]"`. Main CLI unaffected if not installed.
- Five initial tools: `query_graph`, `describe_schema`, `list_packages`, `callers_of_class`, `endpoints_for_controller`.
- Module-scoped Neo4j driver (started as eager, made lazy in a later commit — see `39be5c2`).
- Every session opened with `default_access_mode=neo4j.READ_ACCESS` → Neo4j rejects any `CREATE`/`MERGE`/`DELETE`/`SET` at the session level. Verified live: a `DETACH DELETE (f:File)` attempt returned `[{"error": "Writing in read access mode not allowed"}]` and the 13460 file count stayed unchanged.
- Extracted `clean_row` helper to `codegraph/codegraph/utils/neo4j_json.py` so both cli and mcp share it.
- 18 unit tests in `codegraph/tests/test_mcp.py` with a `FakeDriver`/`FakeSession`/`FakeRecord` pattern — no real Neo4j needed for tests.
- README section "Exposing the graph to Claude via MCP" filled in with concrete install + config snippet.

**`e7382f7 fix(framework)`** — detector hardening driven by the Twenty e2e test.
- Twenty end-to-end revealed three bugs: twenty-server mis-labeled as "React TS 65%" instead of NestJS, twenty-front at only 30% confidence (hoisted deps invisible), and `package_manager=null` on both packages (lockfile at monorepo root, not package root).
- Added `FrameworkType.NESTJS` + `nest-cli.json` / `@nestjs/core` / `@Module|@Injectable|@Controller` indicators. NestJS scores 125 raw points on a real NestJS package vs React's ~80, so it wins the `max(scores)` decisively.
- New `_walk_up_to_repo_root(max_hops=10)` iterator — yields `project_path` then each parent, stops at a `.git` entry or filesystem root.
- Rewrote `_detect_package_manager` to walk up for lockfiles.
- New `_workspace_dependencies` property that merges own `package.json` deps + any parent `package.json` found walking up **whose manifest declares a `workspaces` field**. The workspaces guard prevents leakage from unrelated enclosing projects.
- 9 new tests including 2 opt-in integration tests against `/tmp/twenty` that skip cleanly if the clone is missing.

**`39be5c2 fix(review)`** — code-reviewer round 1+2 fixes.
- **Lazy `_driver`.** `mcp._driver` is now `Optional[Driver]`; a new `_get_driver()` constructs it on first tool call. `import codegraph.mcp` no longer touches Neo4j. `main()` closes the driver only if constructed.
- **`describe_schema` error routing.** Was dereferencing `e.message` directly — `None` on ad-hoc `Neo4jError` instances. Now routes through the shared `_err_msg` like every other tool.
- **Shared `_workspace_package_jsons()` cache** in `framework.py`. Both `_workspace_dependencies` and `_get_dependency_version` consume one parse-once cache instead of each re-walking and re-parsing on every call. Closes an N × depth disk-read cost on deep monorepos.
- **Defensive `copy.deepcopy` of own `package_json`** in the workspace cache so iteration-site mutation can't corrupt `self._package_json`.
- **`_FakeSession.run` always-pops** in the test fake (was conditional — would silently reuse the last response on a 4+ call).
- +9 new tests: describe_schema error paths, `_strip_ignored_components`, `_load_ignore_filter` resolution branches (default auto-detect, no-config-no-default, explicit-missing-relative, explicit-missing-absolute).
- Three review rounds total; round 3 returned "clean".

**`7588522 feat(mcp)`** — 5 additional pre-built retrievers.
- `files_in_package(name, limit=50)` — uses `(f:File {package:$name})` directly via the existing `file_package` property index.
- `hook_usage(hook_name, limit=50)` — `(Function)-[:USES_HOOK]->(Hook)`, `DISTINCT` to dedupe multiple call sites, returns `is_component` flag for agent triage.
- `gql_operation_callers(op_name, op_type=None, limit=50)` — optional filter to `{query, mutation, subscription}`. `labels(caller)[0]` returned as `caller_kind`.
- `most_injected_services(limit=20, max=100)` — the canonical "DI hub detection" query. `count(DISTINCT caller)` so a caller injecting into multiple methods counts once.
- `find_class(name_pattern, limit=50)` — case-sensitive `CONTAINS` backed by the `class_name` range index. Empty pattern rejected explicitly.
- Shared `_validate_limit(limit, max_limit=1000)` helper. Rejects non-int (including `bool`, because `bool` is an `int` subclass in Python) before any Cypher is built. **Limits are validated-then-interpolated because Neo4j 5.x rejects `LIMIT $param` as a syntax error** — every new tool follows the same pattern `callers_of_class.max_depth` does.
- +41 new tests (parametrized shared error-path coverage across all 5 tools; happy-path + limit-validation + empty-input per tool).
- End-to-end verified live against Twenty: every tool returned real data. `most_injected_services(5)` surfaced `TwentyConfigService` (136 injections), matching the raw Cypher we ran earlier.
- Code-reviewer pass returned **clean** on the first round — no fixes needed.

---

## Repository state

| Thing | Value |
|---|---|
| Current branch | `dev` |
| Base branch | `main` |
| Commits ahead of `main` | 6 (see above) |
| Remote status | `dev` pushed to `origin/dev` ✅ |
| PR | **not opened yet** |
| Working tree | Clean (only `.claude/` untracked, intentional — agent config) |
| Test count | 103 |
| Test runtime | ~10 s |
| Byte-compile | Clean |
| Last `pip install -e .` | After commit `c198c5d` (MCP server). Re-run if you modify `pyproject.toml`. |

---

## Environment setup

### Python + venv

```bash
cd codegraph
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .
.venv/bin/pip install "mcp>=1.0" pytest    # MCP extra + test deps
```

- System `python3` (3.12) is fine for `compileall` and `pytest` if pytest is installed globally, but **all CLI-level invocations of `codegraph` / `codegraph-mcp` must go through `.venv/bin/`** because they depend on `typer`, `neo4j`, `tree-sitter`, `rich`, and `mcp` which live in the venv.
- There is **no system-wide `python`** (no `python` on PATH, only `python3`). Bash tool calls using `python` will fail with command-not-found. Use `python3` or `.venv/bin/python`.

### Neo4j

The bundled `codegraph/docker-compose.yml` runs Neo4j on:
- Bolt: `bolt://localhost:7688`
- Browser: `http://localhost:7475`
- Auth: `neo4j` / `codegraph123`

Start with `cd codegraph && docker compose up -d`. The container name is `codegraph-neo4j`. It's currently **up and healthy** and has the Twenty graph loaded from the last `codegraph index` run.

### Twenty CRM fixture

Cloned at `/tmp/twenty` this session. Shallow clone from `https://github.com/twentyhq/twenty.git`. Two packages that matter for codegraph:
- `/tmp/twenty/packages/twenty-server` — NestJS backend (v11.1.16, yarn). 2549 classes, 110 endpoints, 428 GraphQL operations.
- `/tmp/twenty/packages/twenty-front` — React (TypeScript) frontend. Tons of components + hooks.

`/tmp/twenty` may or may not survive between sessions — `/tmp` is wiped on reboot. If missing, re-clone with `git clone --depth 1 https://github.com/twentyhq/twenty.git /tmp/twenty`.

The two opt-in integration tests in `tests/test_framework.py` (`test_twenty_server_is_nestjs`, `test_twenty_front_is_react_with_high_confidence`) auto-skip if `/tmp/twenty` is missing, so they don't block CI.

### agent-onboarding source repo

Cloned at `/tmp/agent-onboarding` on branch `autoplay`. This is the source of the ports we did. The 6 fixture apps used by `tests/test_framework.py` live at `/tmp/agent-onboarding/tests/fixtures/{react,nextjs,vue,sveltekit,angular,odoo}-app`. If missing, re-clone from the internal GitLab: `git clone git@gitlab.leyton.fr:masri/agent-onboarding.git /tmp/agent-onboarding && cd /tmp/agent-onboarding && git checkout autoplay`.

---

## Running things

### Reindex Twenty (from scratch — wipes the graph)

```bash
cd codegraph
.venv/bin/codegraph index /tmp/twenty -p packages/twenty-server -p packages/twenty-front
```

Takes ~30s parse + ~65s resolve on this machine. Reports stats at the end. Default `--wipe` is on; pass `--no-wipe` if you want incremental (currently a no-op — everything re-merges over the top, no stale cleanup).

### Query the graph directly

```bash
.venv/bin/codegraph query "MATCH (p:Package) RETURN p.name, p.framework, p.confidence"
.venv/bin/codegraph query --json "MATCH (c:Class {is_controller:true}) RETURN c.name LIMIT 5"
```

### Run the MCP server standalone (for JSON-RPC smoke tests)

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | timeout 10 .venv/bin/codegraph-mcp
```

For `tools/call`, build a fresh stdin each time (FastMCP handles one init + many calls per session fine, but multi-call + tool-call + complex queries can take >10s; bump the timeout on slower machines).

### Run tests

```bash
cd codegraph
.venv/bin/python -m pytest tests/ -q          # full suite, ~10s
.venv/bin/python -m pytest tests/test_mcp.py -v  # just mcp
python3 -m pytest tests/ -q                    # system python works too if pytest is installed globally
```

### Wire the MCP server into Claude Code

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "codegraph": {
      "command": "/full/path/to/codegraph/.venv/bin/codegraph-mcp",
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

Restart Claude Code. The 10 codegraph tools should appear in the `/mcp` menu. **Not yet verified against a live Claude Code client** — only smoke-tested via the raw JSON-RPC pipe.

---

## What's next (ranked)

The ranking assumes the same pattern the session has been using: `plan → implement → e2e validate → review loop → push`. Each tier item has enough detail to `/plan` it without re-exploring.

### Tier A — cheap, high-leverage (pick one)

#### A1. MCP resources / prompts — `queries.md` as named prompt templates

**What:** Expose the queries in `codegraph/queries.md` as `@mcp.prompt()` templates. An agent calls `prompts/get` with a name like `"blast_radius"` and gets back a structured prompt the LLM can use to drive the next tool call, instead of having to hand-write Cypher via `query_graph`.

**Why:** Natural companion to the 10 tools we just shipped. Converts the "examples" documentation into machine-consumable templates. No schema changes, no loader changes, no new dependencies.

**Scope:** ~150 LOC.
- Parse `queries.md` → extract each `## N. Title` section + its Cypher fenced block.
- Register each as a `@mcp.prompt(name="...", description="...")` returning a `PromptMessage` list that includes the Cypher + an explanation of what it does.
- Alternatively: hard-code a curated subset of 5-8 prompts in `mcp.py` rather than parsing `queries.md` (more maintainable but drifts from docs).
- Tests: monkeypatch the FastMCP prompt registry, assert the registered prompts have the expected names.
- README: one new subsection under "Exposing the graph to Claude via MCP".

**Gotchas:** FastMCP's prompt API is separate from the tool API and uses a different decorator signature. The existing test fake (`FakeDriver`) doesn't need changes; prompts don't touch Neo4j. `mcp.server.fastmcp.FastMCP.list_prompts()` is the sister to `list_tools()`.

**Delivers:** Completes the "expose the graph to agents" story on the MCP side. Nothing else is missing at the retrieval layer.

#### A2. GitHub Actions CI workflow

**What:** `.github/workflows/test.yml` that runs pytest on push and PR.

**Why:** No CI yet. Cheap (~30 LOC YAML). Worth doing before the repo sees contributors or before we open the PR for the 6 session commits.

**Scope:** ~30 LOC YAML.
- Python 3.10, 3.11, 3.12 matrix.
- Install `requirements.txt` + `mcp` + `pytest`.
- Run `python -m compileall -q codegraph` + `python -m pytest tests/`.
- Skip Neo4j-requiring tests automatically (none currently require it; all are mocked).
- The two Twenty integration tests in `test_framework.py` auto-skip because `/tmp/twenty` doesn't exist in CI — no extra guarding needed.

**Gotchas:** None. This is pure infra.

**Delivers:** Safety net before the PR lands.

### Tier B — meaningful, moderate effort

#### B1. Incremental re-indexing — `codegraph index --since HEAD~N`

**What:** Diff git, re-parse only touched files, upsert into the existing graph (no wipe).

**Why:** Today `codegraph index` wipes and rebuilds. For agent workflows where Claude Code edits files in a long session, you can't keep the graph current without a ~95s rebuild. Incremental closes that loop. Listed on the README roadmap as "Incremental re-indexing on file changes".

**Scope:** ~400 LOC. Touches:
- `codegraph/cli.py` — new `--since <ref>` / `--since-files <file1,file2>` flags. Mutually exclusive with the default "index everything" mode.
- `codegraph/loader.py` — new semantics: don't wipe, delete-then-merge per file, handle orphan node cleanup for files that were deleted since the last run.
- `codegraph/parser.py` — unchanged (parser is stateless).
- `codegraph/resolver.py` — tricky. Cross-file resolution is a global pass. Two options:
  - (a) Reparse only changed files + run `link_cross_file` over the full index each time (slower but safe).
  - (b) Re-run `link_cross_file` only for edges touching changed files (faster but has cascade cases).
  - **Recommend (a) for v1**, add (b) as a follow-up if perf is a real problem.
- `codegraph/tests/test_incremental.py` — new file. Create a small fake repo in `tmp_path`, index it, modify one file, re-index with `--since`, assert the graph matches a full re-index of the new state.

**Gotchas:**
- **Stale edges.** If an old file had `IMPORTS` edges that no longer exist, the new parse will emit fewer edges but the old ones will still be in Neo4j. Need to delete all edges originating from `:File {path:$p}` before re-inserting.
- **Orphan nodes.** Functions / Classes inside a now-deleted file need cleanup too. Or accept that they'll be orphaned — Cypher queries filter by `:File` membership typically, so orphans may be harmless.
- **Git detection.** `--since HEAD~5` implies a git repo; add an error for non-git paths or fall back to "just reindex everything".

**Delivers:** The final roadmap item for "make the graph stay fresh". Unlocks **Tier B2** (MCP write tools) because it provides the upsert primitive.

#### B2. MCP write tools behind `--allow-write`

**What:** Add `reindex_file(path)` and `wipe_graph()` tools to `codegraph-mcp`, gated by a `--allow-write` flag on the server.

**Why:** Lets Claude Code refresh the graph after editing without shelling out. Currently the agent has to drop to Bash, run `codegraph index`, and wait 95s.

**Scope:** ~100 LOC after B1 lands.
- New CLI flag `codegraph-mcp --allow-write` (passed via the `args` field in `~/.claude.json` `mcpServers` block).
- Sessions are still `READ_ACCESS` for the existing 10 tools; the new tools open a separate `WRITE_ACCESS` session.
- `reindex_file(path)` calls the same internals as `codegraph index --since-files <path>`.
- `wipe_graph()` requires a confirmation parameter or just a strong warning in the docstring.
- Tests: monkeypatched driver + assert `WRITE_ACCESS` was requested for the write tools only.

**Blocked by:** B1 (incremental re-indexing).

#### B3. Investigate the 29% unresolved imports

**What:** Twenty indexing logged `imports: total=77417 resolved=54823 unresolved=22594 (70.8% resolved)`. 22594 unresolved is a lot. Some are legit external npm packages (fine — `:External` nodes), but some fraction are definitely TS path aliases or barrel re-exports that the resolver gave up on.

**Why:** Edges we're dropping on the floor reduce the value of the graph for every downstream query.

**Scope:** Investigation first, then fix. Needs:
- Dump a sample of unresolved import specifiers: `MATCH (f:File)-[r:IMPORTS_EXTERNAL]->(e:External) RETURN e.specifier, count(f) AS n ORDER BY n DESC LIMIT 50`.
- Categorize: (a) real externals like `react`, `lodash` — keep. (b) tsconfig path aliases like `@/components/...` — resolver should have handled these. (c) barrel re-exports like `../../shared` → `shared/index.ts` — may be falling through.
- Read `codegraph/resolver.py` to understand which step gives up and why.
- Likely fix: beef up the alias resolution + barrel-export handling in `resolver.py`.

**Needs investigation before planning.** Don't write a plan from cold.

### Tier C — defer

#### C1. `relationship_mapper` port (low value)

`RENDERS` and `RENDERS_COMPONENT` edges are already in the schema. The only net-adds from agent-onboarding's `relationship_mapper.py` would be `NAVIGATES_TO` (route → route) and `SHARES_STATE` (components using same hooks/stores). Both are fuzzy heuristics with low confidence. Not worth it until MCP usage reveals a specific need.

#### C2. Python / Go parser frontends

Big tree-sitter work. Not the bottleneck. Current codebase is TypeScript-focused and that's fine.

#### C3. `knowledge_enricher` LLM-powered semantic pass

The biggest bet from the agent-onboarding analysis. Adds LLM-generated semantic edges (cross-file feature clustering, element → feature binding, etc.) on top of the structural graph. Worth revisiting once real-world MCP usage surfaces questions worth enriching. Defer until agents are actually asking questions the structural graph can't answer.

#### C4. Rich per-query provenance in MCP responses

Attaching file paths and line ranges to every returned row would help LLM grounding. Separate concern; defer until someone asks.

---

## Known open questions

1. **Does the live Claude Code client actually show the 10 codegraph tools?** Only verified via raw JSON-RPC pipe this session. Need to add the `mcpServers` block to `~/.claude.json`, restart Claude Code, and confirm `/mcp` lists codegraph. Low risk but unverified.

2. **Unresolved imports percentage** (see B3). 29% is suspicious; investigation before a fix.

3. **`find_class` case sensitivity** — we kept it case-sensitive so the `class_name` index is usable. If agents consistently miss the case, we may need a `name_lower` property and a matching index. Revisit if user reports come in.

4. **`gql_operation_callers` name uniqueness** — Twenty has 428 GraphQL operations. Some names may exist across query/mutation/subscription types. The `op_type` parameter narrows it, but the default (None) returns all matches. Is that the right default? For now yes — the agent can filter client-side.

5. **Incremental indexing edge semantics** (see B1). Stale edge cleanup is the hardest piece. Full-delete-and-reinsert is safe but can cascade. A per-file edge TTL or versioning would be cleaner but much more work.

6. **Who is the canonical maintainer of `.codegraphignore`?** The file is hand-written by users. Do we want a `codegraph ignore init` command that scaffolds a sensible default? Not shipped this session, deliberately out of scope for the ignore commit.

---

## Session workflow conventions (for the next agent)

These have worked well and are worth continuing:

1. **`/plan` before every non-trivial implementation.** Write the plan to `~/.claude/plans/<name>.md`. Include: Context (why), Critical files, Design decisions with rejected alternatives, Tests, Verification, explicit Non-goals. Get user sign-off before coding.

2. **Atomic commits with detailed messages.** Every commit is scoped to one conceptual change. Commit messages are ~30-50 lines with an overview, a per-file rationale, and a verification note. See `git log --format=fuller` for the established style.

3. **E2E test on Twenty after every feature.** Run `codegraph index /tmp/twenty -p packages/twenty-server -p packages/twenty-front` and check `:Package` / MCP tool responses against a real monorepo. This is how we caught the framework detector's NestJS / workspace / lockfile bugs.

4. **Run `feature-dev:code-reviewer` after shipping.** Loop until clean. Round 1 usually finds 2-5 issues, round 2 usually finds 1-2, round 3 is usually clean. The scope prompt in this session's review calls was deliberately tight (per-commit) — agents get confused if you hand them the whole repo.

5. **Limits in Cypher.** Neo4j 5.x **does not accept `LIMIT $param`** as a bind parameter. Validate the integer via `_validate_limit` and **interpolate** into the Cypher string. This is the same pattern `callers_of_class.max_depth` uses. Every new MCP tool with a limit should follow suit.

6. **Test fakes pin the pattern.** The `_FakeDriver` / `_FakeSession` / `_FakeRecord` trio in `test_mcp.py` is how we test Neo4j-dependent code without Neo4j. It's deliberately minimal — if you find yourself extending it significantly, consider whether you're testing the wrong layer.

7. **Never commit the `.claude/` directory.** It's intentionally untracked (agent config, per-session). Leave it out of `git add`.

---

## Plan archive — what's been written

Plans live in `~/.claude/plans/`. Not in the repo. Relevant ones from this session:

- `sunny-giggling-moon.md` — **this file gets overwritten each plan mode session.** Currently contains the "extend MCP tool surface with 5 retrievers" plan that shipped as `7588522`. Previously contained the ignore filter plan (b71bc45), then the MCP server plan (c198c5d), then the framework-detector fix plan (e7382f7), then this one. Each new `/plan` overwrites the previous.
- `framework-detector-port.md` — the framework detection port plan that shipped as `9fb4d1d`. Not overwritten.

**Next agent caveat:** if you're about to `/plan` something, be aware that the harness may dump its output into `sunny-giggling-moon.md` and overwrite whatever was there. Read the file before starting a plan mode session if you want to preserve the prior plan — copy it elsewhere first.

---

## Non-goals (keep these out of scope unless user asks)

- **Make `codegraph` work on non-TypeScript codebases.** It's TS-focused by design.
- **Web UI or dashboard.** Neo4j Browser at `:7475` is the interactive surface; everything else is Cypher + MCP.
- **Real-time file watching.** Incremental re-index on demand is enough; no watchers.
- **Auth / TLS / rate-limiting on MCP.** Stdio-only, trusts the local Claude Code process spawning it.
- **Exposing internal state via `query_graph` helper methods** — the escape hatch is `query_graph(raw_cypher)` and that's by design.
- **Database migrations between codegraph schema versions.** Users wipe and re-index when upgrading.
- **Windows support.** Not tested; not a goal.
- **Replacing the existing `is_controller` / `is_component` / etc. per-file flags.** They stay alongside the new `:Package` node as within-package resolution.
- **More than 10 MCP tools in a batch.** If tool surface grows further, add tools incrementally in small batches so each gets a proper review loop.
- **Porting more from `agent-onboarding/`.** Only the three pieces we shipped (ignore filter, framework detector, relationship-mapper-skipped) made sense. The rest (`knowledge_enricher`, `selector_extractor`, `deep_selector_agent`, `style_extractor`, `page_scanner`, `smart_explorer`) are browser/UI-specific and don't fit codegraph's value prop.

---

## How to continue in a fresh agent session

Starter prompt template for the next agent:

```
I'm continuing work on codegraph, a Python tool that indexes TypeScript
monorepos into Neo4j. Read ROADMAP.md at the repo root for the full
context of what shipped in the previous session and what's next.

Current working directory: /home/edouard-gouilliard/Obsidian/SecondBrain/Personal/projects/graphrag-code

Before doing anything:
1. `git status` and `git log --oneline -10` to confirm repo state.
2. Check that .venv exists in codegraph/ — if not, rebuild per ROADMAP.md.
3. Verify Neo4j is up: `docker ps | grep codegraph-neo4j`.
4. Run the test suite as a smoke check: `cd codegraph && .venv/bin/python -m pytest tests/ -q`.

Then pick up at the "What's next" section of ROADMAP.md. My picks for
next step, in order: A1 (MCP prompts), A2 (CI workflow), B1 (incremental
re-indexing). Propose one, /plan it, then implement.

Do not push to origin without asking. Do not open a PR without asking.
```

---

## Appendix — quick reference of what's where

### Key source files (all under `codegraph/codegraph/`)

| File | Purpose | LOC |
|---|---|---|
| `cli.py` | Typer CLI: `index`, `query`, `validate`, `wipe`, REPL | ~490 |
| `parser.py` | tree-sitter TS/TSX walker with framework-construct detection | ~1160 |
| `resolver.py` | Cross-file reference resolution, `link_cross_file`, `Index` aggregator | ~550 |
| `loader.py` | Neo4j batch writer, constraints, indexes, `LoadStats` | ~830 |
| `schema.py` | Node + edge dataclasses shared across parser → loader | ~370 |
| `config.py` | `codegraph.toml` / `pyproject.toml` config loader | ~190 |
| `ignore.py` | `.codegraphignore` parser + `IgnoreFilter` class | ~180 |
| `framework.py` | Per-package framework detection (`FrameworkDetector`) | ~510 |
| `mcp.py` | FastMCP stdio server with 10 tools | ~410 |
| `ownership.py` | Git log → author mapping onto graph nodes | ~130 |
| `validate.py` | Post-load sanity-check suite | ~400 |
| `repl.py` | Interactive Cypher REPL | ~320 |
| `utils/neo4j_json.py` | Shared `clean_row` helper used by cli + mcp | ~30 |

### Tests

| File | Count | Target |
|---|---|---|
| `tests/test_ignore.py` | 19 | `ignore.py` + `cli._strip_ignored_components` + `cli._load_ignore_filter` |
| `tests/test_framework.py` | 23 | `framework.py` (14 existing + 9 from `fix(framework)`, including 2 opt-in Twenty tests) |
| `tests/test_mcp.py` | 61 | `mcp.py` (20 original + 41 from the retriever batch) |
| **Total** | **103** | |

### Key decisions recorded in commit messages (not README)

Grep the session's commits for these topics:

- Why `.codegraphignore` not `.agentignore` → `b71bc45` body
- Why `is_component = False` rather than deleting `FunctionNode` → `b71bc45` body
- Why `:Package` as flat properties rather than `:Package-[:USES]->:Framework` → `9fb4d1d` plan (`framework-detector-port.md`)
- Why NestJS indicator weights outrank React → `e7382f7` body
- Why the `workspaces` field guard on workspace-root package.json → `e7382f7` body
- Why the driver is lazy and not eager → `39be5c2` body
- Why `_FakeSession.run` unconditionally pops → `39be5c2` body
- Why `LIMIT` is interpolated not parameterised → `7588522` body and commit messages of earlier MCP tools

### Git remotes

```
origin  git@github.com:cognitx-leyton/graphrag-code.git
```

Protected branches are `main`, `release`, `hotfix`. `dev` is the working branch. All PRs go into `main` via the dev → main flow.
