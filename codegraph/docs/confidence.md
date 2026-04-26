# Edge Confidence Labels

Every relationship in the codegraph property graph carries two properties:

- **`confidence`** — categorical label: `EXTRACTED`, `INFERRED`, or `AMBIGUOUS`
- **`confidence_score`** — numeric score in the range `[0.0, 1.0]`

These fields let consumers filter edges by reliability. A high-confidence subgraph (score >= 0.9) is useful for strict architecture checks, while the full graph including lower-confidence edges is better for exploratory analysis.

---

## Taxonomy

| Label | Meaning | Typical score |
|---|---|---|
| **EXTRACTED** | Derived directly from the AST with no heuristics. The relationship is a syntactic fact. | 1.0 |
| **INFERRED** | Resolved via a heuristic (name matching, barrel re-exports, MRO guessing). Likely correct but not guaranteed. | 0.5 -- 0.9 |
| **AMBIGUOUS** | Multiple equally valid targets exist; the edge picks one but the choice is uncertain. | < 0.5 |

`AMBIGUOUS` is reserved for future use. Today all edges are either `EXTRACTED` or `INFERRED`.

---

## Edge Classification

### Structural edges (always EXTRACTED / 1.0)

These come straight from the AST with no resolution step:

`DEFINES_CLASS`, `DEFINES_FUNC`, `HAS_METHOD`, `DEFINES_IFACE`, `DEFINES_ATOM`, `HAS_COLUMN`, `EXPOSES`, `RESOLVES`, `BELONGS_TO`, `MEMBER_OF`, `OWNED_BY`, `LAST_MODIFIED_BY`, `CONTRIBUTED_BY`, `READS_ATOM`, `WRITES_ATOM`, `READS_ENV`, `HANDLES_EVENT`, `EMITS_EVENT`, `DECORATED_BY`

### Import edges (confidence varies by resolution strategy)

| Strategy | Label | Score | When |
|---|---|---|---|
| `direct` | EXTRACTED | 1.0 | Resolved to an exact `.py` / `.ts` file |
| `relative` | EXTRACTED | 1.0 | Relative import (e.g. `from .b import x`) resolved to a file |
| `alias` | INFERRED | 0.9 | Resolved via a `tsconfig.json` path alias |
| `workspace` | INFERRED | 0.85 | Resolved via workspace/monorepo package boundary |
| `barrel` | INFERRED | 0.8 | Resolved through an `__init__.py` or `index.ts` barrel |

External (unresolved) imports default to EXTRACTED / 1.0 -- the import statement itself is a fact.

### CALLS edges (confidence varies by receiver kind)

| Receiver | Label | Score | Example |
|---|---|---|---|
| `self` / `this` | EXTRACTED | 1.0 | `self.foo()`, `this.bar()` |
| `super()` | INFERRED | 0.7 | `super().run()` (MRO guess) |
| `this.field` | INFERRED | 0.6 | DI-injected field call |
| `name` (class target) | INFERRED | 0.5 | Bare `helper()` resolved to a class method |
| `name` (function) | INFERRED | 0.5 | Bare `helper()` resolved to a module function |

### Other cross-file edges

| Edge kind | Label | Score | Rationale |
|---|---|---|---|
| `EXTENDS`, `IMPLEMENTS` | EXTRACTED | 1.0 | AST heritage clause |
| `INJECTS`, `PROVIDES`, `EXPORTS_PROVIDER` | EXTRACTED | 1.0 | NestJS decorator metadata |
| `CALLS_ENDPOINT` | INFERRED | 0.7 | URL pattern matching |
| `RENDERS` | INFERRED | 0.8 | JSX component name resolution |
| `USES_HOOK` | EXTRACTED | 0.9 | Hook name from AST |
| `TESTS` | INFERRED | 0.5 | File-name pairing heuristic |
| `TESTS_CLASS` | INFERRED | 0.6 | Test-class name matching |

---

## Querying Confidence in Cypher

**High-confidence CALLS only:**

```cypher
MATCH (a)-[r:CALLS]->(b)
WHERE r.confidence_score >= 0.9
RETURN a.name, b.name, r.confidence, r.confidence_score
```

**Distribution of confidence labels:**

```cypher
MATCH ()-[r]->()
WHERE r.confidence IS NOT NULL
RETURN type(r) AS edge_type, r.confidence, count(*) AS cnt
ORDER BY edge_type, r.confidence
```

**Find all low-confidence edges:**

```cypher
MATCH (a)-[r]->(b)
WHERE r.confidence_score < 0.7
RETURN type(r) AS kind, a.name, b.name, r.confidence_score
ORDER BY r.confidence_score
LIMIT 25
```

---

## Filtering in Arch-Check Policies

When writing or customising `arch-check` policies, you can exclude low-confidence edges to reduce false positives. For example, to check import cycles only among high-confidence imports:

```cypher
MATCH path = (a:File)-[:IMPORTS*2..6]->(a)
WHERE ALL(r IN relationships(path) WHERE r.confidence_score >= 0.8)
RETURN [n IN nodes(path) | n.path] AS cycle
```

This filters out barrel-resolved imports (score 0.8) and below, keeping only direct and relative imports in the cycle analysis.
