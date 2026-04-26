### Python (plain) — always applicable when any `.py` file is indexed

**Node types extracted:**
- `:File` — every `.py` file walked (`language='py'`, `loc`, `is_test`).
- `:Class` — every `class` definition (module-level and nested). Properties:
  `name`, `file`, `is_abstract` (true when ABC/ABCMeta in MRO).
- `:Function` — every `def` at module level (NOT methods inside classes).
  Properties: `name`, `file`, `exported` (always true for module-level Python),
  `docstring` (PEP 257 first statement), `return_type` (raw annotation text),
  `params_json`.
- `:Method` — every `def` inside a class. Properties: `name`, `class_id`,
  `file`, `is_static` (via `@staticmethod`), `is_constructor` (`__init__`),
  `visibility` (`public` / `private` per leading underscore; dunder always
  public), `return_type`, `params_json`, `docstring`.
- `:Decorator` — one node per unique decorator name across the codebase
  (e.g. `dataclass`, `app.get`, `staticmethod`).

**Edge types extracted:**
- `(:File)-[:DEFINES_CLASS]->(:Class)` — for every class.
- `(:File)-[:DEFINES_FUNC]->(:Function)` — for every module-level function.
- `(:Class)-[:HAS_METHOD]->(:Method)` — for every method.
- `(:Class|:Function|:Method)-[:DECORATED_BY]->(:Decorator)` — once per decorator
  application (multiple decorators on the same target produce multiple edges).
- `(:File)-[:IMPORTS]->(:File)` — resolved relative imports (`from .foo import x`).
- `(:File)-[:IMPORTS_EXTERNAL]->(:External)` — unresolvable imports (third-party).
- `(:File)-[:IMPORTS_SYMBOL {symbol}]->(:File)` — for `from x import y` named imports.
- `(:Class)-[:EXTENDS]->(:Class)` — for base classes resolvable in the indexed set.
- `(:Class|:Method|:Function)-[:CALLS]->(:Method|:Function)` — Phase-4 method
  call graph. Confidence varies: `self.foo()` is EXTRACTED (1.0), bare `foo()`
  is INFERRED (~0.5).

**Signals / patterns the parser recognises:**
- `class Foo(Bar, Baz):` — class definition with bases.
- `class Foo(ABC):` or `class Foo(metaclass=ABCMeta):` → `is_abstract=true`.
- `@staticmethod def foo(...)` → `is_static=true`.
- `def __init__(self, ...)` → `is_constructor=true`.
- Triple-quoted string as the first statement → `docstring`.
- `def foo(a: int, b: str = "x", *args, **kwargs) -> bool:` → all parts captured
  in `params_json` and `return_type`.

**Known Stage-2 gaps — DO NOT flag as bugs:**
- Async detection: `async def` is parsed but `is_async` is always `false` on
  `:Method`. Stage 2 will populate it.
- Python `Protocol` and `ABC` classes are NOT mapped to `:Interface` nodes
  (TypeScript-only today).
- Pytest fixtures (`@pytest.fixture`) and parametrize markers are recognised
  as decorators but no `:Fixture` node type exists yet.
- `typing.TypeVar`, `Generic`, `Annotated` are not extracted as separate
  entities.
- Module-level type aliases (`MyType = list[int]`) are not extracted.

### FastAPI — only when `:Package {framework: 'FastAPI'}` exists

**Node types extracted:**
- `:Endpoint` — every route handler (Stage-2 work, partial). Properties:
  `method` (HTTP verb upper-case), `path`, `controller_class` (empty for
  function-style handlers), `file`, `handler` (function or method name).

**Edge types extracted:**
- `(:File|:Class)-[:EXPOSES]->(:Endpoint)` — for the file or controller class.
- `(:Function|:Method)-[:HANDLES]->(:Endpoint)` — for the handler.

**Signals / patterns the parser recognises:**
- `@app.get('/users')`, `@app.post(...)`, `@app.put(...)`, `@app.delete(...)`,
  `@app.patch(...)`, `@app.head(...)`, `@app.options(...)` — top-level app.
- `@router.get('/users')` etc. on `APIRouter` instances — common in modular
  FastAPI apps.
- Path parameters in the URL string (`/users/{user_id}`) are preserved
  verbatim in `Endpoint.path`.

**Known Stage-2 gaps — DO NOT flag as bugs:**
- Dependency injection via `Depends(...)` is not yet linked as `:INJECTS`
  edges. The decorator is captured but the dependency target is not resolved.
- Pydantic `BaseModel` request/response bodies are not extracted as
  `:Schema` or `:Column` nodes.
- WebSocket routes (`@app.websocket(...)`) are recognised as decorators but
  no separate node type exists.
- Background tasks (`BackgroundTasks`) are not modelled.

### Flask — only when `:Package {framework: 'Flask'}` exists

**Signals / patterns the parser recognises:**
- `@app.route('/users', methods=['GET'])` and `@app.route('/users')` (default
  GET) at module level.
- `@bp.route(...)` and `@blueprint.route(...)` for `Blueprint` instances.
- HTTP method extracted from the `methods=` kwarg; defaults to `GET` when
  the kwarg is absent.

**Known Stage-2 gaps — DO NOT flag as bugs:**
- Class-based views (`MethodView`, `View`) are recognised as classes but the
  individual HTTP-method dispatchers (`def get(self): ...`) are not yet
  linked to `:Endpoint` nodes.
- `before_request`, `after_request`, `errorhandler` decorators are captured
  on `:Decorator` but no special edge.

### Django — only when `:Package {framework: 'Django'}` exists

**Node types extracted:**
- `:Class` with `is_entity=true` and `table_name` — Django models.
- `:Column` — model fields. Properties: `entity_id`, `name`, `type` (e.g.
  `CharField`, `IntegerField`), `nullable`, `primary`.

**Edge types extracted:**
- `(:Class)-[:HAS_COLUMN]->(:Column)` — for every model field.

**Signals / patterns the parser recognises:**
- Field assignments inside a `models.Model` subclass:
  `name = models.CharField(max_length=100, null=True)`.
- 27 Django field types: `CharField`, `IntegerField`, `TextField`,
  `BooleanField`, `DateField`, `DateTimeField`, `EmailField`, `URLField`,
  `FloatField`, `DecimalField`, `JSONField`, `UUIDField`, `SlugField`,
  `BinaryField`, `FileField`, `ImageField`, `FilePathField`, `IPAddressField`,
  `GenericIPAddressField`, `PositiveIntegerField`, `PositiveSmallIntegerField`,
  `SmallIntegerField`, `BigIntegerField`, `DurationField`, `TimeField`,
  `AutoField`, `BigAutoField`.
- `ForeignKey(...)`, `OneToOneField(...)`, `ManyToManyField(...)` → relation
  records (Stage-2: not yet linked as `:RELATES_TO` edges).

**Known Stage-2 gaps — DO NOT flag as bugs:**
- Django views (function-based, class-based, generic views) are NOT extracted
  as `:Endpoint` — Stage 2 will read `urls.py` to wire URL → view → endpoint.
- Django admin registrations are not modelled.
- Custom managers / querysets are recognised as classes but not specially.
- Form classes are not extracted as schemas.

### SQLAlchemy — only when `sqlalchemy` is in dependencies

**Node types extracted:**
- `:Class` with `is_entity=true` and `table_name` — when the class inherits
  from `Base`, `DeclarativeBase`, or `Model`.
- `:Column` — for `Column(...)` and `mapped_column(...)` calls in the class
  body.

**Edge types extracted:**
- `(:Class)-[:HAS_COLUMN]->(:Column)`.

**Signals / patterns the parser recognises:**
- `__tablename__ = 'users'` assignment → `Class.table_name`.
- `id = Column(Integer, primary_key=True)` → `:Column {name:'id',
  type:'Integer', primary:true}`.
- `name: Mapped[str] = mapped_column(String(100))` → `:Column {name:'name',
  type:'String'}`.
- `relationship(...)` and `ForeignKey(...)` → recorded as relations
  (Stage-2: not yet linked as `:RELATES_TO`).

**Known Stage-2 gaps — DO NOT flag as bugs:**
- SQLAlchemy `__table_args__` constraints (`UniqueConstraint`, `Index`) are
  not extracted as separate nodes.
- Declarative event listeners (`@event.listens_for`) are captured as
  decorators but no special edge.
- Type-hint-driven column inference (PEP 484 `Mapped[Optional[int]]`) is
  partial — the type extraction takes the literal annotation text.
