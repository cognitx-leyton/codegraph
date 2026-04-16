---
allowed-tools: Bash(codegraph query:*), Bash(codegraph query:*), Bash(.venv/bin/codegraph query:*)
description: Show the latest author, top contributors, and CODEOWNERS team for a file
---

## Usage

```
/who-owns <path>
```

Path must match `:File.path` exactly — repo-root-relative with forward slashes (e.g. `codegraph/codegraph/loader.py`, not absolute, not with a leading `./`).

Joins three ownership edges written by the Phase-7 ownership pass:

| Edge | Source | Columns |
|---|---|---|
| `LAST_MODIFIED_BY` | most-recent commit from `git log` | author name, email, timestamp |
| `CONTRIBUTED_BY` | all authors for the file, with commit counts | roll-up of top 5 |
| `OWNED_BY` | `CODEOWNERS` file | team name(s) |

## What this does

```bash
codegraph query "
MATCH (f:File {path: '$ARGUMENTS'})
OPTIONAL MATCH (f)-[lm:LAST_MODIFIED_BY]->(last:Author)
OPTIONAL MATCH (f)-[c:CONTRIBUTED_BY]->(co:Author)
OPTIONAL MATCH (f)-[:OWNED_BY]->(t:Team)
WITH f, last, lm, t, co, c
ORDER BY c.commits DESC
WITH f,
     last,
     lm,
     collect(DISTINCT t.name) AS teams,
     collect({author: co.name, email: co.email, commits: c.commits})[..5] AS top_contributors
RETURN f.path AS file,
       last.name AS last_modified_by,
       last.email AS last_email,
       lm.at AS last_modified_at,
       teams,
       top_contributors
"
```

## Caveats

- **Requires ownership indexing.** `/graph-refresh` runs with `--skip-ownership` by default (it's ~30s slower with it). If `last_modified_by` comes back null and `top_contributors` is `[{author: null, ...}]`, re-index without the flag:
  ```bash
  codegraph index . -p codegraph/codegraph -p codegraph/tests --no-wipe
  ```
- **`CODEOWNERS` must be present.** If the repo has no `CODEOWNERS` file (or `.github/CODEOWNERS` / `docs/CODEOWNERS`), the `teams` column will be empty. That's not a bug — it's the absence of team-level ownership metadata.
- **Path has to match exactly.** Use `/graph "MATCH (f:File) WHERE f.path CONTAINS 'loader' RETURN f.path"` if you're not sure of the stored path.
- **Author email is the join key** (`CREATE CONSTRAINT author_email ... UNIQUE`). If the same person commits under multiple emails, they appear as separate authors.

## After running

If `top_contributors` lists the same 1-2 people across many files, that's your bus-factor risk. If `teams` is empty on a file that *should* be owned, update `CODEOWNERS` and re-index.
