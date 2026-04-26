# Graph Schema Reference

Authoritative reference for every node label, relationship type, and property the codegraph indexer writes into Neo4j. The source of truth is [`codegraph/schema.py`](../codegraph/schema.py); this document explains and groups what's there.

If you spot a divergence between this doc and `schema.py`, the code wins — please open a PR to fix the doc.

---

## 1. Overview

Codegraph stores a **labelled property graph** in Neo4j 5.x. Two parsers — TypeScript / TSX (`parser.py`) and Python (`py_parser.py`) — emit the same `ParseResult` shape; the loader (`loader.py`) writes both into a single, language-agnostic schema. Cross-file resolution (`resolver.py`) runs between parse and load, turning name-based references (`extends Foo`, `<MyComponent />`) into typed edges.

A few invariants apply globally:

- **Every relationship carries `confidence` + `confidence_score`** properties. Structural edges (`DEFINES_CLASS`, `HAS_METHOD`, `BELONGS_TO`, …) are always `EXTRACTED` / `1.0`; resolved edges (`CALLS`, `IMPORTS_SYMBOL` via barrel, `TESTS`) drop to `INFERRED` with a per-strategy score. Full taxonomy + scoring rules: see [`confidence.md`](confidence.md).
- **Nodes carry their own `id`** as a stable, deterministic string (e.g. `class:src/foo.ts#Bar`, `method:class:src/foo.ts#Bar#run`). IDs are MERGE keys — re-indexing the same file produces the same IDs and updates in place.
- **Specialised labels stack** on `:Class`: an entity is `:Class:Entity`, a NestJS module is `:Class:Module`, a controller is `:Class:Controller`. The same applies to `:File:TestFile` and `:Function:Component`.
- **Hyperedges (3+ participants)** are modelled as `:EdgeGroup` nodes with `:MEMBER_OF` edges from each member, since Neo4j relationships are strictly binary. See [`hyperedges.md`](hyperedges.md).

### Indexed properties and unique constraints

The loader installs these on first run (`init_schema()`):

| Label | Unique constraint | Secondary index(es) |
|---|---|---|
| `:File` | `path` | `package` |
| `:Class` | `id` | `name`, `file` |
| `:Function` | `id` | `name` |
| `:Method` | `id` | `name` |
| `:Interface` | `id` | — |
| `:Endpoint` | `id` | `path` |
| `:GraphQLOperation` | `id` | `name` |
| `:Column` | `id` | — |
| `:Atom` | `id` | — |
| `:EnvVar` | `name` | — |
| `:Event` | `name` | — |
| `:External` | `specifier` | — |
| `:Hook` | `name` | — |
| `:Decorator` | `name` | — |
| `:Author` | `email` | — |
| `:Team` | `name` | — |
| `:Route` | `id` | — |
| `:Package` | `name` | — |
| `:EdgeGroup` | `id` | `kind` |

Use these in your `WHERE` clauses for fast lookups — `WHERE c.name = 'Foo'` hits the `class_name` index; `WHERE c.id = 'class:src/foo.ts#Foo'` hits the unique constraint. Avoid `WHERE c.file CONTAINS '...'` on hot paths; full string scans are linear.

---

## 2. Node catalogue

15 first-class node types plus the `:EdgeGroup` hyperedge intermediary. Specialised stacked labels (`:Component`, `:Controller`, `:Entity`, `:Module`, `:Resolver`, `:TestFile`) are not separate node types — they're conditional add-ons over `:Class` / `:Function` / `:File`.

### 2.1 `PackageNode` → `:Package`

**Purpose**: one node per monorepo package, carrying the framework detection result so queries can branch by stack in a single hop.

**Properties**:

| Name | Type | Description |
|---|---|---|
| `name` | string | Unique package name; matches the `package` field on every `:File` inside it. |
| `framework` | string | Display name returned by detection: `"React"`, `"Next.js"`, `"NestJS"`, `"FastAPI"`, `"Odoo"`, … |
| `framework_version` | string \| null | Version pinned in `package.json` / `pyproject.toml`, when known. |
| `typescript` | bool | True if the package uses TypeScript. |
| `styling` | string[] | Detected styling libraries (`["tailwind", "emotion"]`). |
| `router` | string \| null | Router name when applicable (`"react-router"`, `"next-app"`). |
| `state_management` | string[] | Detected state libs (`["jotai", "zustand"]`). |
| `ui_library` | string \| null | Detected component library (`"shadcn"`, `"mui"`). |
| `build_tool` | string \| null | `"vite"`, `"webpack"`, `"setuptools"`, … |
| `package_manager` | string \| null | `"pnpm"`, `"npm"`, `"poetry"`, … |
| `confidence` | float | Detector confidence 0.0-1.0. |

**Emitted by**: the framework-detection pass (`framework.py`) once per configured `-p <path>` scope, before any file-level work.

**Common queries**:

```cypher
// All Next.js packages
MATCH (p:Package {framework: 'Next.js'}) RETURN p.name, p.framework_version

// Files in a specific framework
MATCH (f:File)-[:BELONGS_TO]->(p:Package {framework: 'NestJS'})
RETURN f.path LIMIT 20
```

### 2.2 `FileNode` → `:File`

**Purpose**: every source file that the indexer parsed, regardless of language.

**Properties**:

| Name | Type | Description |
|---|---|---|
| `path` | string | Repo-relative path (POSIX separators). Unique. |
| `package` | string | Owning package name; foreign key to `:Package.name`. |
| `language` | string | `"ts"`, `"tsx"`, `"py"`. |
| `loc` | int | Lines of code (raw newline count). |
| `is_controller` | bool | TS/NestJS — file contains a `@Controller`-decorated class. |
| `is_injectable` | bool | TS/NestJS — file contains `@Injectable`. |
| `is_module` | bool | TS/NestJS — file contains `@Module`. |
| `is_component` | bool | TS/React — file exports a JSX component. |
| `is_entity` | bool | TS/TypeORM — file contains `@Entity`. |
| `is_resolver` | bool | TS/GraphQL — file contains `@Resolver`. |
| `is_test` | bool | Filename matches a known test convention (TS: `*.spec.ts/x`, `*.test.ts/x`; Python: `test_*.py`, `*_test.py`). When true, the `:TestFile` label is also added. |

**Emitted by**: every parser. Test-file flagging happens during walk-time.

**Common queries**:

```cypher
// All NestJS controller files
MATCH (f:File {is_controller: true}) RETURN f.path

// All test files in a package
MATCH (f:TestFile)-[:BELONGS_TO]->(p:Package {name: 'codegraph'})
RETURN f.path
```

### 2.3 `ClassNode` → `:Class` (+ `:Entity`, `:Module`, `:Controller`, `:Resolver`)

**Purpose**: one node per class declaration. Stacked labels reflect framework role.

**Properties**:

| Name | Type | Description |
|---|---|---|
| `id` | string | `class:<file>#<name>`. Unique. |
| `name` | string | Class name as declared. |
| `file` | string | Owning file path. |
| `is_controller` | bool | NestJS — has `@Controller`. |
| `is_injectable` | bool | NestJS — has `@Injectable`. |
| `is_module` | bool | NestJS — has `@Module`. |
| `is_entity` | bool | TypeORM — has `@Entity`. |
| `is_resolver` | bool | GraphQL — has `@Resolver`. |
| `is_abstract` | bool | TS `abstract class`, Python `ABC` subclass. |
| `base_path` | string | NestJS controller base route, parsed from `@Controller('users')`. Empty for non-controllers. |
| `table_name` | string | TypeORM `@Entity('users')` table name. Empty for non-entities. |

**Emitted by**: TS parser and Python parser. Entity / module / resolver / controller flags are TS-only in Stage 1 (Python-side framework labelling lands in Stage 2).

**Common queries**:

```cypher
// Find classes by name across all files
MATCH (c:Class) WHERE c.name CONTAINS 'Service' RETURN c.name, c.file

// All entity classes with their table names
MATCH (e:Entity) RETURN e.name, e.table_name
```

### 2.4 `MethodNode` → `:Method`

**Purpose**: a method declared on a class. Constructors count.

**Properties**:

| Name | Type | Description |
|---|---|---|
| `id` | string | `method:<class_id>#<name>` (so `method:class:src/foo.ts#Bar#run`). Unique. |
| `class_id` | string | The owning `:Class.id`. Foreign key for `HAS_METHOD`. |
| `name` | string | Method name. |
| `file` | string | Owning file path (matches the class's file). |
| `is_static` | bool | TS `static` / Python `@staticmethod`. |
| `is_async` | bool | `async` keyword. |
| `is_constructor` | bool | True for `constructor` (TS) or `__init__` (Python). |
| `visibility` | string | `"public"` / `"private"` / `"protected"`. TS reads modifiers; Python uses leading-underscore convention (single = protected, double = private). |
| `return_type` | string | Best-effort string of the return-type annotation. Empty when not annotated. |
| `params_json` | string | JSON-encoded list of `{name, type}` objects, one per parameter. |
| `docstring` | string | Method docstring (Python) or leading JSDoc text (TS). |

**Emitted by**: both parsers, during class-body walk.

**Common queries**:

```cypher
// All methods named 'run' across the graph
MATCH (m:Method {name: 'run'}) RETURN m.file, m.class_id

// Method count per class
MATCH (c:Class)-[:HAS_METHOD]->(m:Method)
RETURN c.name, count(m) AS methods ORDER BY methods DESC LIMIT 10
```

### 2.5 `FunctionNode` → `:Function` (+ `:Component`)

**Purpose**: a top-level (module-scope) function. Class methods are `:Method`, not `:Function`.

**Properties**:

| Name | Type | Description |
|---|---|---|
| `id` | string | `func:<file>#<name>`. Unique. |
| `name` | string | Function name. |
| `file` | string | Owning file. |
| `is_component` | bool | TS only — inferred React component (PascalCase + returns JSX). When true, the `:Component` label is also added. |
| `exported` | bool | True if the function is named in an `export` statement (TS) or has no leading underscore (Python heuristic). |
| `docstring` | string | Function docstring (Python) or JSDoc (TS). |
| `return_type` | string | Best-effort return-type annotation. |
| `params_json` | string | JSON-encoded `[{name, type}, ...]`. |

**Emitted by**: both parsers.

**Common queries**:

```cypher
// All React components
MATCH (c:Component) RETURN c.name, c.file

// All exported functions in a path
MATCH (f:Function {exported: true}) WHERE f.file STARTS WITH 'codegraph/codegraph/'
RETURN f.name, f.file
```

### 2.6 `InterfaceNode` → `:Interface`

**Purpose**: TypeScript `interface` declarations.

**Properties**:

| Name | Type | Description |
|---|---|---|
| `id` | string | `interface:<file>#<name>`. Unique. |
| `name` | string | Interface name. |
| `file` | string | Owning file. |

**Emitted by**: TS parser only. Python doesn't have a direct equivalent; `typing.Protocol` classes land as `:Class` with `is_abstract=True`.

**Common queries**:

```cypher
// All interfaces in a package
MATCH (i:Interface)-[:BELONGS_TO]->()  // no direct edge — go via :File
WITH i MATCH (f:File {path: i.file})-[:BELONGS_TO]->(p:Package)
RETURN p.name, i.name
```

### 2.7 `EndpointNode` → `:Endpoint`

**Purpose**: an HTTP route handler. One node per (method, path, handler) tuple.

**Properties**:

| Name | Type | Description |
|---|---|---|
| `id` | string | `endpoint:<HTTP_method>:<path>@<file>#<handler>`. Unique. |
| `method` | string | `GET`, `POST`, `PUT`, `DELETE`, `PATCH`, `OPTIONS`. |
| `path` | string | Route path. For NestJS, this is base-path-joined (`@Controller('users')` + `@Get(':id')` → `/users/:id`). |
| `controller_class` | string | The `:Class.id` of the owning controller, or `"file:<path>"` for module-level handlers (FastAPI/Flask `@app.get`). Used internally to wire `EXPOSES`. |
| `file` | string | File where the handler lives. |
| `handler` | string | Method or function name that implements the route. |

**Emitted by**: TS parser (NestJS controllers, decorators). Python parser (FastAPI / Flask `@app.get`/`@router.post`/`@app.route`). `controller_class` decides whether `:File` or `:Class` becomes the parent of `EXPOSES`.

**Common queries**:

```cypher
// Endpoint inventory grouped by HTTP method
MATCH (e:Endpoint) RETURN e.method, count(*) ORDER BY count(*) DESC

// All endpoints under /users
MATCH (e:Endpoint) WHERE e.path STARTS WITH '/users'
RETURN e.method, e.path, e.handler
```

### 2.8 `ColumnNode` → `:Column`

**Purpose**: a column on a TypeORM entity (or a SQLAlchemy / Django model field).

**Properties**:

| Name | Type | Description |
|---|---|---|
| `id` | string | `column:<entity_id>#<name>`. Unique. |
| `entity_id` | string | The owning `:Class.id`. |
| `name` | string | Column / field name. |
| `type` | string | Column type as written (`"varchar"`, `"int"`, `"CharField"`, `"Integer"`). |
| `nullable` | bool | Whether the column is nullable. |
| `unique` | bool | Has a unique constraint. |
| `primary` | bool | Primary key. |
| `generated` | bool | TypeORM `@PrimaryGeneratedColumn` / Django `AutoField`. |

**Emitted by**: TS parser (TypeORM `@Column`, `@PrimaryGeneratedColumn`, `@CreateDateColumn`, …) and Python parser (SQLAlchemy `Column(...)`, Django `models.CharField(...)`).

**Common queries**:

```cypher
// Entities and their primary keys
MATCH (e:Entity)-[:HAS_COLUMN]->(c:Column {primary: true})
RETURN e.name, c.name, c.type

// Wide tables (>10 columns)
MATCH (e:Entity)-[:HAS_COLUMN]->(c:Column)
WITH e, count(c) AS cols WHERE cols > 10
RETURN e.name, cols ORDER BY cols DESC
```

### 2.9 `GraphQLOperationNode` → `:GraphQLOperation`

**Purpose**: a GraphQL query / mutation / subscription declared in a NestJS `@Resolver`.

**Properties**:

| Name | Type | Description |
|---|---|---|
| `id` | string | `gqlop:<op_type>:<name>@<file>#<handler>`. Unique. |
| `op_type` | string | `"query"`, `"mutation"`, or `"subscription"`. |
| `name` | string | Operation name (e.g. `"users"`, `"createUser"`). |
| `return_type` | string | Best-effort return type from the decorator or method signature. |
| `file` | string | Owning file. |
| `resolver_class` | string | `:Class.id` of the resolver. |
| `handler` | string | Method that implements the operation. |

**Emitted by**: TS parser only (NestJS `@Query`, `@Mutation`, `@Subscription` decorators).

**Common queries**:

```cypher
// All mutations and the methods that handle them
MATCH (op:GraphQLOperation {type: 'mutation'})<-[:HANDLES]-(m:Method)
RETURN op.name, m.name, op.file
```

### 2.10 `EventNode` → `:Event`

**Purpose**: a named event token (NestJS `@OnEvent('user.created')`, EventEmitter `emit('foo')`). Singleton — one node per distinct event name.

**Properties**:

| Name | Type | Description |
|---|---|---|
| `name` | string | Event name (e.g. `"user.created"`). Unique. |

**Emitted by**: TS parser (NestJS event handler / emitter calls). Python parser does not currently emit events.

**Common queries**:

```cypher
// Events with both a handler and an emitter (closed loop)
MATCH (e:Event)<-[:EMITS_EVENT]-(:Method)
MATCH (e)<-[:HANDLES_EVENT]-(:Method)
RETURN DISTINCT e.name
```

### 2.11 `AtomNode` → `:Atom`

**Purpose**: a Jotai (or similar) state atom, declared at module scope in a TS/TSX file.

**Properties**:

| Name | Type | Description |
|---|---|---|
| `id` | string | `atom:<file>#<name>`. Unique. |
| `name` | string | Atom variable name. |
| `file` | string | Owning file. |
| `family` | bool | True if the atom was created with `atomFamily(...)` (parameterised atoms). |

**Emitted by**: TS parser (frontend-targeted Stage 8 pass).

**Common queries**:

```cypher
// Most-read atoms
MATCH (:Function)-[r:READS_ATOM]->(a:Atom)
RETURN a.name, a.file, count(r) AS reads ORDER BY reads DESC LIMIT 10

// Orphan atoms (defined, never read or written)
MATCH (a:Atom) WHERE NOT (:Function)-[:READS_ATOM|WRITES_ATOM]->(a)
RETURN a.name, a.file
```

### 2.12 `EnvVarNode` → `:EnvVar`

**Purpose**: an environment variable referenced from code (e.g. `process.env.FOO`, `os.environ['BAR']`, `os.getenv("BAZ")`). Singleton — one node per distinct name.

**Properties**:

| Name | Type | Description |
|---|---|---|
| `name` | string | Env var name. Unique. |

**Emitted by**: both parsers.

**Common queries**:

```cypher
// Env vars and the files that read them
MATCH (f:File)-[:READS_ENV]->(e:EnvVar) RETURN e.name, collect(f.path)
```

### 2.13 `RouteNode` → `:Route`

**Purpose**: a frontend route declaration (e.g. React Router `<Route path="/x" element={<Home/>} />`).

**Properties**:

| Name | Type | Description |
|---|---|---|
| `id` | string | `route:<path>@<file>`. Unique. |
| `path` | string | URL path. |
| `component_name` | string | Name of the component rendered at this route. |
| `file` | string | File where the route is declared. |

**Emitted by**: TS parser. Routes are persisted as nodes but not currently linked by edges from the loader; they're available for ad-hoc queries.

**Common queries**:

```cypher
MATCH (r:Route) RETURN r.path, r.component_name LIMIT 20
```

### 2.14 `ExternalNode` → `:External`

**Purpose**: an unresolved import target — a third-party package or a path the resolver couldn't pin down. One node per distinct specifier.

**Properties**:

| Name | Type | Description |
|---|---|---|
| `specifier` | string | The raw import string, e.g. `"react"`, `"@nestjs/common"`, `"lodash/fp"`. Unique. |

**Emitted by**: the loader, when an `IMPORTS` edge has `props.external == true`.

**Common queries**:

```cypher
// Most-imported third-party packages
MATCH (:File)-[:IMPORTS_EXTERNAL]->(x:External)
RETURN x.specifier, count(*) AS uses ORDER BY uses DESC LIMIT 20
```

### 2.15 `EdgeGroupNode` → `:EdgeGroup`

**Purpose**: hyperedge intermediary for N-ary relationships. See [`hyperedges.md`](hyperedges.md) for the full pattern.

**Properties**:

| Name | Type | Description |
|---|---|---|
| `id` | string | `edgegroup:<kind>:<name>` (protocol) or `community:<id>` (Leiden). Unique. |
| `name` | string | Human-readable label. |
| `kind` | string | Discriminator: `"protocol_implementers"` or `"community"`. |
| `node_count` | int | Member count at creation time. |
| `confidence` | float | 1.0 for deterministic; variable for statistical groupings. |

**Emitted by**: `resolver.link_cross_file()` for protocol implementers; `analyze.persist_communities()` for Leiden communities.

### Singleton helper labels

Three more node labels exist but aren't backed by a dataclass — they're singleton MERGE'd by the loader from edge metadata:

| Label | Key | Source |
|---|---|---|
| `:Hook` | `name` | `USES_HOOK` edge `props.hook` |
| `:Decorator` | `name` | `DECORATED_BY` edge `dst_id` (`dec:<name>`) |
| `:Author`, `:Team` | `email` / `name` | Ownership pass (Phase 7) |

---

## 3. Edge catalogue

Every relationship has `confidence` + `confidence_score` properties. The "Default confidence" column below is the value emitted at write time; see [`confidence.md`](confidence.md) for the full per-strategy breakdown.

### 3.1 Imports

| Edge | From → To | Emitted when | Default confidence |
|---|---|---|---|
| `IMPORTS` | `:File` → `:File` | An import statement resolves to a known file in the index. Carries `specifier`, `type_only` props. | `EXTRACTED` 1.0 (direct/relative), `INFERRED` 0.8-0.9 (alias/workspace/barrel) |
| `IMPORTS_SYMBOL` | `:File` → `:File` | A *named* symbol is imported (`import { Foo } from './x'`). Carries `symbol` (the imported name) and `type_only`. Multiple `IMPORTS_SYMBOL` edges may coexist between the same file pair, one per symbol. | Same as `IMPORTS` |
| `IMPORTS_EXTERNAL` | `:File` → `:External` | The import target couldn't be resolved to an in-repo file — third-party package, missing module, deliberate external. | `EXTRACTED` 1.0 |

### 3.2 Definitions (file → child)

| Edge | From → To | Emitted when | Default confidence |
|---|---|---|---|
| `DEFINES_CLASS` | `:File` → `:Class` | A class is declared in the file. | `EXTRACTED` 1.0 |
| `DEFINES_FUNC` | `:File` → `:Function` | A module-scope function is declared. | `EXTRACTED` 1.0 |
| `DEFINES_IFACE` | `:File` → `:Interface` | A TypeScript `interface` is declared. | `EXTRACTED` 1.0 |
| `DEFINES_ATOM` | `:File` → `:Atom` | A Jotai-style atom is declared at module scope. | `EXTRACTED` 1.0 |
| `HAS_METHOD` | `:Class` → `:Method` | A method is declared in the class body. | `EXTRACTED` 1.0 |
| `HAS_COLUMN` | `:Class` → `:Column` | An entity field is declared with a `@Column` / `Column(...)` / `models.XxxField(...)` call. | `EXTRACTED` 1.0 |

### 3.3 Calls

| Edge | From → To | Emitted when | Default confidence |
|---|---|---|---|
| `CALLS` | `:Method` → `:Method` | A method body invokes another method. Carries `resolution` prop: `"this"`, `"this.<field>"`, `"super"`, or `"name"`. | `EXTRACTED` 1.0 (`this`/`self`), `INFERRED` 0.5-0.7 (everything else) |
| `CALLS_ENDPOINT` | `:Method` \| `:Function` → `:Endpoint` | Code makes an HTTP call (`fetch`, `axios`, `httpx`) whose URL pattern matches an endpoint's `path`. Carries `url`. | `INFERRED` 0.7 |

### 3.4 Inheritance

| Edge | From → To | Emitted when | Default confidence |
|---|---|---|---|
| `EXTENDS` | `:Class` → `:Class` | `class Foo extends Bar` (TS) or `class Foo(Bar)` (Python). Resolved by name in the second pass. | `EXTRACTED` 1.0 |
| `IMPLEMENTS` | `:Class` → `:Class` | `class Foo implements IBar` (TS) or `class Foo(typing.Protocol)` subclasses. The target may be a regular class, an interface promoted to class, or a Protocol. | `EXTRACTED` 1.0 |

### 3.5 Dependency injection (NestJS)

| Edge | From → To | Emitted when | Default confidence |
|---|---|---|---|
| `INJECTS` | `:Class` → `:Class` | A class constructor accepts another class as a parameter (DI). | `EXTRACTED` 1.0 |
| `PROVIDES` | `:Class` (`:Module`) → `:Class` | A `@Module({ providers: [X] })` declares X as a provider. | `EXTRACTED` 1.0 |
| `EXPORTS_PROVIDER` | `:Class` (`:Module`) → `:Class` | A `@Module({ exports: [X] })` re-exports a provider. | `EXTRACTED` 1.0 |
| `IMPORTS_MODULE` | `:Class` (`:Module`) → `:Class` (`:Module`) | A `@Module({ imports: [OtherModule] })` declaration. | `EXTRACTED` 1.0 |
| `DECLARES_CONTROLLER` | `:Class` (`:Module`) → `:Class` (`:Controller`) | A `@Module({ controllers: [X] })` declaration. | `EXTRACTED` 1.0 |
| `REPOSITORY_OF` | `:Class` → `:Class` | A class injects `Repository<EntityFoo>` — links the class to the entity it works with. | `EXTRACTED` 1.0 |

### 3.6 HTTP / GraphQL

| Edge | From → To | Emitted when | Default confidence |
|---|---|---|---|
| `EXPOSES` | `:Class` (`:Controller`) → `:Endpoint` | A controller class declares an endpoint via decorators. **Or** `:File` → `:Endpoint` for module-level handlers (FastAPI/Flask `@app.get`). | `EXTRACTED` 1.0 |
| `HANDLES` | `:Method` → `:Endpoint` \| `:GraphQLOperation` | The method is the implementation body for the endpoint or GraphQL operation. | `EXTRACTED` 1.0 |
| `RESOLVES` | `:Class` (`:Resolver`) → `:GraphQLOperation` | A `@Resolver`-decorated class declares a `@Query` / `@Mutation` / `@Subscription`. | `EXTRACTED` 1.0 |
| `RETURNS` | `:GraphQLOperation` → `:Class` | The operation's return type is a known entity / DTO class. | `EXTRACTED` 1.0 |
| `USES_OPERATION` | `:Method` \| `:Function` → `:GraphQLOperation` | A frontend caller issues a GraphQL operation by name (gql tag literal). Carries `op_name`. | `INFERRED` 0.7 |

### 3.7 Frontend (React + state)

| Edge | From → To | Emitted when | Default confidence |
|---|---|---|---|
| `RENDERS` | `:Function` → `:Function` | A component returns JSX that includes another component (`<Foo />`). Resolved by name. | `INFERRED` 0.8 |
| `USES_HOOK` | `:Function` → `:Hook` | A component calls a hook (`useState`, `useEffect`, custom `useFoo`). Carries `hook` prop. | `EXTRACTED` 0.9 |
| `READS_ATOM` | `:Function` → `:Atom` | A component reads an atom (`useAtomValue(fooAtom)`, `useAtom(fooAtom)`). | `EXTRACTED` 1.0 |
| `WRITES_ATOM` | `:Function` → `:Atom` | A component writes an atom (`useSetAtom(fooAtom)`, the setter from `useAtom`). | `EXTRACTED` 1.0 |
| `READS_ENV` | `:File` → `:EnvVar` | The file references `process.env.X` or `os.environ['X']`. | `EXTRACTED` 1.0 |

### 3.8 Decorators

| Edge | From → To | Emitted when | Default confidence |
|---|---|---|---|
| `DECORATED_BY` | `:Class` \| `:Function` \| `:Method` → `:Decorator` | The target carries an `@Decorator(...)` (TS) or `@decorator` (Python). The destination is a singleton `:Decorator` node keyed by name. | `EXTRACTED` 1.0 |

### 3.9 Tests

| Edge | From → To | Emitted when | Default confidence |
|---|---|---|---|
| `TESTS` | `:File` (`:TestFile`) → `:File` | A test file pairs with a production peer by filename: TS `foo.spec.ts` ↔ `foo.ts`; Python `test_foo.py` ↔ `foo.py` (same directory only). | `INFERRED` 0.5 |
| `TESTS_CLASS` | `:File` (`:TestFile`) → `:Class` | A test file's `describe('FooService', ...)` block names a class — link to that class by name. | `INFERRED` 0.6 |

### 3.10 Events (NestJS event emitter)

| Edge | From → To | Emitted when | Default confidence |
|---|---|---|---|
| `HANDLES_EVENT` | `:Method` → `:Event` | Method has `@OnEvent('user.created')` or similar. | `EXTRACTED` 1.0 |
| `EMITS_EVENT` | `:Method` → `:Event` | Method body calls `eventEmitter.emit('user.created', ...)`. | `EXTRACTED` 1.0 |

### 3.11 Ownership (Phase 7 — git + CODEOWNERS)

| Edge | From → To | Emitted when | Default confidence |
|---|---|---|---|
| `LAST_MODIFIED_BY` | `:File` → `:Author` | git log most-recent commit on the file. Carries `at` (timestamp). | `EXTRACTED` 1.0 |
| `CONTRIBUTED_BY` | `:File` → `:Author` | git log all commits on the file. Carries `commits` (count). | `EXTRACTED` 1.0 |
| `OWNED_BY` | `:File` → `:Team` | CODEOWNERS file matches the file path to a team. | `EXTRACTED` 1.0 |

### 3.12 Packaging

| Edge | From → To | Emitted when | Default confidence |
|---|---|---|---|
| `BELONGS_TO` | `:File` → `:Package` | One per file. Redundant with `File.package` but lets you write one-hop pattern queries. | `EXTRACTED` 1.0 |

### 3.13 Hyperedges

| Edge | From → To | Emitted when | Default confidence |
|---|---|---|---|
| `MEMBER_OF` | any → `:EdgeGroup` | A node participates in a group (protocol implementers, Leiden community). See [`hyperedges.md`](hyperedges.md). | `EXTRACTED` 1.0 |

### 3.14 Other

| Edge | From → To | Emitted when | Default confidence |
|---|---|---|---|
| `RELATES_TO` | `:Class` (`:Entity`) → `:Class` (`:Entity`) | TypeORM `@OneToMany` / `@ManyToOne` / `@ManyToMany` / `@OneToOne` between entities. Carries `kind` (relation kind) and `field` (field name on the source entity). | `EXTRACTED` 1.0 |

---

## 4. Indexing phases

The loader writes nodes and edges in nine logical phases, ordered so each phase can rely on earlier ones. Within `loader.load()` everything happens in one Neo4j session, but the phases are conceptually distinct:

1. **Imports (Phase 1)** — `:File` nodes, `:External` nodes, `IMPORTS`, `IMPORTS_SYMBOL`, `IMPORTS_EXTERNAL`. Resolved cross-file by `resolver.py` using `tsconfig.json` paths, monorepo workspaces, and `__init__.py` / `index.ts` barrels.
2. **Definitions (Phase 1, same pass)** — `:Class`, `:Function`, `:Interface`, `:Method` plus their `DEFINES_*` / `HAS_METHOD` edges. Specialised labels (`:Component`, `:Module`, `:Entity`, `:Resolver`, `:Controller`) are added here.
3. **TypeORM (Phase 2)** — `:Column` nodes with `HAS_COLUMN`, `RELATES_TO` between entities, `REPOSITORY_OF` from the DI scan.
4. **GraphQL + HTTP (Phase 3)** — `:GraphQLOperation` and `:Endpoint` nodes; `EXPOSES`, `HANDLES`, `RESOLVES`, `RETURNS`, `CALLS_ENDPOINT`, `USES_OPERATION` edges.
5. **Method call graph (Phase 4)** — `CALLS` edges between methods. Receiver-kind heuristics (`this`, `this.<field>`, `super`, bare name) drive the per-edge confidence score.
6. **NestJS modules (Phase 5)** — `PROVIDES`, `EXPORTS_PROVIDER`, `IMPORTS_MODULE`, `DECLARES_CONTROLLER` edges. Resolved by class name.
7. **Tests + events (Phase 6)** — `TESTS`, `TESTS_CLASS` (filename + describe-block heuristics); `HANDLES_EVENT`, `EMITS_EVENT`; the `:TestFile` label.
8. **Ownership (Phase 7)** — `:Author`, `:Team` nodes; `LAST_MODIFIED_BY`, `CONTRIBUTED_BY`, `OWNED_BY` edges. Skipped when `--skip-ownership` is passed; required for `/who-owns`.
9. **Frontend / atoms (Phase 8)** — `:Atom`, `:Route`, `:EnvVar` nodes; `DEFINES_ATOM`, `READS_ATOM`, `WRITES_ATOM`, `READS_ENV`, `RENDERS`, `USES_HOOK` edges.
10. **Packaging (Phase 9)** — `:Package` nodes (one per `-p <path>` scope) and `BELONGS_TO` edges. Implemented as a top-of-load step, but logically last because it summarises the whole pass.
11. **Hyperedges (Phase 10)** — `:EdgeGroup` nodes for protocol implementers (during indexing) and Leiden communities (via `codegraph analyze --leiden`). `MEMBER_OF` edges from each member.

---

## 5. Common query patterns

A handful of high-leverage patterns; the full catalogue lives in [`queries.md`](queries.md).

### Find a class by name

```cypher
MATCH (c:Class) WHERE c.name = 'Neo4jLoader'
RETURN c.name, c.file, c.is_injectable
```

### Blast radius of a function or method

```cypher
// Everything that calls `Neo4jLoader.load`
MATCH (caller:Method)-[:CALLS*1..3]->(target:Method)
WHERE target.name = 'load'
  AND target.class_id CONTAINS '#Neo4jLoader'
RETURN DISTINCT caller.file, caller.name
```

### Endpoint inventory by method

```cypher
MATCH (e:Endpoint) RETURN e.method, count(*) AS routes
ORDER BY routes DESC
```

### React hook usage hot list

```cypher
MATCH (:Function)-[:USES_HOOK]->(h:Hook)
RETURN h.name, count(*) AS uses
ORDER BY uses DESC LIMIT 20
```

### Most-injected services

```cypher
MATCH (c:Class)-[:INJECTS]->(target:Class)
RETURN target.name, target.file, count(c) AS injectors
ORDER BY injectors DESC LIMIT 10
```

### High-confidence import cycles only

```cypher
MATCH path = (a:File)-[:IMPORTS*2..6]->(a)
WHERE ALL(r IN relationships(path) WHERE r.confidence_score >= 0.9)
RETURN [n IN nodes(path) | n.path] AS cycle, length(path) AS hops
ORDER BY hops LIMIT 20
```

### Files by team owner

```cypher
MATCH (f:File)-[:OWNED_BY]->(t:Team)
WITH t, count(f) AS files
RETURN t.name, files ORDER BY files DESC
```

---

## See also

- [`confidence.md`](confidence.md) — full confidence taxonomy and per-strategy scoring.
- [`hyperedges.md`](hyperedges.md) — `:EdgeGroup` + `:MEMBER_OF` pattern for N-ary relationships.
- [`arch-policies.md`](arch-policies.md) — built-in conformance policies that consume this schema.
- [`queries.md`](queries.md) — full Cypher cookbook.
- [`codegraph/schema.py`](../codegraph/schema.py) — the dataclass definitions and constants this doc reflects.
- [`codegraph/loader.py`](../codegraph/loader.py) — the Neo4j writer (constraints, indexes, MERGE patterns).
