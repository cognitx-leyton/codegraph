# Hyperedges (`:EdgeGroup` + `:MEMBER_OF`)

Codegraph models group relationships ("hyperedges") that connect 3+ nodes as `:EdgeGroup` intermediary nodes with `:MEMBER_OF` edges from each participant. This is the standard property-graph pattern for N-ary relationships in Neo4j, which only supports binary edges natively.

---

## Neo4j model

```
(:Class)-[:MEMBER_OF]->(:EdgeGroup {kind: 'protocol_implementers'})
(:Class)-[:MEMBER_OF]->(:EdgeGroup {kind: 'community'})
```

An `:EdgeGroup` node has these properties:

| Property | Type | Description |
|----------|------|-------------|
| `id` | string | Unique key: `edgegroup:<kind>:<name>` (protocol) or `community:<id>` (Leiden) |
| `name` | string | Human-readable label, e.g. `"IEventHandler implementers"` |
| `kind` | string | Discriminator: `protocol_implementers`, `community` |
| `node_count` | int | Number of members at creation time |
| `confidence` | float | 1.0 for deterministic groups, variable for statistical |
| `cohesion` | float | Community-only: internal edge density score |
| `label` | string | Community-only: auto-generated description |

---

## Current kinds

### `protocol_implementers`

Emitted during the indexing pass by `link_cross_file()` in `resolver.py`. When 2+ classes share an `IMPLEMENTS` edge to the same interface, one EdgeGroup is created and all implementers are linked via `MEMBER_OF`.

**Threshold**: 2+ implementers (a single implementer is not grouped).

**Lifecycle**: stale protocol-implementer groups are deleted (`DETACH DELETE`) before re-writing on each index run. Community groups (`kind='community'`) are unaffected.

### `community`

Emitted by `codegraph analyze --leiden` via `persist_communities()` in `analyze.py`. Uses the Leiden algorithm on the IMPORTS graph to detect tightly-coupled clusters.

---

## MCP tool: `describe_group`

```
describe_group(name_or_id, kind=None, limit=50)
```

Matches by exact `id` or substring on `name`. Optionally filter by `kind`. Returns columns: `group_id`, `group_name`, `group_kind`, `group_size`, `confidence`, `cohesion`, `member_kind`, `member_name`, `member_file`.

---

## Example queries

```cypher
-- All edge groups with member counts
MATCH (eg:EdgeGroup)
OPTIONAL MATCH (member)-[:MEMBER_OF]->(eg)
RETURN eg.name AS name, eg.kind AS kind, count(member) AS members
ORDER BY kind, name
```

```cypher
-- Members of a protocol-implementer group
MATCH (eg:EdgeGroup {kind: 'protocol_implementers'})
WHERE eg.name CONTAINS 'IEventHandler'
MATCH (member)-[:MEMBER_OF]->(eg)
RETURN member.name AS class_name, member.file AS file
```

```cypher
-- Classes sharing a protocol group (co-membership)
MATCH (a)-[:MEMBER_OF]->(eg:EdgeGroup {kind: 'protocol_implementers'})<-[:MEMBER_OF]-(b)
WHERE a <> b
RETURN a.name AS class_a, b.name AS class_b, eg.name AS shared_group
```

---

## Extending with new kinds

To add a new EdgeGroup kind:

1. Choose a unique `kind` string (e.g. `"auth_flow"`).
2. Create `EdgeGroupNode` instances with that kind in whichever pass computes the grouping.
3. Append `MEMBER_OF` edges from participants to the group's `id`.
4. Pass the groups through to `loader.load(edge_groups=...)` or write them directly via `_write_edge_groups()`.
5. Update the stale-cleanup logic in `_write_edge_groups()` if the new kind should be cleaned on re-index (add a `DETACH DELETE` for the specific `kind`).
