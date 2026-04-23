# Architecture-Conformance Policies

Reference for the five built-in policies run by `codegraph arch-check` and the `/arch-check` slash command. Each section covers: what the policy detects, why the invariant matters, the exact Cypher, how to interpret a violation, and common false positives.

If a policy fires on your PR and you believe it shouldn't, read the "False positives" subsection first — most violations are either load-bearing bugs or one of the known noise patterns, and the doc flags which is which.

---

## 1. `import_cycles`

### What it detects

File-level import cycles of length 2-6. A cycle is a sequence of `:File` nodes connected by `:IMPORTS` edges that returns to its starting point:

```cypher
MATCH path = (a:File)-[:IMPORTS*2..6]->(a)
RETURN [n IN nodes(path) | n.path] AS cycle, length(path) AS hops
```

### Why it matters

Import cycles make modules untestable in isolation, break tree-shaking, and pin code into tight coupling that's expensive to split later. In Python they cause `ImportError` when the cycle is forced into different import orders; in TypeScript they silently turn exports into `undefined` at load time. Either way: they're almost never intentional.

### Interpreting a violation

Each row in the sample lists one cycle as a path: `["a.py", "b.py", "a.py"]` means `a.py` imports `b.py`, which imports `a.py`. The `hops` column is the cycle length — short cycles (2 hops, direct A↔B) are usually easier to break than long ones (3+ hops, fan through multiple modules).

**Typical resolutions**:
- Extract the shared types / constants into a new leaf module both can import
- Invert the dependency direction (dependency injection, event emitter, callback)
- Merge the two modules if they're genuinely that coupled

### False positives

- **Re-export barrels**: `__init__.py` / `index.ts` files that re-export symbols from the module directory can form cycles with their submodules. Indexer treats them as first-class files; the cycle is real but mostly harmless. Consider refactoring to a dedicated barrel (`_exports.py`) that doesn't import from the submodules.
- **Conditional imports under `if TYPE_CHECKING:`**: the parser records these as regular imports. If the cycle only exists at type-check time (never at runtime), it's less urgent — but still worth refactoring since the types are coupled.

---

## 2. `cross_package`

### What it detects

Imports that cross a forbidden package boundary. The default pair (configured in `.arch-policies.toml`) is:

```toml
[[policies.cross_package.pairs]]
importer = "twenty-front"
importee = "twenty-server"
```

Any `:File` in `twenty-front` that imports from `:File` in `twenty-server` is a violation:

```cypher
MATCH (a:File)-[:IMPORTS]->(b:File)
WHERE a.package = 'twenty-front' AND b.package = 'twenty-server'
RETURN a.path AS importer, b.path AS importee
```

### Why it matters

Frontend and backend have different runtimes, different bundlers, different security models. Importing backend code into the frontend either breaks the build or (worse) leaks server-only secrets into the client bundle. The rule is a hard boundary — if you need to share something, extract it to a shared package (`twenty-types`, `twenty-shared`).

### Extending the rule set

Add pairs to `[policies.cross_package]` in `.arch-policies.toml`:

```toml
[policies.cross_package]
enabled = true
pairs = [
  { importer = "twenty-front",      importee = "twenty-server" },
  { importer = "packages/docs",     importee = "packages/twenty-server" },   # docs must not import from app
  { importer = "packages/twenty-types", importee = "packages/twenty-server" },  # shared types must be leaf
]
```

Every pair becomes an additional violation bucket. The report aggregates them so CI output stays compact. See [Configuring policies](#configuring-policies--arch-policiestoml) for the full schema.

### Interpreting a violation

`importer` is the file that broke the rule; `importee` is the file it shouldn't have reached. `importer_package` / `importee_package` tell you which boundary was crossed (useful once you have multiple rules).

**Typical resolutions**:
- Move the needed symbol into a shared leaf package both sides can import from
- Duplicate the constant or type (if it's small and stable — accept the minor drift cost)
- Replace the direct import with an HTTP call if the boundary is actually runtime, not build-time

### False positives

- **Auto-generated files**: a codegen step that writes generated types into the wrong package directory can trip this. Either fix the codegen target dir, or exclude generated files by `path` pattern before indexing.
- **Monorepo tooling**: if Turborepo / Nx / Lerna creates symlinks between packages, the indexer may follow them. Check that your `.codegraphignore` excludes `node_modules` and symlink-dense directories.

---

## 3. `layer_bypass`

### What it detects

Controllers that reach a `*Repository` method within 3 hops of `CALLS` without traversing a `*Service`:

```cypher
MATCH (ctrl:Controller)-[:HAS_METHOD]->(m:Method)-[:CALLS*1..3]->(target:Method)
MATCH (repo:Class)-[:HAS_METHOD]->(target)
WHERE repo.name ENDS WITH 'Repository'
  AND NOT EXISTS {
    MATCH (ctrl)-[:HAS_METHOD]->(:Method)-[:CALLS*1..3]->(:Method)<-[:HAS_METHOD]-(svc:Class)
    WHERE svc.name ENDS WITH 'Service'
  }
RETURN ctrl.name AS controller, repo.name AS repository, target.name AS method
```

### Why it matters

The Controller → Service → Repository layering is the default pattern in NestJS and most backend frameworks for a reason. Services are where business rules, validation, transaction boundaries, and cross-cutting concerns (auditing, caching, authorization) live. When a Controller talks to a Repository directly, all of that is bypassed — and the bypass usually stays hidden until someone needs to add one of those concerns and has to audit every call site.

### Interpreting a violation

`controller` is the class with a HAS_METHOD → CALLS chain into a Repository. `repository` is which Repository it reached. `method` is the specific repo method called. The violation is "controller X short-circuits directly to repo Y to call Z".

**Typical resolutions**:
- Introduce a `*Service` between the Controller and the Repository if one doesn't exist
- Move the call site from the Controller into an existing Service
- If the Controller really does need direct Repository access (e.g. a health-check endpoint reading `_metadata`), document it explicitly and either suppress by renaming or refine the policy

### False positives

- **Naming-convention-only detection**: this policy is a name-based heuristic. A project using `*Manager`, `*Handler`, or `*Facade` as its service layer won't match the `ENDS WITH 'Service'` check. Fork the module and rename to match.
- **Health checks / liveness probes**: a Controller calling `repository.countAll()` to prove the DB is reachable is a legitimate bypass. Consider renaming the repository method (`__healthcheck_countAll`), moving the check into a dedicated `HealthService`, or excluding that Controller by name.
- **Pure read endpoints with no business rules**: if an endpoint genuinely does nothing but read and return, inserting a pass-through Service adds ceremony without value. Accept the one-off violation or relax the policy to only fire on write operations.

---

## 4. `coupling_ceiling`

### What it detects

Files with more than N distinct file-level imports. A file that `:IMPORTS` many other files has high fan-out — it depends on a wide surface area and is likely a coupling magnet:

```cypher
MATCH (f:File)-[:IMPORTS]->(g:File)
WITH f, count(g) AS deps
WHERE deps > $threshold
RETURN f.path AS file, deps
ORDER BY deps DESC
```

### Why it matters

High fan-out files are expensive: every change to any of their dependencies is a potential break. They're hard to test in isolation, hard to move between packages, and hard to reason about. They tend to accumulate more imports over time (gravity effect) because "it already imports everything, so let's add one more". Catching them early — before they cross 20-30 imports — is much cheaper than untangling them later.

### Interpreting a violation

`file` is the path of the offending file. `deps` is how many distinct files it imports. The violation is "this file depends on `deps` other files, which exceeds the configured ceiling of `max_imports`".

**Typical resolutions**:
- Split the file into smaller, focused modules with narrower dependency sets
- Extract a facade or mediator that aggregates the imports, so consumers depend on the facade instead of N direct imports
- Check if some imports are unused and can be removed (the indexer counts all `import` statements, including dead ones)
- For barrel / re-export files (`__init__.py`, `index.ts`), consider raising the threshold or disabling the policy for that specific file pattern via a custom policy override

### Configuration

```toml
[policies.coupling_ceiling]
enabled     = true   # false disables this policy entirely
max_imports = 20     # flag files with more than this many distinct IMPORTS edges
```

Default threshold is 20. Raise it for large monorepo roots or barrel files; lower it for microservice repos where tight coupling matters more.

### False positives

- **Barrel / re-export files**: `__init__.py` and `index.ts` files exist to re-export symbols from submodules. A package `__init__.py` that re-exports 25 submodules will trip the default threshold, but that's its job. Raise `max_imports` or disable the policy if your project relies on deep barrel files.
- **Test files**: integration test files often import many modules under test plus fixtures. They're not production coupling magnets. Consider raising the threshold or adding a custom policy that excludes `tests/` paths.
- **Generated files**: auto-generated code (e.g. GraphQL resolvers, ORM models) can legitimately import many dependencies. Exclude them via `.codegraphignore` before indexing.

---

## 5. `orphan_detection`

### What it detects

Functions, classes, atoms, and endpoints with zero inbound references — symbols that nothing in the graph calls, extends, imports, or handles. Framework entry points (anything with a `DECORATED_BY` edge) are excluded automatically.

Four orphan categories are checked:

| Kind | What it means |
|---|---|
| `orphan_function` | `:Function` with no incoming `CALLS` / `RENDERS` and no outgoing `DECORATED_BY` (not a Typer / MCP / pytest entry point) |
| `orphan_class` | `:Class` with no incoming `EXTENDS`, `INJECTS`, `RESOLVES`, or `IMPORTS_SYMBOL` |
| `orphan_atom` | `:Atom` with no `READS_ATOM` or `WRITES_ATOM` consumers (React state defined but never used) |
| `orphan_endpoint` | `:Endpoint` with no `HANDLES` method (route declared but unhooked) |

### Why it matters

Dead code is a maintenance tax: it confuses readers, inflates bundle sizes, and drifts silently until someone tries to refactor around it. Catching orphans at PR time — rather than during periodic cleanup — prevents accumulation and keeps the codebase honest. The `/dead-code` slash command has always been available for advisory scans; this policy makes the same check a merge gate.

### Configuration

```toml
[policies.orphan_detection]
enabled     = true                                       # false disables entirely
path_prefix = ""                                         # scope to a sub-path (e.g. "src/core/")
kinds       = ["function", "class", "atom", "endpoint"]  # which categories to check
```

- **`path_prefix`**: when non-empty, only symbols whose `file` starts with this prefix are scanned. Useful for focusing on a specific package in a monorepo.
- **`kinds`**: choose which orphan categories to enforce. For example, a pure backend project with no React state can set `kinds = ["function", "class", "endpoint"]` to skip atom checks.

### Interpreting a violation

Each row in the sample has three columns: `kind` (which category), `name` (the symbol name), and `file` (where it's defined). The violation means "this symbol has no consumer in the graph".

**Typical resolutions**:
- Delete the dead symbol if it's genuinely unused
- Add the missing caller, import, or wiring that should reference it
- If the symbol is a legitimate entry point invoked via reflection or external dispatch (e.g. registered in `pyproject.toml [console_scripts]`), add a decorator so it gets a `DECORATED_BY` edge

### False positives

- **Decorator exclusion is broad**: any function with *any* decorator (`@staticmethod`, `@property`, `@dataclass`, etc.) is excluded, not just framework entry points. This is intentionally conservative — it may hide a genuinely dead decorated function, but it eliminates most false positives from framework dispatchers.
- **Protocol / duck-typed implementations**: a class that satisfies a protocol without an explicit `EXTENDS` edge (no `class Foo(Protocol)` base) will show as `orphan_class`. Use `/graph` to double-check inheritance.
- **CLI entry points in `pyproject.toml`**: functions registered as `[console_scripts]` or `[gui_scripts]` entry points aren't in the graph. They'll appear as orphans unless they also have a decorator.

---

## Configuring policies — `.arch-policies.toml`

Every policy (built-in or custom) is tunable via a `.arch-policies.toml` file at the repo root. Missing file → all built-in defaults. `codegraph init` scaffolds a starter template.

Full schema:

```toml
[meta]
schema_version = 1   # required in future versions; omit for v1 (backwards compatible)

# ── Built-in policies: tune or disable ─────────────────────────

[policies.import_cycles]
enabled  = true   # false disables this policy entirely
min_hops = 2      # minimum cycle length (must be >= 2)
max_hops = 6      # maximum cycle length to detect

[policies.cross_package]
enabled = true
pairs = [
  { importer = "apps/web",    importee = "apps/api" },
  { importer = "packages/ui", importee = "packages/server" },
]

[policies.layer_bypass]
enabled           = true
controller_labels = ["Controller"]   # Neo4j labels to match as controllers
repository_suffix = "Repository"      # class name suffix for repos
service_suffix    = "Service"         # class name suffix for the required intermediate layer
call_depth        = 3                  # max CALLS hops to traverse

[policies.coupling_ceiling]
enabled     = true   # false disables this policy entirely
max_imports = 20     # flag files importing more than this many distinct files

[policies.orphan_detection]
enabled     = true                                       # false disables entirely
path_prefix = ""                                         # scope to a sub-path (e.g. "src/core/")
kinds       = ["function", "class", "atom", "endpoint"]  # which categories to check

# ── Custom policies: user-authored Cypher ──────────────────────

[[policies.custom]]
name          = "no_fat_files"
description   = "Files over 500 LOC"
count_cypher  = "MATCH (f:File) WHERE f.loc > 500 RETURN count(f) AS v"
sample_cypher = "MATCH (f:File) WHERE f.loc > 500 RETURN f.path AS file, f.loc AS loc LIMIT $limit"
enabled       = true   # optional, defaults to true

[[policies.custom]]
name          = "no_dead_endpoints"
description   = "Endpoints without a HANDLES method"
count_cypher  = "MATCH (e:Endpoint) WHERE NOT EXISTS { (:Method)-[:HANDLES]->(e) } RETURN count(e) AS v"
sample_cypher = "MATCH (e:Endpoint) WHERE NOT EXISTS { (:Method)-[:HANDLES]->(e) } RETURN e.path AS route LIMIT $limit"
```

### Rules
- Every section is optional. Omit to use defaults.
- Every `count_cypher` must return a single row with column `v` containing an integer ≥ 0.
- Every `sample_cypher` should use `LIMIT $limit` — the `$limit` parameter is injected automatically from `settings.sample_limit` (default 10). Avoid hardcoding a LIMIT integer; it will cap results below `sample_limit` and trigger a deprecation warning. A `$scope` parameter (list of path prefixes, empty when unscoped) is also available for queries that need to respect `--scope`.
- Custom policy names must be unique and must not collide with built-in names (`import_cycles`, `cross_package`, `layer_bypass`, `coupling_ceiling`, `orphan_detection`).
- Malformed TOML or invalid fields → exit code 2 with a clear error message (not exit code 1, which means policy violations).

### Schema versioning

The `[meta]` section carries metadata about the config file itself. Currently the only field is `schema_version`:

- **Omitted or `1`**: current schema, fully supported.
- **Greater than supported**: `codegraph arch-check` exits with code 2 and a message telling you which codegraph version to upgrade to.
- **`0` or negative**: rejected as invalid.

Existing `.arch-policies.toml` files without `[meta]` continue to work — they're treated as version 1.

### Worked examples by repo shape

**Full-stack monorepo (Next.js + NestJS)** — front must never import from server:
```toml
[policies.cross_package]
pairs = [
  { importer = "apps/web", importee = "apps/server" },
]
```

**Pure Python service** — no NestJS controllers, disable the layer-bypass policy:
```toml
[policies.layer_bypass]
enabled = false

[[policies.custom]]
name          = "no_views_calling_models_directly"
description   = "Django views should go through a service"
count_cypher  = "MATCH (:Class {name:'View'})-[:HAS_METHOD]->(:Method)-[:CALLS]->(:Method)<-[:HAS_METHOD]-(m:Class) WHERE m.name ENDS WITH 'Model' RETURN count(m) AS v"
sample_cypher = "MATCH (v:Class {name:'View'})-[:HAS_METHOD]->(:Method)-[:CALLS]->(:Method)<-[:HAS_METHOD]-(m:Class) WHERE m.name ENDS WITH 'Model' RETURN v.name AS view, m.name AS model LIMIT $limit"
```

**Shared types package** — must be leaf (no outbound imports to any app):
```toml
[policies.cross_package]
pairs = [
  { importer = "packages/types", importee = "apps/web" },
  { importer = "packages/types", importee = "apps/server" },
  { importer = "packages/types", importee = "services/worker" },
]
```

## Suppression — accepted violations

Sometimes a violation is known, understood, and deliberately accepted as technical debt. Rather than disabling an entire policy, you can suppress individual violations by adding `[[suppress]]` entries to `.arch-policies.toml`. Each suppression requires a reason so the rationale doesn't get lost.

### TOML syntax

```toml
[[suppress]]
policy = "import_cycles"
key    = "src/lib/coordinatesUtils.ts -> src/lib/fieldValidation.ts"
reason = "Mutual dependency is intentional — shared geometric types"

[[suppress]]
policy = "coupling_ceiling"
key    = "src/App.tsx"
reason = "Root component, fan-out is expected"

[[suppress]]
policy = "orphan_detection"
key    = "orphan_function:legacy_helper"
reason = "Called via eval in migration script"

[[suppress]]
policy = "layer_bypass"
key    = "HealthController -> MetricsRepository.count"
reason = "Health check endpoint, no business logic needed"

[[suppress]]
policy = "cross_package"
key    = "apps/web/src/shared.ts -> apps/api/src/types.ts"
reason = "Shared type import, pending extraction to packages/types"
```

### Key format reference

Each policy uses a different key format to identify the specific violation:

| Policy | Key format | Example |
|---|---|---|
| `import_cycles` | Edge: `"fileA -> fileB"` | `"src/a.ts -> src/b.ts"` |
| `cross_package` | `"importer_path -> importee_path"` | `"apps/web/x.ts -> apps/api/y.ts"` |
| `layer_bypass` | `"Controller -> Repository.method"` | `"UserCtrl -> UserRepo.find"` |
| `coupling_ceiling` | File path | `"src/App.tsx"` |
| `orphan_detection` | `"kind:name"` | `"orphan_function:dead_fn"` |
| Custom policies | All sample row values joined by ` \| ` | `"big.py \| 999"` |

For `import_cycles`, the key is an **edge** (`"A -> B"`), not the full cycle path. If the edge `A -> B` appears as a consecutive pair in any detected cycle, that cycle is suppressed. This avoids issues with cycle rotation and lets you target the specific dependency you've accepted.

### Behaviour

- **Exit code**: `codegraph arch-check` exits 0 when all remaining (unsuppressed) violations are resolved. Suppressed violations do not count as failures.
- **Visibility**: suppressed violations are printed as `WARN` (yellow) in the table and listed after the failure details so they don't disappear silently.
- **Stale detection**: if a suppression entry no longer matches any current violation (the code was fixed or the violation changed shape), it is flagged as stale at the bottom of the report. This encourages cleanup — remove stale entries to keep the config honest. A typo in `policy` (e.g. `"import_cycle"` instead of `"import_cycles"`) will also appear as stale — double-check the policy name if a suppression shows up as stale unexpectedly.
- **Sample window**: suppressions are matched against the violation sample (first 10 rows). When a policy reports more violations than the sample window, only violations visible in the sample can be suppressed. To reliably suppress all violations of a pattern, ensure the total violation count matches the number of suppressions.
- **JSON output**: `suppressed_count` and `suppressed_sample` appear per policy; `stale_suppressions` appears at the top level of the JSON report.

### Required fields

Every `[[suppress]]` entry must have all three fields:

- `policy` — non-empty string naming the policy (built-in or custom). The name is not validated against known policies at parse time — a typo will appear as a stale suppression at report time.
- `key` — non-empty string identifying the specific violation.
- `reason` — non-empty string explaining why this violation is accepted.

Missing or empty fields → exit code 2 (config error).

---

## Scoping to specific packages

When multiple codebases share a Neo4j instance (common with `codegraph index --no-wipe`), use `--scope` to restrict policies to the packages you indexed:

```bash
codegraph arch-check --scope codegraph/codegraph --scope codegraph/tests
```

Each `--scope` value is a path prefix matched against node `file`/`path` properties. Only nodes whose path starts with at least one prefix are included in policy queries. Omitting `--scope` queries the entire graph (original behaviour).

**Interaction with `orphan_detection.path_prefix`**: if `path_prefix` is set in `.arch-policies.toml`, it takes precedence over `--scope` for orphan detection. If `path_prefix` is empty (default), `--scope` is used instead.

**Custom policies**: `--scope` does not apply to `[[policies.custom]]` — custom Cypher is user-authored, so add your own `WHERE` clauses if needed.

---

## Exit codes

`codegraph arch-check` returns:
- **0** — every policy passed.
- **1** — one or more policies reported violations.
- **2** — `.arch-policies.toml` is malformed or semantically invalid.

CI job fails on any non-zero exit. The `arch-report.json` artifact is always uploaded on violations (exit 1); config errors (exit 2) are surfaced in the step log.

## Adding a policy you can't express in the built-ins

1. **First try a custom policy** — `[[policies.custom]]` with raw Cypher. Covers ~80% of real extensions.
2. **If Cypher isn't enough** — fork `codegraph/codegraph/arch_check.py`, add a new `_check_<name>(driver, cfg)` function, wire it into `_run_all`. Worth it when the policy needs multi-step state (e.g. cross-query aggregation, custom sampling) or Python logic that doesn't round-trip through Cypher.
