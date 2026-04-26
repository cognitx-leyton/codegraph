### TypeScript / TSX (plain) — always applicable when any `.ts` / `.tsx` file is indexed

**Node types extracted:**
- `:File` — every `.ts` / `.tsx` file walked (`language='ts'` or `'tsx'`,
  `loc`, flags: `is_test`, `is_controller`, `is_injectable`, `is_module`,
  `is_component`, `is_entity`, `is_resolver` — propagated from class flags).
- `:Class` — every `class` and `abstract class` declaration. Properties:
  `name`, `file`, `is_abstract`, `is_controller`, `is_injectable`, `is_module`,
  `is_entity`, `is_resolver`, `base_path` (for routed controllers),
  `table_name` (for ORM entities).
- `:Function` — every top-level `function` declaration. Properties: `name`,
  `file`, `exported`, `is_component` (true when return type is JSX).
- `:Method` — every method inside a class. Properties: `name`, `class_id`,
  `file`, `is_static`, `is_async`, `is_constructor`, `visibility` (`public`
  / `private` / `protected`), `return_type`, `params_json`.
- `:Interface` — every `interface` declaration.
- `:Decorator` — one per unique decorator name.

**Edge types extracted:**
- `(:File)-[:DEFINES_CLASS]->(:Class)`.
- `(:File)-[:DEFINES_FUNC]->(:Function)`.
- `(:File)-[:DEFINES_IFACE]->(:Interface)`.
- `(:Class)-[:HAS_METHOD]->(:Method)`.
- `(:Class|:Method|:Function)-[:DECORATED_BY]->(:Decorator)`.
- `(:File)-[:IMPORTS]->(:File)` — resolved.
- `(:File)-[:IMPORTS_EXTERNAL]->(:External)` — third-party.
- `(:File)-[:IMPORTS_SYMBOL {symbol}]->(:File)` — for named imports.
- `(:Class)-[:EXTENDS]->(:Class)` — class inheritance.
- `(:Class)-[:IMPLEMENTS]->(:Interface)` — interface implementation.
- `(:Class|:Method|:Function)-[:CALLS]->(:Method|:Function)` — method call graph.

**Signals / patterns the parser recognises:**
- `class Foo extends Bar implements IBaz {}` — bases captured for both
  `EXTENDS` and `IMPLEMENTS`.
- `abstract class Foo { abstract m(): void; }` — `is_abstract=true` on Class.
- `static`, `private`, `protected`, `public`, `async`, `constructor` modifiers.
- Arrow functions assigned to module-level `const` are NOT yet captured
  as `:Function` nodes (Stage-2 work).

**Known gaps — DO NOT flag as bugs:**
- `const Foo = (...) => ...` arrow-function form is recognised as a class
  property but not extracted as `:Function` at module level.
- TypeScript namespaces (`namespace Foo { ... }`) and module declarations
  are not modelled.
- Type aliases (`type Foo = ...`) are not extracted as nodes.
- Enums are not extracted as separate node types — they appear as classes.
- JSDoc `@deprecated` and other custom JSDoc tags are not parsed.

### NestJS — only when `:Package {framework: 'NestJS'}` exists

**Node types extracted:**
- `:Class` flags: `is_controller`, `is_injectable`, `is_module`, `is_resolver`.
- `:Endpoint` — every HTTP-method-decorated handler. Properties: `method`
  (HTTP verb), `path`, `controller_class`, `file`, `handler` (method name).
- `:GraphQLOperation` — for `@Query`, `@Mutation`, `@Subscription`,
  `@ResolveField`. Properties: `op_type` (query/mutation/subscription),
  `name`, `return_type`, `file`, `resolver_class`, `handler`.

**Edge types extracted:**
- `(:Class)-[:EXPOSES]->(:Endpoint)` — controller exposes routes.
- `(:Method)-[:HANDLES]->(:Endpoint)` — handler method.
- `(:Class)-[:RESOLVES]->(:GraphQLOperation)` — resolver class.
- `(:Method)-[:HANDLES]->(:GraphQLOperation)` — resolver method.
- `(:Class)-[:INJECTS]->(:Class)` — DI relationships from constructor params.
- `(:Module)-[:PROVIDES]->(:Class)` — module's `providers` array.
- `(:Module)-[:DECLARES_CONTROLLER]->(:Class)` — module's `controllers` array.
- `(:Module)-[:IMPORTS_MODULE]->(:Module)` — module's `imports` array.
- `(:Module)-[:EXPORTS_PROVIDER]->(:Class)` — module's `exports` array.

**Signals / patterns the parser recognises:**
- `@Controller('users')` → `is_controller=true`, `base_path='users'`.
- `@Controller()` → `is_controller=true`, no base path.
- `@Injectable()` → `is_injectable=true`.
- `@Module({ providers: [], controllers: [], imports: [], exports: [] })`
  → `is_module=true` plus PROVIDES / IMPORTS_MODULE / DECLARES_CONTROLLER /
  EXPORTS_PROVIDER edges.
- HTTP method decorators: `@Get`, `@Post`, `@Put`, `@Patch`, `@Delete`,
  `@Options`, `@Head`, `@All` (all eight verbs).
- GraphQL decorators: `@Resolver`, `@Query`, `@Mutation`, `@Subscription`,
  `@ResolveField`.
- Constructor injection: `constructor(private readonly userService: UserService) {}`
  → `INJECTS` edge from the containing class to `UserService`.

**Known gaps — DO NOT flag as bugs:**
- Custom decorators that wrap NestJS decorators (`@Public()`, `@Roles(...)`)
  are captured as `:Decorator` nodes but not specially mapped.
- Guards, pipes, interceptors, filters are recognised but not given
  dedicated edges.
- Dynamic modules (`MyModule.forRoot(...)`) are partially supported — the
  static analyser may not resolve runtime configuration.

### TypeORM — only when `typeorm` is in dependencies

**Node types extracted:**
- `:Class` with `is_entity=true` and `table_name`.
- `:Column` — for every `@Column`, `@PrimaryColumn`, `@PrimaryGeneratedColumn`,
  `@CreateDateColumn`, `@UpdateDateColumn`, `@DeleteDateColumn`,
  `@VersionColumn`, `@ObjectIdColumn` decorator on a class field.

**Edge types extracted:**
- `(:Class)-[:HAS_COLUMN]->(:Column)`.
- `(:Class)-[:RELATES_TO]->(:Class)` — `@ManyToOne`, `@OneToMany`,
  `@OneToOne`, `@ManyToMany` between entities.
- `(:Class)-[:REPOSITORY_OF]->(:Class)` — when `Repository<Entity>` appears
  in a service's constructor injection.

**Signals / patterns the parser recognises:**
- `@Entity('users')` or `@Entity({ name: 'users' })` → `is_entity=true`,
  `table_name='users'`.
- `@Entity()` → `is_entity=true`, table name defaults to lowercased class name.
- `@Column({ nullable: true, unique: true })` → `:Column` with those flags.
- `@PrimaryGeneratedColumn()` → `:Column` with `primary=true`, `generated=true`.

**Known gaps — DO NOT flag as bugs:**
- Embedded entities (`@Embedded(...)`) are recognised but flattened — the
  embedded fields don't get separate `:Column` nodes.
- Entity inheritance with `@TableInheritance` is partial.
- Custom column transformers are not modelled.

### React — only when `:Package {framework: 'React'}` or `'React (TypeScript)'` or `'Next.js'` exists

**Node types extracted:**
- `:Function` with `is_component=true` — function declarations whose body
  returns JSX.
- `:Hook` — references to React hooks (`useState`, `useEffect`, …).

**Edge types extracted:**
- `(:Function)-[:RENDERS]->(:Function)` — when a component's JSX includes
  another component by name.
- `(:Function)-[:USES_HOOK]->(:Hook)` — when a component calls a hook.

**Signals / patterns the parser recognises:**
- `function Foo() { return <div />; }` — function declaration returning JSX
  → `is_component=true`.
- `<MyComponent prop={x} />` inside JSX → `RENDERS` edge.
- `useState(...)`, `useEffect(...)`, `useMemo(...)`, `useCallback(...)`,
  `useRef(...)`, `useContext(...)`, `useReducer(...)`, plus library hooks
  (`useQuery`, `useMutation`, `useAtom`, etc.).

**Known gaps — DO NOT flag as bugs:**
- Arrow-function components (`const Foo = () => <div />`) are NOT yet
  captured as `:Function {is_component:true}`. Stage 2.
- HOC patterns (`withFoo(Bar)`) and forwardRef wrappings are not unwrapped.
- Class components (`class Foo extends Component`) are recognised as classes
  but not flagged as components.
- Component composition through children prop is not traced.

### GraphQL (NestJS-style code-first) — only when `@nestjs/graphql` is in dependencies

**Node types extracted:**
- `:GraphQLOperation` — see NestJS section above.

**Edge types extracted:**
- `(:Function)-[:USES_OPERATION]->(:GraphQLOperation)` — when a frontend
  component or function references an operation by name.

**Signals / patterns the parser recognises:**
- `@Query(() => User)`, `@Mutation(() => Boolean)`, `@Subscription(...)`
  inside a resolver class.
- Operation name from the method name (or `name:` option in the decorator).
- Literal `gql\`...\`` template strings → recorded as `gql_literals` for
  cross-layer wiring.

**Known gaps — DO NOT flag as bugs:**
- Schema-first GraphQL (separate `.graphql` files) is not parsed — only
  code-first.
- Federation directives are captured as decorator names but not modelled.
- Subscription resolvers' `@Subscription(filter:...)` filter logic is not
  inspected.
