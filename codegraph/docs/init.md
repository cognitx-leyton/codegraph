# `codegraph init` — scaffold codegraph into any repo

`codegraph init` is the fastest path from "I heard about codegraph" to "I'm querying my repo in Cypher". One command, 4-5 short questions, and you have a working graph plus Claude Code slash commands plus an architecture-conformance CI gate.

## What it does, in order

1. **Preflight** — finds the git root (errors out with a clear message if you're not in a git repo).
2. **Repo shape detection** — scans the top level and one layer of standard monorepo folders (`apps/`, `packages/`, `services/`) for `pyproject.toml` / `package.json` / `tsconfig.json`. Uses whatever it finds as default suggestions for the prompts.
3. **Interactive Q&A** — 4-5 questions; every answer has a sensible default. `--yes` skips this step entirely.
4. **Scaffolds files** — writes the Claude Code slash commands, the GitHub Actions workflow, the `.arch-policies.toml` policy config, and the `docker-compose.yml`. Existing files are skipped unless you pass `--force`. `CLAUDE.md` is always *appended to* — never clobbered.
5. **Starts Neo4j** — runs `docker compose up -d` and polls for HTTP readiness (up to 90s). Skipped with `--skip-docker`.
6. **First index** — runs `codegraph index` against the packages you confirmed in step 3, so the graph is queryable immediately. Skipped with `--skip-index`.
7. **Next-steps banner** — prints 3-4 commands to get you querying.

## Flags

| Flag | Effect |
|---|---|
| `--yes` / `-y` | Non-interactive. Accepts all detected defaults: every detected package, no cross-package policies, all three install targets enabled (Claude Code, CI, Docker Neo4j). Useful in automation or CI. |
| `--force` | Overwrite existing scaffolded files. Does NOT overwrite `CLAUDE.md` — that's always appended safely. |
| `--skip-docker` | Write `docker-compose.yml` but don't start the container. Useful when you're running Neo4j on another machine, or using a hosted instance like Neo4j Aura. |
| `--skip-index` | Don't run the first `codegraph index` after scaffolding. Useful when the repo is too big to index on first try, or when you want to customize `.arch-policies.toml` before the first run. |

## The prompts

```
Detected languages: py, ts
Package candidates: apps/web, apps/api

Package paths to index (comma-separated) [apps/web, apps/api]:
Add cross-package boundaries (importer must not import importee)? [y/N]:
  (if y) Forbidden import — importer package (empty to finish): apps/web
         Forbidden import — importee package: apps/api
Install Claude Code slash commands into .claude/commands/? [Y/n]:
Install GitHub Actions arch-check gate into .github/workflows/? [Y/n]:
Set up local Neo4j via docker-compose? [Y/n]:
```

Defaults (what `--yes` picks): all packages detected in step 2, zero cross-pairs, all three install targets = yes.

## Files written

| Path | When | Substituted variables |
|---|---|---|
| `.claude/commands/*.md` (×7) | if Claude Code install = yes | `$DEFAULT_PACKAGE_PREFIX` in `dead-code.md`, `$PACKAGE_PATHS_FLAGS` in `graph-refresh.md` |
| `.github/workflows/arch-check.yml` | if CI install = yes | `$PACKAGE_PATHS_FLAGS`, `$PIPX_VERSION` |
| `.arch-policies.toml` | always | `$CROSS_PAIRS_TOML` |
| `docker-compose.yml` | if Neo4j setup = yes | `$CONTAINER_NAME`, `$NEO4J_BOLT_PORT`, `$NEO4J_HTTP_PORT` |
| `CLAUDE.md` | always (appended) | `$CONTAINER_NAME`, `$NEO4J_BOLT_PORT`, `$PACKAGE_PATHS_FLAGS` |

Templates live in `codegraph/codegraph/templates/` and use `string.Template` syntax (stdlib, no Jinja dependency).

## Troubleshooting

**"Not a git repository"** — run `git init` first. Codegraph needs a git root to locate itself and to scope ownership edges correctly.

**"docker not found on PATH"** — install Docker Desktop (Mac/Windows) or the Docker engine (Linux), then re-run. Or pass `--skip-docker` and point codegraph at a hosted Neo4j via the `CODEGRAPH_NEO4J_URI` env var.

**"Neo4j did not become ready in 90s"** — the container is taking longer than usual to pull the image (cold start). Run `docker compose logs neo4j` to check, then re-run `codegraph init` — it'll skip steps that already completed.

**"Port 7687 busy"** — another Neo4j instance (or another service) is already on that port. Edit `docker-compose.yml` to map different host ports (e.g. `7690:7687`), then also update `CODEGRAPH_NEO4J_URI=bolt://localhost:7690` in your shell rc. Future versions of `codegraph init` will auto-detect and pick free ports.

**CLAUDE.md already has a codegraph section** — init detects this (looks for the `## Using the codegraph knowledge graph` heading) and skips the append. Safe to re-run any number of times.

## After init

The banner at the end tells you what to try first:

```
codegraph query "MATCH (c:Class) RETURN c.name LIMIT 5"
codegraph arch-check
# Inside Claude Code:
/graph "MATCH (f:File) RETURN count(f)"
```

If any of these are empty or erroring out, start with:
- `docker compose ps` — is the Neo4j container up?
- `codegraph query "MATCH (n) RETURN count(n)"` — did indexing produce nodes? If zero, the package paths in `.arch-policies.toml` may not match real files. Edit and re-run `codegraph index . $PACKAGE_PATHS_FLAGS --no-wipe`.

## When to re-run `codegraph init`

- Adding a new top-level package — re-run with `--force` to refresh `.github/workflows/arch-check.yml` (which bakes in the `-p` flags).
- Changing cross-package boundaries — edit `.arch-policies.toml` directly; no re-init needed.
- Upgrading codegraph — `pipx upgrade cognitx-codegraph` then re-run `codegraph init --force` to pull any template changes (commands, workflow, compose).
