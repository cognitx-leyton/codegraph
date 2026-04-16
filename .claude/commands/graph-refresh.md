---
allowed-tools: Bash(codegraph/.venv/bin/codegraph index:*), Bash(.venv/bin/codegraph index:*), Bash(codegraph index:*)
description: Re-index the codegraph Python package so /graph queries reflect the latest on-disk state
---

## Why

codegraph is a static snapshot of the codebase at index time. Edits after indexing don't show up in the graph until you re-index. Run this command after any **structural** change — adding/removing classes, functions, methods, imports, decorators; renaming; moving files. For cosmetic edits (comment changes, reformatting), it's not necessary.

## What this does

Re-parses every `.py` file under `codegraph/codegraph/` and `codegraph/tests/` and upserts nodes / edges into Neo4j. **Does not wipe the rest of the graph** — Twenty (or any other indexed TS repos) stays untouched. Typical runtime: ~5 seconds for both packages.

```bash
codegraph/.venv/bin/codegraph index \
    /home/edouard-gouilliard/Obsidian/SecondBrain/Personal/projects/graphrag-code \
    -p codegraph/codegraph \
    -p codegraph/tests \
    --no-wipe \
    --skip-ownership
```

`--no-wipe` keeps other graphs alive. `--skip-ownership` skips the git-log pass (faster; owners can be added back later if needed).

## After running

Re-run any `/graph` queries you had open — results should reflect the latest code. If something unexpected disappeared, it's more likely a parser edge case than a data loss: check the AST of the file in question, or open an issue.

## Indexing a different repo

To point the graph at some other TS / Python repo:

```bash
codegraph/.venv/bin/codegraph index /path/to/repo -p <package>
```

Drop `--no-wipe` if you want to start from a clean graph (wipes everything, including the codegraph + Twenty snapshots).
