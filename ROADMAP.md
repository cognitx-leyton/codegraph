# codegraph — Roadmap & Session Handoff

> **Purpose of this document.** Capture enough context for a fresh agent session (or a human returning after time away) to continue work on codegraph without re-deriving state from scratch. Separate from the user-facing roadmap bullets in `README.md`, which stay short and pitch-oriented.
>
> **Last updated:** 2026-04-17 after commits `af77cd3` → `ee2ac35` (slash commands + arch-check CI + onboarding scaffolder + Python Stage 2 + MCP prompt templates + describe_schema CypherSyntaxError fix + query_graph bool/limit validation fix + max_depth bounds + bool bypass fix for all three traversal tools + 15 missing MCP tool tests for full coverage + query_graph error-handling dedup into _run_read + container name collision fix via project-path hash suffix).

---

## TL;DR — where we are

- **Branch:** `archon/task-fix-issue-18-container-name-collision`. Working tree clean. Container name collision fix landed as `ee2ac35`.
- **Tests:** 317 passing + 1 deselected (Docker-slow integration test), 0 warnings. Run via `.venv/bin/python -m pytest tests/ -q` from `codegraph/`.
- **Graph indexed:** Twenty CRM is currently loaded into the local Neo4j container at `bolt://localhost:7688` (13,473 files, 2,559 classes, 6,088 methods, 5,562 CALLS, 6,708 hook usages, 4,593 RENDERS).
- **MCP server:** 13 read-only tools live + **29 prompt templates** (all Cypher blocks from `queries.md` auto-registered via `_register_query_prompts()`). `codegraph-mcp` console script registered. Smoke-tested via raw JSON-RPC.
- **Package:** `cognitx-codegraph` v0.1.8 in `pyproject.toml`. Wheel + sdist build cleanly. **Not yet on PyPI** — needs one-time operational setup (Trusted Publisher registration).
- **CI:** `.github/workflows/arch-check.yml` — every PR to `main` spins up Neo4j, indexes, runs `codegraph arch-check`, fails on architecture violations. Verified live on PR #8 (42s, exit 0).
- **Onboarding:** `codegraph init` scaffolds everything needed to dogfood codegraph in any repo. Live-tested against 3 fixtures including the real Twenty monorepo (13k files indexed end-to-end).
- **Python Stage 2:** FastAPI / Flask / Django / SQLAlchemy framework detection + `:Endpoint` nodes. `/trace-endpoint` now works against Python repos.

---

## Shipped since the last roadmap update (commit `edd53cb`)

```
ee2ac35 fix(init):      prevent container name collision via project-path hash suffix (#18)
8c5396c Merge pull request #72 from cognitx-leyton/archon/task-chore-issue-32-query-graph-dedup
0cad8af chore:          bump version to 0.1.9
6d9205b chore(mcp):     deduplicate query_graph error-handling into _run_read (#32)
27d4fec chore:          bump version to 0.1.8
e77e3cd Merge pull request #70 from cognitx-leyton/archon/task-chore-issue-31-missing-mcp-tests
939dfc3 test(mcp):      add 15 missing MCP tool tests for full coverage (#31)
8556630 chore:          bump version to 0.1.7
e500554 Merge pull request #66 from cognitx-leyton/archon/task-fix-issue-33-max-depth-bounds
6b74617 fix(mcp):       reject bool values for max_depth in callers_of_class, calls_from, callers_of (#33)
619923e chore:          bump version to 0.1.6
87623d9 chore:          bump version to 0.1.5
6fe0730 fix(mcp):       reject bool and out-of-range limit in query_graph (#30)
11f02cb chore:          bump version to 0.1.4
fa031dd fix(mcp):       catch CypherSyntaxError in describe_schema before ClientError (#29)
eaee6a7 chore:          bump version to 0.1.3
357ad03 feat(mcp):      expose queries.md as MCP prompt templates (#12)
6493224 feat(parser):   Python Stage 2 framework detection + endpoints + resolver fixes
c6da6c6 fix(cli):       detect modern src-layout Python packages via pyproject.toml
d0abe53 feat(onboarding): one-command install for any repo via codegraph init
b12520a chore(ci):      enable workflow_dispatch for arch-check
55789fd feat(arch-check): first-class CLI subcommand + GitHub Actions gate
af77cd3 feat(commands): add 5 graph-powered slash commands for daily dev work
453a6a4 chore(loader):  unify test-file pairing + widen graph index scope
d48ee26 feat(parser):   emit Python CALLS edges + wire MCP call-graph tools
edb8cca feat(parser):   extract docstrings, params, and return types for Python
1cfc590 feat(claude):   wire codegraph CLI into this repo's Claude Code setup
154954c feat(parser):   index Python codebases via tree-sitter-python (Stage 1)
09822fa docs(roadmap):  session handoff document for continuing work across agents
```

Six sessions' worth of work grouped by theme:

### Init fix: container name collision via project-path hash suffix (issue #18)
- `ee2ac35 fix(init)` — `codegraph init` previously derived the Docker container name solely from the repo directory basename (`cognitx-codegraph-{repo_name}`). Two worktrees with the same basename (e.g. two repos both named `app`) would collide on the container name, causing the second `init --yes` to silently reuse or clobber the first container. Fixed in `init.py` by computing an 8-character SHA-1 hex digest of the resolved absolute repo path (`hashlib.sha1(str(detected.root.resolve()).encode()).hexdigest()[:8]`) and appending it: `cognitx-codegraph-{repo_name}-{path_hash}`. The hash is deterministic — same path always produces the same suffix — so re-running `init` on the same repo continues to reference the correct container. Two new unit tests in `test_init.py`: `test_container_name_includes_path_hash` (two `app`-named repos → distinct names, valid 8-char hex suffixes) and `test_container_name_is_deterministic` (same path → identical name across two calls). Integration test in `test_init_integration.py` updated to compute the expected hash and match the full `cognitx-codegraph-{name}-{hash}` pattern. Review also added `.resolve()` defensively so the hash is stable even if `_prompt_config` is called before path resolution. Test count: 315 → 317.

### Version bump
- `0cad8af chore` — bumped `pyproject.toml` to v0.1.9 after PR #72 merged.

### MCP code deduplication: query_graph error-handling into _run_read (issue #32)
- `6d9205b chore(mcp)` — Replaced the 10-line duplicated `try/except` block inside `query_graph()` (lines 234–243) with a single delegation: `return _run_read(cypher)[:limit]`. The `_run_read` helper already owns driver acquisition, session management, and all error handling (`CypherSyntaxError`, `ClientError`, `ServiceUnavailable`). The old inline copy was an exact duplicate. Post-dedup: `query_graph` is now 4 lines of pure input validation + delegation, same output contract. All 8 `query_graph` tests pass unchanged — error handling, limit slicing, and row serialisation all work identically through `_run_read`. One subtle trade-off accepted: the new code calls `clean_row()` on all rows before slicing (whereas the old code sliced raw records first), but `clean_row()` is trivially cheap and Cypher-level `LIMIT` in the user's query bounds the set in practice.

### MCP test coverage: 15 missing tool tests (issue #31)
- `939dfc3 test(mcp)` — Added 15 unit tests to `tests/test_mcp.py` (94 → 109 in that file; suite 300 → 315 overall). Covered three previously untested tools: `calls_from` (happy-path, file-filter, bad-limit), `callers_of` (happy-path, file-filter, bad-limit), `describe_function` (happy-path, file-filter, no-decorators). Also extended the two error-path parametrized tests (`test_new_tools_surface_client_error`, `test_new_tools_surface_service_unavailable`) with three entries each for the new tools. Each test verifies output data shape, Cypher query structure, parameter binding, and error handling — matching the established `_FakeDriver` pattern.

### MCP bug fix: max_depth bounds + bool bypass in traversal tools (issue #33)
- `6b74617 fix(mcp)` — `callers_of_class`, `calls_from`, and `callers_of` had mismatched `max_depth` bounds and all three let `max_depth=True` / `False` slip through validation (Python `bool` is a subclass of `int`). Fixed in two passes: (1) aligned all three tools to `default=1`, `max=5` (was: `callers_of_class` had `default=3`, `max=10`; the other two were already `default=1`, `max=5`); (2) added `or isinstance(max_depth, bool)` guard to each validator, matching the `_validate_limit` pattern already in use for `limit` parameters. Docstrings and error messages updated to reflect the new bounds. `tests/test_mcp.py` changes: 3 existing `callers_of_class` tests updated for new bounds; 6 new tests added for `calls_from` (default, custom, bad); 6 new tests added for `callers_of` (default, custom, bad); `True` and `False` added to all three `bad` parametrize lists (6 more test cases). Test count 280 → 300.

### MCP bug fix: query_graph bool and out-of-range limit validation (issue #30)
- `6fe0730 fix(mcp)` — `query_graph()` was silently capping `limit=5000` to 1000 instead of rejecting it, and accepted `True`/`False` as valid limits (Python bool is a subclass of int, so the old `isinstance(limit, int)` guard passed). Fixed by replacing the inline `isinstance` check + `min(limit, 1000)` cap with a call to `_validate_limit(limit)`, the same helper already used by all 7 other tools in `mcp.py`. Also fixed the stale docstring ("cap 1000" → "max 1000"). Three test changes in `test_mcp.py`: updated error message in `test_query_graph_rejects_bad_limit`; renamed `test_query_graph_caps_huge_limit` → `test_query_graph_rejects_huge_limit` (now expects rejection for limit=5000); added parametrized `test_query_graph_rejects_bool_limit` covering `True` and `False`. Test count 278 → 280.

### MCP bug fix: describe_schema CypherSyntaxError (issue #29)
- `fa031dd fix(mcp)` — `describe_schema()` in `mcp.py` now catches `CypherSyntaxError` before the broader `ClientError` handler, returning `{"error": "Cypher syntax error: ..."}` consistently. Matches the pattern already used in `_run_read()` and `query_graph()`. One new test (`test_describe_schema_surfaces_cypher_syntax_error`) added to `test_mcp.py` — injects a `CypherSyntaxError`, calls `describe_schema()`, asserts the error dict has the correct prefix and original message. Test count 277 → 278.

### MCP prompt templates (issue #12)
- `357ad03 feat(mcp)` — `_parse_queries_md()`, `_slugify()`, `_register_query_prompts()` added to `mcp.py` (lines 47–131). Parses all `##` headings + fenced Cypher blocks in `queries.md`, registers each as a FastMCP `Prompt` via `Prompt.from_function()`. 29 prompts registered at server startup (matches the 29 Cypher blocks in `queries.md`). Prompt names are slugified from the heading (e.g. `schema-overview`, `4-impact-analysis-who-depends-on-x`); duplicate headings get `-2`/`-3` suffixes. `//` comment lines become descriptions; heading is the fallback. Missing `queries.md` is handled gracefully (0 prompts, no crash). 10 new tests in `test_mcp.py` cover parsing, slugification, registration, rendering, and the missing-file edge case.

### Python frontend (Stage 2)
- `6493224 feat(parser)` — `py_parser.py` extended with framework detection for FastAPI (`@app.get` / `@router.post`), Flask (`@app.route`), Django (`urls.py` path matching + class-based views), and SQLAlchemy (`class Model(Base)` with `Column` fields). Emits `:Endpoint` nodes with method + path. `framework.py` gains `FrameworkType.FASTAPI` / `FLASK` / `DJANGO` with scored heuristics. Resolver fixes for edge cases exposed by the e2e test. `/trace-endpoint` now returns rows against Python repos. Adds 3 new test files: `test_py_framework.py` (13 tests), `test_py_parser_endpoints.py` (18 tests), `test_resolver_bugs.py` (13 tests).

### Python frontend (Stage 1)
- `154954c feat(parser)` — `py_parser.py` with tree-sitter-python. Walks modules, classes, methods, imports, decorators. Mirrors `parser.py`'s `ParseResult` contract. Python frontend is an **optional extra** (`pip install "cognitx-codegraph[python]"`), keeps the TS-only install light.
- `edb8cca feat(parser)` — extend FunctionNode/MethodNode with `docstring`, `return_type`, `params_json`. Parser emits them from Python AST; loader persists them on the node.
- `d48ee26 feat(parser)` — Python method CALLS edges. Covers `self.foo()` / `cls.foo()` → `"this"`, `self.field.bar()` → `"this.field"`, bare `foo()` / `obj.foo()` → `"name"`, `super().foo()` → new `"super"` resolution via `class_extends`. Confidence="typed" for all first three. Also fixed loader bug where function-level `DECORATED_BY` edges were silently dropped (the partitioner only routed class + method prefixes).
- `453a6a4 chore(loader)` — shared `TS_TEST_SUFFIXES` / `PY_TEST_PREFIX` / `PY_TEST_SUFFIX_TRAILING` constants in `schema.py`; `_write_test_edges` now pairs Python `test_*.py` / `*_test.py` → `*.py` (same-directory MVP). `codegraph/tests/` included in the default index scope.

### Daily slash commands (5 new)
- `af77cd3 feat(commands)` — `.claude/commands/{blast-radius,dead-code,who-owns,trace-endpoint,arch-check}.md`. Each mirrors the existing `/graph` + `/graph-refresh` frontmatter + narrative. Zero new code; pure Cypher curation over the established MCP surface.

### Architecture-conformance CI gate
- `55789fd feat(arch-check)` — `codegraph/codegraph/arch_check.py` with `PolicyResult` / `ArchReport` dataclasses mirroring `validate.py`. 3 built-in policies: `import_cycles`, `cross_package`, `layer_bypass`. CLI subcommand `codegraph arch-check [--json]` exits 0/1 per the violation count. `.github/workflows/arch-check.yml` spins up `neo4j:5.24-community` as a service container on every PR to `main`. Full e2e verified on PR #8: 42s, 3/3 PASS, report artifact uploaded.
- `b12520a chore(ci)` — added `workflow_dispatch` so the gate can be triggered manually from the Actions UI without a PR.

### Onboarding (`codegraph init`)
- `d48ee26` (concurrent work) + `d0abe53 feat(onboarding)` — `codegraph init` scaffolds `.claude/commands/` (×7), `.github/workflows/arch-check.yml`, `.arch-policies.toml`, `docker-compose.yml`, and a `CLAUDE.md` snippet. With `--yes` also starts Neo4j via `docker compose up -d`, waits for HTTP readiness, and runs the first index. Flags: `--force`, `--yes`, `--skip-docker`, `--skip-index`. Templates (11 files) live under `codegraph/codegraph/templates/` and ship with the wheel via `[tool.setuptools.package-data]`.
- **PyPI rename**: `pyproject.toml` name → `cognitx-codegraph` v0.2.0 (the bare `codegraph` name is taken on PyPI at v1.2.0 by a different project). CLI command stays `codegraph` because that's declared separately in `[project.scripts]`. `.github/workflows/release.yml` publishes on `v*` tags via OIDC Trusted Publisher — no token in secrets.
- **`.arch-policies.toml` config** — `codegraph/codegraph/arch_config.py` parses per-repo policy tuning + user-authored `[[policies.custom]]` Cypher policies. Tunes built-ins (cycle hop range, cross-package pairs, service/repository suffix names). `codegraph arch-check --config <path>` honours explicit overrides.
- `c6da6c6 fix(cli)` — caught via real-repo e2e: `codegraph index` was misclassifying modern src-layout Python packages (with `pyproject.toml` but no root `__init__.py`) as TS. Fixed by adding `pyproject.toml` / `setup.py` / `setup.cfg` to the Python marker list. Twenty-style TS monorepos unaffected.

---

## Verified working (not just "tests pass")

Beyond unit/integration tests, these were dogfooded against real systems:

- **PR #8 on GitHub** — `cognitx-leyton/graphrag-code` PR `dev → main`, `arch-check` workflow ran 42s, 3/3 PASS, report artifact retrieved. Injected-cycle negative test confirmed exit 1.
- **Fresh pipx install** — built wheel → `pipx install cognitx_codegraph-0.2.0-py3-none-any.whl[python]` → `codegraph init --yes` in a throwaway synthetic monorepo → Neo4j container up, first index ran, 2 classes + 5 methods indexed.
- **Real monorepo (Twenty)** — `codegraph init --yes --skip-index` against `/home/edouard-gouilliard/.superset/worktrees/easy-builder/rls-enforcement-plan-implementation/` (13k TS files). Container healthy, scaffold idempotent with pre-existing `.claude/` + `CLAUDE.md`. Separately ran `codegraph index . -p packages/twenty-front -p packages/twenty-server` → 13,473 files parsed in 27s, 70.8% imports resolved, full load in ~3 min. `codegraph arch-check` correctly reported 184,809 real import cycles in `twenty-front/apollo/optimistic-effect/*` and `object-metadata/*`, exit 1.

---

## Repository state

| Thing | Value |
|---|---|
| Current branch | `archon/task-fix-issue-18-container-name-collision` |
| Base branch | `main` |
| Unpushed commits | 1 (`ee2ac35` — container name collision fix, pending PR) |
| Open PR | Issue #18 container-name-collision branch pending merge. |
| Working tree | Clean |
| Test count | 317 passing + 1 deselected |
| Test runtime | ~16 s |
| Byte-compile | Clean |
| Last editable install | After `357ad03`. Re-run `cd codegraph && .venv/bin/pip install -e .` after any `pyproject.toml` edit. |
| Wheel built? | Yes — `codegraph/dist/cognitx_codegraph-0.2.0-py3-none-any.whl` (from this session) |

---

## Environment setup

### Python + venv

```bash
cd codegraph
python3 -m venv .venv
.venv/bin/pip install -e ".[python,mcp,test]"
```

- `[python]` enables tree-sitter-python (Stage 1 Python frontend).
- `[mcp]` installs the FastMCP stdio server.
- `[test]` installs pytest + pytest-cov.
- All CLI-level invocations of `codegraph` / `codegraph-mcp` must go through `.venv/bin/` OR be installed via `pipx install cognitx-codegraph` (which ships with Python 3.10+ and the tool lives on PATH).

### Neo4j

`codegraph/docker-compose.yml` runs Neo4j on:
- Bolt: `bolt://localhost:7688`
- Browser: `http://localhost:7475`
- Auth: `neo4j` / `codegraph123`

Start with `cd codegraph && docker compose up -d`. Container name: `codegraph-neo4j`.

Note: `codegraph init` scaffolds a *different* docker-compose for the target repo, exposing on ports 7687/7474 by default. Don't confuse the two — the codegraph-repo's dev Neo4j is on 7688/7475.

### Fixtures

- **Twenty CRM** — cloned at `/home/edouard-gouilliard/.superset/worktrees/easy-builder/rls-enforcement-plan-implementation/` (from the work-tree referenced in the last e2e verification). If missing: `git clone --depth 1 https://github.com/twentyhq/twenty.git /tmp/twenty`.
- **Synthetic test fixtures** live in `tests/` — `conftest.py` helpers + `tmp_path` scaffolding per test.

---

## Running things

### Scaffold a new repo (the main onboarding entry point)

```bash
pipx install --force '/path/to/codegraph/dist/cognitx_codegraph-0.2.0-py3-none-any.whl[python]'
cd /path/to/any-repo
codegraph init              # interactive
codegraph init --yes        # accept all defaults (scaffold + docker + first index)
codegraph init --yes --skip-docker --skip-index   # files-only dry run
```

After PyPI publish: replace the `pipx install` with `pipx install cognitx-codegraph`.

### Re-index Twenty (from scratch — wipes the graph)

```bash
cd codegraph
.venv/bin/codegraph index /path/to/twenty -p packages/twenty-server -p packages/twenty-front
```

Takes ~30s parse + ~100s resolve + ~50s load on this machine. Reports stats at the end.

### Re-index the codegraph repo itself (dogfood)

The `/graph-refresh` slash command does this — re-runs `codegraph index` against `codegraph/codegraph/` + `codegraph/tests/` with `--no-wipe --skip-ownership`.

### Query the graph

```bash
.venv/bin/codegraph query "MATCH (p:Package) RETURN p.name, p.framework, p.confidence"
.venv/bin/codegraph query --json "MATCH (c:Class {is_controller:true}) RETURN c.name LIMIT 5"
```

### Run the architecture-conformance gate locally

```bash
.venv/bin/codegraph arch-check                 # Rich table output, exits 0/1
.venv/bin/codegraph arch-check --json > arch-report.json
.venv/bin/codegraph arch-check --config ./my-policies.toml --repo /path/to/repo
```

### Run the MCP server standalone (JSON-RPC smoke test)

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | timeout 10 .venv/bin/codegraph-mcp
```

### Run tests

```bash
cd codegraph
.venv/bin/python -m pytest tests/ -q              # full suite, ~12 s
.venv/bin/python -m pytest tests/ -q -m slow      # include Docker integration
.venv/bin/python -m pytest tests/test_mcp.py -v   # single module
```

### Wire the MCP server into Claude Code

Add to `~/.claude.json`:

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

(Assumes `pipx install cognitx-codegraph[mcp]` — the `codegraph-mcp` command lives on PATH.)

---

## What's next (ranked)

The ranking assumes the same `plan → implement → e2e validate → commit` cycle this project uses. Each item has enough detail to `/plan` it from cold.

### Tier A — operational (must-do before the v0.2.0 story is complete)

#### A1. Push `dev` + merge PR #8 + publish to PyPI

**What:** `git push origin dev`, bring PR #8 up to date, merge it, register `cognitx-codegraph` on pypi.org with Trusted Publisher config, push `v0.2.0` tag to trigger `release.yml`.

**Why:** Everything is built and verified. Only thing left is the one-time ops setup. Until this happens, "easiest possible onboarding" is blocked on users building the wheel locally.

**Scope:** ~30 min operational.
- `git push origin dev` — 5 unpushed commits land.
- PR #8 is already open; rebase or merge depending on how stale it is.
- PyPI: create the `cognitx-codegraph` project on pypi.org. Go to Project → Publishing → add Trusted Publisher with owner `cognitx-leyton`, repo `graphrag-code`, workflow `release.yml`, environment `release`.
- GitHub: Settings → Environments → create a `release` environment (required for Trusted Publishers to accept the OIDC token).
- `git tag v0.2.0 && git push origin v0.2.0` — `release.yml` auto-builds + publishes.
- Verify: fresh machine, `pipx install cognitx-codegraph` works.

**Gotchas:** If the PyPI project name `cognitx-codegraph` is also taken by the time you try (unlikely), rename in `pyproject.toml` and bump to 0.2.1.

**Delivers:** The "easiest possible" quickstart is truly live. `README.md` quickstart ships working.

#### A2. Live Claude Code client verification of the 10 MCP tools

**What:** Install `cognitx-codegraph[mcp]` on a real machine, add the `mcpServers` block to `~/.claude.json`, restart Claude Code, confirm the 10 tools appear in `/mcp`.

**Why:** We've smoke-tested via raw JSON-RPC but never verified the UI. Low risk, high confidence gain.

**Scope:** 15 min of manual verification.

### Tier B — feature work, ranked

~~#### B1. Python Stage 2 — framework detection + endpoints~~ **SHIPPED** (`6493224`)

~~#### B2. MCP resources / prompts — `queries.md` as named prompt templates~~ **SHIPPED** (`357ad03`)

#### B3. Incremental re-indexing (`codegraph index --since HEAD~N`)

**What:** Diff git, re-parse only touched files, upsert into the existing graph without wiping.

**Why:** Full re-index of Twenty takes ~3 min. For agent workflows where code changes mid-session, that's too slow to close the loop.

**Scope:** ~400 LOC. Touches `cli.py` (new flag), `loader.py` (upsert semantics, orphan cleanup), `resolver.py` (re-run `link_cross_file` over full index — option (a) from previous plans).

**Blocked by**: nothing. Unlocks **B4 (MCP write tools behind `--allow-write`)**.

#### B4. MCP write tools behind `--allow-write`

**What:** `reindex_file(path)` + `wipe_graph()` tools, gated by a `--allow-write` CLI flag on `codegraph-mcp`.

**Why:** Agents can refresh the graph after editing without shelling out for 3 min.

**Scope:** ~100 LOC after B3 lands. Separate `WRITE_ACCESS` session for these tools only.

#### B5. Agent-native RAG — graph-selected context injection

**What:** Claude Code hook / extension that, when the user mentions a symbol, queries the graph for its 1-hop neighbours and injects a tight brief (maybe 2k tokens) instead of letting the model grep/read raw files.

**Why:** The biggest potential unlock. Turns codegraph from "cool query tool" into "core context pipeline for every AI dev session." Novel enough to open-source as its own thing.

**Scope:** ~1 week of focused work. Needs a Claude Code extension surface (hook? plugin?) to inject context before tool calls. Likely prototyped as a separate repo first.

**Gotchas:** Tight coupling to Claude Code's extension API — may require using the official `@anthropic-ai/claude-code` SDK rather than MCP.

#### B6. Investigate the 29% unresolved imports

**What:** Twenty indexing resolves 70.8% of imports (54,820 / 77,389). Investigate what the 22,569 unresolved are.

**Why:** Edges we're dropping on the floor reduce the value of the graph for every downstream query.

**Scope:** Investigation first. Query: `MATCH (f:File)-[r:IMPORTS_EXTERNAL]->(e:External) RETURN e.specifier, count(f) AS n ORDER BY n DESC LIMIT 50`. Categorize: legit externals (keep), tsconfig path aliases (resolver bug), barrel re-exports (resolver bug). Likely fix is beefing up alias + barrel handling in `resolver.py`.

### Tier C — more arch-check policies

Custom Cypher policies are already supported via `[[policies.custom]]` in `.arch-policies.toml`. Worth shipping a few more **built-ins** for common needs:

- **Coupling ceiling** — any file with >N distinct IMPORTS edges is flagged.
- **Orphan detection** — functions/classes/endpoints with zero inbound references AND no framework-entry-point decorator. Already possible via the existing `/dead-code` slash command; promoting to a policy means it blocks merges.
- **Endpoint auth coverage** — every `:Endpoint` with `method IN ('POST','PUT','PATCH','DELETE')` must have a DECORATED_BY to an auth-guard. Requires knowing which decorators count as auth — configurable.
- **Public-API stability** — breaking changes to exported symbols detected by diffing graph state between commits (needs graph persistence beyond CI).

**Scope:** ~50 LOC per built-in + tests. Mostly a question of priority — each one is cheap.

### Tier D — defer (still)

- **`relationship_mapper` port** — `RENDERS` is already there; `NAVIGATES_TO` / `SHARES_STATE` are fuzzy heuristics. Not worth it until MCP usage reveals a specific need.
- **Go parser frontend** — big tree-sitter work, not the bottleneck.
- **`knowledge_enricher` LLM-powered semantic pass** — biggest bet from the agent-onboarding analysis. Revisit once real-world MCP usage surfaces questions worth enriching.
- **Web UI / dashboard** — Neo4j Browser at `:7475` is the interactive surface.
- **Real-time file watching** — incremental re-index on demand is enough; no watchers.

---

## Known open questions

1. **Live Claude Code client verification** (A2 above) — still unverified against a running Claude Code UI. Only smoke-tested via raw JSON-RPC pipe.

2. **Unresolved imports percentage** (B6) — 29% is high; investigation before fix.

3. ~~**Python Stage 2 priority vs. arch-check policy expansion vs. incremental re-indexing**~~ — B1 (Python Stage 2) and B2 (MCP prompts) are now shipped. Next priority: B3 (incremental re-indexing) vs. more arch-check policies vs. B4 (MCP write tools).

4. **Init's first-index timeout on huge repos** — `codegraph init --yes` runs the first index synchronously. Twenty's 3-minute index is fine; a 20k+ file repo (e.g. Babel, TypeScript compiler, monorepo-of-monorepos) would time out the user's patience. Should init have a `--skip-index` nudge for giant repos, or detect and prompt? Currently the user can pass `--skip-index` manually.

5. **`.arch-policies.toml` schema versioning** — no version field today. If we evolve the schema, old repos silently misbehave. Consider adding `[meta] schema_version = 1` and erroring on unknown versions.

6. **Twenty's 184,809 import cycles** — surfaced by the e2e run. Are these real architectural problems or an artefact of the cycle detection (e.g. barrel files counting twice)? Needs a quick sample-and-validate. If the heuristic is over-reporting, cap the cycle length or dedupe by node set.

---

## Session workflow conventions (for the next agent)

These have worked well and are worth continuing:

1. **`/plan_local` before non-trivial implementation.** Writes to `~/.claude/plans/` or repo-local `.claude/plans/`. Get user sign-off before coding. The plan is a contract against which the work gets verified.

2. **Atomic commits with detailed bodies.** Every commit is scoped to one conceptual change. See `git log --format=fuller` for the established style.

3. **E2E validation on a real fixture after every feature.** Run `codegraph index` + the new feature against Twenty or the codegraph repo itself. This is how we caught the src-layout Python detection bug in `c6da6c6`, and the loader's function-DECORATED_BY drop earlier.

4. **Dogfood slash commands during development.** `/graph`, `/graph-refresh`, `/blast-radius`, `/arch-check` — use them on codegraph's own code. Every time something's confusing or wrong, there's likely a real bug.

5. **Limits in Cypher are interpolated, not parameterised.** Neo4j 5.x rejects `LIMIT $param`. Validate via `_validate_limit` then interpolate. Established pattern in every MCP tool.

6. **`_FakeDriver` / `_FakeSession` / `_FakeResult` pattern** for testing Neo4j-dependent code without Neo4j. Extend minimally; if a test needs something significantly different, you're probably testing the wrong layer.

7. **Never commit user-local `.claude/` files.** The 7 shipped slash commands are committed (project-shared). User-local scratch commands stay untracked.

8. **`codegraph-neo4j` (dev) is on port 7688/7475.** Any `docker compose up` scaffolded by `codegraph init` exposes on 7687/7474 by default — don't confuse the two graphs.

---

## Plan archive — what's been written

Repo-local plans under `.claude/plans/`:
- `graph-slash-commands.plan.md` — shipped as `af77cd3`.
- `arch-check-ci.plan.md` — shipped as `55789fd` + `b12520a`.
- `glimmering-painting-yao.md` (in `~/.claude/plans/`) — the most recent "one-command onboarding" plan, shipped as `d0abe53`.

- `fix-issue-33-max-depth-bounds.plan.md` — shipped as `6b74617`.
- `issue-31-missing-mcp-tests.plan.md` — shipped as `939dfc3`.
- `query-graph-dedup.plan.md` — shipped as `6d9205b`.
- `fix-container-name-collision.plan.md` — shipped as `ee2ac35`.

Older plans (not in repo): `sunny-giggling-moon.md` (the MCP retriever batch), `framework-detector-port.md`. These live in `~/.claude/plans/` and get overwritten on each `/plan` session unless preserved manually.

---

## Non-goals (keep these out of scope unless user asks)

- ~~**Make `codegraph` work on non-TypeScript codebases.**~~ **Obsolete** — Python Stage 1 shipped. Python Stage 2 (framework detection) is tier B.
- **Web UI or dashboard.** Neo4j Browser + Claude Code slash commands are the interactive surfaces.
- **Real-time file watching.** Incremental re-index on demand is enough (B3); no watchers.
- **Auth / TLS / rate-limiting on MCP.** Stdio-only, trusts the local Claude Code process.
- **Exposing internal state via `query_graph` helpers** — `query_graph(raw_cypher)` is the escape hatch by design.
- **Database migrations between codegraph schema versions.** Users wipe and re-index when upgrading.
- **Windows support.** Untested; not a goal.
- **Indexing `node_modules`** — skipped via `.codegraphignore` defaults.
- **Replacing per-file flags (`is_controller`, `is_component`, ...) with everything on `:Package`.** Both coexist; the flags are within-package resolution.
- **More than 10 MCP tools in a single batch.** Add incrementally so each gets a proper review loop.

---

## How to continue in a fresh agent session

Starter prompt for the next agent:

```
I'm continuing work on codegraph. Read ROADMAP.md for full context.

Working directory: /home/edouard-gouilliard/Obsidian/SecondBrain/Personal/projects/graphrag-code

Before doing anything:
1. `git status && git log --oneline -10` to confirm repo state.
2. Check .venv exists in codegraph/ — if not, rebuild per ROADMAP.
3. `docker ps | grep codegraph-neo4j` — dev Neo4j should be up on 7688.
4. Run tests as a smoke check: `cd codegraph && .venv/bin/python -m pytest tests/ -q`.

Then pick up at the "What's next" section. Unless the user says otherwise,
my priority order is: Tier A (push + PyPI publish + Claude Code
verification) → B3 (incremental re-indexing) → B4 (MCP write tools).

Do not push to origin without asking. Do not publish to PyPI without
asking. Do not merge the open PR #8 without asking.
```

---

## Appendix — quick reference of what's where

### Key source files (all under `codegraph/codegraph/` unless noted)

| File | Purpose | Approximate LOC |
|---|---|---|
| `cli.py` | Typer CLI: `init`, `repl`, `index`, `validate`, `arch-check`, `query`, `wipe` | ~570 |
| `init.py` | `codegraph init` scaffolder (detection + prompts + template render + docker + first index) | ~310 |
| `parser.py` | tree-sitter TS/TSX walker with framework-construct detection | ~1160 |
| `py_parser.py` | tree-sitter Python walker (Stage 1: classes, methods, functions, imports, decorators, CALLS, docstrings, params, return types) | ~560 |
| `resolver.py` | Cross-file reference resolution (TS path aliases + Python module imports + class heritage + method calls + super()) | ~660 |
| `loader.py` | Neo4j batch writer, constraints, indexes, `LoadStats` | ~815 |
| `schema.py` | Node + edge dataclasses shared across parser → loader (+ shared test-pairing constants) | ~390 |
| `config.py` | `codegraph.toml` / `pyproject.toml` config loader | ~190 |
| `arch_check.py` | Architecture-conformance runner + 3 built-in policies + custom policy support | ~290 |
| `arch_config.py` | `.arch-policies.toml` parser → typed `ArchConfig` | ~275 |
| `ignore.py` | `.codegraphignore` parser + `IgnoreFilter` | ~180 |
| `framework.py` | Per-package framework detection (`FrameworkDetector`) | ~510 |
| `mcp.py` | FastMCP stdio server with 13 tools + 29 prompt templates | ~610 |
| `ownership.py` | Git log → author mapping onto graph nodes | ~130 |
| `validate.py` | Post-load sanity-check suite | ~400 |
| `repl.py` | Interactive Cypher REPL | ~320 |
| `utils/neo4j_json.py` | Shared `clean_row` helper | ~30 |
| `utils/repl_skin.py` | REPL formatting helpers | ~500 |
| `templates/**/*` | 11 files scaffolded by `codegraph init` | ~300 (markdown + YAML + TOML) |

### Tests (`codegraph/tests/`)

| File | Count | Target |
|---|---|---|
| `test_ignore.py` | 19 | `ignore.py` + cli helpers |
| `test_framework.py` | 18 | `framework.py` (TS) |
| `test_py_framework.py` | 13 | `framework.py` (Python Stage 2) |
| `test_mcp.py` | 109 | `mcp.py` (13 tools + 29 prompts + describe_schema + query_graph + depth/bool validation + full coverage for calls_from, callers_of, describe_function) |
| `test_py_parser.py` | 28 | `py_parser.py` (Stage 1 parsing) |
| `test_py_parser_calls.py` | 12 | Method-body CALLS emission |
| `test_py_parser_endpoints.py` | 18 | Python Stage 2 endpoint parsing |
| `test_py_resolver.py` | 14 | Python import resolution + CALLS wiring + super() |
| `test_resolver_bugs.py` | 13 | Resolver edge-case regression tests |
| `test_loader_partitioning.py` | 3 | Function DECORATED_BY routing |
| `test_loader_pairing.py` | 6 | TS + Python test-file pairing |
| `test_arch_check.py` | 19 | Policies + orchestrator + custom policy runner |
| `test_arch_config.py` | 20 | `.arch-policies.toml` parser (built-ins + custom + validation errors) |
| `test_init.py` | 19 | Scaffolder helpers (detection, prompts, render, write, container name uniqueness) |
| `test_init_integration.py` | 2 (1 slow) | End-to-end scaffold + optional Docker |
| **Total** | **317** | |

### Key decisions recorded in commit messages

Grep commit bodies for rationale:
- Why `.codegraphignore` not `.agentignore` → `b71bc45`
- Why `:Package` as flat properties rather than `:Package-[:USES]->:Framework` → `9fb4d1d`
- Why NestJS indicator weights outrank React → `e7382f7`
- Why the driver is lazy and not eager → `39be5c2`
- Why `LIMIT` is interpolated not parameterised → `7588522`
- Why Python CALLS reuse the TS `"this"` / `"this.field"` / `"name"` vocabulary → `d48ee26`
- Why function-level DECORATED_BY routing was missing → `d48ee26`
- Why `pyproject.toml` / `setup.py` / `setup.cfg` are Python markers → `c6da6c6`
- Why `cognitx-codegraph` as the PyPI name → `d0abe53`
- Why `queries.md` headings/fenced-blocks drive prompt registration (not hardcoded names) → `357ad03`
- Why Python Stage 2 uses `framework.py` scored heuristics rather than per-file flags → `6493224`
- Why `query_graph` rejects bool limits (Python bool ⊂ int — `isinstance(True, int)` is True) → `6fe0730`
- Why all three traversal tools use `default=1, max=5` for `max_depth` (consistent bounds; bool bypass was the same root cause as #30; `or isinstance(max_depth, bool)` guard matches `_validate_limit` pattern) → `6b74617`
- Why `query_graph` delegates to `_run_read` instead of owning its own try/except (DRY: `_run_read` already handles all three error types; the 10-line inline copy was an exact duplicate; one accepted trade-off is that `clean_row()` now runs before slicing rather than after, which is negligible) → `6d9205b`
- Why container name uses `sha1(resolved_path)[:8]` rather than a random suffix (deterministic — re-running `init` on the same repo always references the same container; SHA-1 hex chars are Docker-safe; `.resolve()` ensures symlinks don't produce diverging hashes) → `ee2ac35`

### Git remotes

```
origin  git@github.com:cognitx-leyton/graphrag-code.git
```

Protected branches: `main`, `release`, `hotfix`. `dev` is the working branch. PRs go into `main` via the `dev → main` flow. PR #8 is currently open.
