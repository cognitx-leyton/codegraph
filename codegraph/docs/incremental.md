# Incremental indexing

Reference for the four mechanisms codegraph offers to keep the Neo4j graph in sync with the working tree without re-parsing every file. They layer rather than compete: `--update` and `--since` are the two underlying flags on `codegraph index`; `codegraph watch` and `codegraph hook install` are convenience drivers that invoke `codegraph index` with the appropriate flag in response to file-system events or git events.

If you only read one section, read [Choosing between them](#5-choosing-between-them) — the four mechanisms map to four use cases and the wrong choice usually wastes minutes per cycle, not seconds.

---

## 1. `--update` — SHA-256 content-addressed cache

### How it works

`codegraph index . --update` keys a per-file `ParseResult` cache by SHA-256 of file bytes plus the repo-relative path. On every run the indexer rehashes each candidate file; cache hits skip the parse step entirely and feed the cached result straight into the cross-file resolver. Cache misses parse normally and write the new result back into the cache.

### Where the cache lives

Under `<repo>/.codegraph-cache/`:

```
.codegraph-cache/
├── manifest.json              {"version": "<codegraph version>", "files": {rel_path: sha256_hash}}
└── ast/
    ├── <hash1>.json           one cached ParseResult per content hash
    ├── <hash2>.json
    └── ...
```

The hash function (`cache.file_content_hash`) is `sha256(content_bytes || 0x00 || rel_path)`. Including the relative path keeps the cache portable across checkouts: identical bytes at different paths produce different hashes, so the same file mirrored in two trees doesn't collide.

### When entries get pruned

On every successful `--update` run, after writing the new manifest, codegraph computes `stale = old_manifest.values() - new_manifest.values()` and unlinks the corresponding `<hash>.json` files. Pruning is skipped when `--max-files` is set (truncated runs can't tell deletion from "didn't visit").

You'll see this line in the indexer output:

```
cache: 142 hits, 3 misses, 1 deleted, 4 pruned
```

### When the cache is invalidated wholesale

The manifest carries a `"version"` field equal to `codegraph.__version__`. `AstCache.load_manifest` returns an empty dict whenever:

- the manifest file is missing, or
- the JSON is corrupt, or
- the version field doesn't match the current package version.

Any of those conditions causes a cold rebuild: every file is parsed, every entry rewritten under the new version. This is intentional — parser logic changes between releases, and silently reusing stale `ParseResult` objects across versions would corrupt the graph.

### Implications

- `--update` implies `--no-wipe` (forced in `_run_index`).
- `--update` implies `--skip-ownership` (the git-log walk is the slow part of a "warm" run; you can re-add it with a separate full index when you need updated authorship).
- `--update` and `--since` are mutually exclusive — passing both raises `ConfigError`.
- Stale-subgraph cleanup runs after the manifest diff: any file whose hash changed (or whose entry disappeared) has its file subgraph dropped from Neo4j before the upsert. See [the cascade-delete logic](#cascade-delete-mechanics) for what that means structurally.

### `.gitignore` integration

`codegraph init` writes `.codegraph-cache/` to `.gitignore` (creating the file if needed, appending under a `# codegraph` header otherwise). If you didn't run `init`, add it manually — committing the cache is harmless functionally but bloats the repo and pollutes diffs.

### Invocation

```bash
codegraph index . --update
codegraph index . --update --json    # agent-native; single JSON document on stdout
```

---

## 2. `--since <git-ref>` — git-diff incremental mode

### How it works

`git diff --name-status <ref>` is run against the working tree. The output is parsed into two sets:

- `modified` — added, modified, copied, type-changed, or rename-target paths.
- `deleted` — deleted paths and rename-source paths.

Both sets are filtered to file extensions in `_CODE_EXTENSIONS = {.py, .ts, .tsx}`; everything else (markdown, JSON, lockfiles, YAML, configs) is dropped. The indexer then walks every package as usual, but `Neo4jLoader.load(touched_files=changed_files)` restricts every node and edge insertion to the changed set, and `delete_file_subgraph(changed | deleted)` clears stale data first.

### What gets re-indexed

Only files in `modified ∪ deleted`. Cross-file edges are rewritten when **either** endpoint sits in the touched set, so renames and "move method to another file" refactors work correctly without forcing a full reindex.

### Cascade delete mechanics

For every changed-or-deleted path, `Neo4jLoader.delete_file_subgraph` runs three statements (resilient to schema drift — new edge types are auto-handled by `DETACH DELETE`):

1. Grandchildren of owned classes (`Method`, `Endpoint`, `Column`, `GqlOperation`, etc.) — but **not** Class or Decorator (those have cross-file edges).
2. Direct owned children (`Class`, `Function`, `Interface`, `Atom`).
3. The `:File` node itself (`DETACH DELETE` then auto-removes `IMPORTS`, `BELONGS_TO`, etc.).

Then the upsert reinstates everything from the freshly parsed `ParseResult`.

### Implications

- `--since` implies `--no-wipe` and `--skip-ownership`, both forced in `_run_index`.
- If the diff returns no code-file changes, the indexer prints `No changes since <ref>` and exits with empty stats. No Neo4j writes happen.
- The git ref is anything `git diff` accepts: `HEAD~1`, `HEAD~10`, `main`, `origin/main`, a tag (`v0.1.50`), a SHA, a merge-base spec.

### Examples

```bash
codegraph index . --since HEAD~1            # last commit only
codegraph index . --since main              # everything since branching from main
codegraph index . --since v0.1.50           # changes since a release
codegraph index . --since origin/main       # changes since the remote tip
```

---

## 3. `codegraph watch` — filesystem watcher

### Requirements

`pip install "codegraph[watch]"` to pull in `watchdog`. The CLI raises a helpful `ImportError` if the extra is missing.

### How it works

`codegraph watch <repo>` schedules a recursive watchdog observer at `<repo>` and collects changed paths into a set. After each change, a debounce timer restarts; once the timer expires, the accumulated batch is reported and `codegraph index <repo> --since HEAD --json` is launched in a subprocess. The CLI streams a one-line "rebuild complete" log on success.

On macOS the implementation prefers `PollingObserver` over the default FSEvents-based one — FSEvents drops rapid saves under load.

### Debounce window

Default `--debounce` is `3.0` seconds. The watcher checks every 0.5 s whether `(now - last_trigger) >= debounce` and rebuilds when the inequality holds. Set `--debounce` lower for tighter loops, higher to coalesce noisy save bursts.

### What triggers a re-index

Any `on_any_event` from watchdog: writes, moves, creates, deletes. The handler filters to:

- Suffix in `{.py, .ts, .tsx}` (`_WATCHED_EXTENSIONS`).
- No path component starting with `.` (skips `.git/`, `.venv/`, dotfiles).
- No path component in `_EXCLUDE_DIRS = {.git, node_modules, .venv, __pycache__, .mypy_cache, .pytest_cache}`.

### Flags

| Flag | Default | Notes |
|---|---|---|
| `--debounce` | `3.0` | Seconds. |
| `-p` / `--package` | from `codegraph.toml` | Repeatable. Forwarded to the subprocess. |
| `--uri` / `--user` / `--password` | env or defaults | Forwarded. |

### When to use it

Active development, TDD loops, "I want my graph fresh in the editor without thinking about it." The CPU cost is small because the underlying mechanism is `--since HEAD`, which is a tight git diff plus a per-file upsert.

---

## 4. `codegraph hook install` — git hooks

### What gets installed

Two hooks are written into the git hooks directory (which respects `core.hooksPath`, so Husky / pre-commit / lefthook setups don't get clobbered):

- **`post-commit`** — runs `codegraph index . --since HEAD~1 --json` after every commit, silencing output to `/dev/null`. Skips when a rebase / merge / cherry-pick is in flight (`MERGE_HEAD`, `CHERRY_PICK_HEAD`, `rebase-merge/`, `rebase-apply/` markers).
- **`post-checkout`** — runs `codegraph index . --since "$PREV_HEAD" --json` only when `$BRANCH_SWITCH == 1`. File checkouts are skipped (otherwise `git checkout -- foo.py` would re-index).

Both hook bodies start with a portable Python detection block (`_PYTHON_DETECT` in `hooks.py`) that:

1. Looks up `codegraph` on `PATH`, parses the shebang, and validates the interpreter can `import codegraph`.
2. Falls back to `python3` then `python` from `PATH`.
3. Exits 0 silently if no working interpreter is found — a missing codegraph install **never blocks a commit**.

### Idempotency

```bash
codegraph hook install     # writes both hooks; appends to existing if present, marked with begin/end sentinels
codegraph hook status      # "post-commit: installed" / "post-checkout: installed"
codegraph hook uninstall   # removes only the codegraph block; preserves other hook content
```

The install is detected by the literal markers `# codegraph-hook-start` / `# codegraph-checkout-hook-start`. Running `install` twice is a no-op (`already installed at <path>`).

### When to use it

Lower-CPU than `watch`. Runs only on commit and branch switch, not on every save. Right answer for "I want the graph current when I push but I don't need it current while I'm typing." Pairs well with `--update` for CI: the hook keeps local state warm, CI uses the cache for fast warm rebuilds.

---

## 5. Choosing between them

| Use case | Best mechanism |
|---|---|
| One-off update on a feature branch | `codegraph index . --since main` |
| Active editing (TDD loop, big refactor) | `codegraph watch` |
| Long-running repo, indexed in CI | `codegraph index . --update` (cache survives across CI runs if `.codegraph-cache/` is restored from a build cache step) |
| Local dev, low ceremony, "fire and forget" | `codegraph hook install` |
| First time on a new clone | `codegraph index .` (no flags — full cold build, populates the cache) |

The mechanisms aren't exclusive. The most common production setup is: `hook install` locally + `--update` in CI + `watch` during long sessions.

---

## 6. Cache layout and edge cases

### What's stored

`.codegraph-cache/` only ever contains `manifest.json` and `ast/<hash>.json` files (one cached `ParseResult` per content hash). No intermediate Neo4j state, no graph dumps, no logs. It's safe to delete the directory at any time — the next run rebuilds it.

### What happens on `--wipe`

The default `codegraph index` (no `--update`, no `--since`) runs with `wipe=True`, which `DETACH DELETE`s every node and relationship in Neo4j. **The on-disk cache is untouched** — `--wipe` only affects Neo4j. So `codegraph index . && codegraph index . --update` is a valid two-step "reset Neo4j, then go incremental" workflow.

### How to nuke and rebuild

If you suspect cache corruption or want a guaranteed clean rebuild from scratch:

```bash
rm -rf .codegraph-cache/
codegraph index . --wipe        # cold rebuild, fills the cache from scratch
```

`AstCache.clear()` does the same thing programmatically (deletes every `*.json` and `*.tmp` under `ast/`, plus the manifest), but it's not exposed on the CLI today — use `rm -rf`.

### Atomicity

Both `manifest.json` and individual cache entries are written via temp-file-then-`os.replace`. A crash mid-write leaves either the old file or the new file; never a half-written one.

---

## 7. Performance characteristics

| Mode | Parse cost | Load cost | Typical wall time on the codegraph repo (~22 files) |
|---|---|---|---|
| Cold (no flags) | O(files) | O(edges) | ~5 s |
| `--update` warm (no edits) | O(files) hash + 0 parse | O(0) Neo4j writes when nothing changed | ~1 s |
| `--update` warm (5 edits) | O(files) hash + O(5) parse | O(5 file subgraphs) cascade-delete + upsert | ~2 s |
| `--since HEAD~1` (5 edits) | O(5) parse | O(5 file subgraphs) cascade-delete + upsert | ~2 s |

`--update` rehashes everything on every run, so its floor is "one stat + one read per file." `--since` skips the rehash but pays a `git diff` (cheap) and can miss changes that aren't committed (since git only sees commits, not the working tree dirty state — be aware of this when chaining with the watcher; the watcher uses `--since HEAD` which on a dirty tree still points at the last-committed state).

---

## 8. Troubleshooting

**"Stale graph after a refactor"** — Nuke and rebuild: `codegraph index . --wipe`. The cache survives, Neo4j is rewritten from current parse output.

**"Cache appears corrupt"** — `rm -rf .codegraph-cache/` and re-run `codegraph index . --update`. The cache is fully reproducible from source.

**"Hook fires but graph isn't updating"** — Run `codegraph hook status` first. If both hooks show "installed," check that `.git/hooks/post-commit` actually exists (`core.hooksPath` may have moved them — see [What gets installed](#what-gets-installed)). Then run the hook body manually: `bash .git/hooks/post-commit` after a real commit. If the embedded `_PYTHON_DETECT` block can't find a working `codegraph` interpreter, the hook silently exits 0 — install codegraph into the same environment your shell uses.

**"Watch loops on its own outputs"** — Confirm `.codegraph-cache/` is in `.gitignore`. The watcher already filters dotfiles via `any(part.startswith(".") for part in path.parts)`, so cache writes shouldn't trigger it, but if a different output directory is being written (e.g. `codegraph-out/`) and isn't dotted, the watcher will see it. Either move the output to a dotted directory or extend `_EXCLUDE_DIRS` in `watch.py`.

**"`--since` says 'No changes' but I edited files"** — `git diff` only sees committed state by default. Uncommitted edits don't show up in `git diff <ref>` unless you use `git diff` with no ref or pass a ref older than your working state. Commit, then re-run; or use `--update` (which sees on-disk content directly via SHA-256).

**"Cache version mismatch on every run"** — `AstCache.load_manifest` returns `{}` when the manifest's `version` field doesn't match `codegraph.__version__`. If you're seeing 0 cache hits after a `pip install -U codegraph`, that's expected — the first warm run after an upgrade is a cold rebuild.

---

## See also

- [`README.md`](../README.md#incremental-indexing) — the two-paragraph summary.
- [`codegraph/cache.py`](../codegraph/cache.py) — the cache implementation.
- [`codegraph/cli.py`](../codegraph/cli.py) — `_run_index` orchestrates `--update` / `--since`.
- [`codegraph/loader.py`](../codegraph/loader.py) — `delete_file_subgraph` + `touched_files` upsert.
- [`codegraph/watch.py`](../codegraph/watch.py) — debounced watchdog wrapper.
- [`codegraph/hooks.py`](../codegraph/hooks.py) — git hook install / uninstall / status.
