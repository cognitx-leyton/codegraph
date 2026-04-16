---
allowed-tools: Bash(codegraph query:*), Bash(codegraph/.venv/bin/codegraph query:*), Bash(.venv/bin/codegraph query:*)
description: Run a read-only Cypher query against the live codegraph Neo4j graph
---

## Usage

```
/graph <cypher>
```

Runs the Cypher against the local Neo4j instance via `codegraph query --json`. Read-only — writes (`CREATE`, `MERGE`, `DELETE`, `SET`) are **not** rejected at the CLI level (unlike the MCP server), so be careful what you execute. If you're unsure, stick to `MATCH` queries.

Assumes:
- Neo4j is up at `bolt://localhost:7688` (`docker compose up -d` from `codegraph/` if not).
- The graph has been indexed at least once (run `/graph-refresh` if you get zero results on queries you expect to match).

## Canonical query patterns for this repo

The graph is currently indexed for `codegraph/codegraph/` (the Python package) — ~18 files, 41 classes, 82 module functions, ~150 methods, decorators via `:Decorator` nodes, imports via `IMPORTS` / `IMPORTS_SYMBOL` / `IMPORTS_EXTERNAL` edges.

### Blast radius — who depends on a file?

```cypher
MATCH (f:File)-[:IMPORTS]->(target:File {path: 'codegraph/codegraph/schema.py'})
RETURN f.path AS caller
ORDER BY f.path
```

### Who imports a specific symbol?

```cypher
MATCH (f:File)-[r:IMPORTS_SYMBOL]->(g:File)
WHERE r.symbol = 'IgnoreFilter'
RETURN f.path AS caller, g.path AS source
```

### Find a class by substring

```cypher
MATCH (c:Class)
WHERE c.name CONTAINS 'Node' AND c.file STARTS WITH 'codegraph/codegraph/'
RETURN c.name, c.file
ORDER BY c.name
```

### Methods on a class

```cypher
MATCH (c:Class {name: 'IgnoreFilter'})-[:HAS_METHOD]->(m:Method)
RETURN m.name, m.visibility, m.is_constructor
ORDER BY m.name
```

### Census of dataclasses

```cypher
MATCH (f:File)-[:DEFINES_CLASS]->(c:Class)-[:DECORATED_BY]->(d:Decorator {name: 'dataclass'})
WHERE f.path STARTS WITH 'codegraph/codegraph/'
RETURN f.path, count(c) AS dataclass_count
ORDER BY dataclass_count DESC
```

### What decorators does a file use?

```cypher
MATCH (:File {path: 'codegraph/codegraph/mcp.py'})-[:DEFINES_FUNC]->(fn:Function)-[:DECORATED_BY]->(d:Decorator)
RETURN fn.name, d.name
ORDER BY fn.name
```

### Unresolved (external) imports from a file

```cypher
MATCH (:File {path: 'codegraph/codegraph/cli.py'})-[r:IMPORTS {external: true}]->(e:External)
RETURN e.specifier
ORDER BY e.specifier
```

## Running it

Invoke with a single Cypher string as argument. The command runs from the repo root:

```bash
codegraph/.venv/bin/codegraph query --json "$ARGUMENTS"
```

The `--json` output makes the response machine-parseable if you're planning follow-up queries. Drop `--json` for a rendered Rich table.
