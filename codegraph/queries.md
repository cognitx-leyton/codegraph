# Example Cypher queries

Open the Neo4j browser at **http://localhost:7475** (user `neo4j`, pass `codegraph123`)
or use `codegraph query "<cypher>"`.

To render visually, return a `path` or graph elements. To get a table, return scalars.

---

## Schema overview

```cypher
// Inventory of node labels and edge types
CALL db.labels() YIELD label RETURN label ORDER BY label;
CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType ORDER BY relationshipType;
```

---

## 0. Package & framework inventory

```cypher
// Every indexed package with its detected framework
MATCH (p:Package)
RETURN p.name, p.framework, p.framework_version, p.typescript,
       p.package_manager, p.build_tool, p.confidence
ORDER BY p.confidence DESC
```

```cypher
// Every file inside any Next.js package (useful for scoping refactors)
MATCH (f:File)-[:BELONGS_TO]->(p:Package {framework:'Next.js'})
RETURN f.path LIMIT 50
```

```cypher
// React components inside TypeScript packages only
MATCH (p:Package {typescript:true})<-[:BELONGS_TO]-(f:File)-[:DEFINES_FUNC]->(fn:Function {is_component:true})
RETURN p.name, fn.name, f.path LIMIT 50
```

---

## 1. HTTP API surface audit

```cypher
// Every REST endpoint exposed by the server
MATCH (c:Controller)-[:EXPOSES]->(e:Endpoint)
RETURN c.name AS controller, e.method, e.path, e.handler, c.file
ORDER BY e.path
```

```cypher
// Endpoints under a URL prefix
MATCH (e:Endpoint) WHERE e.path STARTS WITH '/auth'
RETURN e.method, e.path, e.handler
ORDER BY e.path
```

## 2. GraphQL operations (Twenty's primary API)

```cypher
// Every GraphQL operation, with its resolver
MATCH (r:Resolver)-[:RESOLVES]->(op:GraphQLOperation)
RETURN op.type AS type, op.name, r.name AS resolver, op.return_type
ORDER BY op.name
```

```cypher
// Most-called operations (frontend-driven)
MATCH (op:GraphQLOperation)<-[:USES_OPERATION]-(caller)
RETURN op.type, op.name, count(caller) AS callers
ORDER BY callers DESC LIMIT 20
```

## 3. Backend ↔ frontend linking

```cypher
// Frontend code that uses a specific GraphQL operation
MATCH (op:GraphQLOperation {name:'eventLogs'})<-[:USES_OPERATION]-(caller)
RETURN labels(caller) AS kind, caller.name, caller.file
```

```cypher
// Pages that hit any /auth/* endpoint
MATCH (e:Endpoint)<-[:CALLS_ENDPOINT]-(caller)
WHERE e.path STARTS WITH '/auth'
RETURN e.path, caller.name, caller.file
```

## 4. Impact analysis: who depends on X?

```cypher
// All classes that inject AuthService (1-hop)
MATCH (c:Class)-[:INJECTS]->(:Class {name:'AuthService'})
RETURN c.name, c.file

// Transitive: anything reachable upstream within 3 DI hops
MATCH path = (root:Class)-[:INJECTS*1..3]->(:Class {name:'AuthService'})
RETURN DISTINCT root.name, length(path) AS distance
ORDER BY distance
```

```cypher
// Files that import the FooService symbol specifically (Phase 1.1)
MATCH (a:File)-[r:IMPORTS_SYMBOL {symbol:'AuthService'}]->(b:File)
RETURN a.path
```

## 5. Method-level call graph

```cypher
// Methods called by a specific endpoint handler
MATCH (e:Endpoint {path:'/auth/google'})<-[:HANDLES]-(handler:Method)
MATCH path = (handler)-[:CALLS*1..3]->(callee:Method)
RETURN DISTINCT callee.name, callee.file LIMIT 50
```

```cypher
// Who calls a specific method (high confidence only)
MATCH (caller:Method)-[r:CALLS {confidence:'typed'}]->(callee:Method {name:'signIn'})
RETURN caller.name, caller.file
```

## 6. Data layer: TypeORM entities, columns, relations

```cypher
// All columns of an entity
MATCH (e:Entity {name:'UserWorkspaceEntity'})-[:HAS_COLUMN]->(col:Column)
RETURN col.name, col.type, col.nullable, col.unique, col.primary
ORDER BY col.primary DESC, col.name
```

```cypher
// Entity relationship subgraph (visual)
MATCH (e:Entity {name:'WorkspaceEntity'})
MATCH path = (e)-[:RELATES_TO*1..2]-(other:Entity)
RETURN path
```

```cypher
// Endpoints that transitively touch the User table
MATCH (ep:Endpoint)<-[:HANDLES]-(handler:Method)
MATCH (ep)<-[:EXPOSES]-(c:Class)
MATCH (c)-[:INJECTS*0..3]->(svc:Class)-[:REPOSITORY_OF]->(:Entity {name:'UserWorkspaceEntity'})
RETURN DISTINCT ep.method, ep.path
```

## 7. NestJS module graph (DI scope correctness)

```cypher
// What does AuthModule provide and import?
MATCH (m:Module {name:'AuthModule'})
OPTIONAL MATCH (m)-[:PROVIDES]->(svc:Class)
OPTIONAL MATCH (m)-[:IMPORTS_MODULE]->(other:Module)
RETURN m.name, collect(DISTINCT svc.name) AS provides, collect(DISTINCT other.name) AS imports
```

```cypher
// Most-injected modules (architectural hotspots)
MATCH (m:Module)<-[:IMPORTS_MODULE]-()
RETURN m.name, count(*) AS imported_by
ORDER BY imported_by DESC LIMIT 10
```

## 8. Test coverage gaps

```cypher
// Controllers with no test file
MATCH (c:Controller)<-[:DEFINES_CLASS]-(f:File)
WHERE NOT EXISTS { (:TestFile)-[:TESTS]->(f) }
RETURN c.name, f.path
```

```cypher
// Test files for a specific class
MATCH (t:TestFile)-[:TESTS_CLASS]->(:Class {name:'AuthService'})
RETURN t.path
```

## 9. Ownership and review routing

```cypher
// Last person to touch a file
MATCH (f:File {path:'packages/twenty-server/src/engine/core-modules/auth/services/auth.service.ts'})
MATCH (f)-[r:LAST_MODIFIED_BY]->(a:Author)
RETURN a.name, a.email, datetime({epochSeconds: r.at})
```

```cypher
// Top contributors to a directory
MATCH (f:File)-[r:CONTRIBUTED_BY]->(a:Author)
WHERE f.path STARTS WITH 'packages/twenty-server/src/engine/core-modules/auth'
RETURN a.name, sum(r.commits) AS total
ORDER BY total DESC LIMIT 10
```

## 10. Frontend state and routing

```cypher
// Top hooks across the frontend
MATCH (h:Hook)<-[:USES_HOOK]-()
RETURN h.name, count(*) AS uses
ORDER BY uses DESC LIMIT 20
```

```cypher
// Components in a specific page area
MATCH (c:Component)
WHERE c.file CONTAINS '/settings/security'
RETURN c.name, c.file
```

## 11. Architectural metrics

```cypher
// Hub files (most incoming imports)
MATCH (f:File)<-[:IMPORTS]-()
RETURN f.path, count(*) AS in_imports
ORDER BY in_imports DESC LIMIT 10
```

```cypher
// Orphan files (no imports in or out — possible parse failure or dead code)
MATCH (f:File)
WHERE NOT (f)-[:IMPORTS|IMPORTS_EXTERNAL]->()
  AND NOT ()-[:IMPORTS]->(f)
RETURN f.path LIMIT 50
```

```cypher
// Shortest path between two files
MATCH (a:File), (b:File)
WHERE a.path ENDS WITH 'google-auth.controller.ts'
  AND b.path ENDS WITH 'workspace.entity.ts'
MATCH p = shortestPath((a)-[:IMPORTS*..8]->(b))
RETURN [n IN nodes(p) | n.path] AS hops
```

## 12. Graph-RAG: feature slice for an LLM prompt

```cypher
// Everything relevant to the auth/google feature, deterministically
MATCH (e:Endpoint) WHERE e.path STARTS WITH '/auth/google'
MATCH (c:Controller)-[:EXPOSES]->(e)
OPTIONAL MATCH (c)-[:INJECTS*0..2]->(dep:Class)
OPTIONAL MATCH (op:GraphQLOperation)<-[:USES_OPERATION]-(fe)
WITH collect(DISTINCT c.file) + collect(DISTINCT dep.file) + collect(DISTINCT fe.file) AS files
UNWIND files AS f
RETURN DISTINCT f
```
