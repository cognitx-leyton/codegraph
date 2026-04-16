---
allowed-tools: Bash(codegraph query:*), Bash(codegraph query:*), Bash(.venv/bin/codegraph query:*)
description: Run built-in architecture-conformance policies — cycles, cross-package imports, layer violations
---

## Usage

```
/arch-check
```

No args. Runs three built-in policies and reports violations. Zero violations = architecture still holds. Non-zero = investigate.

| Policy | What it detects |
|---|---|
| **Import cycles** | File `IMPORTS` paths of length 2-6 that loop back to the start |
| **Cross-package imports** | `twenty-front` importing from `twenty-server` (front/back boundary) |
| **Controller → Repository bypass** | Controllers that call Repository methods within 3 hops without going through a `*Service` class — skips the service layer |

Each policy is an independent Cypher block. To extend the default policy set, edit this file and add a new block following the pattern.

## What this does

```bash
echo "=== Policy 1: file-level IMPORTS cycles ==="
codegraph query "
MATCH path = (a:File)-[:IMPORTS*2..6]->(a)
RETURN [n IN nodes(path) | n.path] AS cycle,
       length(path) AS hops
ORDER BY hops ASC
LIMIT 10
"

echo ""
echo "=== Policy 2: cross-package boundary (twenty-front -> twenty-server) ==="
codegraph query "
MATCH (a:File)-[:IMPORTS]->(b:File)
WHERE a.package = 'twenty-front' AND b.package = 'twenty-server'
RETURN a.path AS importer, b.path AS importee
LIMIT 10
"

echo ""
echo "=== Policy 3: Controller -> Repository bypass (skips *Service) ==="
codegraph query "
MATCH (ctrl:Controller)-[:HAS_METHOD]->(m:Method)-[:CALLS*1..3]->(target:Method)
MATCH (repo:Class)-[:HAS_METHOD]->(target)
WHERE repo.name ENDS WITH 'Repository'
  AND NOT EXISTS {
    MATCH (ctrl)-[:HAS_METHOD]->(:Method)-[:CALLS*1..3]->(:Method)<-[:HAS_METHOD]-(svc:Class)
    WHERE svc.name ENDS WITH 'Service'
  }
RETURN ctrl.name AS controller, repo.name AS repository, target.name AS method
LIMIT 10
"
```

## Caveats

- **Policies are project-specific.** The default set is tuned for this repo (codegraph) + Twenty. A fresh repo with different conventions will see either false positives or zero coverage. Rewrite the policies in this file — it's designed to be forked.
- **Cycle bound is `*2..6`.** Very long cycles (depth > 6) won't be detected. If you suspect one, raise the upper bound (slower query).
- **The Controller→Repository check is a heuristic.** It relies on naming convention (`*Service`, `*Repository`). Projects that use different names need to edit the `ENDS WITH` clauses.
- **Python coverage is limited.** No `:Controller` label for Python yet (NestJS-only in Stage 1). Policy 3 is effectively TS-only.

## After running

Treat each violation as a conversation, not a blocker. Some cycles are intentional (tight-coupled modules that refactoring would make worse). Some cross-package imports are bridges (e.g. shared types). Read the output, then decide whether to fix the code or refine the policy.

## Extending the policy set

Add a new policy by appending an `echo` header + `codegraph query` block. Keep each policy focused on a single invariant. Examples of policies worth adding:

- "No file may have more than 15 distinct IMPORTS" (coupling ceiling)
- "Every `:Entity` class must have at least one `:Column`" (ORM completeness)
- "No `:Endpoint` may exist without a matching `HANDLES` method" (dead routes — also caught by `/dead-code`)
- "Shared-types package must not import from any app package" (dependency-direction)

## CI integration

The same three policies also run as `codegraph arch-check` — a first-class CLI subcommand that exits non-zero on any violation and emits a JSON report with `--json`. That's the authoritative runner; this slash command is the interactive convenience wrapper. Both hit the same Cypher, so there's no logic drift.

`.github/workflows/arch-check.yml` wires the CLI into CI (Neo4j as a service container, index-on-PR, exit-code gating). Trigger scope is configured inline at the top of the workflow file — the shipped default is PR-to-main, with commented-out alternatives for push-to-dev and manual `workflow_dispatch`. Edit the `on:` block to match your team's policy. See `codegraph/docs/arch-policies.md` for the policy reference (what each detects, common false positives, how to interpret violations).
