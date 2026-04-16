---
allowed-tools: Bash(codegraph index:*), Bash(.venv/bin/codegraph index:*), Bash(codegraph index:*)
description: Re-index your repo so /graph queries reflect the latest on-disk state
---

## Why

codegraph is a static snapshot of the codebase at index time. Edits after indexing don't show up in the graph until you re-index. Run this command after any **structural** change — adding/removing classes, functions, methods, imports, decorators; renaming; moving files. For cosmetic edits (comment changes, reformatting), it's not necessary.

## What this does

Re-parses every source file under the configured packages and upserts nodes / edges into Neo4j. **Does not wipe the rest of the graph** — other indexed repos survive. Typical runtime: ~5 seconds for a medium package.

```bash
codegraph index . $PACKAGE_PATHS_FLAGS --no-wipe --skip-ownership
```

`--no-wipe` keeps other graphs alive. `--skip-ownership` skips the git-log pass (faster; owners can be added back later if needed).

## After running

Re-run any `/graph` queries you had open — results should reflect the latest code. If something unexpected disappeared, it's more likely a parser edge case than a data loss: check the AST of the file in question, or open an issue.

## Indexing a different repo

To point the graph at some other TS / Python repo:

```bash
codegraph index /path/to/repo -p <package>
```

Drop `--no-wipe` if you want to start from a clean graph (wipes everything in the Neo4j database).
