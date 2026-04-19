# codegraph — Roadmap & Session Handoff

> **Purpose of this document.** Capture enough context for a fresh agent session (or a human returning after time away) to continue work on codegraph without re-deriving state from scratch. Separate from the user-facing roadmap bullets in `README.md`, which stay short and pitch-oriented.
>
> **Last updated:** 2026-04-19 after commits `3b320b4` → `db3291e` (fix(crlf): normalise CRLF line endings across all file-read paths (issue #155); PR #156 merged; 475 tests passing, v0.1.39).

---

## TL;DR — where we are

- **Branch:** `archon/task-fix-issue-155`. Normalised CRLF line endings across all file-read paths (issue #155) — 7 call sites across `ignore.py`, `ownership.py`, `mcp.py`, `framework.py`, and `init.py` switched from `Path.read_text()` / `Path.write_text()` to `open(..., newline="")`. PR #156 merged to main; version at v0.1.39.
- **Tests:** 475 passing + 1 deselected (Docker-slow integration test), 0 warnings. Run via `.venv/bin/python -m pytest tests/ -q` from `codegraph/`.
- **Graph indexed:** Twenty CRM is currently loaded into the local Neo4j container at `bolt://localhost:7688` (13,473 files, 2,559 classes, 6,088 methods, 5,562 CALLS, 6,708 hook usages, 4,593 RENDERS).
- **MCP server:** 13 read-only tools + **2 write tools** (`wipe_graph`, `reindex_file`) gated by `--allow-write` flag + **29 prompt templates** (all Cypher blocks from `queries.md` auto-registered via `_register_query_prompts()`). `codegraph-mcp` console script registered. Smoke-tested via raw JSON-RPC.
- **Package:** `cognitx-codegraph` v0.1.32 in `pyproject.toml`. Wheel + sdist build cleanly. **Not yet on PyPI** — needs one-time operational setup (Trusted Publisher registration). `release.yml` now waits for propagation and smoke-tests the published version.
- **Resolver:** Workspace import resolution now handles bare package names and subpath imports for monorepos (`twenty-ui/display` → `packages/twenty-ui/src/display/index.ts`). Scoped npm packages (`@scope/pkg/sub`) resolved correctly. `tsconfig.json` `"extends"` chains followed recursively (including TS 5.0+ array form). Estimated ~8,081 previously-unresolved Twenty workspace imports now route correctly.
- **CI:** `.github/workflows/arch-check.yml` — every PR to `main` spins up Neo4j, indexes, runs `codegraph arch-check`, fails on architecture violations. Verified live on PR #8 (42s, exit 0).
- **Onboarding:** `codegraph init` scaffolds everything needed to dogfood codegraph in any repo. Live-tested against 3 fixtures including the real Twenty monorepo (13k files indexed end-to-end).
- **Python Stage 2:** FastAPI / Flask / Django / SQLAlchemy framework detection + `:Endpoint` nodes. `/trace-endpoint` now works against Python repos.
- **Incremental re-indexing:** `codegraph index --since <git-ref>` diffs git, cleans stale subgraphs, and upserts only touched files. Implies `--no-wipe`. REPL supports `index --since HEAD~1`.

---

## Shipped since the last roadmap update (commit `3b320b4`)

```
db3291e fix(crlf): normalise CRLF line endings across all file-read paths
fa90f98 Merge pull request #156 from cognitx-leyton/archon/task-fix-issue-152
dfaba1f chore: bump version to 0.1.39
3b320b4 docs(roadmap): update session handoff
6ea3c20 fix(stats): handle CRLF line endings in stat placeholder replacement
9a86b8a Merge pull request #153 from cognitx-leyton/archon/task-fix-issue-149
d182dce chore: bump version to 0.1.38
a5d0b5f docs(roadmap): update session handoff
5888953 test(stats): extend _format_stat_line tests for interfaces and endpoints
a64088f Merge pull request #150 from cognitx-leyton/archon/task-fix-issue-143
92f0c67 chore: bump version to 0.1.37
f8653a3 docs(roadmap): update session handoff
7815b72 fix(stats): tighten scoped edge counts to AND logic, add --include-cross-scope-edges flag
60745ba Merge pull request #146 from cognitx-leyton/archon/task-fix-issue-144
210a1f5 chore: bump version to 0.1.36
df49d03 docs(roadmap): update session handoff
37d71a2 test(stats): add auto-scope edge-case for stats command
76a4574 Merge pull request #145 from cognitx-leyton/archon/task-fix-issue-140
31ec89f chore: bump version to 0.1.35
1e53a80 docs(roadmap): update session handoff
8da989a test(stats): add edge-case coverage for stats command
32d66d4 Merge pull request #141 from cognitx-leyton/archon/task-fix-issue-137
7958de3 chore: bump version to 0.1.34
3b2f52a docs(roadmap): update session handoff
de21f68 feat(cli): add codegraph stats subcommand with scope filtering and --update flag
de41ee2 Merge pull request #138 from cognitx-leyton/archon/task-fix-issue-123
737f89e chore: bump version to 0.1.33
e185737 docs(roadmap): update session handoff
623dc8c docs(stats): update codebase stats to reflect current graph state
5299144 Merge pull request #135 from cognitx-leyton/archon/task-fix-issue-133
edd3ae2 chore: bump version to 0.1.32
a797178 docs(roadmap): update session handoff
59c916a docs(test): fix install-test retry documentation and add scope filter
2efe9b7 Merge pull request #134 from cognitx-leyton/archon/task-fix-issue-131
ab2a0a1 chore: bump version to 0.1.31
d4a50c3 docs(roadmap): update session handoff
61de3b1 docs(github): add pull request template
a4fa7d8 Merge pull request #132 from cognitx-leyton/archon/task-fix-issue-124
b876054 chore: bump version to 0.1.30
2391bfc docs(roadmap): update session handoff
581d9db Merge pull request #130 from cognitx-leyton/archon/task-fix-issue-126
82ec7d3 chore: bump version to 0.1.29
d5fdc80 docs(roadmap): update session handoff
5b6af3c fix(test): use pip show instead of importlib to verify installed version
5f18867 Merge pull request #129 from cognitx-leyton/archon/task-fix-issue-127
42fa4f3 chore: bump version to 0.1.28
ffd2009 docs(roadmap): update session handoff
af36698 fix(test): add exit 1 to install-retry loop on final failure
639b279 Merge pull request #128 from cognitx-leyton/archon/task-fix-issue-124
000fd94 chore: bump version to 0.1.27
55f192c docs(roadmap): update session handoff
1d538fa fix(test): resolve install-test flakiness and version hardcode
4768f69 Merge pull request #125 from cognitx-leyton/archon/task-fix-issue-121
9b79c9a chore: bump version to 0.1.26
3961abd docs(roadmap): update session handoff
039497d fix(ci): align arch-check workflow paths with pyproject.toml auto-scope
3d69ec3 Merge pull request #122 from cognitx-leyton/archon/task-fix-issue-119
eb4a4c8 chore: bump version to 0.1.25
2f525f5 docs(roadmap): update session handoff
e40fcec fix(arch-check): set correct package paths in pyproject.toml auto-scope
8df3c62 Merge pull request #120 from cognitx-leyton/archon/task-fix-issue-117
8898ae2 chore: bump version to 0.1.24
40f6f58 docs(roadmap): update session handoff
d04af53 fix(arch-config): use fully-qualified policy paths in validation error messages
5765b4e Merge pull request #118 from cognitx-leyton/archon/task-fix-issue-114
aaea980 chore: bump version to 0.1.23
32839a8 docs(roadmap): update session handoff
2103d57 feat(arch-check): make sample_limit configurable via [settings] in .arch-policies.toml
c23923b Merge pull request #115 from cognitx-leyton/archon/task-fix-issue-111
d263cdf chore: bump version to 0.1.22
e246ced docs(roadmap): update session handoff
082c943 test(arch-check): assert and test the incomplete→not-passed invariant
14bd396 Merge pull request #112 from cognitx-leyton/archon/task-fix-issue-109
e31c2a2 chore: bump version to 0.1.21
e0951c6 docs(roadmap): update session handoff
28a5eda fix(arch-check): warn when suppression coverage is partial due to sample truncation
30d13d9 Merge pull request #110 from cognitx-leyton/archon/task-fix-issue-105
5013666 chore: bump version to 0.1.20
d7d4172 docs(roadmap): update session handoff
ae21e20 feat(arch-check): auto-scope from config packages, add --no-scope flag
325f4ff Merge pull request #106 from cognitx-leyton/archon/task-fix-issue-105
1d9154f chore: bump version to 0.1.19
1ca7de2 docs(roadmap): update session handoff
c6460d2 fix(resolver): handle scoped npm packages and tsconfig extends array
92b58fe Merge pull request #103 from cognitx-leyton/archon/task-feat-issue-14-mcp-write-tools
8cf25f7 chore: bump version to 0.1.18
e94a436 docs(roadmap): update session handoff
daae936 feat(mcp): add write tools for reindexing and edge loading
aa48cd0 Merge pull request #99 from cognitx-leyton/archon/task-feat-issue-13-incremental-reindex
149b955 chore:          bump version to 0.1.17
6d9c028 docs(roadmap):  update session handoff
06e9873 feat(incremental): add --since flag for incremental re-indexing
7327e46 Merge pull request #95 from cognitx-leyton/archon/task-feat-issue-23-arch-check-suppression
87b6997 chore:          bump version to 0.1.16
7290c13 docs(roadmap):  update session handoff
9d05a44 feat(arch-check): add inline suppression for false-positive violations
508826e Merge pull request #92 from cognitx-leyton/archon/task-feat-issue-22-arch-check-scope
7c95ac2 chore:          bump version to 0.1.15
aff9f10 docs(roadmap):  update session handoff
9ebc0e4 feat(arch-check): add --scope flag to filter policies by path prefix
4956838 Merge pull request #89 from cognitx-leyton/archon/task-feat-issue-17-orphan-detection
1b27921 fix(arch-check): exclude pytest entry points from orphan_detection function query
d171787 chore:          bump version to 0.1.14
78fb177 docs(roadmap):  update session handoff
2dd72b7 feat(arch-check): add orphan_detection policy to surface unreachable nodes
9c4130d Merge pull request #85 from cognitx-leyton/archon/task-feat-issue-16-coupling-ceiling
ad9ccac chore:          bump version to 0.1.13
62ded5a docs(roadmap):  update session handoff
4213450 feat(arch-check): add coupling_ceiling policy to cap inbound imports (#16)
6c23313 Merge pull request #82 from cognitx-leyton/archon/task-chore-issue-24-pypi-propagation-delay
ec54142 chore:          bump version to 0.1.12
ce1d179 docs(roadmap):  update session handoff
dd17072 chore(ci):      add PyPI propagation wait and smoke test to release workflow (#24)
995e47e Merge pull request #79 from cognitx-leyton/archon/task-chore-issue-19-arch-policies-versioning
732ce1d chore:          bump version to 0.1.11
bc70d01 chore(arch-config): add schema_version field to arch-policies config (#19)
5d88fac chore:          bump version to 0.1.10
3f8551c Merge pull request #76 from cognitx-leyton/archon/task-fix-issue-18-container-name-collision
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

Thirty-three sessions' worth of work grouped by theme:

### CRLF line endings across all file-read paths (issue #155)

- `db3291e fix(crlf)` — Systematic audit of every `Path.read_text()` / `Path.write_text()` call that processes user files (ignore rules, ownership, MCP tools, framework detection, init scaffolding). **7 call sites** across 5 files switched to `open(..., encoding="utf-8", newline="")` so Python's universal-newline translation is bypassed and raw line endings are preserved through the regex/string logic. **4 new tests** added: `test_ignore_crlf_line_endings` (`.codegraphignore` with CRLF parses file/route/component patterns), `test_parse_codeowners_crlf` (CODEOWNERS with CRLF parses rules + owners), `test_append_claude_md_crlf` (CLAUDE.md with CRLF appended without `\r\r` corruption), `test_python_deps_crlf_requirements` (requirements.txt with CRLF parses dep names without trailing `\r`). Code-review: 1 issue found and fixed (`ownership.py` was missing `encoding="utf-8"`). Arch-check: 5/5 policies pass. Test count: 471 → 475.

- `fa90f98 merge` + `dfaba1f chore` — PR #156 (branch `archon/task-fix-issue-155`, CRLF normalisation, issue #155) merged to `main`; version bumped to v0.1.39.

### CRLF line endings in stat placeholder replacement (issue #152)

- `6ea3c20 fix(stats)` — `_update_stat_placeholders` in `cli.py` failed silently on files with Windows-style CRLF (`\r\n`) line endings because `read_text()` performs universal newline translation (collapses `\r\n` → `\n`) and `write_text()` similarly normalises, yet the regex anchors in `_STAT_PLACEHOLDER_RE` expected `\n`. Two changes: **(1)** `_STAT_PLACEHOLDER_RE` anchor changed from `\n` to `\r?\n` so the pattern matches both LF and CRLF files. **(2)** `_update_stat_placeholders` switched from `Path.read_text()` / `Path.write_text()` to `open(path, encoding="utf-8", newline="")` for both read and write, bypassing Python's universal-newline translation so raw byte sequences pass through unmodified to the regex. **(3)** New test `test_update_replaces_content_crlf` in `tests/test_stats.py` (line 284–301) writes a markdown file with CRLF endings via `write_bytes` and asserts the placeholder is replaced correctly. Code-review: 0 issues (after fixing a vacuous-test issue found in round 1 where `read_text` was still used). Arch-check: 5/5 policies pass. Test count: 470 → 471.

- `9a86b8a merge` + `d182dce chore` — PR #153 (branch `archon/task-fix-issue-149`, extended `_format_stat_line` tests for interfaces/endpoints, issue #149) merged to `main`; version bumped to v0.1.38.

### `_format_stat_line` tests — interfaces and endpoints (issue #149)

- `5888953 test(stats)` — Two new test additions to `tests/test_stats.py`. **(1) Parametrized test `test_format_stat_line_interfaces_endpoints`** (2 cases): verifies `"4 interfaces"` / `"7 endpoints"` appear in the stat line when non-zero, and are absent when zero. Mirrors the existing `test_format_stat_line_hooks_decorators` pattern. **(2) Extended `test_format_stat_line_all_nonzero`** from 4 keys to all 8 keys, validating the full output string including correct ordering: `files → classes → module functions → methods → interfaces → endpoints → hooks → decorators`. Code-review: 0 issues. Arch-check: 5/5 policies pass. Test count: 468 → 470.

- `a64088f merge` + `92f0c67 chore` — PR #150 (branch `archon/task-fix-issue-143`, scoped edge AND logic + `--include-cross-scope-edges` flag, issue #143) merged to `main`; version bumped to v0.1.37.

### Stats scoped edge AND logic + `--include-cross-scope-edges` flag (issue #143)

- `7815b72 fix(stats)` — `_query_graph_stats()` in `cli.py` now uses **AND** by default for scoped edge Cypher (both source and target file paths must match a scope prefix). Previously, OR logic was used, which could count cross-scope edges that only partially match. A new `cross_scope_edges: bool = False` parameter restores OR behaviour when set to `True`. The `stats()` CLI command gains a `--include-cross-scope-edges` flag that threads through to `_query_graph_stats`. The `--scope` help text updated to document the AND-default semantics. **2 new tests** in `tests/test_stats.py`: `test_query_graph_stats_with_scope_cross_edges` (verifies `cross_scope_edges=True` produces OR-based Cypher) and `test_stats_include_cross_scope_edges_flag` (CLI integration test). Existing `test_query_graph_stats_with_scope` updated to assert the edge Cypher contains `AND` and not `OR`. Code-review: 0 issues. Arch-check: 5/5 policies pass. Test count: 466 → 468.

- `60745ba merge` + `210a1f5 chore` — PR #146 (branch `archon/task-fix-issue-144`, auto-scope edge-case test, issue #144) merged to `main`; version bumped to v0.1.36.

### Stats auto-scope edge-case test (issue #144)

- `37d71a2 test(stats)` — 1 new test `test_stats_auto_scope` added to `tests/test_stats.py` (line 333–367). Monkeypatches `codegraph.cli.load_config` to return a `CodegraphConfig(packages=["codegraph", "tests"], source="codegraph.toml")` and `GraphDatabase.driver` with a `_FakeDriver`. Invokes `stats --json` (no `--scope`, no `--no-scope`) to trigger the auto-scope branch at `cli.py:861-864`. Asserts the `scopes` parameter forwarded to Neo4j matches the config packages and the Cypher uses `STARTS WITH` for scope filtering. Code-review: 0 issues. Arch-check: 5/5 policies pass. Test count: 465 → 466.

- `76a4574 merge` + `31ec89f chore` — PR #145 (branch `archon/task-fix-issue-140`, stats edge-case tests, issue #140) merged to `main`; version bumped to v0.1.35.

### Stats edge-case test coverage (issue #140)

- `8da989a test(stats)` — 6 new parametrised tests added to `tests/test_stats.py`, covering three edge-case scenarios missed in the initial stats test suite: **(1) `test_query_graph_stats_empty_scope_is_global`** — `scope=None` and `scope=[]` both take the `else` branch (falsy check), producing global Cypher with no `STARTS WITH` clause and no `scopes` param. **(2) `test_query_graph_stats_scope_trailing_slash`** — scope prefix strings (with or without trailing slash) are forwarded verbatim to the `$scopes` Cypher param and the query includes `STARTS WITH`. **(3) `test_format_stat_line_hooks_decorators`** — hook/decorator labels appear in the stat line when non-zero and are omitted when zero, confirming the skip-zero behaviour is intentional. Code-review: 0 HIGH/MEDIUM issues. Arch-check: 5/5 policies pass. Test count: 459 → 465.

- `32d66d4 merge` + `7958de3 chore` — PR #141 (branch `archon/task-fix-issue-137`, `codegraph stats` subcommand, issue #137) merged to `main`; version bumped to v0.1.34.

### `codegraph stats` subcommand — live graph counts with scope + markdown update (issue #137)

- `de21f68 feat(cli)` — `cli.py` gains three helper functions and a new `stats` Typer subcommand. **`_query_graph_stats(driver, scope)`** runs two Cypher queries (one for node counts by label, one for edge counts by type) using `coalesce(n.file, n.path)` to handle both `File` (`.path`) and all other node kinds (`.file`); scope prefix filtering is applied when `scope` is set. **`_format_stat_line(stats)`** produces a human-readable prose string like `"~21 files, 56 classes, 134 module functions, ~178 methods"` (omitting zero-count labels, approximating counts with `~`). **`_update_stat_placeholders(files, stat_line, quiet)`** uses a regex lambda replacement (safe against metacharacters) to rewrite the content between `<!-- codegraph:stats-begin -->` / `<!-- codegraph:stats-end -->` delimiters in each target file, skipping files with no delimiters and reporting unchanged files. The **`stats()` command** exposes `--json`, `--scope/-s`, `--no-scope`, `--update`, `--file/-f`, `--repo` options; auto-scopes from `codegraph.toml` / `pyproject.toml` (same logic as `arch-check`). Placeholder delimiters inserted in `CLAUDE.md`, `.claude/commands/graph.md`, and `codegraph/codegraph/templates/claude/commands/graph.md`, replacing the old HTML-comment stat lines. **11 new tests** in `tests/test_stats.py`: `_query_graph_stats` scoped + unscoped (verifies Cypher params), `_format_stat_line` all-nonzero / zero-omission / empty graph, `_update_stat_placeholders` replace / no-delimiters-skip / no-change-skip / missing-file-skip, CLI `--json` output, CLI `--update` end-to-end with `files_updated` key in JSON. Code-review fixes applied: explicit `_LABEL_MAP` dict replaced a dead capitalize() loop; JSON output deferred so `--json --update` reports `files_updated`; `import os` removed; lambda replacement for regex safety; `coalesce(n.file, n.path)` fixed 0-file-count bug. Arch-check: 5/5 policies pass, 0 violations. Test count: 448 → 459.

- `de41ee2 merge` + `737f89e chore` — PR #138 (branch `archon/task-fix-issue-123`, codebase stats update, issue #123) merged to `main`; version bumped to v0.1.33.

### Codebase stats update — CLAUDE.md and graph.md (issue #123, PR #138 merged as #138)

- `623dc8c docs(stats)` — Three `.md` files updated to reflect actual graph state (6 insertions, 3 deletions; zero source code). `CLAUDE.md:61`, `.claude/commands/graph.md:20`, and `codegraph/codegraph/templates/claude/commands/graph.md:20` all had stale stats copied from early development. Updated from `~18 files, 41 classes, 82 module functions, ~150 methods` → `~20 files, 56 classes, 134 module functions, ~180 methods`; `handful of files` → `~17 files` for the test suite; an HTML comment hint added to remind future editors to run `/graph-refresh` and update these counts after significant structural changes. Template and live `graph.md` stat lines kept byte-identical. 448 tests unchanged; byte-compile clean.

- `5299144 merge` + `edd3ae2 chore` — PR #135 (branch `archon/task-fix-issue-133`, install-test exponential backoff + scope-filter skip guard, issue #133) merged to `main`; version bumped to v0.1.32.

### Install-test exponential backoff + scope skip guard (issue #133, PR #134 merged as #135)

- `59c916a docs(test)` — `.claude/commands/test.md` Stage 2 (PyPI install test) received two independent improvements. **(1) Exponential backoff:** `BACKOFF=30` (fixed) replaced with `BACKOFF=15` (initial) + `BACKOFF=$((BACKOFF * 2))` after each `sleep`, giving a 15s → 30s retry sequence (two sleeps, total 45s max wait vs. 90s before). Pass criteria text updated to "exponential backoff (15s, 30s)". **(2) Scope-filter skip guard:** a `SCOPE="${ARGUMENTS:-all}"` check at the top of the bash block detects when the user runs `/test unit`, `/test self-index`, or `/test leytongo` — any scope that is not `install` or `all` — and emits `SKIP: install test (scope is '...', not 'install' or 'all')` before exiting 0. A tip was added after the pass criteria: "Run `/test unit` to skip the install test during local development." Both changes confined to Stage 2 only; all regression guards preserved (`exit 1`, `--no-cache-dir`, `pip show` version check). 448 tests unchanged.

- `2efe9b7 merge` — PR #134 (branch `archon/task-fix-issue-131`, PR template) merged to `main`.

- `ab2a0a1 chore` — `pyproject.toml` version bumped to v0.1.31.

### PR template + version bump to 0.1.30 (issue #131, PR #132)

- `61de3b1 docs(github)` — `.github/pull_request_template.md` created (13 lines). Contains an HTML comment explaining the template's purpose, a pre-filled `Closes #` line on its own (so GitHub auto-closes linked issues on merge), a `## Summary` free-text section, and a 3-item checklist: conventional commit prefix, `pytest tests/ -q` green, `codegraph arch-check` exit 0. Checklist references align exactly with `CLAUDE.md` conventions. No code changes — docs-only. 448 tests unchanged.

- `a4fa7d8 merge` — PR #132 (branch `archon/task-fix-issue-124`) merged to `main`. Housekeeping: closed issue #124 programmatically after its fix had already shipped in PR #128 without a `Closes` keyword.

- `b876054 chore` — `pyproject.toml` version bumped to v0.1.30.

### Closed issue #124 + version bump to 0.1.29 (PR #130)

- `581d9db merge` — PR #130 (branch `archon/task-fix-issue-126`) merged to `main`. This appears to be the final merge associated with the issue #126 fix series.

- `82ec7d3 chore` — `pyproject.toml` version bumped to v0.1.29.

- **Issue #124 closure** — GitHub issue #124 ("install-test flakiness and `__version__` hardcode") was left open after its fix shipped in PR #128 (`1d538fa`), which lacked a `Closes #124` keyword. Closed manually this session with a comment referencing the merged PR. No code changes — purely a housekeeping step.

### Install-test editable-install leakage — `pip show` instead of `importlib.metadata` (issue #126)

- `5b6af3c fix(test)` — `.claude/commands/test.md` Stage 2 version assertion was using `importlib.metadata.version("cognitx-codegraph")` inside the fresh temp venv. Because Python's import machinery can see the repo's editable install via `.egg-info` or `.pth` entries on `sys.path`, this returned the editable version rather than the PyPI-installed version, producing a false-positive assertion even when the target venv had no real install. Replaced with `"$TMPVENV/bin/pip" show cognitx-codegraph | awk '/^Version:/{print $2}'` (plus a `NONE` fallback when `pip show` returns nothing). `pip show` is scoped to the venv's own `site-packages` and is immune to both leakage vectors. `importlib` removed from the test command entirely. 448 tests unchanged.

- `5f18867 merge` + `42fa4f3 chore` — PR #129 (issue #126) merged to `main`; version bumped to v0.1.28.

### Install-retry loop `exit 1` on final failure (issue #127)

- `af36698 fix(test)` — `.claude/commands/test.md` Stage 2 install-retry `else` block was missing a non-zero exit code after emitting the "Install FAILED" echo. Added `exit 1` so CI/pipeline contexts that read exit codes detect the failure rather than silently proceeding. A clarifying comment documents the dual-signal design: `exit 1` for CI, the echo for Claude Code slash-command context where the exit code surfaces differently. No production code changes. 448 tests unchanged.

- `639b279 merge` + `000fd94 chore` — PR #128 (issue #127) merged to `main`; version bumped to v0.1.27.

### Install-test flakiness + `__version__` hardcode (issue #124)

- `1d538fa fix(test)` — Two related problems fixed in one commit. **(1) `__init__.py` hardcoded `__version__ = "0.1.0"`** which never changed with version bumps; replaced with `importlib.metadata.version("cognitx-codegraph")` (with a graceful fallback to `"0.0.0"` for editable installs before the package is installed). **(2) `.claude/commands/test.md` Stage 2 bash block** was a single `pip install` + `python -c` assertion that would fail transiently on slow networks. Replaced with a retry loop (3 attempts, 10s backoff) + `TMPDIR`-aware venv + version assertion (`codegraph.__version__ == <pyproject.toml version>`). Code-review fixes applied: `TMPDIR` env var shadowing avoided (renamed to `_tmpdir`); `2>/dev/null` removed from `pip install` so diagnostic errors surface. 448 tests unchanged.

- `4768f69 merge` + `9b79c9a chore` — PR #125 (CI arch-check workflow paths, issue #121) merged to `main`; version bumped to v0.1.26.

### CI arch-check workflow — align index paths and drop explicit --scope flags (issue #121)

- `039497d fix(ci)` — `.github/workflows/arch-check.yml` had a mismatch between the paths used for indexing (repo-root-relative `codegraph/codegraph` and `codegraph/tests`) and the paths recorded in the graph (relative to `codegraph/` where the CLI runs: `codegraph` and `tests`). This caused `codegraph arch-check` in CI to receive `--scope codegraph/codegraph --scope codegraph/tests` which never matched any graph nodes, so the scope filter was silently a no-op. Fixed by: **(1)** index step now runs `cd codegraph && codegraph index . -p codegraph -p tests --skip-ownership` (same `-p` values as `pyproject.toml` auto-scope); **(2)** arch-check step drops the explicit `--scope` flags and becomes `cd codegraph && codegraph arch-check --json | tee arch-report.json` — auto-scope now activates from `[tool.codegraph]` in `pyproject.toml`; **(3)** artifact upload path corrected from `arch-report.json` (repo root) to `codegraph/arch-report.json` (where `tee` writes it); **(4)** `CLAUDE.md` "Reproducing a failing check locally" command updated from `-p codegraph/codegraph -p codegraph/tests` to `-p codegraph -p tests`. No code changes — CI YAML and docs only. 448 tests unchanged.

- `3d69ec3 merge` + `eb4a4c8 chore` — PR #122 (pyproject.toml auto-scope config, issue #119) merged to `main`; version bumped to v0.1.25.

### pyproject.toml auto-scope config — activating issue #105 fix for local dev (issue #119)

- `e40fcec fix(arch-check)` — `codegraph/pyproject.toml` gains a `[tool.codegraph]` section with `packages = ["codegraph", "tests"]`. This activates the auto-scope feature shipped in `ae21e20` (issue #105): without a config entry, `codegraph arch-check` run from `codegraph/` had no scope and reported violations from all co-indexed codebases (e.g., leytongo). With this config it auto-scopes to codegraph's own packages and exits 0 (5/5 policies pass, 0 violations). Paths are relative to the `codegraph/` directory where the CLI is run (`codegraph` and `tests`, not `codegraph/codegraph` and `codegraph/tests` which are repo-root-relative). `--no-scope` still overrides and exposes all graph violations. No new tests — the auto-scope feature was already fully tested; this was a missing config entry, not a code bug.

- `8df3c62 merge` + `8898ae2 chore` — PR #120 (fully-qualified paths in typed-getter validation errors, issue #117) merged to `main`; version bumped to v0.1.24.

### Fully-qualified paths in typed-getter validation errors (issue #117)

- `d04af53 fix(arch-config)` — `arch_config.py` typed-getter helpers `_bool`, `_int`, and `_str` previously hardcoded `f"policies.{section}.{key}"` in error messages regardless of the actual config section being validated. Fixed by renaming the `section` parameter to `section_path` and changing the error format to `f"{section_path}.{key}"` — the caller now passes the full dotted path (e.g. `"policies.import_cycles"`, `"settings"`). All 12 call sites updated. The `settings.sample_limit` inline validation from `2103d57` (which was inlined specifically to avoid the wrong `policies.` prefix) is now safely replaced with `_int(settings, "sample_limit", 10, config_path, "settings")`, removing 5 lines of duplicated logic. **1 new test** in `test_arch_config.py`: `test_sample_limit_bool_rejected` — verifies the error message says `"settings.sample_limit"` not `"policies.settings.sample_limit"`. Test count: 447 → 448.

- `5765b4e merge` + `aaea980 chore` — PR #118 (configurable `sample_limit`, issue #114) merged to `main`; version bumped to v0.1.23.

### Configurable sample_limit via `[settings]` in `.arch-policies.toml` (issue #114)

- `2103d57 feat(arch-check)` — `arch_config.py` gains a `sample_limit: int = 10` field on `ArchConfig` and parses it from a new `[settings]` TOML section in `load_arch_config()` (between `[meta]` and `[policies]`). Validation rejects non-integer values, booleans, and values < 1 with a descriptive error; error messages use the `settings.sample_limit` path (not the `policies.` prefix from the shared `_int` helper, which required inlining the validation). `arch_check.py` removes the `SAMPLE_LIMIT = 10` module-level constant; `run_arch_check()`, `_run_all()`, all six `_check_*()` functions, and `_apply_suppressions()` now accept and thread `sample_limit` as a parameter. The incomplete-coverage warning message updated from "Increase SAMPLE_LIMIT" to "Increase `settings.sample_limit` in `.arch-policies.toml`". **5 new tests** in `test_arch_config.py`: `test_default_sample_limit`, `test_custom_sample_limit`, `test_sample_limit_below_1_rejected`, `test_settings_must_be_table`, `test_sample_limit_wrong_type_rejected`. **2 new tests** in `test_arch_check.py`: `test_sample_limit_threaded_to_policy_queries` (verifies `limit=25` reaches the Neo4j query), `test_render_incomplete_warning_references_config` (verifies warning text references the TOML config path). One existing test fixed: `spy_run_all` was given the new `sample_limit` parameter. Code-review fix: inlined the `sample_limit` validation rather than using `_int()` which hardcodes the `policies.` prefix. `test_missing_file_returns_defaults` now also asserts `cfg.sample_limit == 10`. Test count: 440 → 447.

- `c23923b merge` + `d263cdf chore` — PR #115 (incomplete→not-passed invariant, issue #111) merged to `main`; version bumped to v0.1.22.

### Incomplete→not-passed invariant (issue #111)

- `082c943 test(arch-check)` — `arch_check.py` gains an invariant comment + `assert not (incomplete and new_violation_count == 0)` inside `_apply_suppressions()`, explaining why suppressed rows drawn from the truncated sample guarantee `passed=False` when `incomplete=True` (at least one row was not suppressed at the full-count level). `tests/test_arch_check.py` gains `test_invariant_incomplete_implies_not_passed`: 15 violations, sample_size=10, all 10 suppressed → asserts `incomplete=True`, `passed=False`, `violation_count=5`. This covers the previously untested invariant boundary: incomplete=True cannot coexist with passed=True. Test count: 439 → 440.

- `14bd396 merge` + `e31c2a2 chore` — PR #112 (incomplete suppression coverage warning, issue #109) merged to `main`; version bumped to v0.1.21.

### Incomplete suppression coverage warning (issue #109)

- `28a5eda fix(arch-check)` — `arch_check.py` gains an `incomplete_suppression_coverage: bool = False` field on `PolicyResult`. `_apply_suppressions()` detects when `violation_count > len(sample)` (i.e. the sample was truncated) and at least one suppression matched, then sets the flag on the resulting `PolicyResult`. `_render()` emits a yellow **WARN** banner listing the original violation count and the sample size when the flag is set, so the user knows that unseen violations may not be suppressed. **6 new tests** in `test_arch_check.py`: `test_apply_suppressions_incomplete_coverage_when_truncated` (flag True when truncated + match), `test_apply_suppressions_no_incomplete_flag_when_count_equals_sample` (flag False when no truncation), `test_apply_suppressions_no_incomplete_flag_when_no_suppression_matches` (flag False when truncated but no match), `test_incomplete_suppression_coverage_in_json` (field appears in JSON output), `test_render_incomplete_coverage_warning` (warning text appears in CLI output), `test_render_no_warning_when_coverage_complete` (warning absent when flag False). Test count: 433 → 439.

- `30d13d9 merge` + `5013666 chore` — PR #110 (auto-scope, issue #105) merged to `main`; version bumped to v0.1.20.

### Arch-check auto-scope from config packages + `--no-scope` flag (issue #105)

- `ae21e20 feat(arch-check)` — `cli.py` `arch_check` command gains two new behaviours. **(1) Auto-scope from config:** when `--scope` is omitted and `--no-scope` is not set, the command calls `load_config()` to read `codegraph.toml` / `pyproject.toml`; if `packages` are configured, those paths become the effective scope (forwarded to `run_arch_check()` as the `scope` list). A Rich console message reports the auto-detected scope (suppressed in `--json` mode). **(2) `--no-scope` flag:** explicit escape hatch to disable auto-scope and pass `None` scope, restoring the old behaviour of checking the full graph with no path filtering. Precedence: `--scope` explicit > auto-scope from config > `--no-scope` > no filtering (backward compat). **4 new tests** in `test_arch_check.py`: `test_arch_check_cli_auto_scope_from_config` (config packages become scope), `test_arch_check_cli_explicit_scope_overrides_config` (`--scope` wins over config), `test_arch_check_cli_no_scope_flag_disables_auto` (`--no-scope` passes `None`), `test_arch_check_cli_no_config_no_scope_passes_none` (no config = no filtering, backward compat). Test count: 429 → 433.

- `325f4ff merge` + `1d9154f chore` — PR #106 (auto-scope, issue #105) merged to `main`; version bumped to v0.1.19.

### Unresolved imports — workspace registry + tsconfig extends chains (issue #15)

- `c6460d2 fix(resolver)` — `resolver.py` gains four key additions: **(1) `PackageConfig.pkg_json_name`** — new optional field populated by reading `"name"` from `package.json` alongside the existing `tsconfig.json` and path-alias loading. **(2) `Resolver._workspace_pkgs`** — registry dict built in `set_path_index()` that maps every package's `pkg_json_name` to its `PackageConfig`; enables O(1) lookup during resolution. **(3) `Resolver._try_workspace(raw)`** — new method that resolves bare workspace import specifiers (`twenty-ui/display`, `@twenty/shared/utils`) by splitting the specifier into `pkg_name` + `subpath`, looking up `_workspace_pkgs`, and probing `src/<subpath>/index.ts` first then the package root (with JS→TS remap). Scoped packages (`@scope/name`) are handled by keeping both segments before the third `/` as the package name. **(4) `Resolver.resolve()` wired** — `_try_workspace()` is called as the final fallback after alias resolution, before giving up and emitting `IMPORTS_EXTERNAL`. **(5) `_read_ts_paths()` extends chains** — now follows `"extends"` recursively with 10-level cycle-cap; parent paths are inherited; child overrides take precedence; TS 5.0+ `"extends": [...]` array form normalised to list before iteration. `cli.py` updated to print `name=<pkg_json_name>` in the index output for packages with a `package.json` name. **15 new tests** in `test_resolver_bugs.py`: `TestWorkspaceResolution` (7 tests: subpath, bare import, nested subpath, no-src fallback, unknown package, alias coexistence, JS remap) + `TestTsconfigExtends` (5 tests: parent inherit, child override, 3-level chain, missing parent, circular) + 3 additional tests for scoped packages and extends-as-array. Test count: 414 → 429.

- `92b58fe merge` + `8cf25f7 chore` — PR #103 (MCP write tools, issue #14) merged to `main`; version bumped to v0.1.18.

### MCP write tools — `wipe_graph` + `reindex_file` behind `--allow-write` (issue #14)

- `daae936 feat(mcp)` — `mcp.py` gains two write tools gated by a module-level `_allow_write: bool` flag (set via `--allow-write` CLI argument parsed with `argparse` after FastMCP startup): `wipe_graph(confirm=False)` (destructive wipe, requires `confirm=True` in addition to `--allow-write`; uses a `WRITE_ACCESS` Neo4j session) and `reindex_file(path, package=None)` (single-file re-index that validates file extension, auto-resolves package from graph if not provided, checks file exists on disk, detects test files by naming convention, parses with `PyParser` or `TsParser`, calls `delete_file_subgraph()` to cascade-clean the old subgraph, then loads new File/Class/Function/Method/Interface/Endpoint/Column/GraphQLOperation/Atom nodes + intra-file edges + DECORATED_BY edges via whitelist-validated edge kinds to prevent Cypher injection). A `_WRITE_GATE_MSG` constant provides a consistent error for both tools when `--allow-write` is absent. Module docstring updated with `--allow-write` docs and `mcpServers` config example. `main()` updated to parse `--allow-write` via `argparse`. **18 new tests** in `test_mcp.py` covering: write-session mode, gate blocking for both tools, CLI flag parsing, `wipe_graph` requires-confirm + happy-path + error surfaces, `reindex_file` bad-extension + blocked + no-package + package-lookup-from-graph + happy-path + file-not-on-disk + error surfaces + DECORATED_BY edge loading + Neo4j error propagation on package lookup. Two tests in `test_loader_partitioning.py` and `test_py_parser.py` updated for decorator count (13 → 15). Test count: 396 → 414.

- `aa48cd0 merge` + `149b955 chore` — PR #99 (incremental re-indexing, issue #13) merged to `main`; version bumped to v0.1.17.

### Incremental re-indexing — `--since` flag for fast incremental updates (issue #13)

- `06e9873 feat(incremental)` — `loader.py` gains `delete_file_subgraph(tx, file_path)`: a cascading 10-step Cypher cleanup that removes a File node and all its children (Classes → Methods, Functions, Interfaces, Atoms) plus orphaned Endpoint / GraphQLOperation / Column nodes connected via `EXPOSES` / `RESOLVES` / `HAS_COLUMN` before the class deletion. `_file_from_id(node_id)` extracts file paths from all node ID formats (`file:`, `class:`, `func:`, `method:`, `endpoint:`, `gqlop:`, `atom:`). `load()` gains a `touched_files: set[str] | None` parameter that filters nodes and edges to only those involving touched files (packages are always written). `cli.py` gains `_git_changed_files(repo_root, since)` which shells out to `git diff --name-status` and categorises files as modified/added (re-index) vs deleted (cleanup-only), with rename handling (old name → deleted, new name → modified). `--since` option on `codegraph index`: implies `--no-wipe`, skips ownership, calls `delete_file_subgraph()` for each deleted/modified file, then calls `load(touched_files=...)` for only the re-parsed files. `repl.py` passes `--since` through `_cmd_index()` so `index --since HEAD~1` works in the interactive REPL. `tests/test_incremental.py` (new, 21 tests): `delete_file_subgraph` cascades correctly (10-step Cypher), `_file_from_id` handles all 7 prefix formats, `load(touched_files=...)` filters nodes + edges, `_git_changed_files` parses `M`/`A`/`D`/`R` status lines, end-to-end `_run_index` with `--since` wires cleanup + selective load. Test count: 375 → 396.

### Version bump + inline suppression PR merged to main

- `87b6997 chore` + `7327e46 merge` — bumped `pyproject.toml` to v0.1.16 and merged PR #95 (inline suppression, issue #23) to `main`.

### Inline suppression — false-positive suppression for arch-check violations (issue #23)

- `9d05a44 feat(arch-check)` — `arch_config.py` gains a `Suppression` dataclass (`policy: str`, `key: str`, `reason: str`) and a `_parse_suppressions()` function that parses `[[suppress]]` entries from `.arch-policies.toml`; `ArchConfig.suppressions` holds the list. `arch_check.py` extends `PolicyResult` with `suppressed_count: int` and `suppressed_sample: list[str]`; extends `ArchReport` with `stale_suppressions: list[str]` (suppressions that matched no violation). Three new functions: `_violation_key(policy, row)` generates the canonical per-policy key string (cycle edge `"A -> B"`, file path, `"kind:name"`, etc.); `_match_suppression_key(suppression_key, violation_key)` performs substring matching so `"A -> B"` matches any cycle containing that consecutive pair; `_apply_suppressions(policy, result, suppressions)` walks violations in the sample, removes matching ones, and tracks stale entries. `run_arch_check()` calls `_apply_suppressions()` after every built-in and custom policy result; stale entries are collected into `ArchReport.stale_suppressions`. `_render()` gains a **WARN** state (yellow) for policies that passed only because suppressions removed all violations — visually distinct from a clean PASS; stale suppression entries are listed after the policy table with a "stale suppressions" header. `to_json()` includes the new `stale_suppressions` field. `codegraph/docs/arch-policies.md` gets a full "Suppression" section: TOML format, key format reference table (one row per policy type), sample-window caveat, stale-suppression behaviour, and a note that unknown policy names appear as stale (useful for typo detection). **24 new tests**: 8 in `test_arch_config.py` (parse valid suppression, missing policy field, missing key field, optional reason defaults empty, empty suppress list, multi-entry, unknown policy name doesn't error at parse time); 15 in `test_arch_check.py` (violation key generation for all 5 policy types, suppression matching exact/substring/no-match, apply_suppressions clears violations, stale detection, integration). One code-review fix: replaced `suppressions.index(s)` with `id_to_idx = {id(s): i ...}` mapping to avoid O(n) scan and broken-with-duplicate-entries behaviour. Test count: 351 → 375.

### Version bump + `--scope` PR merged to main

- `7c95ac2 chore` + `508826e merge` — bumped `pyproject.toml` to v0.1.15 and merged PR #92 (`--scope` flag, issue #22) to `main`.

### `--scope` flag for arch-check — path-prefix filtering on all built-in policies (issue #22)

- `9ebc0e4 feat(arch-check)` — `arch_check.py` gains a `_scope_filter(scope, node_alias)` helper that generates a `WHERE x.path STARTS WITH $s0 OR ...` Cypher fragment + param dict for any number of prefixes. `scope: list[str] | None` is threaded through `run_arch_check()` → `_run_all()` → all five built-in `_check_*()` functions (`import_cycles`, `cross_package`, `layer_bypass`, `coupling_ceiling`, `orphans`). `orphan_detection.path_prefix` in `.arch-policies.toml` takes precedence over `--scope` when explicitly set — `--scope` is a convenience override, not a hard override. Custom `[[policies.custom]]` Cypher is intentionally not auto-scoped (user owns that query). `cli.py` gains a `--scope` repeatable `typer.Option` forwarded to `run_arch_check()`. `.github/workflows/arch-check.yml` updated to pass `--scope codegraph/codegraph --scope codegraph/tests` so CI checks only the indexed paths. `docs/arch-policies.md` gets a new "Scoping to specific packages" section. **9 new tests**: single-prefix filtering for all 5 policies, backwards-compat (no scope → no WHERE), multi-prefix OR-join (verifies `_scope0`/`_scope1` params), orphan path_prefix precedence, orchestrator forwarding. Test count: 342 → 351.

- `1b27921 fix(arch-check)` — `orphan_detection` function query was including pytest entry points (`@pytest.fixture`, `@pytest.mark.*`) in the orphan set. Fixed by extending the `NONE` predicate to exclude functions decorated with any decorator whose name starts with `pytest`. Matched the existing `@mcp.tool` / `@app.command` / `@router.*` / `@app.*` exclusion pattern. No new tests needed — existing fixture coverage confirms the fix.

### Version bump + orphan_detection PR merged to main

- `d171787 chore` + `4956838 merge` — bumped `pyproject.toml` to v0.1.14 and merged PR #89 (orphan_detection policy + pytest entry-point fix, issue #17) to `main`.

### Orphan detection — fifth built-in arch-check policy (issue #17)

- `2dd72b7 feat(arch-check)` — `arch_check.py` gains `_check_orphans()`: reuses the dead-code Cypher from `/dead-code` to find functions, classes, atoms, and endpoints with zero inbound references and no framework-entry-point decorator. Supports an optional `path_prefix` to scope the check and a `kinds` list to restrict which node types are flagged. Result is a standard `PolicyResult` wired into `_run_all()` after `coupling_ceiling`. `arch_config.py` gains `VALID_ORPHAN_KINDS = {"function", "class", "atom", "endpoint"}`, `OrphanDetectionConfig` dataclass (`enabled: bool`, `path_prefix: str`, `kinds: list[str]`), `orphan_detection` field on `ArchConfig`, and `_parse_orphan_detection()` that validates kind values and rejects empty lists; `"orphan_detection"` added to the builtins collision-guard set. Fixed `CALL {}` → `CALL () {}` to suppress Neo4j 5.x deprecation warning. `docs/arch-policies.md` gets section 5 documenting the policy; intro updated from "four" to "five" built-in policies; `orphan_detection` added to the reserved names list and the full TOML schema example; duplicate Exit codes section removed. **11 new tests**: 4 in `test_arch_check.py` (clean graph, violations detected, path-prefix scope, kinds config) + 7 in `test_arch_config.py` (defaults, disabled, custom prefix, custom kinds, invalid kind rejected, empty kinds rejected, builtin collision); 3 orchestrator tests updated for the now-5-policy `_run_all()`. Test count: 330 → 341.

### Version bump + coupling_ceiling PR merged to main

- `ad9ccac chore` + `9c4130d merge` — bumped `pyproject.toml` to v0.1.13 and merged PR #85 (coupling_ceiling policy, issue #16) to `main`.

### Coupling ceiling — fourth built-in arch-check policy (issue #16)

- `4213450 feat(arch-check)` — `arch_check.py` gains `_check_coupling_ceiling()`: counts inbound `IMPORTS` edges per file using a Cypher aggregation query, flags any file whose fan-in exceeds `max_imports` (default 20), samples up to 5 offending importers per violating file for actionable output. The result is a standard `PolicyResult` wired into `_run_all()` after `layer_bypass`. `arch_config.py` gains `CouplingCeilingConfig` dataclass (`enabled: bool`, `max_imports: int ≥ 1`) and a `coupling_ceiling` field on `ArchConfig`; `_parse_coupling_ceiling()` validates that `max_imports` is ≥ 1 (rejects 0 and negatives); the `builtins` collision-guard set is updated so a custom policy cannot shadow `coupling_ceiling`. Module docstrings in both files updated. `docs/arch-policies.md` gets a full section 4 documenting the policy (what, why, interpreting results, TOML config, false-positive guidance) and the intro updated from "three" to "four" built-in policies. **6 new tests**: 3 in `test_arch_check.py` (clean graph, violations detected, threshold respected) + 3 in `test_arch_config.py` (tune `max_imports`, disable the policy, reject `max_imports < 1`); 3 orchestrator tests updated for the now-4-policy `_run_all()`. Test count: 324 → 330.

### Version bump + PyPI propagation PR merged

- `ec54142 chore` + `6c23313 merge` — bumped `pyproject.toml` to v0.1.12 and merged PR #82 (PyPI propagation wait + smoke test for the release workflow, issue #24) to `main`.

### PyPI propagation wait + smoke test in release workflow (issue #24)
- `dd17072 chore(ci)` — `release.yml` gains two post-publish steps. Step 1 (`id: version`) reads the version from `codegraph/pyproject.toml` via Python `tomllib` and writes it to `$GITHUB_OUTPUT`. Step 2 (`wait-for-pypi`) polls `https://pypi.org/pypi/cognitx-codegraph/<version>/json` at 10-second intervals with a 300-second timeout, exiting with a `::error::` annotation if the package never appears. Step 3 (`smoke-test`) creates a fresh venv in `/tmp`, installs the exact published version, and runs `codegraph --help` as a smoke test. Both consuming steps pass the version through `env:` rather than direct `${{ }}` interpolation in `run:` blocks (defense-in-depth against injection).

### Arch-policies schema versioning (issue #19)
- `bc70d01 chore(arch-config)` — `arch_config.py` gains `CURRENT_SCHEMA_VERSION = 1` constant and a `schema_version: int` field on `ArchConfig` (defaults to 1). `load_arch_config()` now parses a `[meta]` table from `.arch-policies.toml`: validates the value is an integer (rejects bools), rejects zero, and raises a descriptive `ValueError` with an upgrade message for any version greater than `CURRENT_SCHEMA_VERSION`. Files without `[meta]` are silently treated as version 1 — full backwards compatibility. `codegraph/codegraph/templates/arch-policies.toml` gains `[meta]\nschema_version = 1` so scaffolded repos start version-aware. `codegraph/docs/arch-policies.md` documents the new `[meta]` section and "Schema versioning" subsection. 7 new tests added: `test_missing_meta_defaults_to_version_1`, `test_explicit_version_1_accepted`, `test_future_version_rejected`, `test_zero_version_rejected`, `test_wrong_type_rejected`, `test_meta_not_a_table_rejected`, `test_version_bool_rejected`. Test count: 317 → 324.

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
| Current branch | `archon/task-fix-issue-152` |
| Base branch | `main` |
| Unpushed commits | 1 (`6ea3c20` — fix CRLF line endings in stat placeholder replacement, pending PR) |
| Open PR | None. PR #153 (issue #149 — extended `_format_stat_line` tests) merged to main. |
| Working tree | Clean |
| Test count | 471 passing + 1 deselected |
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

### Query graph statistics

```bash
.venv/bin/codegraph stats                              # Rich table: node + edge counts
.venv/bin/codegraph stats --json                       # JSON output
.venv/bin/codegraph stats --scope codegraph            # scoped to a path prefix
.venv/bin/codegraph stats --update                     # rewrite <!-- codegraph:stats-begin/end --> in CLAUDE.md etc.
.venv/bin/codegraph stats --update --file myfile.md    # target a specific file
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

#### A1. Push `dev` + publish to PyPI

**What:** Merge the open PyPI propagation wait PR (#24), register `cognitx-codegraph` on pypi.org with Trusted Publisher config, push a version tag to trigger `release.yml`.

**Why:** Everything is built and verified — including the post-publish propagation wait and smoke test (shipped `dd17072`). Only thing left is the one-time ops setup. Until this happens, "easiest possible onboarding" is blocked on users building the wheel locally.

**Scope:** ~30 min operational.
- Merge PR for issue #24 (pypi-propagation-delay).
- PyPI: create the `cognitx-codegraph` project on pypi.org. Go to Project → Publishing → add Trusted Publisher with owner `cognitx-leyton`, repo `graphrag-code`, workflow `release.yml`, environment `release`.
- GitHub: Settings → Environments → create a `release` environment (required for Trusted Publishers to accept the OIDC token).
- `git tag v0.1.11 && git push origin v0.1.11` — `release.yml` auto-builds, publishes, waits for propagation, and runs the install smoke test.
- Verify: fresh machine, `pipx install cognitx-codegraph` works.

**Gotchas:** If the PyPI project name `cognitx-codegraph` is also taken by the time you try (unlikely), rename in `pyproject.toml` and bump the version.

**Delivers:** The "easiest possible" quickstart is truly live. `README.md` quickstart ships working. `release.yml` now self-validates via the smoke test on every publish.

#### A2. Live Claude Code client verification of the 10 MCP tools

**What:** Install `cognitx-codegraph[mcp]` on a real machine, add the `mcpServers` block to `~/.claude.json`, restart Claude Code, confirm the 10 tools appear in `/mcp`.

**Why:** We've smoke-tested via raw JSON-RPC but never verified the UI. Low risk, high confidence gain.

**Scope:** 15 min of manual verification.

### Tier B — feature work, ranked

~~#### B1. Python Stage 2 — framework detection + endpoints~~ **SHIPPED** (`6493224`)

~~#### B2. MCP resources / prompts — `queries.md` as named prompt templates~~ **SHIPPED** (`357ad03`)

~~#### B3. Incremental re-indexing (`codegraph index --since HEAD~N`)~~ **SHIPPED** (`06e9873`)

~~#### B4. MCP write tools behind `--allow-write`~~ **SHIPPED** (`daae936`)

~~#### B5. `codegraph stats` — live graph counts + markdown placeholder update~~ **SHIPPED** (`de21f68`)

Live Neo4j counts by label/edge-type with `--json`, `--scope`, `--update` (rewrites `<!-- codegraph:stats-begin/end -->` delimiters). Auto-scopes from config like `arch-check`. 11 new tests, 459 total.

#### B6. Agent-native RAG — graph-selected context injection

**What:** Claude Code hook / extension that, when the user mentions a symbol, queries the graph for its 1-hop neighbours and injects a tight brief (maybe 2k tokens) instead of letting the model grep/read raw files.

**Why:** The biggest potential unlock. Turns codegraph from "cool query tool" into "core context pipeline for every AI dev session." Novel enough to open-source as its own thing.

**Scope:** ~1 week of focused work. Needs a Claude Code extension surface (hook? plugin?) to inject context before tool calls. Likely prototyped as a separate repo first.

**Gotchas:** Tight coupling to Claude Code's extension API — may require using the official `@anthropic-ai/claude-code` SDK rather than MCP.

~~#### B7. Investigate the 29% unresolved imports~~ **SHIPPED** (`c6460d2`)

Workspace registry + tsconfig extends chains now resolve bare package imports and scoped npm packages. Estimated ~8,081 previously-IMPORTS_EXTERNAL Twenty workspace imports now route to real files. Remaining unresolved are genuine third-party externals (react, apollo, etc.).

### Tier C — more arch-check policies

Custom Cypher policies are already supported via `[[policies.custom]]` in `.arch-policies.toml`. Worth shipping a few more **built-ins** for common needs:

~~- **Coupling ceiling** — any file with >N distinct IMPORTS edges is flagged.~~ **SHIPPED** (`4213450`)

~~- **Orphan detection** — functions/classes/endpoints with zero inbound references AND no framework-entry-point decorator.~~ **SHIPPED** (`2dd72b7`)
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

2. ~~**Unresolved imports percentage** (B6)~~ — **SHIPPED** (`c6460d2`). Workspace registry + tsconfig extends chains implemented. Remaining unresolved imports are genuine third-party externals.

3. ~~**Python Stage 2 priority vs. arch-check policy expansion vs. incremental re-indexing**~~ — B1 (Python Stage 2) and B2 (MCP prompts) are now shipped. Next priority: B3 (incremental re-indexing) vs. more arch-check policies vs. B4 (MCP write tools).

4. **Init's first-index timeout on huge repos** — `codegraph init --yes` runs the first index synchronously. Twenty's 3-minute index is fine; a 20k+ file repo (e.g. Babel, TypeScript compiler, monorepo-of-monorepos) would time out the user's patience. Should init have a `--skip-index` nudge for giant repos, or detect and prompt? Currently the user can pass `--skip-index` manually.

5. ~~**`.arch-policies.toml` schema versioning**~~ — **SHIPPED** (`bc70d01`). `[meta] schema_version = 1` added; forward-compat guard raises on unknown versions; backwards-compat confirmed (files without `[meta]` treated as v1).

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
- `arch-policies-versioning.plan.md` — shipped as `bc70d01`.
- `pypi-propagation-delay.plan.md` — shipped as `dd17072`.
- `coupling-ceiling-policy.plan.md` — shipped as `4213450`.
- `feat-orphan-detection-policy.plan.md` — shipped as `2dd72b7`.
- `arch-check-scope.plan.md` — shipped as `9ebc0e4`.
- `arch-check-suppression.plan.md` — shipped as `9d05a44`.
- `incremental-reindex.plan.md` — shipped as `06e9873`.
- `mcp-write-tools.plan.md` — shipped as `daae936`.
- `fix-unresolved-imports.plan.md` — shipped as `c6460d2`.
- `fix-issue-105-auto-scope.plan.md` — shipped as `ae21e20`.
- `incomplete-suppression-warning.plan.md` — shipped as `28a5eda`.
- `document-invariant-incomplete-passed.plan.md` — shipped as `082c943`.
- `configurable-sample-limit.plan.md` — shipped as `2103d57`.
- `fix-typed-getter-prefix.plan.md` — shipped as `d04af53`.
- `fix-issue-119-arch-check-scope.plan.md` — shipped as `e40fcec`.
- `fix-ci-arch-check-scope.plan.md` — shipped as `039497d`.
- `fix-install-test-flakiness.plan.md` — shipped as `1d538fa`.

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
| `cli.py` | Typer CLI: `init`, `repl`, `index`, `validate`, `arch-check`, `query`, `wipe` (+ `--since` incremental flag + `_git_changed_files`) | ~625 |
| `init.py` | `codegraph init` scaffolder (detection + prompts + template render + docker + first index) | ~310 |
| `parser.py` | tree-sitter TS/TSX walker with framework-construct detection | ~1160 |
| `py_parser.py` | tree-sitter Python walker (Stage 1: classes, methods, functions, imports, decorators, CALLS, docstrings, params, return types) | ~560 |
| `resolver.py` | Cross-file reference resolution (TS path aliases + Python module imports + class heritage + method calls + super()) | ~660 |
| `loader.py` | Neo4j batch writer, constraints, indexes, `LoadStats` (+ `delete_file_subgraph`, `_file_from_id`, `touched_files` filter) | ~900 |
| `schema.py` | Node + edge dataclasses shared across parser → loader (+ shared test-pairing constants) | ~390 |
| `config.py` | `codegraph.toml` / `pyproject.toml` config loader | ~190 |
| `arch_check.py` | Architecture-conformance runner + 5 built-in policies + `--scope` path-prefix filtering + suppression + incomplete-coverage warning + custom policy support + configurable `sample_limit` | ~705 |
| `arch_config.py` | `.arch-policies.toml` parser → typed `ArchConfig` (incl. `Suppression` dataclass + `[settings]` section with `sample_limit`) | ~464 |
| `ignore.py` | `.codegraphignore` parser + `IgnoreFilter` | ~180 |
| `framework.py` | Per-package framework detection (`FrameworkDetector`) | ~510 |
| `mcp.py` | FastMCP stdio server with 15 tools (13 read-only + `wipe_graph` + `reindex_file` behind `--allow-write`) + 29 prompt templates | ~720 |
| `ownership.py` | Git log → author mapping onto graph nodes | ~130 |
| `validate.py` | Post-load sanity-check suite | ~400 |
| `repl.py` | Interactive Cypher REPL (+ `--since` pass-through in `_cmd_index`) | ~328 |
| `utils/neo4j_json.py` | Shared `clean_row` helper | ~30 |
| `utils/repl_skin.py` | REPL formatting helpers | ~500 |
| `templates/**/*` | 11 files scaffolded by `codegraph init` | ~300 (markdown + YAML + TOML) |

### Tests (`codegraph/tests/`)

| File | Count | Target |
|---|---|---|
| `test_ignore.py` | 19 | `ignore.py` + cli helpers |
| `test_framework.py` | 18 | `framework.py` (TS) |
| `test_py_framework.py` | 13 | `framework.py` (Python Stage 2) |
| `test_mcp.py` | 127 | `mcp.py` (15 tools: 13 read-only + `wipe_graph` + `reindex_file` + 29 prompts + describe_schema + query_graph + depth/bool validation + full coverage for calls_from, callers_of, describe_function + write-tool gating + DECORATED_BY edge loading) |
| `test_py_parser.py` | 28 | `py_parser.py` (Stage 1 parsing) |
| `test_py_parser_calls.py` | 12 | Method-body CALLS emission |
| `test_py_parser_endpoints.py` | 18 | Python Stage 2 endpoint parsing |
| `test_py_resolver.py` | 14 | Python import resolution + CALLS wiring + super() |
| `test_resolver_bugs.py` | 28 | Resolver edge-case regression tests (+ 15 new: workspace resolution, scoped npm packages, tsconfig extends chains) |
| `test_loader_partitioning.py` | 3 | Function DECORATED_BY routing |
| `test_loader_pairing.py` | 6 | TS + Python test-file pairing |
| `test_arch_check.py` | 65 | Policies + orchestrator + custom policy runner (including coupling_ceiling + orphan_detection + --scope filtering + suppression + CLI auto-scope / --no-scope + incomplete coverage warning + incomplete→not-passed invariant + sample_limit threading) |
| `test_arch_config.py` | 51 | `.arch-policies.toml` parser (built-ins + custom + validation errors + schema_version + coupling_ceiling + orphan_detection config + suppression + configurable sample_limit + fully-qualified getter paths) |
| `test_init.py` | 19 | Scaffolder helpers (detection, prompts, render, write, container name uniqueness) |
| `test_init_integration.py` | 2 (1 slow) | End-to-end scaffold + optional Docker |
| `test_incremental.py` | 21 | `delete_file_subgraph`, `_file_from_id`, `load(touched_files=...)`, `_git_changed_files`, end-to-end `_run_index --since` wiring |
| **Total** | **448** | |

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
- Why schema versioning defaults to 1 (not error) when `[meta]` is absent (backwards compatibility — all existing `.arch-policies.toml` files predate versioning; treating them as v1 is correct and avoids breaking CI for repos that don't adopt `[meta]` immediately) → `bc70d01`
- Why release.yml polls the JSON API (not the CDN file) for propagation wait (JSON API is updated by PyPI's warehouse immediately; CDN is a separate propagation step — JSON API positive means the package is in PyPI's DB; the smoke test install step then catches CDN lag if it exists) → `dd17072`
- Why `${{ steps.version.outputs.version }}` flows through `env:` not direct `run:` interpolation (defense-in-depth: GitHub recommends avoiding direct `${{ }}` in `run:` blocks to prevent injection if a version string ever contained shell metacharacters) → `dd17072`
- Why `coupling_ceiling` uses a two-query approach (count query + sample query) rather than embedding the sample in the count query (two small focused queries are cleaner and faster than a combined aggregation + `COLLECT` that materialises all importers before slicing; the sample is only needed when there's a violation, so the count query acts as a fast guard) → `4213450`
- Why `max_imports` must be ≥ 1 (a ceiling of 0 would flag every file with any imports, which is never useful and almost certainly a config mistake; the validator raises a descriptive `ValueError` rather than silently clamping) → `4213450`
- Why `orphan_detection` reuses the `/dead-code` Cypher verbatim rather than writing a new query (the slash command already encodes the correct framework-entry-point exclusion list — `@mcp.tool`, `@app.command`, `@pytest.fixture`, `@router.*`, `@app.*`; reusing it keeps the policy and the interactive command consistent) → `2dd72b7`
- Why `CALL {}` was changed to `CALL () {}` (Neo4j 5.x deprecated the form without parentheses; the new form is required in Neo4j 6.x and the warning was appearing in test output) → `2dd72b7`
- Why `kinds` defaults to all four types rather than just `["function", "class"]` (the policy is meant to surface all unreachable code; users who want narrower coverage explicitly opt in via config; rejecting an empty list rather than silently defaulting is consistent with `max_imports ≥ 1`) → `2dd72b7`
- Why `--scope` does not override an explicit `orphan_detection.path_prefix` in `.arch-policies.toml` (`path_prefix` in config is a deliberate, committed choice; `--scope` is a convenience CLI override that should not silently clobber committed policy config; if the user wants `--scope` to control orphan scoping they leave `path_prefix` unset in the TOML) → `9ebc0e4`
- Why custom `[[policies.custom]]` Cypher is excluded from `--scope` auto-scoping (the user writes that Cypher directly; auto-injecting a WHERE clause into arbitrary Cypher could break syntax or semantics; the user who cares about scoping their custom policies already controls the query) → `9ebc0e4`
- Why suppression uses substring matching rather than exact-match for cycle keys (`"A -> B"` matches any cycle that contains that directed edge pair, regardless of cycle length or starting node; exact match would require users to reproduce the full cycle string, which is fragile) → `9d05a44`
- Why suppression matching operates only on the sample rows, not on the full violation count (the violation count comes from an aggregation query; we can't know which of the un-sampled violations would also match without fetching all rows; applying `passed=True` only when `violation_count == suppressed_count` is the safe conservative path) → `9d05a44`
- Why `suppressions.index(s)` was replaced with an `id_to_idx` identity map (`index()` is O(n) and broken when two `Suppression` objects are equal by value; identity-keyed dict gives O(1) lookup and correct behaviour with duplicate entries) → `9d05a44`
- Why unknown policy names in `[[suppress]]` don't error at parse time (policy names are validated at match time so that stale suppressions for renamed or removed policies surface as "stale" warnings rather than hard config errors — easier to clean up) → `9d05a44`
- Why `delete_file_subgraph` uses 10 explicit Cypher steps rather than a single `DETACH DELETE` on the File node (`DETACH DELETE` on File removes edges but leaves child-of-class nodes — Endpoint, GraphQLOperation, Column — orphaned as islands with no incoming edges; the 10-step cascade explicitly targets each child type before deleting its parent) → `06e9873`
- Why `_file_from_id` uses `split("@")[1].split("#")[0]` for endpoint/gqlop IDs (those ID formats are `endpoint:{method}:{path}@{file}#{handler}` and `gqlop:{type}:{name}@{file}#{handler}` — `@` separates the structural prefix from the file path, and `#` separates the file from the handler name) → `06e9873`
- Why `--since` implies `--no-wipe` and skips ownership (wiping then re-indexing defeats the purpose of incremental; ownership requires git-log over all files and is expensive — skipping it on incremental runs keeps the fast-path fast) → `06e9873`
- Why `--allow-write` is an `argparse` flag parsed after FastMCP startup rather than an env var or `typer.Option` (FastMCP's `main()` owns the event loop and doesn't expose a pre-run hook; `argparse` lets us parse `sys.argv` before handing control to FastMCP without forking or wrapping the process) → `daae936`
- Why `wipe_graph` requires both `--allow-write` AND `confirm=True` (two independent safeguards: the flag is set at server startup by an operator, `confirm=True` must come from the calling agent at request time — operator permission ≠ intent; either alone is insufficient for a destructive wipe) → `daae936`
- Why `reindex_file` validates `edge.kind` against an allowlist before Cypher interpolation (edge kinds come from parsed schema dataclass strings, but validating them prevents injection if a bug or future parser change produced unexpected values; the allowlist is all known `schema.py` edge constants) → `daae936`
- Why DECORATED_BY edges in `reindex_file` match Decorator nodes by `{name: $name}` not `{id: $dst}` (Decorator nodes have a `name` property but their ID is not stored as a standalone property — it's synthesised from parent ID; matching by name is stable and correct; the src_id prefix routes to the right parent label: `class:` → Class, `func:` → Function, `method:` → Method) → `daae936`
- Why `reindex_file` only loads intra-file edges, not cross-file edges (cross-file edges require resolving imports against the full graph; doing that inside a single-file tool would require re-running the full resolver, which is a 30s+ operation on large repos; cross-file edges can be refreshed by running a full incremental re-index via `--since`) → `daae936`
- Why `_try_workspace` splits scoped packages at the third `/` rather than the first (scoped npm packages have two-part names `@scope/pkg`; splitting at the first `/` would give `@scope` as the package name, which is wrong; a second split is applied when `pkg_name` starts with `@` to grab `@scope/pkg` correctly) → `c6460d2`
- Why `_try_workspace` probes `src/<subpath>/index.ts` before the package root (monorepos almost universally use `src/` as the source root; probing `src/` first avoids false-positive matches against root-level config or build artifacts with the same directory name) → `c6460d2`
- Why `_read_ts_paths` caps `extends` recursion at 10 levels (the vast majority of real tsconfig chains are 2–3 levels; 10 is enough for pathological cases while preventing runaway recursion in malformed projects; the `_seen` set provides the primary cycle guard, the cap is a secondary defence) → `c6460d2`
- Why `extends` as an array is normalised to a list before processing (TS 5.0 added array-valued `extends`; treating a string as a single-element list keeps the loop uniform and avoids a separate code path; the existing string-based path is the common case so no performance impact) → `c6460d2`
- Why auto-scope reads `codegraph.toml` / `pyproject.toml` rather than inferring from the repo structure (the config's `packages` list is the authoritative user declaration of what _this_ codegraph installation cares about; inferring from directory heuristics would re-derive something the user already stated explicitly, and would be wrong for multi-tenant graphs where leytongo / Twenty are co-indexed) → `ae21e20`
- Why `incomplete_suppression_coverage` fires only when truncated AND at least one suppression matched (truncation alone is benign — the warning exists to alert users that suppressions may not cover unseen violations; if no suppression matched the visible sample, there's nothing to warn about) → `28a5eda`
- Why the incomplete-coverage warning uses the original `violation_count + suppressed_count` total rather than `violation_count` alone (the number the user cares about is the full pre-suppression count; `violation_count` at render time has already had `suppressed_count` subtracted, so adding it back reconstructs the original total that triggered the warning) → `28a5eda`
- Why `sample_limit` is in `[settings]` not `[policies]` (`[policies]` is reserved for per-policy tuning; `sample_limit` is a cross-cutting runtime parameter that affects all policies uniformly — putting it in a separate `[settings]` section makes the config intent clearer and avoids polluting the per-policy namespace) → `2103d57`
- Why the `[settings]` validation inlines the check rather than reusing `_int()` (`_int()` hardcodes `"policies."` as the key prefix in its error message, which would produce `"policies.settings.sample_limit"` — an incorrect path; inlining gives the correct `"settings.sample_limit"` in error messages without changing the shared helper's contract) → `2103d57`
- Why `sample_limit` rejects values < 1 (a limit of 0 would return no samples and produce vacuous PASS results — never useful and almost certainly a config mistake; the validator raises a descriptive `ValueError` rather than silently clamping, consistent with `max_imports ≥ 1`) → `2103d57`
- Why `_bool`/`_int`/`_str` helpers now take `section_path` instead of `section` and format errors as `f"{section_path}.{key}"` (callers are the only ones with full context on where the value lives in the TOML tree; the helper had no basis for assuming `"policies."` as a universal prefix — `sample_limit` lives under `"settings"`, not `"policies"`) → `d04af53`
- Why CI index uses `-p codegraph -p tests` (not `-p codegraph/codegraph`) and arch-check drops explicit `--scope` (the CLI runs from `codegraph/`, so graph paths are relative to that directory — `codegraph/cli.py`, not `codegraph/codegraph/cli.py`; explicit `--scope codegraph/codegraph` never matched anything and silently bypassed scope filtering; letting `pyproject.toml` auto-scope drive both local and CI keeps them in sync) → `039497d`
- Why `pyproject.toml` packages use `["codegraph", "tests"]` not `["codegraph/codegraph", "codegraph/tests"]` (`load_config` discovers `pyproject.toml` from the `codegraph/` directory where `arch-check` is run; `codegraph index .` from that directory stores file paths relative to `.`, so graph paths are `codegraph/cli.py` not `codegraph/codegraph/cli.py`; the longer paths are only correct when indexing from the repo root — which CI does via `-p codegraph/codegraph`) → `e40fcec`
- Why `__version__` uses `importlib.metadata.version()` rather than a hardcoded string (a hardcoded string must be updated manually on every version bump and was already stale at `"0.1.0"` while pyproject.toml was at `0.1.26`; `importlib.metadata` reads the installed package metadata which is always in sync with `pyproject.toml` after `pip install -e .`; fallback to `"0.0.0"` covers the case where the package is imported from source without being installed) → `1d538fa`
- Why `TMPDIR` was renamed to `_tmpdir` in the test slash command (TMPDIR is a standard POSIX environment variable; shadowing it in the shell scope could cause downstream tools in the same script to create temp files in the wrong directory; `_tmpdir` is a local variable name that avoids the collision) → `1d538fa`
- Why `2>/dev/null` was removed from `pip install` in the test slash command (silently suppressing pip's stderr hides diagnostic information — network errors, SSL failures, package conflict messages — that are essential when the install fails; the retry loop already provides flakiness tolerance, so suppression is no longer needed as a noise-reduction measure) → `1d538fa`
- Why `assert not (incomplete and new_violation_count == 0)` is sound (when `incomplete=True`, at least `violation_count - len(sample)` violations were never fetched; even if all sampled rows were suppressed, the unseen rows remain — so `violation_count > 0` is guaranteed and `passed` can never be True; the assert documents and enforces this invariant to catch future regressions) → `082c943`
- Why `--no-scope` is needed when auto-scope is active (the graph may deliberately co-index multiple projects for cross-project arch-check; `--no-scope` restores the pre-#105 full-graph behaviour without requiring the user to delete their config) → `ae21e20`
- Why `--scope` takes precedence over auto-scope (explicit always beats implicit; a CI job that passes `--scope` should not be silently overridden by whatever config the target repo happens to have) → `ae21e20`
- Why `_git_changed_files` treats renamed files as delete-old + add-new (the old path's subgraph must be cleaned so its nodes don't become orphaned; the new path is re-parsed fresh; treating a rename as a single "move" would require a graph rename operation that doesn't exist) → `06e9873`
- Why `load(touched_files=...)` always writes packages even in incremental mode (Package nodes encode framework-level metadata shared across files; filtering them out to save time could leave the Package table stale if the only changed file was the one that determined the framework) → `06e9873`

### Git remotes

```
origin  git@github.com:cognitx-leyton/graphrag-code.git
```

Protected branches: `main`, `release`, `hotfix`. `dev` is the working branch. PRs go into `main` via the `dev → main` flow. PR #8 is currently open.
