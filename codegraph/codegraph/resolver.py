"""Import resolution + cross-file linking (Phase 1-8)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .schema import (
    CALLS,
    CALLS_ENDPOINT,
    ClassNode,
    DECLARES_CONTROLLER,
    Edge,
    EXPORTS_PROVIDER,
    EXTENDS,
    FunctionNode,
    IMPLEMENTS,
    IMPORTS,
    IMPORTS_MODULE,
    IMPORTS_SYMBOL,
    INJECTS,
    MethodNode,
    PackageNode,
    ParseResult,
    PROVIDES,
    RELATES_TO,
    RENDERS,
    REPOSITORY_OF,
    RETURNS,
    USES_HOOK,
    USES_OPERATION,
)

_EXT_CANDIDATES = ["", ".ts", ".tsx", ".d.ts", "/index.ts", "/index.tsx", "/index.d.ts"]
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")

# NodeNext-style imports use .js extensions even when the source is .ts on disk.
_JS_TO_TS_REMAP = {".js": ".ts", ".jsx": ".tsx", ".mjs": ".mts", ".cjs": ".cts"}


# ── tsconfig JSONC ───────────────────────────────────────────

def _strip_jsonc(raw: str) -> str:
    out: list[str] = []
    i, n = 0, len(raw)
    while i < n:
        ch = raw[i]
        if ch == '"':
            out.append(ch)
            i += 1
            while i < n:
                c = raw[i]
                out.append(c)
                i += 1
                if c == "\\" and i < n:
                    out.append(raw[i])
                    i += 1
                elif c == '"':
                    break
            continue
        if ch == "/" and i + 1 < n:
            nxt = raw[i + 1]
            if nxt == "/":
                i += 2
                while i < n and raw[i] != "\n":
                    i += 1
                continue
            if nxt == "*":
                i += 2
                while i + 1 < n and not (raw[i] == "*" and raw[i + 1] == "/"):
                    i += 1
                i += 2
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _resolve_npm_tsconfig(start_dir: Path, package_name: str) -> Optional[Path]:
    """Walk up from *start_dir* looking for node_modules/<package_name>/tsconfig.json."""
    current = start_dir.resolve()
    while True:
        candidate = current / "node_modules" / package_name / "tsconfig.json"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _read_ts_paths(tsconfig: Path, _seen: Optional[set[str]] = None) -> dict[str, list[str]]:
    if not tsconfig.exists():
        return {}
    resolved_key = str(tsconfig.resolve())
    if _seen is None:
        _seen = set()
    if resolved_key in _seen or len(_seen) >= 10:
        return {}
    _seen.add(resolved_key)
    try:
        raw = tsconfig.read_text()
    except OSError:
        return {}
    cleaned = _strip_jsonc(raw)
    cleaned = _TRAILING_COMMA_RE.sub(r"\1", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return {}
    # Follow "extends" chain — parent paths are inherited, child overrides.
    paths: dict[str, list[str]] = {}
    extends = data.get("extends")
    if isinstance(extends, str):
        extends = [extends]
    if isinstance(extends, list):
        for ext in extends:
            if not isinstance(ext, str):
                continue
            if ext.startswith(".") or ext.startswith("/"):
                # Relative or absolute path — existing logic
                parent = (tsconfig.parent / ext).resolve()
                if not parent.suffix:
                    parent = parent.with_suffix(".json")
            else:
                # npm package — resolve from node_modules
                parent = _resolve_npm_tsconfig(tsconfig.parent, ext)
                if parent is None:
                    continue
            paths.update(_read_ts_paths(parent, _seen))
    child_paths = (data.get("compilerOptions") or {}).get("paths") or {}
    paths.update(child_paths)
    return paths


@dataclass
class PackageConfig:
    name: str
    root: Path
    repo_root: Path
    aliases: dict[str, list[Path]] = field(default_factory=dict)
    language: str = "ts"  # "ts" (TypeScript/TSX) or "py" (Python)
    pkg_json_name: Optional[str] = None  # "name" from package.json (e.g. "twenty-ui")


def load_package_config(repo_root: Path, package_dir: Path) -> PackageConfig:
    cfg = PackageConfig(name=package_dir.name, root=package_dir.resolve(), repo_root=repo_root.resolve())
    for key, targets in _read_ts_paths(package_dir / "tsconfig.json").items():
        alias_prefix = key.rstrip("*")
        resolved: list[Path] = []
        for t in targets:
            resolved.append((package_dir / t.rstrip("*")).resolve())
        cfg.aliases[alias_prefix] = resolved
    # Read package.json "name" for workspace package resolution.
    try:
        pkg_data = json.loads((package_dir / "package.json").read_text())
        cfg.pkg_json_name = pkg_data.get("name") or None
    except (OSError, json.JSONDecodeError):
        pass
    return cfg


def load_python_package_config(repo_root: Path, package_dir: Path) -> PackageConfig:
    """Build a :class:`PackageConfig` for a Python package directory.

    Unlike TS, Python has no tsconfig equivalent — imports are resolved
    purely by filesystem layout (relative imports walk up, absolute imports
    match the top-level package name and resolve under the package root).
    The returned config has ``language="py"`` and empty ``aliases``. The
    ``name`` is the directory basename, which doubles as the Python
    top-level package name (what ``from <name> import ...`` would use).
    """
    return PackageConfig(
        name=package_dir.name,
        root=package_dir.resolve(),
        repo_root=repo_root.resolve(),
        aliases={},
        language="py",
    )


# ── Index ────────────────────────────────────────────────────

@dataclass
class Index:
    files_by_path: dict[str, ParseResult] = field(default_factory=dict)
    class_by_name_in_file: dict[tuple[str, str], ClassNode] = field(default_factory=dict)
    func_by_name_in_file: dict[tuple[str, str], FunctionNode] = field(default_factory=dict)
    class_name_to_files: dict[str, list[str]] = field(default_factory=dict)
    func_name_to_files: dict[str, list[str]] = field(default_factory=dict)
    method_by_class_and_name: dict[tuple[str, str], MethodNode] = field(default_factory=dict)
    # Phase 3: endpoint lookup structures
    endpoint_nodes: list = field(default_factory=list)  # list of (EndpointNode, file_id)
    gql_operations: dict[tuple[str, str], list] = field(default_factory=dict)  # (op_type, name) -> list of (op, file)
    # Phase 9: per-package framework detection
    packages: list[PackageNode] = field(default_factory=list)

    def add(self, result: ParseResult) -> None:
        path = result.file.path
        self.files_by_path[path] = result
        for c in result.classes:
            self.class_by_name_in_file[(path, c.name)] = c
            self.class_name_to_files.setdefault(c.name, []).append(path)
        for f in result.functions:
            self.func_by_name_in_file[(path, f.name)] = f
            self.func_name_to_files.setdefault(f.name, []).append(path)
        for m in result.methods:
            self.method_by_class_and_name[(m.class_id, m.name)] = m
        for e in result.endpoints:
            self.endpoint_nodes.append((e, path))
        for op in result.gql_operations:
            self.gql_operations.setdefault((op.op_type, op.name), []).append((op, path))


# ── Prefix-indexed path resolution (Phase 1.2) ───────────────

class PathIndex:
    """Precomputed set of file paths + helpers, zero filesystem calls."""

    def __init__(self, files: set[str]) -> None:
        self.files: set[str] = files
        self.by_stem: dict[str, list[str]] = {}  # filename without ext → paths
        for p in files:
            name = p.rsplit("/", 1)[-1]
            stem = name
            for ext in (".ts", ".tsx", ".d.ts"):
                if stem.endswith(ext):
                    stem = stem[: -len(ext)]
                    break
            self.by_stem.setdefault(stem, []).append(p)

    def try_resolve(self, base_rel: str) -> Optional[str]:
        """Try appending known extensions / index files to `base_rel` and return first match."""
        for ext in _EXT_CANDIDATES:
            candidate = (base_rel + ext) if ext else base_rel
            if candidate in self.files:
                return candidate
        return None


class Resolver:
    def __init__(self, repo_root: Path, packages: list[PackageConfig]) -> None:
        self.repo_root = repo_root.resolve()
        self.packages = packages
        self._path_index: Optional[PathIndex] = None
        self._alias_cache: dict[str, list[tuple[str, Path]]] = {}
        self._workspace_pkgs: dict[str, PackageConfig] = {}

    def set_path_index(self, path_index: PathIndex) -> None:
        self._path_index = path_index
        # Precompute alias → [(alias_prefix, absolute_target_dir)] for quick scan.
        # Keyed by str(pkg.root) (not pkg.name) so two packages with the same
        # basename (e.g. apps/frontend/src and apps/backend/src) get distinct buckets.
        self._alias_cache = {}
        for pkg in self.packages:
            pkg_key = str(pkg.root)
            for alias, targets in pkg.aliases.items():
                self._alias_cache.setdefault(pkg_key, [])
                for t in targets:
                    self._alias_cache[pkg_key].append((alias, t))
        # Workspace package registry: map package.json "name" → PackageConfig
        # so bare imports like 'twenty-ui/display' can resolve to source files.
        self._workspace_pkgs = {}
        for pkg in self.packages:
            if pkg.pkg_json_name:
                self._workspace_pkgs[pkg.pkg_json_name] = pkg

    def resolve(self, importer_rel: str, specifier: str) -> Optional[str]:
        if self._path_index is None:
            return None
        spec = specifier.strip()
        if not spec:
            return None

        # Python files dispatch to their own resolver — TS logic (extension
        # candidates, tsconfig aliases, .d.ts fallback) doesn't apply.
        if self._is_python_file(importer_rel):
            return self._resolve_python(importer_rel, spec)

        # Relative
        if spec.startswith("."):
            importer_abs = (self.repo_root / importer_rel).resolve()
            target = (importer_abs.parent / spec).resolve()
            try:
                base_rel = str(target.relative_to(self.repo_root)).replace("\\", "/")
            except ValueError:
                return None
            hit = self._path_index.try_resolve(base_rel)
            if hit:
                return hit
            # NodeNext: remap .js → .ts when the literal path doesn't exist
            return self._try_js_remap(base_rel)

        # Absolute from repo root — rare
        if spec.startswith("/"):
            return self._path_index.try_resolve(spec.lstrip("/"))

        # Alias lookup — try importer's own package first, then fall through
        importer_pkg = self._package_for_file(importer_rel)
        if importer_pkg and importer_pkg in self._alias_cache:
            hit = self._try_aliases(spec, self._alias_cache[importer_pkg])
            if hit:
                return hit
        for pkg_name, alias_pairs in self._alias_cache.items():
            if pkg_name == importer_pkg:
                continue  # already tried
            hit = self._try_aliases(spec, alias_pairs)
            if hit:
                return hit
        # Workspace package resolution: try matching bare specifier against
        # package.json names (e.g. 'twenty-ui/display' → packages/twenty-ui/src/display)
        return self._try_workspace(spec)

    def _try_aliases(self, spec: str, alias_pairs: list[tuple[str, Path]]) -> Optional[str]:
        """Try resolving *spec* against a list of (alias_prefix, target_dir) pairs."""
        if self._path_index is None:
            return None
        for alias, target_dir in alias_pairs:
            if spec.startswith(alias):
                rest = spec[len(alias):]
                candidate = (target_dir / rest).resolve() if rest else target_dir
                try:
                    base_rel = str(candidate.relative_to(self.repo_root)).replace("\\", "/")
                except ValueError:
                    continue
                hit = self._path_index.try_resolve(base_rel)
                if hit:
                    return hit
                # NodeNext: remap .js → .ts for aliased imports too
                hit = self._try_js_remap(base_rel)
                if hit:
                    return hit
        return None

    def _package_for_file(self, rel: str) -> Optional[str]:
        """Return the cache key (``str(pkg.root)``) for the package that contains *rel*."""
        abs_path = (self.repo_root / rel).resolve()
        for pkg in self.packages:
            try:
                abs_path.relative_to(pkg.root)
                return str(pkg.root)
            except ValueError:
                continue
        return None

    def _try_js_remap(self, base_rel: str) -> Optional[str]:
        """Remap NodeNext .js/.jsx/.mjs/.cjs extensions to .ts/.tsx/.mts/.cts."""
        if self._path_index is None:
            return None
        for js_ext, ts_ext in _JS_TO_TS_REMAP.items():
            if base_rel.endswith(js_ext):
                remapped = base_rel[: -len(js_ext)] + ts_ext
                if remapped in self._path_index.files:
                    return remapped
        return None

    # ── Workspace (monorepo) resolution ────────────────────────────────

    def _try_workspace(self, spec: str) -> Optional[str]:
        """Resolve a bare workspace package import like ``twenty-ui/display``.

        Splits the specifier on the first ``/``, matches the prefix against
        ``package.json`` names of indexed packages, then resolves the
        remainder under ``<pkg_root>/src/`` (falling back to ``<pkg_root>/``
        if no ``src/`` directory exists).  Scoped packages (``@scope/name``)
        are handled by splitting on the second ``/``.
        """
        if self._path_index is None:
            return None
        pkg_name, _, sub_path = spec.partition("/")
        pkg = self._workspace_pkgs.get(pkg_name)
        # Scoped packages: @scope/name → split on the second '/'
        if pkg is None and pkg_name.startswith("@") and sub_path:
            scoped_name, _, sub_path = sub_path.partition("/")
            pkg_name = f"{pkg_name}/{scoped_name}"
            pkg = self._workspace_pkgs.get(pkg_name)
        if pkg is None:
            return None
        src_dir = pkg.root / "src"
        source_root = src_dir if src_dir.is_dir() else pkg.root
        candidate = (source_root / sub_path) if sub_path else source_root
        try:
            base_rel = str(candidate.resolve().relative_to(self.repo_root)).replace("\\", "/")
        except ValueError:
            return None
        hit = self._path_index.try_resolve(base_rel)
        if hit:
            return hit
        return self._try_js_remap(base_rel)

    # ── Python resolution ─────────────────────────────────────────────

    def _is_python_file(self, rel: str) -> bool:
        """Check if ``rel`` lives under a Python package (``language=="py"``)."""
        abs_path = (self.repo_root / rel).resolve()
        for pkg in self.packages:
            if pkg.language != "py":
                continue
            try:
                abs_path.relative_to(pkg.root)
                return True
            except ValueError:
                continue
        return False

    def _resolve_python(self, importer_rel: str, spec: str) -> Optional[str]:
        """Resolve a Python import specifier to a rel file path, or ``None``.

        Three rules:

        1. **Relative** (``.x`` / ``..x`` / ``.``): walk up ``dots - 1``
           directories from the importer's parent, then resolve the
           remainder as a module path.
        2. **Absolute intra-package** (``codegraph.schema``): if the first
           segment matches a Python package's ``name``, strip it and
           resolve under the package root.
        3. **External**: return ``None``; the caller emits an
           ``IMPORTS_EXTERNAL`` edge.
        """
        # Count leading dots (relative import level).
        leading_dots = 0
        while leading_dots < len(spec) and spec[leading_dots] == ".":
            leading_dots += 1

        if leading_dots > 0:
            remainder = spec[leading_dots:]
            importer_abs = (self.repo_root / importer_rel).resolve()
            base = importer_abs.parent
            for _ in range(leading_dots - 1):
                base = base.parent
            return self._resolve_python_module(base, remainder)

        # Absolute intra-package import: strip the top-level name.
        # Try the importer's own package first to avoid basename collisions
        # when multiple Python packages share the same directory name.
        first = spec.split(".")[0]
        remainder = ".".join(spec.split(".")[1:])
        importer_root = self._package_for_file(importer_rel)
        candidates = sorted(
            (pkg for pkg in self.packages if pkg.language == "py" and pkg.name == first),
            key=lambda p: (str(p.root) != importer_root),  # own package sorts first
        )
        for pkg in candidates:
            hit = self._resolve_python_module(pkg.root, remainder)
            if hit:
                return hit

        # External — the caller emits IMPORTS_EXTERNAL.
        return None

    def _resolve_python_module(self, base: Path, module_path: str) -> Optional[str]:
        """Given a filesystem base + a dotted module path, find a ``.py`` file.

        Tries the module as a plain file (``base/foo/bar.py``) first, then as
        a package (``base/foo/bar/__init__.py``). Returns the repo-relative
        path if found in the path index, else ``None``.
        """
        if self._path_index is None:
            return None

        if not module_path:
            # ``from . import X`` → base/__init__.py
            candidate = base / "__init__.py"
            return self._path_index_membership(candidate)

        parts = module_path.split(".")
        # Try as .py file.
        file_candidate = base.joinpath(*parts).with_suffix(".py")
        hit = self._path_index_membership(file_candidate)
        if hit is not None:
            return hit
        # Try as package: <parts>/__init__.py
        pkg_candidate = base.joinpath(*parts) / "__init__.py"
        return self._path_index_membership(pkg_candidate)

    def _path_index_membership(self, candidate: Path) -> Optional[str]:
        """Return the rel path if ``candidate`` is in the path index, else None."""
        if self._path_index is None:
            return None
        try:
            rel = str(candidate.resolve().relative_to(self.repo_root)).replace("\\", "/")
        except ValueError:
            return None
        return rel if rel in self._path_index.files else None


# ── URL matching for Phase 3 ─────────────────────────────────

def _url_pattern_to_regex(path_template: str) -> re.Pattern:
    """Convert '/rest/users/:id' → '^/rest/users/[^/]+$' (with prefix tolerance)."""
    escaped = re.escape(path_template)
    escaped = re.sub(r"\\:[A-Za-z_]\w*", r"[^/?#]+", escaped)
    # Allow trailing slashes / query strings
    return re.compile(f"^{escaped}/?(?:[?#].*)?$")


# ── Cross-file linker ────────────────────────────────────────

def link_cross_file(index: Index, resolver: Resolver) -> list[Edge]:
    """Emit all cross-file edges in one pass."""
    edges: list[Edge] = []

    # Build path index (Phase 1.2 speedup)
    path_index = PathIndex(set(index.files_by_path.keys()))
    resolver.set_path_index(path_index)

    unresolved_count = 0
    total_imports = 0

    # Precompute endpoint patterns
    endpoint_patterns: list[tuple] = []  # (pattern, endpoint_node, file)
    for ep, ep_file in index.endpoint_nodes:
        endpoint_patterns.append((_url_pattern_to_regex(ep.path), ep, ep_file))

    for rel, result in index.files_by_path.items():
        fid = f"file:{rel}"

        # -- Imports --
        for spec in result.imports:
            total_imports += 1
            target = resolver.resolve(rel, spec.specifier)
            if target is not None:
                edges.append(Edge(
                    kind=IMPORTS,
                    src_id=fid,
                    dst_id=f"file:{target}",
                    props={"specifier": spec.specifier, "type_only": spec.type_only},
                ))
                # Phase 1.1: per-symbol edges
                all_syms = list(spec.symbols)
                if spec.default:
                    all_syms.append(spec.default)
                if spec.namespace:
                    all_syms.append(f"* as {spec.namespace}")
                for sym in all_syms:
                    edges.append(Edge(
                        kind=IMPORTS_SYMBOL,
                        src_id=fid,
                        dst_id=f"file:{target}",
                        props={"symbol": sym, "type_only": spec.type_only},
                    ))
            else:
                unresolved_count += 1
                edges.append(Edge(
                    kind=IMPORTS,
                    src_id=fid,
                    dst_id=f"external:{spec.specifier}",
                    props={"specifier": spec.specifier, "type_only": spec.type_only, "external": True},
                ))

        # -- Class heritage --
        for cls_name, parent in result.class_extends:
            target = _find_class(rel, parent, index, resolver)
            if target:
                edges.append(Edge(
                    kind=EXTENDS,
                    src_id=f"class:{rel}#{cls_name}",
                    dst_id=f"class:{target}#{parent}",
                ))
        for cls_name, iface in result.class_implements:
            target = _find_class(rel, iface, index, resolver)
            if target:
                edges.append(Edge(
                    kind=IMPLEMENTS,
                    src_id=f"class:{rel}#{cls_name}",
                    dst_id=f"class:{target}#{iface}",
                ))

        # -- DI --
        for cls_name, injected in result.di_refs:
            target = _find_class(rel, injected, index, resolver)
            if target:
                edges.append(Edge(
                    kind=INJECTS,
                    src_id=f"class:{rel}#{cls_name}",
                    dst_id=f"class:{target}#{injected}",
                ))

        # -- Phase 2: TypeORM --
        for cls_name, repo_target in result.repository_refs:
            target = _find_class(rel, repo_target, index, resolver)
            if target:
                edges.append(Edge(
                    kind=REPOSITORY_OF,
                    src_id=f"class:{rel}#{cls_name}",
                    dst_id=f"class:{target}#{repo_target}",
                ))
        for entity_name, kind, field_name, target_name in result.relations:
            target = _find_class(rel, target_name, index, resolver)
            if target:
                edges.append(Edge(
                    kind=RELATES_TO,
                    src_id=f"class:{rel}#{entity_name}",
                    dst_id=f"class:{target}#{target_name}",
                    props={"kind": kind, "field": field_name},
                ))

        # -- Phase 3: GraphQL return types → entities --
        for op in result.gql_operations:
            if op.return_type:
                target = _find_class(rel, op.return_type, index, resolver)
                if target:
                    edges.append(Edge(
                        kind=RETURNS,
                        src_id=op.id,
                        dst_id=f"class:{target}#{op.return_type}",
                    ))

        # -- Phase 3: REST calls → endpoints --
        for caller_name, http_method, url in result.rest_calls:
            # Strip query string if present
            url_clean = url.split("?")[0].split("#")[0]
            for pattern, ep, ep_file in endpoint_patterns:
                if http_method and ep.method != http_method:
                    continue
                if pattern.match(url_clean):
                    src_id = _caller_id_for_fn(rel, caller_name, index)
                    edges.append(Edge(
                        kind=CALLS_ENDPOINT,
                        src_id=src_id,
                        dst_id=ep.id,
                        props={"url": url_clean},
                    ))

        # -- Phase 3: gql literals → operations --
        for caller_name, op_type, op_name in result.gql_literals:
            key = (op_type, op_name)
            ops = index.gql_operations.get(key, [])
            for op, op_file in ops:
                src_id = _caller_id_for_fn(rel, caller_name, index)
                edges.append(Edge(
                    kind=USES_OPERATION,
                    src_id=src_id,
                    dst_id=op.id,
                    props={"op_name": op_name},
                ))

        # -- Phase 4: method CALLS --
        for caller_mid, recv_kind, recv_name, target_method in result.method_calls:
            # Figure out target class (super() takes a special path).
            if recv_kind == "super":
                target_class_id = _resolve_super_target_class(
                    rel, caller_mid, result, index, resolver
                )
            else:
                target_class_id = _resolve_call_target_class(
                    rel, caller_mid, recv_kind, recv_name, index
                )
            if target_class_id is None:
                continue
            # Does target class have target_method?
            key = (target_class_id, target_method)
            if key in index.method_by_class_and_name:
                m = index.method_by_class_and_name[key]
                confidence = "typed" if recv_kind in ("this", "this.field", "super") else "name"
                edges.append(Edge(
                    kind=CALLS,
                    src_id=caller_mid,
                    dst_id=m.id,
                    props={"confidence": confidence},
                ))

        # -- Phase 5: module providers/imports/exports/controllers --
        for module_name, provider_name in result.module_providers:
            target = _find_class(rel, provider_name, index, resolver)
            if target:
                edges.append(Edge(
                    kind=PROVIDES,
                    src_id=f"class:{rel}#{module_name}",
                    dst_id=f"class:{target}#{provider_name}",
                ))
        for module_name, exported in result.module_exports:
            target = _find_class(rel, exported, index, resolver)
            if target:
                edges.append(Edge(
                    kind=EXPORTS_PROVIDER,
                    src_id=f"class:{rel}#{module_name}",
                    dst_id=f"class:{target}#{exported}",
                ))
        for module_name, imp_module in result.module_imports:
            target = _find_class(rel, imp_module, index, resolver)
            if target:
                edges.append(Edge(
                    kind=IMPORTS_MODULE,
                    src_id=f"class:{rel}#{module_name}",
                    dst_id=f"class:{target}#{imp_module}",
                ))
        for module_name, ctrl in result.module_controllers:
            target = _find_class(rel, ctrl, index, resolver)
            if target:
                edges.append(Edge(
                    kind=DECLARES_CONTROLLER,
                    src_id=f"class:{rel}#{module_name}",
                    dst_id=f"class:{target}#{ctrl}",
                ))

        # -- JSX renders --
        for component_name, rendered in result.jsx_renders:
            target = _find_func(rel, rendered, index, resolver)
            if target:
                edges.append(Edge(
                    kind=RENDERS,
                    src_id=f"func:{rel}#{component_name}",
                    dst_id=f"func:{target}#{rendered}",
                ))

        # -- Hooks --
        for component_name, hook in result.hook_calls:
            edges.append(Edge(
                kind=USES_HOOK,
                src_id=f"func:{rel}#{component_name}",
                dst_id=f"hook:{hook}",
                props={"hook": hook},
            ))

    edges.append(Edge(
        kind="__STATS__",
        src_id="",
        dst_id="",
        props={"total_imports": total_imports, "unresolved_imports": unresolved_count},
    ))
    return edges


def _caller_id_for_fn(rel: str, caller_name: str, index: Index) -> str:
    """Figure out whether caller_name is a :Function, :Method, or fall back to :File."""
    if caller_name and (rel, caller_name) in index.func_by_name_in_file:
        return f"func:{rel}#{caller_name}"
    # Scan methods in this file for matching name
    if caller_name:
        for (class_id, mname), _m in index.method_by_class_and_name.items():
            if mname == caller_name and class_id.startswith(f"class:{rel}#"):
                return f"method:{class_id}#{mname}"
    # Fallback: attribute to file
    return f"file:{rel}"


def _resolve_call_target_class(
    importer: str,
    caller_mid: str,
    recv_kind: str,
    recv_name: str,
    index: Index,
) -> Optional[str]:
    """Figure out target class for a method call."""
    # caller_mid format: method:class:{file}#{class_name}#{method}
    if not caller_mid.startswith("method:class:"):
        return None
    class_id = caller_mid[len("method:"):].rsplit("#", 1)[0]

    if recv_kind == "this":
        return class_id

    if recv_kind == "this.field":
        # Look up the field name in the caller class's DI refs
        caller_result = index.files_by_path.get(importer)
        if caller_result is None:
            return None
        owner_class = class_id.split("#", 1)[1] if "#" in class_id else ""
        # Walk methods to find constructor params whose identifier == recv_name
        # (We didn't store field→type mapping, but di_refs uses type; infer via field name heuristic
        # by looking at constructor_params_json if we had them. For now fall back to name lookup.)
        # Name-only fallback:
        hits = index.class_name_to_files.get(_capitalize_guess(recv_name), [])
        if len(hits) == 1:
            return f"class:{hits[0]}#{_capitalize_guess(recv_name)}"
        return None

    if recv_kind == "name":
        # Try the imported symbols: receiver_name could be a variable bound to a class
        hits = index.class_name_to_files.get(recv_name, [])
        if len(hits) == 1:
            return f"class:{hits[0]}#{recv_name}"
    return None


def _resolve_super_target_class(
    importer: str,
    caller_mid: str,
    result: ParseResult,
    index: Index,
    resolver: Resolver,
) -> Optional[str]:
    """Resolve the target class for a ``super().foo()`` call.

    Walks the enclosing class's first parent in :attr:`ParseResult.class_extends`
    and returns the parent's ``class:{file}#{name}`` id, or ``None`` if the
    parent isn't in the indexed graph (external bases like ``Exception`` /
    ``Enum`` / ``ABC`` fall through).
    """
    if not caller_mid.startswith("method:class:"):
        return None
    class_id = caller_mid[len("method:"):].rsplit("#", 1)[0]
    cls_name = class_id.split("#", 1)[1] if "#" in class_id else ""
    if not cls_name:
        return None
    parents = [p for (c, p) in result.class_extends if c == cls_name]
    if not parents:
        return None
    target_file = _find_class(importer, parents[0], index, resolver)
    if target_file is None:
        return None
    return f"class:{target_file}#{parents[0]}"


def _capitalize_guess(name: str) -> str:
    """Heuristic: 'userService' → 'UserService'."""
    if not name:
        return name
    if name[0].isupper():
        return name
    return name[0].upper() + name[1:]


def _find_class(importer: str, symbol: str, index: Index, resolver: Resolver) -> Optional[str]:
    result = index.files_by_path.get(importer)
    if result is None:
        return None
    for spec in result.imports:
        target_path = resolver.resolve(importer, spec.specifier)
        if target_path is None:
            continue
        if (target_path, symbol) in index.class_by_name_in_file:
            return target_path
    files = index.class_name_to_files.get(symbol, [])
    if len(files) == 1:
        return files[0]
    return None


def _find_func(importer: str, symbol: str, index: Index, resolver: Resolver) -> Optional[str]:
    result = index.files_by_path.get(importer)
    if result is None:
        return None
    for spec in result.imports:
        target_path = resolver.resolve(importer, spec.specifier)
        if target_path is None:
            continue
        if (target_path, symbol) in index.func_by_name_in_file:
            return target_path
    files = index.func_name_to_files.get(symbol, [])
    if len(files) == 1:
        return files[0]
    return None
