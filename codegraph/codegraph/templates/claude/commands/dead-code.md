---
allowed-tools: Bash(codegraph query:*), Bash(codegraph query:*), Bash(.venv/bin/codegraph query:*)
description: List orphan functions, classes, atoms, and endpoints with no inbound references — framework entry points excluded
---

## Usage

```
/dead-code [path_prefix]
```

Scope defaults to `codegraph/codegraph/` if no prefix is given. Pass any string that matches a `:File.path` prefix to scope elsewhere (e.g. `packages/twenty-server/src/engine/`).

Returns four categories of orphan, each tagged with a `kind` column so you can scan them together:

| Kind | What it means |
|---|---|
| `orphan_function` | `:Function` with **no** incoming `CALLS` / `RENDERS` **and** no outgoing `DECORATED_BY` (i.e. not a Typer / MCP / pytest entry point) |
| `orphan_class` | `:Class` with no incoming `EXTENDS`, `INJECTS`, `RESOLVES`, or `IMPORTS_SYMBOL` |
| `orphan_atom` | `:Atom` with no `READS_ATOM` or `WRITES_ATOM` consumers (React state defined but never used) |
| `orphan_endpoint` | `:Endpoint` with no `HANDLES` method (route declared but unhooked) |

## What this does

```bash
PREFIX="${ARGUMENTS:-$DEFAULT_PACKAGE_PREFIX}"

codegraph query "
MATCH (f:Function)
WHERE f.file STARTS WITH '$PREFIX'
  AND NOT EXISTS { ()-[:CALLS]->(f) }
  AND NOT EXISTS { ()-[:RENDERS]->(f) }
  AND NOT EXISTS { (f)-[:DECORATED_BY]->(:Decorator) }
RETURN 'orphan_function' AS kind, f.name AS name, f.file AS file
UNION ALL
MATCH (c:Class)
WHERE c.file STARTS WITH '$PREFIX'
  AND NOT EXISTS { ()-[:EXTENDS]->(c) }
  AND NOT EXISTS { ()-[:INJECTS]->(c) }
  AND NOT EXISTS { ()-[:RESOLVES]->(c) }
  AND NOT EXISTS { (:File)-[:IMPORTS_SYMBOL {symbol: c.name}]->(:File) }
RETURN 'orphan_class' AS kind, c.name AS name, c.file AS file
UNION ALL
MATCH (a:Atom)
WHERE a.file STARTS WITH '$PREFIX'
  AND NOT EXISTS { ()-[:READS_ATOM]->(a) }
  AND NOT EXISTS { ()-[:WRITES_ATOM]->(a) }
RETURN 'orphan_atom' AS kind, a.name AS name, a.file AS file
UNION ALL
MATCH (e:Endpoint)
WHERE e.file STARTS WITH '$PREFIX'
  AND NOT EXISTS { (:Method)-[:HANDLES]->(e) }
RETURN 'orphan_endpoint' AS kind, (e.method + ' ' + e.path) AS name, e.file AS file
ORDER BY kind, file, name
LIMIT 100
"
```

## Caveats

- **Decorator exclusion is load-bearing.** Without the `DECORATED_BY` filter, every `@mcp.tool()`, `@app.command()`, `@pytest.fixture`, `@staticmethod` function shows up as "orphan" because framework dispatchers invoke them via reflection. Keep the filter even if it occasionally hides a genuinely-dead decorated function.
- **Python module-level callers aren't tracked.** The Python parser doesn't emit `CALLS` from top-level code (Stage 1 limitation — resolver's Phase 4 requires a method-scoped caller). So a Python function called only from module-level `if __name__ == "__main__":` blocks will appear as orphan. Spot-check before deleting.
- **Interface / Protocol implementations.** A class that only "satisfies" a duck-typed protocol (no `EXTENDS` edge, no explicit import) will show as `orphan_class`. For abstract-base-class compliance, use `/graph "MATCH (c:Class {name:'Foo'})-[:EXTENDS]->(p:Class) RETURN p"` to double-check.
- **100-row limit.** Raise it for exhaustive cleanup passes.

## After running

Zero results = healthy codebase under that prefix. Non-zero results are candidates, not verdicts — always grep the name in string form before deleting (reflective access, dynamic imports, CLI entry points registered in `pyproject.toml`, Jinja template lookups, etc. won't show up in the graph).
