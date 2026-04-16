---
allowed-tools: Bash(codegraph query:*), Bash(codegraph query:*), Bash(.venv/bin/codegraph query:*)
description: Trace an endpoint URL through its handler methods and everything they transitively call
---

## Usage

```
/trace-endpoint <url_substring>
```

Matches against `:Endpoint.path CONTAINS $ARGUMENTS` — so partial matches work (`/users` picks up `/users/:id`, `/users/profile`, etc.).

Runs two queries in sequence:

1. **Surface** — the matched endpoints and their handler methods (the API shape).
2. **Reach** — every method reachable within 4 `CALLS` hops from each handler, grouped by enclosing class (the data-and-compute reach).

Useful for impact analysis ("what breaks if I change this URL?"), security review ("what does this public endpoint touch?"), and onboarding ("show me a feature end-to-end").

## What this does

```bash
codegraph query "
MATCH (m:Method)-[:HANDLES]->(e:Endpoint)
WHERE e.path CONTAINS '$ARGUMENTS'
OPTIONAL MATCH (ctrl:Class)-[:HAS_METHOD]->(m)
RETURN 'surface' AS layer,
       e.method AS http_method,
       e.path AS route,
       ctrl.name AS controller,
       m.name AS handler,
       e.file AS file
ORDER BY e.path
LIMIT 20
"

codegraph query "
MATCH (m:Method)-[:HANDLES]->(e:Endpoint)
WHERE e.path CONTAINS '$ARGUMENTS'
MATCH path = (m)-[:CALLS*1..4]->(target:Method)
MATCH (enclosing:Class)-[:HAS_METHOD]->(target)
WITH DISTINCT enclosing.name AS class, target.name AS method, target.file AS file
RETURN 'reach' AS layer, class, method, file
ORDER BY class, method
LIMIT 100
"
```

## Caveats

- **Python has no `:Endpoint` nodes yet.** Stage 1 Python only captures classes / functions / imports / decorators; FastAPI / Flask / Django route detection lands in Stage 2. Running this against a URL from a Python-only project returns zero rows. Document the gap rather than pretending the graph has coverage it doesn't.
- **Only typed CALLS resolve reliably.** Python's name-resolved calls (`obj.foo()` where `obj`'s type isn't known) may miss. TS: `this.x()` resolves; dynamic dispatch may not.
- **4-hop bound is a trade-off.** Deep call chains (e.g. orchestrator → saga → worker → DB) may exceed it. Raise to `*1..6` if you're doing deep security review — slower but more complete.
- **`CALLS_ENDPOINT` is the inverse** — that's the edge for *outgoing* HTTP calls to an endpoint (e.g. frontend fetching from backend). If you want "who hits this endpoint from elsewhere", query `CALLS_ENDPOINT` instead.

## After running

The surface output tells you the API contract. The reach output tells you the domain model the endpoint touches — if you see entity classes (`User`, `Workspace`) in the reach, that's your data-sensitivity read. Add a `MATCH (enclosing)-[:HAS_COLUMN]->(col:Column)` hop to pivot into column-level data lineage.
