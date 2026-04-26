### Cypher catalogue — pre-vetted triangulation queries

These run against `bolt://localhost:7688` (or wherever the codegraph CLI is
configured). Always invoke through `codegraph query --json "<cypher>"` so
output is JSON. Counts can be compared directly against `Grep` counts on the
source tree.

#### Universal

```cypher
MATCH (f:File) RETURN f.language, count(*) AS n ORDER BY f.language
```
Per-language file counts. Compare against `find . -name '*.py' | wc -l` etc.

```cypher
MATCH (p:Package) RETURN p.name, p.framework, p.confidence ORDER BY p.name
```
Detected frameworks per package — confirms the inventory you should audit
against.

```cypher
MATCH (f:File)
WHERE NOT (f)-[:DEFINES_CLASS]->() AND NOT (f)-[:DEFINES_FUNC]->()
  AND NOT (f)-[:IMPORTS]->() AND NOT (f)-[:IMPORTS_EXTERNAL]->()
RETURN f.path LIMIT 20
```
Files with zero outgoing structural edges — usually means parser failed.

#### Python — class / function / method completeness

```cypher
MATCH (:File {language:'py'})-[:DEFINES_CLASS]->(c:Class) RETURN count(c) AS n
```
Compare to: `grep -rE "^class [A-Z]" --include='*.py' | wc -l` (modulo nested classes).

```cypher
MATCH (c:Class)-[:HAS_METHOD]->(m:Method) WHERE m.is_constructor = true
RETURN count(m) AS n
```
Compare to: `grep -rE "    def __init__\\(" --include='*.py' | wc -l`.

```cypher
MATCH (m:Method) WHERE m.is_static = true RETURN count(m) AS n
```
Compare to: `grep -rB1 "^    def " --include='*.py' | grep "@staticmethod" | wc -l`.

#### Python — ORM (SQLAlchemy / Django)

```cypher
MATCH (e:Class {is_entity:true}) RETURN e.name, e.table_name, e.file
ORDER BY e.file
```

```cypher
MATCH (c:Class {is_entity:true})-[:HAS_COLUMN]->(col:Column)
RETURN c.name AS entity, count(col) AS columns ORDER BY columns DESC
```
Per-entity column counts. Spot-check: read 2-3 entity files and count fields.

```cypher
MATCH (col:Column) WHERE col.primary = true RETURN count(col) AS n
```

#### Python — FastAPI / Flask / Django routing (Stage-2; expect zero today)

```cypher
MATCH (e:Endpoint) RETURN e.method, count(*) AS n ORDER BY n DESC
```
If detected framework is FastAPI/Flask/Django and this returns 0, that is
the documented Stage-2 gap. Do NOT flag as a bug; note in summary if useful.

#### TypeScript / NestJS — controllers, endpoints, modules

```cypher
MATCH (c:Class {is_controller:true}) RETURN count(c) AS n
```
Compare to: `grep -rE "^@Controller" --include='*.ts' | wc -l`.

```cypher
MATCH (c:Class {is_controller:true})-[:EXPOSES]->(e:Endpoint)
RETURN c.name, count(e) AS endpoints ORDER BY endpoints DESC LIMIT 20
```
Spot for controllers with zero endpoints — that's a parser gap.

```cypher
MATCH (e:Endpoint) RETURN e.method, count(*) AS n ORDER BY n DESC
```
HTTP-verb distribution. Compare each verb to source grep.

```cypher
MATCH (c:Class {is_module:true})-[:PROVIDES]->(:Class) RETURN count(*) AS n
```

#### TypeScript / NestJS — DI

```cypher
MATCH (c:Class)-[:INJECTS]->(s:Class)
RETURN s.name AS service, count(c) AS injected_into
ORDER BY injected_into DESC LIMIT 20
```
Most-injected services. Compare to source: services should appear in many
controller / other-service constructors.

#### TypeScript / TypeORM

```cypher
MATCH (c:Class {is_entity:true}) RETURN count(c) AS n
```
Compare to: `grep -rE "^@Entity" --include='*.ts' | wc -l`.

```cypher
MATCH (c:Class {is_entity:true})-[:HAS_COLUMN]->(col:Column)
RETURN c.name, count(col) AS cols ORDER BY cols DESC LIMIT 20
```

```cypher
MATCH ()-[r:RELATES_TO]->() RETURN count(r) AS n
```
Compare to: `grep -rcE "@(ManyToOne|OneToMany|OneToOne|ManyToMany)" --include='*.ts'`.

#### TypeScript / GraphQL

```cypher
MATCH (op:GraphQLOperation) RETURN op.op_type, count(*) AS n ORDER BY n DESC
```
Compare to: `grep -rE "^\\s*@(Query|Mutation|Subscription)" --include='*.ts' | wc -l`.

```cypher
MATCH (m:Method)-[:HANDLES]->(:GraphQLOperation) RETURN count(*) AS n
```

#### TypeScript / React

```cypher
MATCH (f:Function {is_component:true}) RETURN count(f) AS n
```
Compare to: function declarations returning JSX. Note arrow components are
NOT counted (Stage-2 gap, do not flag).

```cypher
MATCH (c:Function {is_component:true})-[:USES_HOOK]->(h:Hook)
RETURN h.name, count(c) AS components ORDER BY components DESC LIMIT 20
```

#### Cross-cutting — confidence audit

```cypher
MATCH ()-[r:CALLS]->() RETURN r.confidence, count(*) AS n
ORDER BY n DESC
```
EXTRACTED:INFERRED ratio for the call graph. A repo dominated by INFERRED
calls suggests poor type information; not a parser bug, but worth noting.

```cypher
MATCH ()-[r:IMPORTS|IMPORTS_EXTERNAL]->()
RETURN type(r) AS rel, count(*) AS n
```
Resolved-vs-external import ratio. If `IMPORTS_EXTERNAL` dominates a Python
package that has internal-only imports, the resolver may have misconfigured
package boundaries.

#### Cross-cutting — orphans

```cypher
MATCH (c:Class) WHERE NOT (c)-[:HAS_METHOD]->() AND c.is_abstract = false
RETURN c.name, c.file LIMIT 20
```
Concrete classes with zero methods — usually data classes / interfaces, but
worth a sample read.

```cypher
MATCH (m:Method) WHERE NOT (m)<-[:CALLS]-() AND m.visibility = 'public'
  AND m.name <> '__init__' AND m.name <> 'constructor'
RETURN m.class, m.name, m.file LIMIT 20
```
Public methods called by no one in the indexed set. Could be entry points
(legitimate) or extraction gaps in the call graph (parser bug). Sample 3-5
to triage.
