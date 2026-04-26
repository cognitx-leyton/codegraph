"""Tree-sitter parser for TS/TSX with NestJS + React + TypeORM + GraphQL awareness."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from tree_sitter import Language, Node, Parser
import tree_sitter_typescript as tst

from .schema import (
    AtomNode,
    ClassNode,
    ColumnNode,
    DECORATED_BY,
    DEFINES_CLASS,
    DEFINES_FUNC,
    DEFINES_IFACE,
    DEFINES_ATOM,
    Edge,
    EndpointNode,
    EXPOSES,
    HAS_COLUMN,
    HAS_METHOD,
    FileNode,
    FunctionNode,
    GraphQLOperationNode,
    HANDLES,
    ImportSpec,
    InterfaceNode,
    MethodNode,
    ParseResult,
    RESOLVES,
    RouteNode,
)

_LANG_TS = Language(tst.language_typescript())
_LANG_TSX = Language(tst.language_tsx())

_HTTP_DECORATORS = {
    "Get": "GET",
    "Post": "POST",
    "Put": "PUT",
    "Patch": "PATCH",
    "Delete": "DELETE",
    "Options": "OPTIONS",
    "Head": "HEAD",
    "All": "ALL",
}

_GQL_DECORATORS = {
    "Query": "query",
    "Mutation": "mutation",
    "Subscription": "subscription",
    "ResolveField": "field",
}

# Class-level decorators that mark a class as a GraphQL resolver
# (NestJS standard + Twenty conventions)
_RESOLVER_CLASS_DECORATORS = {
    "Resolver",
    "MetadataResolver",
    "CoreResolver",
    "WorkspaceResolver",
}

_TYPEORM_COLUMN_DECORATORS = {
    "Column",
    "PrimaryColumn",
    "PrimaryGeneratedColumn",
    "CreateDateColumn",
    "UpdateDateColumn",
    "DeleteDateColumn",
    "VersionColumn",
    "ObjectIdColumn",
}

_TYPEORM_RELATION_DECORATORS = {
    "ManyToOne",
    "OneToMany",
    "OneToOne",
    "ManyToMany",
}

_EVENT_HANDLER_DECORATORS = {"MessagePattern", "EventPattern", "OnEvent", "OnQueueEvent"}

_REST_METHOD_NAMES = {"get", "post", "put", "patch", "delete", "request", "fetch"}

_URL_LIKE_RE = re.compile(r"^[/]?(rest|api|auth|graphql|webhooks|public)[/\w\-:.?=]*$|^/[a-zA-Z0-9_\-/:.]+$")

_GQL_OP_RE = re.compile(r"\b(query|mutation|subscription)\s+([A-Za-z_][\w]*)\b")
# Field name inside the operation body — this is what matches a resolver method name.
# `query EventLogs($x: Y) { eventLogs(input: $x) { ... } }` → field = 'eventLogs'
_GQL_FIELD_RE = re.compile(
    r"\b(query|mutation|subscription)\b[\s\S]*?\{\s*(\w+)",
)


# ── Public API ───────────────────────────────────────────────

class TsParser:
    def __init__(self) -> None:
        self._ts = Parser(_LANG_TS)
        self._tsx = Parser(_LANG_TSX)

    def parse_file(
        self,
        path: Path,
        rel_path: str,
        package: str,
        is_test: bool = False,
        repo_name: str = "default",
    ) -> Optional[ParseResult]:
        try:
            src = path.read_bytes()
        except OSError:
            return None
        is_tsx = path.suffix.lower() == ".tsx"
        parser = self._tsx if is_tsx else self._ts
        tree = parser.parse(src)
        loc = src.count(b"\n") + 1

        file_node = FileNode(
            path=rel_path,
            package=package,
            language="tsx" if is_tsx else "ts",
            loc=loc,
            is_test=is_test,
            repo=repo_name,
        )
        result = ParseResult(file=file_node)
        walker = _Walker(src, result, is_tsx)
        walker.walk_program(tree.root_node)
        walker.finalize()

        # Propagate flags to file
        for cls in result.classes:
            if cls.is_controller:
                result.file.is_controller = True
            if cls.is_injectable:
                result.file.is_injectable = True
            if cls.is_module:
                result.file.is_module = True
            if cls.is_entity:
                result.file.is_entity = True
            if cls.is_resolver:
                result.file.is_resolver = True
        for fn in result.functions:
            if fn.is_component:
                result.file.is_component = True

        return result


# ── Walker internals ─────────────────────────────────────────

class _Walker:
    def __init__(self, src: bytes, result: ParseResult, is_tsx: bool) -> None:
        self.src = src
        self.result = result
        self.is_tsx = is_tsx

    def _text(self, n: Optional[Node]) -> str:
        if n is None:
            return ""
        return self.src[n.start_byte:n.end_byte].decode("utf-8", "replace")

    def _strip_quotes(self, s: str) -> str:
        s = s.strip()
        if len(s) >= 2 and s[0] in ("'", '"', "`") and s[-1] == s[0]:
            return s[1:-1]
        return s

    # -- program --------------------------------------------------------

    def walk_program(self, root: Node) -> None:
        for child in root.children:
            self._handle_top_level(child)
        # Whole-file URL scan (catches module-level strings, class method bodies, etc.)
        self._scan_file_for_urls(root)

    def finalize(self) -> None:
        pass

    def _scan_file_for_urls(self, root: Node) -> None:
        """Walk every string literal in the file; if URL-like, attribute to enclosing fn/method."""
        seen: set = set()
        for d in _descendants(root):
            if d.type != "string":
                continue
            for sc in d.children:
                if sc.type != "string_fragment":
                    continue
                s = self._text(sc)
                if not _looks_like_backend_url(s):
                    break
                key = (s, d.start_byte)
                if key in seen:
                    break
                seen.add(key)
                # Walk up to find the enclosing function/method/component
                container = self._enclosing_container_name(d)
                self.result.rest_calls.append((container, "", s))
                break

    def _enclosing_container_name(self, n: Node) -> str:
        """Walk up until we hit a function/method/arrow/class declarator and return its name."""
        cur = n.parent
        while cur is not None:
            t = cur.type
            if t == "method_definition":
                name = cur.child_by_field_name("name")
                if name is not None:
                    return self._text(name)
            elif t == "function_declaration":
                name = cur.child_by_field_name("name")
                if name is not None:
                    return self._text(name)
            elif t == "variable_declarator":
                name = cur.child_by_field_name("name")
                if name is not None and name.type == "identifier":
                    return self._text(name)
            cur = cur.parent
        return "<module>"

    def _handle_top_level(self, node: Node) -> None:
        t = node.type
        if t == "import_statement":
            self._handle_import(node)
        elif t == "export_statement":
            self._handle_export_statement(node)
        elif t == "class_declaration":
            self._handle_class(node, decorators=[], exported=False)
        elif t == "abstract_class_declaration":
            self._handle_class(node, decorators=[], exported=False, abstract=True)
        elif t == "function_declaration":
            self._handle_function(node, exported=False)
        elif t == "interface_declaration":
            self._handle_interface(node, exported=False)
        elif t in ("lexical_declaration", "variable_declaration"):
            self._handle_lexical(node, exported=False)
        elif t == "expression_statement":
            # Top-level describe() for tests; require() calls
            self._scan_expression_statement(node)

    def _handle_export_statement(self, node: Node) -> None:
        pending_decorators: list[Node] = []
        for c in node.children:
            ct = c.type
            if ct == "decorator":
                pending_decorators.append(c)
            elif ct == "class_declaration":
                self._handle_class(c, decorators=pending_decorators, exported=True)
                pending_decorators = []
            elif ct == "abstract_class_declaration":
                self._handle_class(c, decorators=pending_decorators, exported=True, abstract=True)
                pending_decorators = []
            elif ct == "function_declaration":
                self._handle_function(c, exported=True)
            elif ct == "interface_declaration":
                self._handle_interface(c, exported=True)
            elif ct in ("lexical_declaration", "variable_declaration"):
                self._handle_lexical(c, exported=True)

    # -- imports --------------------------------------------------------

    def _handle_import(self, node: Node) -> None:
        spec = ImportSpec(specifier="")
        for c in node.children:
            if c.type == "type":
                spec.type_only = True
            elif c.type == "string":
                for sc in c.children:
                    if sc.type == "string_fragment":
                        spec.specifier = self._text(sc)
                        break
            elif c.type == "import_clause":
                self._parse_import_clause(c, spec)
        if spec.specifier:
            self.result.imports.append(spec)

    def _parse_import_clause(self, clause: Node, spec: ImportSpec) -> None:
        for c in clause.children:
            if c.type == "identifier":
                spec.default = self._text(c)
            elif c.type == "namespace_import":
                for sc in c.children:
                    if sc.type == "identifier":
                        spec.namespace = self._text(sc)
            elif c.type == "named_imports":
                for sc in c.children:
                    if sc.type == "import_specifier":
                        # name comes from first identifier child
                        for n in sc.children:
                            if n.type == "identifier":
                                spec.symbols.append(self._text(n))
                                break

    def _scan_expression_statement(self, node: Node) -> None:
        # require() and top-level describe()
        for c in _descendants(node):
            if c.type != "call_expression":
                continue
            fn = c.child_by_field_name("function")
            if fn is None:
                continue
            name = self._text(fn)
            if name == "require":
                args = c.child_by_field_name("arguments")
                if args:
                    for a in args.children:
                        if a.type == "string":
                            for sc in a.children:
                                if sc.type == "string_fragment":
                                    self.result.imports.append(
                                        ImportSpec(specifier=self._text(sc))
                                    )
                                    return
            elif name == "describe":
                args = c.child_by_field_name("arguments")
                if args:
                    for a in args.children:
                        if a.type == "string":
                            for sc in a.children:
                                if sc.type == "string_fragment":
                                    self.result.described_subjects.append(self._text(sc))
                                    return

    # -- classes --------------------------------------------------------

    def _handle_class(
        self,
        node: Node,
        decorators: list[Node],
        exported: bool,
        abstract: bool = False,
    ) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            for c in node.children:
                if c.type == "type_identifier":
                    name_node = c
                    break
        if name_node is None:
            return
        name = self._text(name_node)

        cls = ClassNode(name=name, file=self.result.file.path, is_abstract=abstract,
                        repo=self.result.file.repo)

        # Decorators (class-level)
        for dec in decorators:
            dname, dargs, dargs_raw = self._parse_decorator(dec)
            if not dname:
                continue
            self.result.edges.append(
                Edge(kind=DECORATED_BY, src_id=cls.id, dst_id=f"dec:{dname}")
            )
            if dname == "Controller":
                cls.is_controller = True
                if dargs:
                    cls.base_path = self._normalize_path(self._strip_quotes(dargs[0]))
            elif dname == "Injectable":
                cls.is_injectable = True
            elif dname == "Module":
                cls.is_module = True
                # Parse provider arrays (Phase 5)
                self._parse_module_decorator_arg(dec, name)
            elif dname == "Entity":
                cls.is_entity = True
                if dargs:
                    cls.table_name = self._strip_quotes(dargs[0])
            elif dname in _RESOLVER_CLASS_DECORATORS:
                cls.is_resolver = True

        # Heritage
        class_body = None
        for c in node.children:
            if c.type == "class_heritage":
                self._handle_class_heritage(c, name)
            if c.type == "class_body":
                class_body = c

        self.result.classes.append(cls)
        self.result.edges.append(
            Edge(kind=DEFINES_CLASS, src_id=self.result.file.id, dst_id=cls.id)
        )

        if class_body is not None:
            self._walk_class_body(class_body, cls)

    def _handle_class_heritage(self, heritage: Node, cls_name: str) -> None:
        for c in heritage.children:
            if c.type == "extends_clause":
                for sub in c.children:
                    t = self._type_name_text(sub)
                    if t:
                        self.result.class_extends.append((cls_name, t))
            elif c.type == "implements_clause":
                for sub in c.children:
                    t = self._type_name_text(sub)
                    if t:
                        self.result.class_implements.append((cls_name, t))

    def _type_name_text(self, n: Node) -> Optional[str]:
        if n.type in ("identifier", "type_identifier"):
            return self._text(n)
        if n.type == "generic_type":
            for c in n.children:
                t = self._type_name_text(c)
                if t:
                    return t
        if n.type == "nested_type_identifier":
            for c in reversed(n.children):
                if c.type == "type_identifier":
                    return self._text(c)
        return None

    def _walk_class_body(self, body: Node, cls: ClassNode) -> None:
        pending: list[Node] = []
        for c in body.children:
            if c.type == "decorator":
                pending.append(c)
            elif c.type == "method_definition":
                self._handle_method(c, cls, pending)
                pending = []
            elif c.type in ("public_field_definition", "property_signature"):
                self._handle_field(c, cls, pending)
                pending = []

    # -- methods --------------------------------------------------------

    def _handle_method(self, node: Node, cls: ClassNode, decorators: list[Node]) -> None:
        name_node = node.child_by_field_name("name")
        mname = self._text(name_node) if name_node else "<anon>"

        # Build MethodNode
        is_static = False
        is_async = False
        visibility = "public"
        for c in node.children:
            t = c.type
            if t == "accessibility_modifier":
                visibility = self._text(c)
            elif t == "static":
                is_static = True
            elif t == "async":
                is_async = True

        method = MethodNode(
            name=mname,
            class_id=cls.id,
            file=self.result.file.path,
            is_static=is_static,
            is_async=is_async,
            is_constructor=(mname == "constructor"),
            visibility=visibility,
            repo=self.result.file.repo,
        )
        self.result.methods.append(method)
        self.result.edges.append(Edge(kind=HAS_METHOD, src_id=cls.id, dst_id=method.id))

        # Method decorators
        http_dec: Optional[tuple[str, str]] = None
        gql_dec: Optional[tuple[str, str, str]] = None  # (op_type, op_name, return_type)
        event_handler: Optional[str] = None

        for dec in decorators:
            dname, dargs, dargs_raw = self._parse_decorator(dec)
            if not dname:
                continue
            self.result.edges.append(
                Edge(kind=DECORATED_BY, src_id=method.id, dst_id=f"dec:{dname}")
            )

            if dname in _HTTP_DECORATORS and cls.is_controller:
                sub = self._strip_quotes(dargs[0]) if dargs else ""
                http_dec = (_HTTP_DECORATORS[dname], sub)
            elif dname in _GQL_DECORATORS and cls.is_resolver:
                op_type = _GQL_DECORATORS[dname]
                return_type = self._extract_gql_return_type(dargs_raw)
                gql_dec = (op_type, mname, return_type)
            elif dname in _EVENT_HANDLER_DECORATORS:
                if dargs:
                    event_handler = self._strip_quotes(dargs[0])
            elif dname in _TYPEORM_COLUMN_DECORATORS:
                # (rare on methods but handle fields-as-methods if present)
                pass

        if http_dec:
            http_method, sub = http_dec
            full_path = self._join_paths(cls.base_path, sub)
            ep = EndpointNode(
                method=http_method,
                path=full_path,
                controller_class=cls.id,
                file=self.result.file.path,
                handler=mname,
                repo=self.result.file.repo,
            )
            self.result.endpoints.append(ep)
            self.result.edges.append(Edge(kind=EXPOSES, src_id=cls.id, dst_id=ep.id))
            self.result.edges.append(Edge(kind=HANDLES, src_id=method.id, dst_id=ep.id))

        if gql_dec:
            op_type, op_name, ret = gql_dec
            op = GraphQLOperationNode(
                op_type=op_type,
                name=op_name,
                return_type=ret,
                file=self.result.file.path,
                resolver_class=cls.id,
                handler=mname,
                repo=self.result.file.repo,
            )
            self.result.gql_operations.append(op)
            self.result.edges.append(Edge(kind=RESOLVES, src_id=cls.id, dst_id=op.id))
            self.result.edges.append(Edge(kind=HANDLES, src_id=method.id, dst_id=op.id))

        if event_handler:
            self.result.event_handlers.append((method.id, event_handler))

        # Constructor DI
        if method.is_constructor:
            params = node.child_by_field_name("parameters")
            if params is not None:
                for p in params.children:
                    if p.type in ("required_parameter", "optional_parameter"):
                        type_name, is_repo = self._extract_param_type(p)
                        if type_name:
                            if is_repo:
                                self.result.repository_refs.append((cls.name, type_name))
                            else:
                                self.result.di_refs.append((cls.name, type_name))

        # Walk body for calls + emit events + JSX + hook calls (components handled separately)
        body = node.child_by_field_name("body")
        if body is not None:
            self._scan_method_body(body, cls, method)

    def _scan_method_body(self, body: Node, cls: ClassNode, method: MethodNode) -> None:
        for d in _descendants(body):
            if d.type != "call_expression":
                continue
            fn = d.child_by_field_name("function")
            if fn is None:
                continue
            callee_text = self._text(fn)

            # Event emitters: .add/.emit/.publish/.enqueue with string first arg
            if self._is_emit_call(fn):
                args = d.child_by_field_name("arguments")
                first_str = self._first_string_arg(args)
                if first_str:
                    self.result.event_emitters.append((method.id, first_str))

            # Plain call classification for CALLS edges
            receiver_kind, receiver_name, target_name = self._classify_call(fn)
            if target_name:
                self.result.method_calls.append(
                    (method.id, receiver_kind, receiver_name or "", target_name)
                )

            # REST client calls (backend-to-service are fine; frontend will be detected here too)
            if callee_text in ("fetch",) or self._is_http_member_call(fn):
                args = d.child_by_field_name("arguments")
                first_str = self._first_string_arg(args)
                if first_str and _looks_like_url(first_str):
                    http_method = self._extract_http_method_from_callee(fn)
                    self.result.rest_calls.append((method.id, http_method, first_str))

    def _classify_call(self, fn: Node) -> tuple[str, Optional[str], Optional[str]]:
        """Return (receiver_kind, receiver_name, method_name)."""
        if fn.type == "identifier":
            return "name", None, self._text(fn)
        if fn.type == "member_expression":
            obj = fn.child_by_field_name("object")
            prop = fn.child_by_field_name("property")
            method_name = self._text(prop) if prop else None
            if obj is None or method_name is None:
                return "", None, None
            if obj.type == "this":
                return "this", None, method_name
            if obj.type == "member_expression":
                # this.foo.bar() — grab foo
                inner_obj = obj.child_by_field_name("object")
                inner_prop = obj.child_by_field_name("property")
                if inner_obj is not None and inner_obj.type == "this" and inner_prop is not None:
                    return "this.field", self._text(inner_prop), method_name
            if obj.type == "identifier":
                return "name", self._text(obj), method_name
        return "", None, None

    def _is_http_member_call(self, fn: Node) -> bool:
        if fn.type != "member_expression":
            return False
        prop = fn.child_by_field_name("property")
        if prop is None:
            return False
        return self._text(prop) in _REST_METHOD_NAMES

    def _extract_http_method_from_callee(self, fn: Node) -> str:
        if fn.type == "member_expression":
            prop = fn.child_by_field_name("property")
            if prop:
                name = self._text(prop).upper()
                if name in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                    return name
        return ""

    # Fastify/Express-style server objects that register routes
    _FASTIFY_OBJECTS = {"fastify", "server", "app", "instance", "fastifyInstance"}

    def _is_fastify_route(self, fn: Node) -> bool:
        """Check if a call is a Fastify/Express route registration: ``fastify.get(...)``."""
        if fn.type != "member_expression":
            return False
        obj = fn.child_by_field_name("object")
        prop = fn.child_by_field_name("property")
        if obj is None or prop is None:
            return False
        prop_name = self._text(prop)
        obj_name = self._text(obj)
        return (
            prop_name in ("get", "post", "put", "patch", "delete", "head", "options")
            and obj_name in self._FASTIFY_OBJECTS
        )

    def _is_emit_call(self, fn: Node) -> bool:
        if fn.type != "member_expression":
            return False
        prop = fn.child_by_field_name("property")
        if prop is None:
            return False
        return self._text(prop) in ("add", "emit", "publish", "enqueue")

    def _first_string_arg(self, args: Optional[Node]) -> Optional[str]:
        if args is None:
            return None
        for a in args.children:
            if a.type == "string":
                for sc in a.children:
                    if sc.type == "string_fragment":
                        return self._text(sc)
            elif a.type == "template_string":
                return self._text(a).strip("`")
        return None

    def _extract_param_type(self, param: Node) -> tuple[Optional[str], bool]:
        """Return (type_name, is_repository_of)."""
        ta = None
        for c in param.children:
            if c.type == "type_annotation":
                ta = c
                break
        if ta is None:
            return None, False
        for c in ta.children:
            if c.type in ("type_identifier", "predefined_type"):
                return self._text(c), False
            if c.type == "generic_type":
                # Check if it's Repository<X>
                head = self._generic_head(c)
                if head in ("Repository", "EntityRepository", "MongoRepository", "TreeRepository"):
                    arg = self._generic_first_arg_type(c)
                    if arg:
                        return arg, True
                return self._type_name_text(c), False
            if c.type == "nested_type_identifier":
                return self._type_name_text(c), False
        return None, False

    def _generic_head(self, g: Node) -> Optional[str]:
        for c in g.children:
            if c.type in ("type_identifier", "identifier"):
                return self._text(c)
        return None

    def _generic_first_arg_type(self, g: Node) -> Optional[str]:
        for c in g.children:
            if c.type == "type_arguments":
                for tc in c.children:
                    if tc.type in ("type_identifier", "identifier"):
                        return self._text(tc)
                    if tc.type == "generic_type":
                        return self._generic_head(tc)
                    if tc.type == "nested_type_identifier":
                        return self._type_name_text(tc)
        return None

    def _extract_gql_return_type(self, raw: str) -> str:
        """Pull the target of `() => X` or `() => [X]`."""
        if not raw:
            return ""
        m = re.search(r"=>\s*\[?\s*([A-Z]\w*)", raw)
        return m.group(1) if m else ""

    # -- fields (TypeORM columns) --------------------------------------

    def _handle_field(self, node: Node, cls: ClassNode, decorators: list[Node]) -> None:
        if not cls.is_entity:
            return
        name_node = node.child_by_field_name("name")
        if name_node is None:
            for c in node.children:
                if c.type == "property_identifier":
                    name_node = c
                    break
        if name_node is None:
            return
        field_name = self._text(name_node)

        # Field decorators live as children of the field node, not preceding siblings
        own_decorators = [c for c in node.children if c.type == "decorator"]
        all_decorators = decorators + own_decorators

        for dec in all_decorators:
            dname, dargs, dargs_raw = self._parse_decorator(dec)
            if not dname:
                continue
            if dname in _TYPEORM_COLUMN_DECORATORS:
                col = ColumnNode(entity_id=cls.id, name=field_name)
                if "Primary" in dname:
                    col.primary = True
                if "Generated" in dname:
                    col.generated = True
                # Parse options object
                opts = self._parse_column_options(dargs_raw)
                col.nullable = opts.get("nullable", False)
                col.unique = opts.get("unique", False)
                col.type = opts.get("type", "")
                self.result.columns.append(col)
                self.result.edges.append(Edge(kind=HAS_COLUMN, src_id=cls.id, dst_id=col.id))
            elif dname in _TYPEORM_RELATION_DECORATORS:
                target = self._extract_relation_target(dargs_raw)
                if target:
                    self.result.relations.append((cls.name, dname, field_name, target))

    def _parse_column_options(self, raw: str) -> dict:
        """Cheap regex parse of the decorator options object."""
        out: dict = {}
        if not raw:
            return out
        m = re.search(r"\btype\s*:\s*['\"`](\w+)['\"`]", raw)
        if m:
            out["type"] = m.group(1)
        if re.search(r"\bnullable\s*:\s*true\b", raw):
            out["nullable"] = True
        if re.search(r"\bunique\s*:\s*true\b", raw):
            out["unique"] = True
        return out

    def _extract_relation_target(self, raw: str) -> Optional[str]:
        """Extract X from @ManyToOne(() => X, ...)."""
        if not raw:
            return None
        m = re.search(r"=>\s*([A-Z]\w*)", raw)
        return m.group(1) if m else None

    # -- @Module decorator arg (Phase 5) -------------------------------

    def _parse_module_decorator_arg(self, dec: Node, module_name: str) -> None:
        # Find the call_expression → arguments → object → pairs
        for c in dec.children:
            if c.type != "call_expression":
                continue
            args = c.child_by_field_name("arguments")
            if args is None:
                return
            for a in args.children:
                if a.type == "object":
                    self._scan_module_object(a, module_name)
                    return

    def _scan_module_object(self, obj: Node, module_name: str) -> None:
        for c in obj.children:
            if c.type != "pair":
                continue
            key_node = c.child_by_field_name("key")
            val_node = c.child_by_field_name("value")
            if key_node is None or val_node is None:
                continue
            key = self._text(key_node).strip("'\"")
            items = self._flat_array_identifiers(val_node)
            if key == "providers":
                for it in items:
                    self.result.module_providers.append((module_name, it))
            elif key == "exports":
                for it in items:
                    self.result.module_exports.append((module_name, it))
            elif key == "imports":
                for it in items:
                    self.result.module_imports.append((module_name, it))
            elif key == "controllers":
                for it in items:
                    self.result.module_controllers.append((module_name, it))

    def _flat_array_identifiers(self, n: Node) -> list[str]:
        out: list[str] = []
        for d in _descendants(n):
            if d.type == "identifier":
                parent = d.parent
                if parent is not None and parent.type != "call_expression":
                    txt = self._text(d)
                    if txt and txt[0].isupper():
                        out.append(txt)
            elif d.type == "call_expression":
                # Forward refs: forwardRef(() => X) — grab X
                fn = d.child_by_field_name("function")
                if fn is not None and self._text(fn) == "forwardRef":
                    args = d.child_by_field_name("arguments")
                    if args:
                        for a in args.children:
                            if a.type == "arrow_function":
                                body = a.child_by_field_name("body")
                                if body is not None and body.type == "identifier":
                                    out.append(self._text(body))
        # Dedup preserving order
        seen: set = set()
        r: list[str] = []
        for x in out:
            if x not in seen:
                seen.add(x)
                r.append(x)
        return r

    # -- functions / components -----------------------------------------

    def _handle_function(self, node: Node, exported: bool) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = self._text(name_node)
        fn = FunctionNode(name=name, file=self.result.file.path, exported=exported,
                          repo=self.result.file.repo)
        body = node.child_by_field_name("body")
        if self.is_tsx and _is_pascal(name) and body is not None and _contains_jsx(body):
            fn.is_component = True
        self.result.functions.append(fn)
        self.result.edges.append(Edge(kind=DEFINES_FUNC, src_id=self.result.file.id, dst_id=fn.id))
        if body is not None:
            self._scan_function_body(body, fn)

    def _handle_lexical(self, node: Node, exported: bool) -> None:
        for c in node.children:
            if c.type != "variable_declarator":
                continue
            id_node = c.child_by_field_name("name")
            if id_node is None or id_node.type != "identifier":
                continue
            name = self._text(id_node)
            value = c.child_by_field_name("value")
            if value is None:
                continue

            # Top-level gql`...` literal bound to a const
            if value.type in ("call_expression", "tagged_template_expression"):
                self._scan_top_level_gql(value, name)

            # Function / component
            if value.type in ("arrow_function", "function_expression"):
                fn = FunctionNode(name=name, file=self.result.file.path, exported=exported,
                                  repo=self.result.file.repo)
                body = value.child_by_field_name("body")
                if self.is_tsx and _is_pascal(name):
                    if body is not None and (
                        body.type in ("jsx_element", "jsx_self_closing_element", "jsx_fragment")
                        or _contains_jsx(body)
                    ):
                        fn.is_component = True
                self.result.functions.append(fn)
                self.result.edges.append(
                    Edge(kind=DEFINES_FUNC, src_id=self.result.file.id, dst_id=fn.id)
                )
                if body is not None:
                    self._scan_function_body(body, fn)
                continue

            # Atom / atomFamily (Phase 8)
            if value.type == "call_expression":
                callee = value.child_by_field_name("function")
                callee_name = self._text(callee) if callee else ""
                if callee_name in ("atom", "atomFamily", "atomWithStorage", "atomWithReset"):
                    atom = AtomNode(
                        name=name,
                        file=self.result.file.path,
                        family=(callee_name == "atomFamily"),
                        repo=self.result.file.repo,
                    )
                    self.result.atoms.append(atom)
                    self.result.edges.append(
                        Edge(kind=DEFINES_ATOM, src_id=self.result.file.id, dst_id=atom.id)
                    )

    def _scan_top_level_gql(self, node: Node, binder: str) -> None:
        """Detect `const X = gql`...`` at module scope. Extract field name from body."""
        tmpl_node = None
        if node.type == "tagged_template_expression":
            for c in node.children:
                if c.type == "template_string":
                    tmpl_node = c
                    break
            tag_name = ""
            for c in node.children:
                if c.type in ("identifier", "member_expression"):
                    tag_name = self._text(c)
                    break
            if tmpl_node is None:
                return
            if tag_name != "gql" and not tag_name.endswith(".gql"):
                return
        elif node.type == "call_expression":
            fn_node = None
            for c in node.children:
                if c.type in ("identifier", "member_expression") and fn_node is None:
                    fn_node = c
                elif c.type == "template_string":
                    tmpl_node = c
            if fn_node is None or tmpl_node is None:
                return
            tag = self._text(fn_node)
            if tag != "gql" and not tag.endswith(".gql"):
                return
        else:
            return

        content = self._text(tmpl_node).strip("`")
        self._emit_gql_operations(content, binder)

    def _emit_gql_operations(self, content: str, binder: str) -> None:
        """Extract op_type + field name from a gql document body."""
        # Get document operation type from the FIRST keyword
        m_op = _GQL_OP_RE.search(content)
        op_type = m_op.group(1) if m_op else "query"
        # Field names: every '{ <field>' in the document — but we want the top-level field
        # which is the first identifier after the operation's outer body open brace
        m_field = _GQL_FIELD_RE.search(content)
        if m_field:
            field_name = m_field.group(2)
            self.result.gql_literals.append((binder, op_type, field_name))

    def _scan_function_body(self, body: Node, fn: FunctionNode) -> None:
        """For component bodies: JSX renders, hook calls, atom reads, env reads, gql literals, REST calls."""
        for d in _descendants(body):
            t = d.type

            # Nested atom definitions (Twenty wraps atoms in factory functions)
            if t == "variable_declarator":
                id_node = d.child_by_field_name("name")
                if id_node is not None and id_node.type == "identifier":
                    val = d.child_by_field_name("value")
                    if val is not None and val.type == "call_expression":
                        callee = val.child_by_field_name("function")
                        if callee is not None:
                            cname = self._text(callee)
                            if cname in ("atom", "atomFamily", "atomWithStorage", "atomWithReset"):
                                atom_name = self._text(id_node)
                                self.result.atoms.append(AtomNode(
                                    name=atom_name,
                                    file=self.result.file.path,
                                    family=(cname == "atomFamily"),
                                    repo=self.result.file.repo,
                                ))

            # All string literals: check if URL-like, register as rest_call
            if t == "string":
                for sc in d.children:
                    if sc.type == "string_fragment":
                        s = self._text(sc)
                        if _looks_like_backend_url(s):
                            self.result.rest_calls.append((fn.name, "", s))
                        break

            if t in ("jsx_opening_element", "jsx_self_closing_element"):
                tag = self._jsx_tag_name(d)
                if tag and _is_pascal(tag) and fn.is_component:
                    self.result.jsx_renders.append((fn.name, tag))

            elif t == "call_expression":
                callee = d.child_by_field_name("function")
                if callee is None:
                    continue
                callee_text = self._text(callee)

                # Hook calls (only for components)
                if fn.is_component and _is_hook(callee_text):
                    self.result.hook_calls.append((fn.name, callee_text))
                    # Jotai atom read/write patterns
                    args = d.child_by_field_name("arguments")
                    first_ident = self._first_identifier_arg(args)
                    if first_ident:
                        if callee_text in ("useAtomValue", "useAtomComponentStateValue",
                                           "useAtomStateValue", "useAtom"):
                            self.result.atom_reads.append((fn.name, first_ident))
                        if callee_text in ("useSetAtom", "useSetAtomState",
                                           "useAtomComponentState", "useSetRecoilState"):
                            self.result.atom_writes.append((fn.name, first_ident))

                # REST client calls
                if callee_text == "fetch" or self._is_http_member_call(callee):
                    args = d.child_by_field_name("arguments")
                    first_str = self._first_string_arg(args)
                    if first_str and _looks_like_url(first_str):
                        http_m = self._extract_http_method_from_callee(callee)
                        self.result.rest_calls.append((fn.name, http_m, first_str))

                # Fastify route registration: fastify.get('/path', handler)
                if self._is_fastify_route(callee):
                    args = d.child_by_field_name("arguments")
                    first_str = self._first_string_arg(args)
                    if first_str and first_str.startswith("/"):
                        # Extract method directly from the property name (already
                        # validated by _is_fastify_route) — avoids the
                        # _extract_http_method_from_callee gap for HEAD/OPTIONS.
                        prop = callee.child_by_field_name("property")
                        http_m = self._text(prop).upper() if prop else "GET"
                        ep = EndpointNode(
                            method=http_m,
                            path=first_str,
                            controller_class=self.result.file.id,
                            file=self.result.file.path,
                            handler=fn.name,
                            repo=self.result.file.repo,
                        )
                        self.result.endpoints.append(ep)
                        self.result.edges.append(
                            Edge(kind=EXPOSES, src_id=self.result.file.id, dst_id=ep.id)
                        )
                        self.result.edges.append(
                            Edge(kind=HANDLES, src_id=fn.id, dst_id=ep.id)
                        )

                # ConfigService.get('X')
                if self._is_config_get(callee):
                    args = d.child_by_field_name("arguments")
                    first_str = self._first_string_arg(args)
                    if first_str:
                        self.result.env_reads.append(first_str)

            elif t == "template_string":
                # gql`query Foo { ... }` — parent should be call_expression or tagged_template
                parent = d.parent
                if parent is not None:
                    tag_fn: Optional[Node] = None
                    if parent.type == "call_expression":
                        tag_fn = parent.child_by_field_name("function")
                    elif parent.type == "tagged_template_expression":
                        for pc in parent.children:
                            if pc.type in ("identifier", "member_expression"):
                                tag_fn = pc
                                break
                    if tag_fn is not None:
                        tag_name = self._text(tag_fn)
                        if tag_name.endswith("gql") or tag_name == "gql":
                            content = self._text(d).strip("`")
                            self._emit_gql_operations(content, fn.name)

            elif t == "member_expression":
                # process.env.X
                obj = d.child_by_field_name("object")
                prop = d.child_by_field_name("property")
                if obj is not None and obj.type == "member_expression" and prop is not None:
                    inner_obj = obj.child_by_field_name("object")
                    inner_prop = obj.child_by_field_name("property")
                    if (inner_obj is not None and self._text(inner_obj) == "process"
                            and inner_prop is not None and self._text(inner_prop) == "env"):
                        self.result.env_reads.append(self._text(prop))

    def _is_config_get(self, fn: Node) -> bool:
        if fn.type != "member_expression":
            return False
        prop = fn.child_by_field_name("property")
        if prop is None or self._text(prop) != "get":
            return False
        obj = fn.child_by_field_name("object")
        if obj is None:
            return False
        name = self._text(obj)
        return "config" in name.lower() or "Config" in name

    def _first_identifier_arg(self, args: Optional[Node]) -> Optional[str]:
        if args is None:
            return None
        for a in args.children:
            if a.type == "identifier":
                return self._text(a)
        return None

    def _jsx_tag_name(self, n: Node) -> Optional[str]:
        for c in n.children:
            if c.type == "identifier":
                return self._text(c)
            if c.type == "nested_identifier":
                last = None
                for sc in c.children:
                    if sc.type == "identifier":
                        last = self._text(sc)
                return last
            if c.type == "member_expression":
                return self._text(c).split(".")[-1]
        return None

    # -- interfaces -----------------------------------------------------

    def _handle_interface(self, node: Node, exported: bool) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = self._text(name_node)
        iface = InterfaceNode(name=name, file=self.result.file.path, repo=self.result.file.repo)
        self.result.interfaces.append(iface)
        self.result.edges.append(Edge(kind=DEFINES_IFACE, src_id=self.result.file.id, dst_id=iface.id))

    # -- decorator parsing ---------------------------------------------

    def _parse_decorator(self, dec: Node) -> tuple[Optional[str], list[str], str]:
        """Return (name, string_args, raw_args_text)."""
        name: Optional[str] = None
        args: list[str] = []
        raw = ""
        for c in dec.children:
            if c.type == "call_expression":
                fn = c.child_by_field_name("function")
                if fn is not None:
                    name = self._text(fn).split(".")[-1]
                arg_node = c.child_by_field_name("arguments")
                if arg_node is not None:
                    raw = self._text(arg_node)
                    for a in arg_node.children:
                        if a.type == "string":
                            for sc in a.children:
                                if sc.type == "string_fragment":
                                    args.append(f"'{self._text(sc)}'")
            elif c.type == "identifier":
                name = self._text(c)
            elif c.type == "member_expression":
                name = self._text(c).split(".")[-1]
        return name, args, raw

    # -- route path joining --------------------------------------------

    def _normalize_path(self, p: str) -> str:
        p = p.strip()
        if not p:
            return ""
        if not p.startswith("/"):
            p = "/" + p
        return p.rstrip("/") or "/"

    def _join_paths(self, base: str, sub: str) -> str:
        b = self._normalize_path(base) if base else ""
        s = sub.strip()
        if not s:
            return b or "/"
        if not s.startswith("/"):
            s = "/" + s
        if b and b != "/":
            joined = b + s
        else:
            joined = s
        return joined.rstrip("/") or "/"


# ── Small helpers ────────────────────────────────────────────

def _descendants(n: Node):
    stack = list(n.children)
    while stack:
        node = stack.pop()
        yield node
        stack.extend(node.children)


def _contains_jsx(n: Node) -> bool:
    if n.type in ("jsx_element", "jsx_self_closing_element", "jsx_fragment"):
        return True
    for c in _descendants(n):
        if c.type in ("jsx_element", "jsx_self_closing_element", "jsx_fragment"):
            return True
    return False


def _is_pascal(name: str) -> bool:
    return bool(name) and name[0].isalpha() and name[0].isupper()


def _is_hook(name: str) -> bool:
    if len(name) < 4 or not name.startswith("use"):
        return False
    return name[3].isupper()


def _looks_like_url(s: str) -> bool:
    if not s:
        return False
    if s.startswith("/"):
        return True
    if s.startswith("http"):
        return True
    return False


_BACKEND_URL_RE = re.compile(
    r"^/(rest|api|auth|graphql|webhooks?|public-assets?|file|client-config|health|open-api|openapi)(/[\w\-:.{}/]*)?(?:\?.*)?$"
)


def _looks_like_backend_url(s: str) -> bool:
    """Stricter than _looks_like_url — must look like a real backend route."""
    if not s or len(s) < 2 or len(s) > 200:
        return False
    return bool(_BACKEND_URL_RE.match(s))
