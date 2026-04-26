# `codegraph` CLI Reference

Per-command reference for every Typer subcommand exposed by the `codegraph` console script. The source of truth is [`codegraph/codegraph/cli.py`](../codegraph/cli.py); this page documents flags, output shapes, and exit codes as they actually exist there.

A few invariants apply to every command:

- **`--json`** is supported on every top-level command that produces output. In `--json` mode stdout is a single machine-parseable document (`{"ok": true, ...}` on success, `{"ok": false, "error": ..., "message": ...}` on failure) and Rich console output is suppressed. This is the agent-native invocation path.
- **No subcommand → REPL.** Running bare `codegraph` (or `codegraph repl`) drops into the interactive Cypher shell. See [`repl`](#repl) below.
- **CLI overrides config-file values.** Flags like `--package` / `-p`, `--scope`, and `--ignore-file` shadow whatever is set in `codegraph.toml` or `pyproject.toml [tool.codegraph]`.
- **Default Neo4j connection** is `bolt://localhost:7688` with user `neo4j` / password `codegraph123`. Override with `CODEGRAPH_NEO4J_URI`, `CODEGRAPH_NEO4J_USER`, `CODEGRAPH_NEO4J_PASS` env vars or per-command flags.
- **Connection-failure exit code** is always `2` (`config`, `connection`, or `ignore` errors all map to it).

---

## init

Scaffold codegraph into the current repo: writes config, slash commands, CI gate, `docker-compose.yml`, brings up Neo4j, runs the first index.

### Synopsis

```bash
codegraph init [--force] [--yes/-y] [--skip-docker] [--skip-index] [--bolt-port N] [--http-port N]
```

### Flags

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--force` | bool | false | Overwrite existing files. **Never** overwrites `CLAUDE.md`. |
| `--yes`, `-y` | bool | false | Non-interactive; accept all defaults. |
| `--skip-docker` | bool | false | Write the compose file but don't start Neo4j. |
| `--skip-index` | bool | false | Don't run the initial index after scaffold. |
| `--bolt-port` | int | 7688 | Neo4j Bolt host port (offset from Neo4j's stock 7687 to avoid colliding with a developer's own Neo4j). |
| `--http-port` | int | 7475 | Neo4j HTTP host port (offset from Neo4j's stock 7474). |

Full walkthrough — what gets written, port-collision handling, idempotency, repair mode — lives in **[init.md](./init.md)**.

---

## repl

Start the interactive Cypher shell.

### Synopsis

```bash
codegraph repl [--repo PATH] [--uri URI] [--user USER]
```

### Flags

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--repo` | path | none | Pre-set the current repo on launch. |
| `--uri` | str | `bolt://localhost:7688` | Pre-set the Neo4j URI. |
| `--user` | str | `neo4j` | Pre-set the Neo4j user. |

Equivalent to running `codegraph` with no subcommand. The exit code is forwarded from `run_repl()`.

---

## index

Index a TypeScript / Python codebase into Neo4j.

### Synopsis

```bash
codegraph index REPO [-p PACKAGE]... [--no-wipe] [--update | --since REF]
                     [--ignore-file PATH] [--skip-ownership] [--max-files N]
                     [--no-export] [--no-benchmark] [--no-analyze]
                     [--uri URI --user USER --password PASS] [--json]
```

### Arguments

- **`REPO`** *(required, must be an existing directory)* — repo root to index.

### Flags

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--package`, `-p` | repeatable str | from config | Repo-relative package path. Overrides `codegraph.toml` / `pyproject.toml`. |
| `--wipe / --no-wipe` | bool | true | Wipe Neo4j before load. Implicitly `--no-wipe` when `--update` or `--since` is set. |
| `--update` | bool | false | Incremental: skip unchanged files via SHA256 content cache. Mutually exclusive with `--since`. |
| `--since` | git ref | none | Only re-index files changed since this ref (commit, tag, `HEAD~N`). Implies `--no-wipe`. |
| `--ignore-file` | path | auto-detected | Path to a `.codegraphignore`. Auto-detects `<repo>/.codegraphignore` if unset. |
| `--skip-ownership` | bool | false | Skip git-log ingestion (faster on large histories; disables `/who-owns`). |
| `--max-files` | int | none | Limit files parsed (debug). |
| `--no-export` | bool | false | Skip auto HTML/JSON export after indexing. |
| `--no-benchmark` | bool | false | Skip auto token-reduction benchmark after indexing. |
| `--no-analyze` | bool | false | Skip auto Leiden community detection + `GRAPH_REPORT.md`. |
| `--uri`, `--user`, `--password` | str | env defaults | Neo4j connection. |
| `--json` | bool | false | Emit stats as JSON; suppress Rich tables. |

`--update` and `--since` are mutually exclusive — passing both is a config error. Both imply `--no-wipe` and `--skip-ownership`. See **[incremental.md](./incremental.md)** for the cache layout, manifest, and rebuild semantics.

### Output

**Human:** Rich `Load stats` table with one row per node label and one row per edge type. Then optional `✓ exported graph.html + graph.json → …`, benchmark summary, and `GRAPH_REPORT.md` confirmation.

**`--json`:**

```json
{
  "ok": true,
  "stats": {
    "files": 18, "classes": 41, "functions": 82, "methods": 150,
    "interfaces": 0, "endpoints": 0, "gql_operations": 0,
    "columns": 0, "atoms": 0, "externals": 12,
    "total_imports": 312, "unresolved_imports": 4,
    "edges": {"IMPORTS": 73, "CALLS": 421, "DEFINES": 211, "...": "..."}
  }
}
```

### Exit codes

| Code | Cause |
|---|---|
| 0 | Success. |
| 2 | `ConfigError` (missing packages, conflicting flags), `IgnoreConfigError`, or Neo4j `ServiceUnavailable` / `AuthError`. |

### Example

```bash
codegraph index . -p codegraph/codegraph -p codegraph/tests --update
```

---

## validate

Run the validation suite against an already-loaded graph (coverage, structural assertions, smoke queries).

### Synopsis

```bash
codegraph validate REPO [--uri URI --user USER --password PASS] [--json]
```

### Arguments

- **`REPO`** *(required)* — repo root (used to map Neo4j paths back to disk).

### Flags

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--uri`, `--user`, `--password` | str | env defaults | Neo4j connection. |
| `--json` | bool | false | Emit report as JSON. |

### Output

**Human:** Rich tables for coverage / assertions / smoke results, with green checkmarks or red `FAIL` markers per row.

**`--json`:**

```json
{
  "ok": true,
  "report": {
    "ok": true,
    "coverage": {"...": "..."},
    "assertions": ["..."],
    "smoke": ["..."],
    "errors": [],
    "warnings": []
  }
}
```

See **[schema.md](./schema.md)** for what each assertion is checking.

### Exit codes

| Code | Cause |
|---|---|
| 0 | All checks pass. |
| 1 | One or more checks failed (`report.ok == false`). |
| 2 | Neo4j connection error. |

---

## arch-check

Run architecture-conformance policies against the live graph. Designed as a CI gate.

### Synopsis

```bash
codegraph arch-check [--config PATH] [--repo PATH] [--scope PREFIX]... [--no-scope]
                     [--uri URI --user USER --password PASS] [--json]
```

### Flags

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--config` | path | `<repo>/.arch-policies.toml` | Override policy config location. |
| `--repo` | path | `.` | Repo root used to locate `.arch-policies.toml`. |
| `--scope` | repeatable str | auto from config | Restrict policies to file paths starting with this prefix. |
| `--no-scope` | bool | false | Disable auto-scope; check the entire graph. |
| `--uri`, `--user`, `--password` | str | env defaults | Neo4j connection. |
| `--json` | bool | false | Emit report as JSON. |

When neither `--scope` nor `--no-scope` is set, scope auto-derives from the packages listed in `codegraph.toml` / `pyproject.toml`.

### Output

**Human:** One Rich table per policy with violations listed. A green `✓` or red `✗` summary per policy.

**`--json`:** A single JSON document (produced by `ArchReport.to_json()`) with `ok`, `policies[]`, and `violations[]` fields per policy.

### Exit codes

| Code | Cause |
|---|---|
| 0 | All policies pass. |
| 1 | One or more policy violations (`report.ok == false`). |
| 2 | Config or connection error. |

### Example

```bash
codegraph arch-check --json > arch-report.json
```

Policy reference: **[arch-policies.md](./arch-policies.md)**.

---

## audit

Run an agent-driven extraction self-check against the live graph. Launches an external coding agent (Claude Code, Codex, Cursor, …) with a tightly-scoped prompt that audits whether codegraph extracted everything it claims to support for *this* repo's frameworks. Agent finds extraction bugs (`@Controller` decorator missed, `mapped_column` overlooked, etc.); you triage them as GitHub issues.

The audit itself is read-only — never writes to the graph or the source tree. The agent is launched in headless + permission-bypass mode by default, so it can iterate on `codegraph query` and `Read` calls without per-tool prompts.

### Synopsis

```bash
codegraph audit [--repo PATH] [--agent NAME] [--list-agents]
                [--print-prompt-only]
                [--gh-issue/--no-gh-issue]
                [--bypass/--no-bypass] [--unsafe]
                [--timeout SECONDS] [--recompute-lock]
                [--yes/-y] [--json]
```

### Flags

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--repo` | path | `.` | Repo to audit. |
| `--agent` | str | (prompt) | One of `claude`, `codex`, `gemini`, `aider`, `opencode`, `droid`, `cursor`. If omitted and multiple agents are detected on PATH, prompts. |
| `--list-agents` | bool | false | Print supported agents and detection status, then exit 0. |
| `--print-prompt-only` | bool | false | Render the audit prompt to stdout without launching anything. Useful for inspection or piping to a non-supported agent. |
| `--gh-issue/--no-gh-issue` | bool | (prompt) | After the audit, open a GitHub issue from the report via `gh issue create --label codegraph-audit`. If unset, prompts when findings exist. |
| `--bypass/--no-bypass` | bool | true | Pass the agent's permission-bypass flag (`claude --dangerously-skip-permissions`, `codex --full-auto`, `gemini --yolo`, etc.). `--no-bypass` runs the agent interactively — every tool call prompts. |
| `--unsafe` | bool | false | For codex only: replace the sandboxed `--full-auto` with `--dangerously-bypass-approvals-and-sandbox`. No-op for other agents. |
| `--timeout` | int | `1800` | Agent timeout in seconds (30 min default). |
| `--recompute-lock` | bool | false | Regenerate the prompt-template lock file before launching. Use after intentionally editing a template; otherwise the launch refuses on lock mismatch (anti-tampering). |
| `--yes`, `-y` | bool | false | Non-interactive: auto-pick the only detected agent, skip the GitHub-issue confirmation. |
| `--json` | bool | false | Emit the final report as JSON on stdout. |

### Permission-bypass flags per agent

| Agent | Bypass flag passed | `--unsafe` adds |
|---|---|---|
| `claude` | `--dangerously-skip-permissions` | — |
| `codex` | `--full-auto` (sandboxed) | `--dangerously-bypass-approvals-and-sandbox` |
| `gemini` | `--yolo` | — |
| `aider` | `--yes-always` | — |
| `opencode` | `--auto-approve` | — |
| `droid` | `--yes` | — |
| `cursor` | (no headless mode — writes `.cursor/rules/codegraph-audit.mdc`) | — |

### Output

Default mode prints a Rich summary with the report path and (if used) GitHub-issue URL. The agent's full report is written to `codegraph-out/audit-report.md` with a strict `## Issue N` block schema (parseable by both `--json` and `gh issue create --body-file`).

`--json` emits:

```json
{
  "ok": true,
  "agent": "claude",
  "repo": "/abs/path",
  "report_path": "/abs/path/codegraph-out/audit-report.md",
  "issues_found": 3,
  "findings": [
    {"index": 1, "category": "MISSING_NODE", "severity": "high", "construct": "...", "raw_block": "..."}
  ],
  "gh_issue_url": "https://github.com/<user>/<repo>/issues/42",
  "error": null,
  "warnings": []
}
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Audit completed; either no findings or findings + GitHub issue opened. |
| 1 | Audit completed with findings AND no GitHub issue created. |
| 2 | Pre-launch failure (lock mismatch, no agent detected, agent binary missing). |
| 124 | Agent exceeded `--timeout`. |
| 127 | Agent binary not invokable. |

### Prompt integrity

The prompt templates ship under `codegraph/templates/audit/` and are protected by three layers, all of which fire automatically on any PR touching them:

1. **CODEOWNERS review** required (`codegraph/templates/audit/**` etc.).
2. **`.github/workflows/audit-prompt-integrity.yml`** posts a sticky reviewer warning, runs the static diff lint (no new external URLs in prompt files, no new shell-execution call sites in `audit.py` / `audit_agents.py`, no >50% line-count growth), and verifies the lock.
3. **`templates/audit/.lock`** SHA-256 hashes every prompt file. The runtime checks the lock before launching the agent — refuses to run if the prompt has been tampered with on disk.

To legitimately edit a template:

```bash
# edit codegraph/templates/audit/audit-prompt.md
.venv/bin/python -m codegraph.audit_prompt_lint --update-lock
git diff codegraph/templates/audit/.lock   # lock change visible in the same PR
```

### Examples

```bash
# Smoke test — see which agents are usable on this machine
codegraph audit --list-agents

# Inspect the prompt before running anything
codegraph audit --agent claude --print-prompt-only | less

# Full unattended run, auto-open issue
codegraph audit --agent claude --gh-issue --yes

# Audit with the agent in interactive mode (prompts for each tool call)
codegraph audit --agent claude --no-bypass

# Authorise a legitimate prompt edit
python -m codegraph.audit_prompt_lint --update-lock
codegraph audit --agent claude --recompute-lock
```

---

## query

Run a Cypher query against the current graph.

### Synopsis

```bash
codegraph query CYPHER [-n LIMIT] [--uri URI --user USER --password PASS] [--json]
```

### Arguments

- **`CYPHER`** *(required)* — the Cypher query to execute.

### Flags

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--limit`, `-n` | int | 20 | Max rows to return. |
| `--uri`, `--user`, `--password` | str | env defaults | Neo4j connection. |
| `--json` | bool | false | Emit rows as JSON. |

### Output

**Human:** Rich table with one column per query alias.

**`--json`:**

```json
{
  "ok": true,
  "count": 12,
  "rows": [{"col1": "...", "col2": "..."}, "..."]
}
```

Neo4j `Node` and `Relationship` values are flattened via `clean_row()` so the JSON is round-trip-safe.

### Exit codes

| Code | Cause |
|---|---|
| 0 | Query ran (zero rows is still success). |
| 2 | Neo4j connection error. |

Curated query patterns: **[../queries.md](../queries.md)**. Schema reference: **[schema.md](./schema.md)**.

---

## wipe

Drop every node and relationship in the target Neo4j database.

### Synopsis

```bash
codegraph wipe [--uri URI --user USER --password PASS] [--json]
```

### Flags

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--uri`, `--user`, `--password` | str | env defaults | Neo4j connection. |
| `--json` | bool | false | Emit confirmation as JSON. |

### Output

**Human:** `✓ wiped`.

**`--json`:**

```json
{"ok": true, "action": "wipe", "uri": "bolt://localhost:7688"}
```

### Exit codes

| Code | Cause |
|---|---|
| 0 | Database wiped. |
| 2 | Neo4j connection error. |

---

## stats

Query the live graph for node/edge counts. Optionally patch markdown placeholders in-place with the result.

### Synopsis

```bash
codegraph stats [--scope PREFIX]... [--no-scope] [--include-cross-scope-edges]
                [--update [-f FILE]...] [--repo PATH]
                [--uri URI --user USER --password PASS] [--json]
```

### Flags

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--scope`, `-s` | repeatable str | auto from config | Restrict counts to file-path prefixes. |
| `--no-scope` | bool | false | Disable auto-scope; count the entire graph. |
| `--include-cross-scope-edges` | bool | false | Include edges where one endpoint is outside scope. Default: both endpoints in scope. |
| `--update` | bool | false | Patch markdown stat placeholders in-place. |
| `--file`, `-f` | repeatable path | `CLAUDE.md` + `.claude/commands/graph.md` | Targets when `--update` is set. |
| `--repo` | path | `.` | Repo root for config + markdown lookup. |
| `--uri`, `--user`, `--password` | str | env defaults | Neo4j connection. |
| `--json` | bool | false | Emit stats as JSON. |

Stat placeholders are recognized between the `<!-- codegraph:stats-begin -->` / `<!-- codegraph:stats-end -->` markers.

### Output

**Human:** Rich `Graph stats` table with rows for `files`, `classes`, `functions`, `methods`, `interfaces`, `endpoints`, `hooks`, `decorators` and one row per edge type.

**`--json`:**

```json
{
  "ok": true,
  "stats": {
    "files": 18, "classes": 41, "functions": 82, "methods": 150,
    "interfaces": 0, "endpoints": 0, "hooks": 0, "decorators": 14,
    "edges": {"IMPORTS": 73, "CALLS": 421, "DEFINES": 211}
  },
  "files_updated": 2
}
```

`files_updated` only appears when `--update` was set.

### Exit codes

| Code | Cause |
|---|---|
| 0 | Stats returned. |
| 2 | Neo4j connection error. |

Schema reference: **[schema.md](./schema.md)**.

---

## export

Export the graph as interactive HTML, JSON, GraphML, or Cypher.

### Synopsis

```bash
codegraph export [-o OUT_DIR] [--html/--no-html] [--json-export/--no-json-export]
                 [--graphml] [--cypher] [--scope PREFIX]... [--no-scope]
                 [--max-nodes N] [--repo PATH]
                 [--uri URI --user USER --password PASS] [--json]
```

### Flags

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--out`, `-o` | path | `codegraph-out` | Output directory. |
| `--html / --no-html` | bool | true | Produce `graph.html`. |
| `--json-export / --no-json-export` | bool | true | Produce `graph.json`. |
| `--graphml` | bool | false | Produce `graph.graphml`. |
| `--cypher` | bool | false | Produce `graph.cypher`. |
| `--scope`, `-s` | repeatable str | auto from config | Restrict to paths starting with prefix. |
| `--no-scope` | bool | false | Disable auto-scope. |
| `--max-nodes` | int | 5000 | Max nodes for HTML visualisation. Larger graphs warn-and-skip the HTML. |
| `--repo` | path | `.` | Repo root for config lookup. |
| `--uri`, `--user`, `--password` | str | env defaults | Neo4j connection. |
| `--json` | bool | false | Emit status as JSON. |

### Output

**Human:** One `✓ <path>` line per written file plus a summary `exported N nodes, M edges → K file(s)`.

**`--json`:**

```json
{
  "ok": true,
  "nodes": 1234,
  "edges": 5678,
  "files": ["codegraph-out/graph.html", "codegraph-out/graph.json"],
  "warnings": ["..."]
}
```

`warnings` only appears when an exporter (typically the HTML one when `nodes > max-nodes`) failed soft.

### Exit codes

| Code | Cause |
|---|---|
| 0 | At least one file written. |
| 2 | Neo4j connection error. |

---

## benchmark

Run the token-reduction benchmark: compares the size of canonical Cypher answers vs the raw source corpus.

### Synopsis

```bash
codegraph benchmark [REPO] [--scope PREFIX]... [--no-scope] [-o OUT]
                    [--min-reduction N] [-v]
                    [--uri URI --user USER --password PASS] [--json]
```

### Arguments

- **`REPO`** *(default `.`)* — repo root.

### Flags

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--scope`, `-s` | repeatable str | auto from config | Restrict corpus counting to package paths. |
| `--no-scope` | bool | false | Disable auto-scope. |
| `--out`, `-o` | path | `codegraph-out` | Directory for `benchmark.json`. |
| `--min-reduction` | float | none | Exit 1 if the reduction ratio is below this threshold. |
| `--verbose`, `-v` | bool | false | Show per-query breakdown. |
| `--uri`, `--user`, `--password` | str | env defaults | Neo4j connection. |
| `--json` | bool | false | Emit report as JSON. |

### Output

**Human:** A summary line `Token reduction: <ratio>x` plus per-query rows when `-v` is passed.

**`--json`:** Output of `BenchmarkResult.to_json()`:

```json
{
  "ok": true,
  "corpus_tokens": 124000,
  "queries_evaluated": 12,
  "queries_skipped": 1,
  "avg_query_tokens": 1850,
  "reduction_ratio": 67.0,
  "tokenizer": "chars/4",
  "per_query": [{"name": "...", "rows": 14, "context_tokens": 980, "skipped": false}],
  "timestamp": "2026-04-25T..."
}
```

A copy is also written to `<repo>/<out>/benchmark.json` regardless of `--json`.

### Exit codes

| Code | Cause |
|---|---|
| 0 | Benchmark ran and (if set) `reduction_ratio >= --min-reduction`. |
| 1 | `--min-reduction` set and ratio fell below it. |
| 2 | Neo4j connection error. |

---

## report

Generate `GRAPH_REPORT.md` from Leiden community detection on the live graph. Requires the `[analyze]` extra.

### Synopsis

```bash
codegraph report [REPO] [-o OUT] [--scope PREFIX]... [--no-scope]
                 [--uri URI --user USER --password PASS] [--json]
```

### Arguments

- **`REPO`** *(default `.`)* — repo root.

### Flags

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--out`, `-o` | path | `codegraph-out` | Directory where `GRAPH_REPORT.md` lands. |
| `--scope`, `-s` | repeatable str | auto from config | Restrict analysis to package paths. |
| `--no-scope` | bool | false | Disable auto-scope. |
| `--uri`, `--user`, `--password` | str | env defaults | Neo4j connection. |
| `--json` | bool | false | Emit raw analysis as JSON instead of writing the markdown. |

### Output

**Human:** `✓ GRAPH_REPORT.md → <out> (<N> communities)`.

**`--json`:**

```json
{"ok": true, "analysis": {"community_count": 7, "communities": ["..."], "...": "..."}}
```

### Exit codes

| Code | Cause |
|---|---|
| 0 | Report written (or analysis emitted when `--json`). |
| 2 | `[analyze]` extra not installed, or Neo4j connection error. |

---

## watch

Watch for file changes and rebuild the graph incrementally.

### Synopsis

```bash
codegraph watch [REPO] [--debounce SECONDS] [-p PACKAGE]...
                [--uri URI --user USER --password PASS]
```

### Arguments

- **`REPO`** *(default `.`)* — root of the repo to watch.

### Flags

| Flag | Type | Default | Notes |
|---|---|---|---|
| `--debounce` | float | 3.0 | Seconds to wait after the last change before rebuilding. |
| `--package`, `-p` | repeatable str | from config | Package(s) to watch. |
| `--uri`, `--user`, `--password` | str | env defaults | Neo4j connection. |

Long-running; stop with `Ctrl+C`. Each rebuild reuses the SHA256 cache, so steady-state cost is just the changed files. See **[incremental.md](./incremental.md)** for cache details.

### Exit codes

The exit code is forwarded from `run_watch()` (typically `0` on clean shutdown, non-zero on fatal error).

---

## hook

Manage the post-commit / post-checkout git hooks that keep the graph in sync after every commit.

### `hook install`

```bash
codegraph hook install
```

Installs `post-commit` and `post-checkout` hooks under `.git/hooks/` that re-run `codegraph index --update` for the current repo. Existing hooks are preserved (codegraph appends a marked block).

**Exit codes**: `0` on success, `1` on `RuntimeError` (e.g. not in a git repo).

### `hook status`

```bash
codegraph hook status
```

Prints whether the codegraph hooks are present and pointing at the current binary.

### `hook uninstall`

```bash
codegraph hook uninstall
```

Removes the codegraph block from each hook (other content preserved). Exit `1` on `RuntimeError`.

See **[incremental.md](./incremental.md)** for what the hooks do and when to use them vs `watch`.

---

## install / uninstall (per-platform)

Install or remove codegraph integration for a specific AI coding platform.

### Synopsis

```bash
codegraph install [--all]
codegraph install <platform>
codegraph uninstall <platform>
```

### Supported platforms

`claude`, `codex`, `opencode`, `cursor`, `gemini`, `copilot`, `vscode`, `aider`, `claw`, `droid`, `trae`, `kiro`, `antigravity`, `hermes`.

### `install --all`

Detects every platform that's already configured in the repo (presence of `.claude/`, `.cursor/`, `AGENTS.md`, etc.) and installs codegraph integration for each.

### Output

Each platform command prints a single status line: `<Display Name>: <action1>; <action2>` or `<Display Name>: already installed` / `nothing to remove`.

Per-platform behaviour — what files are written, how the rules block is anchored, hook wiring — is documented in **[platforms.md](./platforms.md)**.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `connection error: Failed to establish connection` (exit 2) | Neo4j container not up | `docker ps \| grep codegraph-neo4j`; if missing, `docker compose up -d` from the repo root. |
| `config error: No packages configured` (exit 2) | Neither `codegraph.toml`, `pyproject.toml [tool.codegraph]`, nor `-p` set | Add packages to config, or pass `-p <path>` per-call. See the Configuration section in the main README. |
| `--since` and `--update` are mutually exclusive | Both flags passed | Pick one. `--since REF` for diff-against-git; `--update` for SHA256-cache delta. |
| Indexing took forever / wiped on every run | Default `--wipe` mode | Use `--update` (cache-based) or `--since HEAD~1` for incremental rebuilds. See **[incremental.md](./incremental.md)**. |
| `arch-check` returns 1 in CI | One or more policy violations | Read the JSON report, fix violations or add a suppression. See **[arch-policies.md](./arch-policies.md)**. |
