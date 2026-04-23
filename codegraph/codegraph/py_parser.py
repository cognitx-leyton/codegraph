"""Python frontend for codegraph (Stage 1 — minimum viable).

Walks a Python source file with ``tree-sitter-python`` and emits the same
:class:`ParseResult` dataclass that :class:`~.parser.TsParser` produces. The
downstream resolver / loader pipeline is language-agnostic and consumes both.

Scope (Stage 1):

- Module files (``.py``) → :class:`~.schema.FileNode` with ``language="py"``
- Top-level classes → :class:`~.schema.ClassNode`
- Top-level functions → :class:`~.schema.FunctionNode`
- Methods inside classes → :class:`~.schema.MethodNode`
- Imports (``import x``, ``from x import y``, relative ``from .x import y``)
  → :class:`~.schema.ImportSpec`
- Class inheritance → ``class_extends`` name-ref pairs (resolver wires edges)
- Decorators on classes and functions → ``DECORATED_BY`` edges with a
  canonical stringified decorator name (``dataclass``, ``property``,
  ``app.command()``, ``mcp.tool()``, etc.)

Out of scope (Stage 2+):
- Framework detection (Typer / pytest / FastAPI / Flask / Django)
- Route endpoint extraction
- Method call graph
- ORM column detection
- Type annotation extraction
- Python ``Protocol`` / ``ABC`` → :class:`~.schema.InterfaceNode` mapping

Ported to mirror ``TsParser``'s public interface so ``cli._run_index`` can
dispatch by file extension without special-casing downstream code.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any, Optional

try:
    from tree_sitter import Language, Parser
    import tree_sitter_python as tsp
    _LANG_PY: Optional["Language"] = Language(tsp.language())
except ImportError:  # pragma: no cover
    # tree-sitter-python is an optional dep under the `[python]` extra.
    # Importing codegraph.py_parser without it should NOT crash the whole
    # package — we raise a clear error at first use instead.
    _LANG_PY = None


from .schema import (
    ClassNode,
    ColumnNode,
    DECORATED_BY,
    DEFINES_CLASS,
    DEFINES_FUNC,
    Edge,
    EndpointNode,
    EXPOSES,
    FileNode,
    FunctionNode,
    HANDLES,
    HAS_COLUMN,
    HAS_METHOD,
    ImportSpec,
    MethodNode,
    ParseResult,
)


# ── Python route decorator mapping ───────────────────────────────────

# Maps canonical decorator base names (without "()" suffix) to HTTP methods.
# None means the method must be extracted from a `methods=` kwarg (Flask-style).
_PY_ROUTE_DECORATORS: dict[str, Optional[str]] = {}
for _obj in ("app", "router"):
    for _method, _verb in [("get", "GET"), ("post", "POST"), ("put", "PUT"),
                           ("delete", "DELETE"), ("patch", "PATCH"),
                           ("head", "HEAD"), ("options", "OPTIONS")]:
        _PY_ROUTE_DECORATORS[f"{_obj}.{_method}"] = _verb

# Flask-style route() — method extracted from `methods=` kwarg, default GET
for _obj in ("app", "bp", "blueprint"):
    _PY_ROUTE_DECORATORS[f"{_obj}.route"] = None


def _descend(root):
    """Iterative depth-first descent over a tree-sitter subtree.

    Yields every descendant (including ``root``). Uses an explicit stack to
    avoid Python recursion limits on deep method bodies.
    """
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(node.children)


class PyParserUnavailable(RuntimeError):
    """Raised when ``tree-sitter-python`` is not installed.

    The ``[python]`` extra provides it:

        pip install "codegraph[python]"
    """


class PyParser:
    """Stateless Python source parser. One instance per indexing run."""

    def __init__(self) -> None:
        if _LANG_PY is None:
            raise PyParserUnavailable(
                "tree-sitter-python is not installed. Install the [python] extra:\n"
                '    pip install "codegraph[python]"'
            )
        self._parser = Parser(_LANG_PY)

    def parse_file(
        self,
        path: Path,
        rel_path: str,
        package: str,
        is_test: bool = False,
    ) -> Optional[ParseResult]:
        """Parse a single ``.py`` file into a :class:`ParseResult`.

        Returns ``None`` if the file can't be read (matching ``TsParser``'s
        behaviour). tree-sitter-python never raises on a parse — it emits
        ``error`` nodes for malformed regions, which we simply skip.
        """
        try:
            src = path.read_bytes()
        except OSError:
            return None

        tree = self._parser.parse(src)
        loc = src.count(b"\n") + 1

        file_node = FileNode(
            path=rel_path,
            package=package,
            language="py",
            loc=loc,
            is_test=is_test,
        )
        result = ParseResult(file=file_node)
        walker = _PyWalker(src, result)
        walker.walk_module(tree.root_node)
        return result


# ── Walker internals ─────────────────────────────────────────────────


class _PyWalker:
    """Walks a ``module`` root and populates a :class:`ParseResult`.

    Node types used (all from ``tree-sitter-python`` 0.23):
    - ``module``
    - ``class_definition``
    - ``function_definition``
    - ``decorated_definition`` (wraps a class/function with its decorators)
    - ``decorator`` (the ``@expr`` line itself)
    - ``import_statement`` (``import x``, ``import x as y``)
    - ``import_from_statement`` (``from x import y``)
    - ``future_import_statement`` (``from __future__ import ...``)
    - ``try_statement`` (for try/except imports — walked into normally)
    - ``identifier``, ``dotted_name``, ``aliased_import``
    """

    def __init__(self, src: bytes, result: ParseResult) -> None:
        self.src = src
        self.result = result

    # ── text helpers ──────────────────────────────────────────────────

    def _text(self, node) -> str:
        return self.src[node.start_byte:node.end_byte].decode("utf-8", "replace")

    def _child_by_field(self, node, field_name: str):
        return node.child_by_field_name(field_name)

    # ── entry point ───────────────────────────────────────────────────

    def walk_module(self, root) -> None:
        """Walk the top-level statements of a module.

        Iterates children of the ``module`` root and recurses into
        ``try_statement`` / ``if_statement`` bodies so try/except imports
        and conditional imports are captured. Class / function bodies are
        handled by dedicated helpers.
        """
        for child in root.children:
            self._walk_top_stmt(child)

    def _walk_top_stmt(self, node) -> None:
        t = node.type

        if t == "class_definition":
            self._handle_class(node, decorators=[])
        elif t == "function_definition":
            self._handle_function(node, decorators=[])
        elif t == "decorated_definition":
            decorators = [c for c in node.children if c.type == "decorator"]
            target = self._child_by_field(node, "definition")
            if target is None:
                # Fall back: look for the first class_definition / function_definition child.
                for c in node.children:
                    if c.type in ("class_definition", "function_definition"):
                        target = c
                        break
            if target is None:
                return
            if target.type == "class_definition":
                self._handle_class(target, decorators=decorators)
            elif target.type == "function_definition":
                self._handle_function(target, decorators=decorators)
        elif t == "import_statement":
            self._handle_import(node)
        elif t == "import_from_statement":
            self._handle_from_import(node)
        elif t == "future_import_statement":
            # `from __future__ import annotations` and friends — emit as an
            # import for graph completeness but it'll always resolve to
            # `:External {specifier:"__future__"}`.
            spec = ImportSpec(specifier="__future__", symbols=self._from_import_symbols(node))
            self.result.imports.append(spec)
        elif t in ("try_statement", "if_statement", "with_statement"):
            # Walk into the body — catches try/except imports, conditional
            # imports under `if sys.version_info >= (3, 11):`, etc.
            for c in node.children:
                self._walk_top_stmt(c)
        elif t == "block":
            for c in node.children:
                self._walk_top_stmt(c)
        elif t == "except_clause":
            for c in node.children:
                self._walk_top_stmt(c)
        elif t in ("else_clause", "elif_clause", "finally_clause"):
            for c in node.children:
                self._walk_top_stmt(c)
        elif t == "expression_statement":
            # Module-level calls: register_plugin(), main(), etc.
            for c in _descend(node):
                if c.type != "call":
                    continue
                fn = c.child_by_field_name("function")
                if fn is None:
                    continue
                recv_kind, recv_name, target = self._classify_py_call(fn)
                if target:
                    self.result.method_calls.append(
                        (self.result.file.id, recv_kind, recv_name or "", target)
                    )

    # ── imports ───────────────────────────────────────────────────────

    def _handle_import(self, node) -> None:
        """``import x`` or ``import x as y`` (possibly multiple, comma-sep)."""
        for child in node.children:
            if child.type == "dotted_name":
                self.result.imports.append(ImportSpec(
                    specifier=self._text(child),
                    symbols=[],
                ))
            elif child.type == "aliased_import":
                # ``import x as y``
                name = self._child_by_field(child, "name")
                alias = self._child_by_field(child, "alias")
                if name is not None:
                    self.result.imports.append(ImportSpec(
                        specifier=self._text(name),
                        namespace=self._text(alias) if alias else None,
                        symbols=[],
                    ))

    def _handle_from_import(self, node) -> None:
        """``from x import y`` / ``from .x import y`` / ``from ..x import y``.

        tree-sitter-python's ``module_name`` field points at the entire
        module expression — for relative imports that's a ``relative_import``
        wrapper containing the ``import_prefix`` (dots) and an optional
        ``dotted_name``. Unwrap that here.
        """
        module_node = self._child_by_field(node, "module_name")
        dots = 0

        if module_node is not None and module_node.type == "relative_import":
            inner_module = None
            for rc in module_node.children:
                if rc.type == "import_prefix":
                    dots = len(self._text(rc))
                elif rc.type == "dotted_name":
                    inner_module = rc
            module_node = inner_module  # may be None for bare `from . import X`

        if module_node is None and dots == 0:
            return  # malformed

        specifier = ("." * dots) + (self._text(module_node) if module_node else "")
        symbols = self._from_import_symbols(node)
        self.result.imports.append(ImportSpec(
            specifier=specifier,
            symbols=symbols,
        ))

    def _from_import_symbols(self, node) -> list[str]:
        """Extract the imported names from a ``from ... import ...`` node."""
        symbols: list[str] = []
        saw_import = False
        for c in node.children:
            if c.type == "import":
                saw_import = True
                continue
            if not saw_import:
                continue
            if c.type == "dotted_name":
                symbols.append(self._text(c))
            elif c.type == "aliased_import":
                name = self._child_by_field(c, "name")
                if name is not None:
                    symbols.append(self._text(name))
            elif c.type == "wildcard_import":
                symbols.append("*")
        return symbols

    # ── classes ───────────────────────────────────────────────────────

    def _handle_class(self, node, decorators) -> None:
        name_node = self._child_by_field(node, "name")
        if name_node is None:
            return
        name = self._text(name_node)
        rel = self.result.file.path
        cls = ClassNode(name=name, file=rel, is_abstract=False)
        self.result.classes.append(cls)

        # DEFINES_CLASS edge
        self.result.edges.append(Edge(
            kind=DEFINES_CLASS,
            src_id=self.result.file.id,
            dst_id=cls.id,
        ))

        # Base classes → class_extends name-refs + is_abstract + ORM entity detection
        base_names: list[str] = []
        superclasses = self._child_by_field(node, "superclasses")
        if superclasses is not None:
            for c in superclasses.children:
                if c.type in ("identifier", "attribute", "dotted_name"):
                    base_name = self._text(c).split(".")[-1]
                    base_names.append(base_name)
                    if base_name in ("ABC", "ABCMeta"):
                        cls.is_abstract = True
                    self.result.class_extends.append((name, base_name))

        # Detect ORM entities: SQLAlchemy (Base, DeclarativeBase, db.Model)
        # and Django (models.Model, Model)
        _ORM_BASES = {"Base", "DeclarativeBase", "Model"}
        if any(b in _ORM_BASES for b in base_names):
            cls.is_entity = True

        # Class-level decorators
        for dec in decorators:
            dname = self._decorator_name(dec)
            if dname:
                self.result.edges.append(Edge(
                    kind=DECORATED_BY,
                    src_id=cls.id,
                    dst_id=f"dec:{dname}",
                ))

        # Walk body for methods + ORM columns
        body = self._child_by_field(node, "body")
        if body is not None:
            self._walk_class_body(body, cls)
            if cls.is_entity:
                self._scan_orm_columns(body, cls)

    def _walk_class_body(self, body, cls: ClassNode) -> None:
        for child in body.children:
            if child.type == "function_definition":
                self._handle_method(child, cls, decorators=[])
            elif child.type == "decorated_definition":
                decorators = [c for c in child.children if c.type == "decorator"]
                target = self._child_by_field(child, "definition")
                if target is None:
                    for c in child.children:
                        if c.type in ("class_definition", "function_definition"):
                            target = c
                            break
                if target is None:
                    continue
                if target.type == "function_definition":
                    self._handle_method(target, cls, decorators=decorators)
                elif target.type == "class_definition":
                    # Nested class — treat as a top-level class for simplicity.
                    self._handle_class(target, decorators=decorators)

    # ── ORM column detection ───────────────────────────────────────────

    # Column-producing call names (SQLAlchemy + Django)
    _COLUMN_CALLS = {
        "Column", "mapped_column",
        # Django model fields
        "CharField", "IntegerField", "FloatField", "BooleanField",
        "TextField", "DateField", "DateTimeField", "TimeField",
        "DecimalField", "EmailField", "URLField", "UUIDField",
        "SlugField", "FileField", "ImageField", "JSONField",
        "BigIntegerField", "SmallIntegerField", "PositiveIntegerField",
        "PositiveSmallIntegerField", "BinaryField", "DurationField",
        "AutoField", "BigAutoField", "SmallAutoField",
    }

    # Relationship/ForeignKey calls → result.relations
    _RELATION_CALLS = {"relationship", "ForeignKey"}

    def _scan_orm_columns(self, body, cls: ClassNode) -> None:
        """Scan a class body for ORM column and relationship assignments."""
        for child in body.children:
            # Assignments are wrapped in expression_statement → assignment
            target = child
            if target.type == "expression_statement":
                for c in target.children:
                    if c.type == "assignment":
                        target = c
                        break
            if target.type == "assignment":
                self._check_column_assignment(target, cls)

    def _check_column_assignment(self, node, cls: ClassNode) -> None:
        """Check if a statement is a column/relationship assignment."""
        # Find assignment: look for "=" with LHS identifier and RHS call
        # Tree-sitter shapes:
        #   assignment: left=identifier, right=call
        #   assignment: left=identifier, type=..., right=call (annotated)

        lhs = self._child_by_field(node, "left")
        rhs = self._child_by_field(node, "right")

        if lhs is None or rhs is None:
            return

        # Get the column name from LHS
        col_name = None
        if lhs.type == "identifier":
            col_name = self._text(lhs)
        elif lhs.type == "pattern_list":
            return  # tuple unpacking, not a column

        if not col_name or col_name.startswith("_"):
            # Skip __tablename__, __table_args__, etc. — but extract tablename
            if col_name == "__tablename__" and rhs.type == "string":
                cls.table_name = self._strip_quotes(self._text(rhs))
            return

        # Get the call name from RHS
        if rhs.type != "call":
            return

        fn = self._child_by_field(rhs, "function")
        if fn is None:
            return

        # Get the function name (handles `Column(...)`, `models.CharField(...)`)
        call_name = self._text(fn).split(".")[-1]

        if call_name in self._COLUMN_CALLS:
            col_type = self._extract_column_type(rhs)
            # Django fields: the type is the field class name itself (CharField, etc.)
            if not col_type and call_name not in ("Column", "mapped_column"):
                col_type = call_name.replace("Field", "")
            col = ColumnNode(entity_id=cls.id, name=col_name, type=col_type)
            self.result.columns.append(col)
            self.result.edges.append(Edge(
                kind=HAS_COLUMN,
                src_id=cls.id,
                dst_id=f"col:{cls.id}#{col_name}",
            ))
            # Scan Column args for nested ForeignKey/relationship calls
            self._scan_nested_relations(rhs, cls, col_name)
        elif call_name in self._RELATION_CALLS:
            # relationship("Address") or ForeignKey("address.id")
            target = self._call_first_string_arg(rhs)
            if target:
                # Strip table references: "address.id" → "address"
                target = target.split(".")[0]
                self.result.relations.append((cls.name, call_name, col_name, target))

    def _scan_nested_relations(self, call_node, cls: ClassNode, col_name: str) -> None:
        """Scan a Column() call's arguments for nested ForeignKey/relationship calls."""
        args = self._child_by_field(call_node, "arguments")
        if args is None:
            return
        for arg in args.children:
            if arg.type == "call":
                fn = self._child_by_field(arg, "function")
                if fn is None:
                    continue
                nested_name = self._text(fn).split(".")[-1]
                if nested_name in self._RELATION_CALLS:
                    target = self._call_first_string_arg(arg)
                    if target:
                        target = target.split(".")[0]
                        self.result.relations.append((cls.name, nested_name, col_name, target))

    def _extract_column_type(self, call_node) -> str:
        """Extract the type from a Column/mapped_column/models.*Field call."""
        args = self._child_by_field(call_node, "arguments")
        if args is None:
            return ""
        for arg in args.children:
            if arg.type in ("(", ")", ","):
                continue
            if arg.type == "keyword_argument":
                continue
            # First positional arg is typically the type
            return self._text(arg).split("(")[0]  # Column(String(50)) → "String"
        return ""

    def _call_first_string_arg(self, call_node) -> Optional[str]:
        """Extract the first string literal argument from a call."""
        args = self._child_by_field(call_node, "arguments")
        if args is None:
            return None
        for arg in args.children:
            if arg.type == "string":
                return self._strip_quotes(self._text(arg))
            if arg.type in ("(", ")", ","):
                continue
            if arg.type == "keyword_argument":
                continue
            break
        return None

    # ── methods ───────────────────────────────────────────────────────

    def _handle_method(self, node, cls: ClassNode, decorators) -> None:
        name_node = self._child_by_field(node, "name")
        if name_node is None:
            return
        name = self._text(name_node)

        is_static = False
        is_constructor = (name == "__init__")
        for dec in decorators:
            dname = self._decorator_name(dec)
            if dname == "staticmethod":
                is_static = True

        visibility = "private" if name.startswith("_") and not name.startswith("__") else "public"
        if name.startswith("__") and name.endswith("__"):
            visibility = "public"  # dunder methods are public API

        method = MethodNode(
            name=name,
            class_id=cls.id,
            file=self.result.file.path,
            is_static=is_static,
            is_async=False,
            is_constructor=is_constructor,
            visibility=visibility,
            return_type=self._extract_return_type(node),
            params_json=self._extract_params_json(node),
            docstring=self._extract_docstring(node),
        )
        self.result.methods.append(method)

        # HAS_METHOD edge
        self.result.edges.append(Edge(
            kind=HAS_METHOD,
            src_id=cls.id,
            dst_id=method.id,
        ))

        # Method decorators + route endpoint detection
        http_dec = None  # (http_method, path) if a route decorator is found
        for dec in decorators:
            dname = self._decorator_name(dec)
            if dname:
                self.result.edges.append(Edge(
                    kind=DECORATED_BY,
                    src_id=method.id,
                    dst_id=f"dec:{dname}",
                ))
                # Check if this decorator is a route decorator
                base = dname.rstrip("()")
                if base in _PY_ROUTE_DECORATORS:
                    verb = _PY_ROUTE_DECORATORS[base]
                    path = self._decorator_first_string_arg(dec) or "/"
                    if verb is None:
                        # Flask-style: extract method from `methods=` kwarg
                        verb = self._decorator_methods_kwarg(dec) or "GET"
                    http_dec = (verb, path)

        if http_dec:
            http_method, path = http_dec
            full_path = self._join_paths(cls.base_path, path)
            ep = EndpointNode(
                method=http_method,
                path=full_path,
                controller_class=cls.id,
                file=self.result.file.path,
                handler=name,
            )
            self.result.endpoints.append(ep)
            self.result.edges.append(Edge(kind=EXPOSES, src_id=cls.id, dst_id=ep.id))
            self.result.edges.append(Edge(kind=HANDLES, src_id=method.id, dst_id=ep.id))

        # Method call graph (Phase 4 input — consumed by resolver)
        body = self._child_by_field(node, "body")
        if body is not None:
            self._scan_body_for_calls(body, method)

    # ── call classification ──────────────────────────────────────────

    def _scan_body_for_calls(self, body, caller) -> None:
        """Walk every ``call`` node under a method/function body and emit call-graph refs.

        *caller* can be a :class:`MethodNode` or :class:`FunctionNode` — any
        object with an ``.id`` attribute.

        Populates ``result.method_calls`` — the resolver then wires typed +
        name-based :data:`~.schema.CALLS` edges across files in Phase 4.
        Descendant walk catches calls nested in ``if`` / ``for`` / lambdas /
        comprehensions.
        """
        for node in _descend(body):
            if node.type != "call":
                continue
            fn = node.child_by_field_name("function")
            if fn is None:
                continue
            recv_kind, recv_name, target = self._classify_py_call(fn)
            if target:
                self.result.method_calls.append(
                    (caller.id, recv_kind, recv_name or "", target)
                )

    def _classify_py_call(self, fn) -> tuple[str, Optional[str], Optional[str]]:
        """Classify a ``call``'s function subexpression.

        Returns ``(receiver_kind, receiver_name, target_method)`` using the TS
        vocabulary so :mod:`~.resolver` Phase 4 logic slots in unchanged:

        - ``"this"`` — resolver treats as ``confidence="typed"``. Used for
          ``self.foo()`` and ``cls.foo()`` (classmethod invokes MRO like self).
        - ``"this.field"`` — also typed; ``self.svc.run()``.
        - ``"super"`` — new; resolver resolves via the enclosing class's first
          ``class_extends`` parent (see :func:`.resolver.link_cross_file`).
        - ``"name"`` — name-based resolution, ``confidence="name"``.

        Falls back to ``("", None, None)`` when we can't identify a target.
        """
        if fn.type == "identifier":
            # Bare call: foo()
            return "name", None, self._text(fn)

        if fn.type == "attribute":
            obj = fn.child_by_field_name("object")
            attr = fn.child_by_field_name("attribute")
            if obj is None or attr is None:
                return "", None, None
            attr_name = self._text(attr)

            # super().foo() — function-valued receiver, special-case super first.
            if obj.type == "call":
                obj_fn = obj.child_by_field_name("function")
                if (obj_fn is not None
                        and obj_fn.type == "identifier"
                        and self._text(obj_fn) == "super"):
                    return "super", None, attr_name
                # get_obj().foo() — keep target, drop receiver name.
                return "name", None, attr_name

            # self.foo() / cls.foo() / obj.foo()
            if obj.type == "identifier":
                obj_name = self._text(obj)
                if obj_name in ("self", "cls"):
                    return "this", None, attr_name
                return "name", obj_name, attr_name

            # self.field.foo() or a.b.c.foo()
            if obj.type == "attribute":
                inner_obj = obj.child_by_field_name("object")
                inner_attr = obj.child_by_field_name("attribute")
                if inner_obj is None or inner_attr is None:
                    return "", None, None
                if (inner_obj.type == "identifier"
                        and self._text(inner_obj) in ("self", "cls")):
                    return "this.field", self._text(inner_attr), attr_name
                # Deeper chain (a.b.c.m()) — use the immediately-preceding
                # attribute as the receiver name; best-effort name resolution.
                return "name", self._text(inner_attr), attr_name

            # Subscripts (a[0].m()), parenthesized wrappers — keep target only.
            return "name", None, attr_name

        # Parenthesized / walrus / anything else — skip (descendant walk
        # still finds inner calls via separate visits).
        return "", None, None

    # ── functions (module level) ──────────────────────────────────────

    def _handle_function(self, node, decorators) -> None:
        name_node = self._child_by_field(node, "name")
        if name_node is None:
            return
        name = self._text(name_node)
        rel = self.result.file.path
        fn = FunctionNode(
            name=name,
            file=rel,
            is_component=False,  # never — that flag is TS/React-specific
            exported=True,       # Python has no `export`; module-level = importable
            docstring=self._extract_docstring(node),
            return_type=self._extract_return_type(node),
            params_json=self._extract_params_json(node),
        )
        self.result.functions.append(fn)

        # DEFINES_FUNC edge
        self.result.edges.append(Edge(
            kind=DEFINES_FUNC,
            src_id=self.result.file.id,
            dst_id=fn.id,
        ))

        # Function decorators + route endpoint detection
        http_dec = None
        for dec in decorators:
            dname = self._decorator_name(dec)
            if dname:
                self.result.edges.append(Edge(
                    kind=DECORATED_BY,
                    src_id=fn.id,
                    dst_id=f"dec:{dname}",
                ))
                base = dname.rstrip("()")
                if base in _PY_ROUTE_DECORATORS:
                    verb = _PY_ROUTE_DECORATORS[base]
                    path = self._decorator_first_string_arg(dec) or "/"
                    if verb is None:
                        verb = self._decorator_methods_kwarg(dec) or "GET"
                    http_dec = (verb, path)

        if http_dec:
            http_method, path = http_dec
            ep = EndpointNode(
                method=http_method,
                path=path,
                controller_class=self.result.file.id,
                file=self.result.file.path,
                handler=name,
            )
            self.result.endpoints.append(ep)
            self.result.edges.append(Edge(kind=EXPOSES, src_id=self.result.file.id, dst_id=ep.id))
            self.result.edges.append(Edge(kind=HANDLES, src_id=fn.id, dst_id=ep.id))

        # Function call graph — same as method scanning
        body = self._child_by_field(node, "body")
        if body is not None:
            self._scan_body_for_calls(body, fn)

    # ── signature + docstring extraction ──────────────────────────────

    def _extract_docstring(self, fn_def_node) -> str:
        """Return the PEP 257 docstring of a function/method, or ``""``.

        Docstring is the first statement of the body when that statement is
        a bare string literal. We dedent per ``textwrap.dedent`` and strip
        the surrounding quotes + string prefix so downstream consumers get
        readable prose, not raw source. Comments between ``def`` and the
        docstring are skipped; anything else as the first statement means
        no docstring.
        """
        body = self._child_by_field(fn_def_node, "body")
        if body is None:
            return ""
        first_stmt = None
        for c in body.children:
            if c.type == "comment":
                continue
            first_stmt = c
            break
        if first_stmt is None or first_stmt.type != "expression_statement":
            return ""
        for c in first_stmt.children:
            if c.type == "string":
                return self._clean_docstring(self._text(c))
        return ""

    def _clean_docstring(self, raw: str) -> str:
        s = raw.strip()
        # Drop prefix chars (r, b, u, f — docstrings rarely prefixed but be safe)
        i = 0
        while i < len(s) and s[i].lower() in "rbuf":
            i += 1
        s = s[i:]
        for q in ('"""', "'''", '"', "'"):
            if s.startswith(q) and s.endswith(q) and len(s) >= 2 * len(q):
                s = s[len(q):-len(q)]
                break
        return textwrap.dedent(s).strip()

    def _extract_return_type(self, fn_def_node) -> str:
        ret = self._child_by_field(fn_def_node, "return_type")
        if ret is None:
            return ""
        return self._text(ret).strip()

    def _extract_params_json(self, fn_def_node) -> str:
        params_node = self._child_by_field(fn_def_node, "parameters")
        if params_node is None:
            return "[]"
        out: list[dict] = []
        for c in params_node.named_children:
            entry = self._param_to_dict(c)
            if entry is not None:
                out.append(entry)
        return json.dumps(out, separators=(",", ":"))

    def _param_to_dict(self, node) -> Optional[dict]:
        t = node.type
        if t == "identifier":
            return {"name": self._text(node), "kind": "positional"}
        if t == "list_splat_pattern":
            return {"name": self._text(node), "kind": "var_positional"}
        if t == "dictionary_splat_pattern":
            return {"name": self._text(node), "kind": "var_keyword"}
        if t in ("typed_parameter", "typed_default_parameter", "default_parameter"):
            entry: dict[str, Any] = {"kind": "positional"}
            name_field = self._child_by_field(node, "name")
            type_field = self._child_by_field(node, "type")
            value_field = self._child_by_field(node, "value")
            if name_field is not None:
                entry["name"] = self._text(name_field)
            else:
                # typed_parameter's name isn't a named field — scan children.
                for c in node.children:
                    if c.type == "identifier":
                        entry["name"] = self._text(c)
                        break
                    if c.type == "list_splat_pattern":
                        entry["name"] = self._text(c)
                        entry["kind"] = "var_positional"
                        break
                    if c.type == "dictionary_splat_pattern":
                        entry["name"] = self._text(c)
                        entry["kind"] = "var_keyword"
                        break
            if type_field is not None:
                entry["type"] = self._text(type_field).strip()
            if value_field is not None:
                entry["default"] = self._text(value_field).strip()
            if "name" not in entry:
                return None
            return entry
        return None

    # ── decorator argument extraction ────────────────────────────────

    def _decorator_first_string_arg(self, dec) -> Optional[str]:
        """Extract the first positional string literal from a decorator call.

        ``@app.get("/users")`` → ``"/users"``
        ``@app.route("/items", methods=["POST"])`` → ``"/items"``
        """
        for c in dec.children:
            if c.type == "call":
                args = self._child_by_field(c, "arguments")
                if args is None:
                    continue
                for arg in args.children:
                    if arg.type == "string":
                        return self._strip_quotes(self._text(arg))
                    if arg.type == "concatenated_string":
                        # f"..." or "a" "b" — just take the raw text
                        return self._strip_quotes(self._text(arg))
                    if arg.type in ("keyword_argument",):
                        continue  # skip kwargs, look for positional
                    if arg.type in ("(", ")", ","):
                        continue
                    break  # first non-string positional → give up
        return None

    def _decorator_methods_kwarg(self, dec) -> Optional[str]:
        """Extract the first HTTP method from a ``methods=[...]`` kwarg.

        ``@app.route("/x", methods=["POST", "PUT"])`` → ``"POST"``
        """
        for c in dec.children:
            if c.type == "call":
                args = self._child_by_field(c, "arguments")
                if args is None:
                    continue
                for arg in args.children:
                    if arg.type == "keyword_argument":
                        key = self._child_by_field(arg, "name")
                        if key and self._text(key) == "methods":
                            value = self._child_by_field(arg, "value")
                            if value and value.type == "list":
                                for item in value.children:
                                    if item.type == "string":
                                        return self._strip_quotes(self._text(item))
        return None

    @staticmethod
    def _strip_quotes(s: str) -> str:
        """Remove surrounding quotes from a string literal."""
        for q in ('"""', "'''", '"', "'"):
            if s.startswith(q) and s.endswith(q):
                return s[len(q):-len(q)]
        return s

    @staticmethod
    def _join_paths(base: str, sub: str) -> str:
        """Join a base path and a sub path, normalising slashes."""
        if not base:
            return sub
        return f"{base.rstrip('/')}/{sub.lstrip('/')}"

    # ── decorator naming ──────────────────────────────────────────────

    def _decorator_name(self, dec) -> Optional[str]:
        """Stringify a decorator into a canonical name.

        Examples:
        - ``@dataclass`` → ``"dataclass"``
        - ``@property`` → ``"property"``
        - ``@app.command()`` → ``"app.command()"``
        - ``@mcp.tool()`` → ``"mcp.tool()"``
        - ``@pytest.mark.parametrize("x", [...])`` → ``"pytest.mark.parametrize()"``

        Arguments inside ``()`` are dropped. The name is the callable
        expression, optionally followed by ``()`` to distinguish a bare
        decorator (``@dataclass``) from a parameterised one
        (``@dataclass()``). This matches the pattern a user would write
        in a Cypher query: ``MATCH (:Decorator {name:'dataclass'})``.
        """
        # A decorator node has the shape `@ <expression> [newline]`.
        # Pull the expression — it's the first non-`@` / non-newline child.
        expr = None
        for c in dec.children:
            if c.type in ("@", "comment"):
                continue
            if c.type == "\n" or c.type == "newline":
                continue
            expr = c
            break
        if expr is None:
            return None

        if expr.type == "identifier":
            return self._text(expr)
        if expr.type in ("attribute", "dotted_name"):
            return self._text(expr)
        if expr.type == "call":
            fn = self._child_by_field(expr, "function")
            if fn is None:
                return None
            base = self._text(fn)
            return f"{base}()"
        # Fallback: take the full source slice and hope it's short.
        return self._text(expr).split("(")[0]
