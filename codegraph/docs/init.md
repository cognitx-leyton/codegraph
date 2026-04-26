# `codegraph init` — scaffold codegraph into any repo

`codegraph init` is the fastest path from "I heard about codegraph" to "I'm querying my repo in Cypher". One command, 4-5 short questions, and you have a working graph plus Claude Code slash commands plus an architecture-conformance CI gate.

## What it does, in order

1. **Docker preflight** — checks that the `docker` binary is on PATH and the daemon is answering. Reports the version and warns if it's older than the recommended `20.10` baseline. Prints OS-aware install / start instructions and exits 1 if Docker is missing or the daemon's down (unless you pass `--skip-docker`). See [Docker presence checks](#docker-presence-checks) below.
2. **Find or create the shared `codegraph-neo4j` container** — every repo on the machine indexes into one shared Neo4j. Init reuses it if running, starts it if stopped, or creates it on first run. See [Shared `codegraph-neo4j` container](#shared-codegraph-neo4j-container) below.
3. **Git root preflight** — errors out with a clear message if you're not in a git repo.
4. **Repo shape detection** — scans the top level and one layer of standard monorepo folders (`apps/`, `packages/`, `services/`) for `pyproject.toml` / `package.json` / `tsconfig.json`. Uses whatever it finds as default suggestions for the prompts.
5. **Interactive Q&A** — 4-5 questions; every answer has a sensible default. `--yes` skips this step entirely.
6. **Scaffolds files** — writes the Claude Code slash commands, the GitHub Actions workflow, the `.arch-policies.toml` policy config, and the `docker-compose.yml`. Existing files are skipped unless you pass `--force`. `CLAUDE.md` is always *appended to* — never clobbered.
7. **Starts Neo4j** — handles the four cases via the auto-detect logic above: reuse running, start stopped, create new, or fail loud on a port collision.
8. **First index** — runs `codegraph index` against the packages you confirmed in step 5, so the graph is queryable immediately. Skipped with `--skip-index`.
9. **Next-steps banner** — prints 3-4 commands to get you querying.

## Flags

| Flag | Effect |
|---|---|
| `--yes` / `-y` | Non-interactive. Accepts all detected defaults: every detected package, no cross-package policies, all three install targets enabled (Claude Code, CI, Docker Neo4j). Useful in automation or CI. |
| `--force` | Overwrite existing scaffolded files. Does NOT overwrite `CLAUDE.md` — that's always appended safely. |
| `--skip-docker` | Write `docker-compose.yml` but don't start the container. Useful when you're running Neo4j on another machine, or using a hosted instance like Neo4j Aura. |
| `--skip-index` | Don't run the first `codegraph index` after scaffolding. Useful when the repo is too big to index on first try, or when you want to customize `.arch-policies.toml` before the first run. |
| `--bolt-port <int>` | Override the default Neo4j Bolt port (default 7688). Stored in `docker-compose.yml` and propagated to all rendered templates (`CLAUDE.md`, `AGENTS.md`, etc.). The default is offset from Neo4j's stock 7687 so codegraph doesn't collide with a developer's own Neo4j instance. |
| `--http-port <int>` | Override the default Neo4j HTTP port (default 7475). Same propagation as `--bolt-port`. Offset from Neo4j's stock 7474 for the same reason. |

## Shared `codegraph-neo4j` container

Every repo on the machine indexes into a single Neo4j container called `codegraph-neo4j`. This is the right model in practice — you can query across repos in Cypher, the indexing pipeline scopes wipe / reload to the configured packages, and you don't pay the disk + RAM cost of N Neo4j instances.

**Init's auto-detect flow** (driven by `find_existing_neo4j_container` in `init.py`):

1. **Container running** → reuse it. Init reads its host-side port mapping (via `docker inspect`) and threads those ports through `config.bolt_port` / `config.http_port` so the rest of init (compose template, readiness probe, first index) talks to the right URL. No `docker compose up` runs; no second container is created.
2. **Container exists but stopped** → `docker start codegraph-neo4j`, then wait for HTTP readiness. If the start fails, init bails with the stderr from Docker.
3. **No `codegraph-neo4j` container** → `docker compose up -d` against the scaffolded `docker-compose.yml`. The compose file uses `container_name: codegraph-neo4j` so subsequent inits in any repo land in the same container.
4. **Port collision (no `codegraph-neo4j` but the bolt port is busy)** → init prints the port number and tells you to re-run with `--bolt-port` / `--http-port` to pick free ones. It does not silently overwrite whatever's on those ports.

Because the container is shared, **`codegraph index --wipe` no longer wipes the entire graph** — it scopes to the configured packages so re-indexing repo A leaves repo B's data untouched. The standalone `codegraph wipe` command keeps its global semantics for an explicit clean slate.

### Docker presence checks

Before any docker subprocess call, init runs a three-way preflight:

- **`docker` not on PATH** → prints an OS-aware install command (`curl -fsSL https://get.docker.com | sh` on Debian/Ubuntu, `brew install --cask docker` on macOS, `winget install Docker.DockerDesktop` on Windows, etc.) and exits 1. Override with `--skip-docker` if you intend to point codegraph at a hosted Neo4j via env vars.
- **Daemon down** (`docker info` fails) → prints the platform-specific start command (`sudo systemctl start docker`, `open -a Docker`, or "launch Docker Desktop"). Exits 1 unless `--skip-docker`.
- **Old version** (< `20.10`) → soft warning with an OS-aware upgrade command. Init continues; the recommended baseline is the cutoff for full `docker compose` v2 support.

The detection logic lives in [`codegraph/codegraph/docker_setup.py`](../codegraph/docker_setup.py) and is pure — it never executes install or upgrade commands automatically (sudo is too risky to automate).

### Custom Neo4j ports

Pass `--bolt-port` / `--http-port` (or set `CODEGRAPH_NEO4J_BOLT_PORT` / `CODEGRAPH_NEO4J_HTTP_PORT`) to bind to ports other than the defaults (7688 / 7475 — offset from Neo4j's stock 7687 / 7474 to avoid colliding with a developer's own Neo4j instance). The chosen ports are baked into `docker-compose.yml`, `CLAUDE.md`, and any subsequently installed platform rules files (`AGENTS.md`, `GEMINI.md`, etc.). When init reuses an existing container, it ignores these flags and uses the container's actual port mapping instead — so your env vars stay accurate.

### Migrating from per-repo containers

Earlier codegraph versions (≤ 0.1.99) created one container per repo (`cognitx-codegraph-<repo>-<8hex>`). After the shared-container refactor, those become orphans. List them and remove by hand:

```bash
docker ps -a --filter "name=cognitx-codegraph-" --format "table {{.Names}}\t{{.Status}}"
docker rm -f $(docker ps -a -q --filter "name=cognitx-codegraph-")
docker volume prune  # reclaim the data volumes
```

Init does *not* migrate data automatically — fresh indexes are cheap (~30s for a 1k-file repo).

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
| `CLAUDE.md` | always (appended) | `$CONTAINER_NAME`, `$NEO4J_BOLT_PORT`, `$NEO4J_HTTP_PORT`, `$PACKAGE_PATHS_FLAGS` |
| `.codegraph-cache/` | added to `.gitignore` | — |

Templates live in `codegraph/codegraph/templates/` and use `string.Template` syntax (stdlib, no Jinja dependency).

The full set of template variables (defined in `init.build_template_vars()`):

- `NEO4J_BOLT_PORT`, `NEO4J_HTTP_PORT` — chosen ports (or the existing container's ports when reusing).
- `CONTAINER_NAME` — `codegraph-neo4j` (shared across every repo on the machine; see [Shared codegraph-neo4j container](#shared-codegraph-neo4j-container)). The legacy `derive_container_name(root)` helper is still exported for callers that want per-repo isolation, but is not used by default.
- `PACKAGE_PATHS_FLAGS` — joined `-p packages/foo -p packages/bar` flags from `codegraph.toml`.
- `DEFAULT_PACKAGE_PREFIX` — first package, used by the `/dead-code` slash command.
- `CROSS_PAIRS_TOML` — cross-package policy block for `.arch-policies.toml`.
- `PIPX_VERSION` — pinned codegraph version for the CI workflow.

## Adding more AI platforms after init

`codegraph init` defaults to installing only Claude Code. To wire codegraph into other agents, run `codegraph install <platform>`:

```bash
codegraph install codex          # writes AGENTS.md
codegraph install cursor         # writes .cursor/rules/codegraph.mdc
codegraph install gemini         # writes GEMINI.md
codegraph install vscode         # writes .github/copilot-instructions.md
codegraph install --all          # detects and installs every platform with a config dir
```

Supported platforms: `claude`, `codex`, `opencode`, `cursor`, `gemini`, `copilot`, `vscode`, `aider`, `claw`, `droid`, `trae`, `kiro`, `antigravity`, `hermes`.

Installs are tracked in `.codegraph/platforms.json`. When you `codegraph uninstall <platform>`, shared rules sections (e.g. an `AGENTS.md` consumed by both Codex and Aider) are preserved if any other installed platform still depends on them. The platform is always removed from the manifest. If you uninstall the last platform sharing a section, the section is removed and the manifest file is cleaned up.

## Troubleshooting

**"Not a git repository"** — run `git init` first. Codegraph needs a git root to locate itself and to scope ownership edges correctly.

**"Docker is not installed"** — the preflight banner prints an OS-aware install command. Follow it, then re-run `codegraph init`. To skip the Docker step entirely (e.g. you have Neo4j running elsewhere), pass `--skip-docker` and point codegraph at the remote URI via `CODEGRAPH_NEO4J_URI`.

**"Docker is installed but the daemon isn't running"** — start it with the printed command (`sudo systemctl start docker` on Linux, `open -a Docker` on macOS, launch Docker Desktop on Windows). Re-run init when the daemon's up.

**"Docker X.Y.Z is installed, but 20.10+ is recommended"** — soft warning. Init continues. Upgrade with the printed command when convenient.

**"Reusing existing codegraph-neo4j container"** — expected on every init after the first one. Init reads the container's host ports via `docker inspect` and uses those for the readiness probe + first index, so you don't have to re-pass `--bolt-port`.

**"Found stopped codegraph-neo4j — starting it…"** — also expected. Init runs `docker start codegraph-neo4j` and waits for HTTP readiness (up to 90s).

**"Neo4j did not become ready in 90s"** — usually a cold image pull on first run. `docker logs codegraph-neo4j` to see what's happening; re-run `codegraph init` once the container's healthy — it skips steps that already completed.

**"Port 7688 (bolt) is already in use — and no codegraph-neo4j container owns it"** — something other than codegraph is holding the port. Find it with `lsof -i :7688` (or `ss -ltnp 'sport = :7688'`), then either stop it or re-run `codegraph init --bolt-port <free-port> --http-port <free-port>`.

**"Old per-repo containers left over"** — earlier codegraph versions created one container per repo (`cognitx-codegraph-<repo>-<8hex>`). They're orphans now. See [Migrating from per-repo containers](#migrating-from-per-repo-containers) for the cleanup commands.

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
