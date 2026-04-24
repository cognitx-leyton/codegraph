"""Tests for Python import resolution in :mod:`codegraph.resolver`.

Builds a synthetic Python package in ``tmp_path`` and runs the full
``PyParser`` + ``Resolver`` + ``link_cross_file`` pipeline, inspecting the
resulting edges. Exercises all three resolution rules: relative imports,
absolute intra-package imports, and external fallback.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.py_parser import PyParser
from codegraph.resolver import (
    Index,
    PathIndex,
    Resolver,
    link_cross_file,
    load_python_package_config,
)
from codegraph.schema import CALLS, IMPORTS, IMPORTS_SYMBOL


# ── Helpers ─────────────────────────────────────────────────────────


def _build_pkg(root: Path, files: dict[str, str]) -> None:
    """Write each key→value under ``root``, creating parent dirs as needed."""
    for rel, content in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)


def _run_pipeline(
    repo_root: Path, package_name: str, package_dir: Path
) -> tuple[Index, list]:
    """Parse every .py under ``package_dir`` and run cross-file linking."""
    parser = PyParser()
    index = Index()
    for p in package_dir.rglob("*.py"):
        rel = str(p.resolve().relative_to(repo_root)).replace("\\", "/")
        result = parser.parse_file(p, rel, package_name, is_test=False)
        assert result is not None, f"failed to parse {rel}"
        index.add(result)

    pkg_config = load_python_package_config(repo_root, package_dir)
    resolver = Resolver(repo_root, [pkg_config])
    edges, _edge_groups = link_cross_file(index, resolver)
    return index, edges


# ── Resolution rules ────────────────────────────────────────────────


def test_relative_import_resolves(tmp_path: Path):
    """`from .b import Bar` inside pkg/a.py → IMPORTS edge to pkg/b.py."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "from .b import Bar\n",
        "pkg/b.py": "class Bar:\n    pass\n",
    })
    index, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")

    imports = [e for e in edges if e.kind == IMPORTS]
    # Expect: a.py → b.py (intra-package)
    resolved = [e for e in imports if not e.dst_id.startswith("external:")]
    assert len(resolved) == 1
    assert resolved[0].src_id == "file:pkg/a.py"
    assert resolved[0].dst_id == "file:pkg/b.py"


def test_absolute_intra_package_import_resolves(tmp_path: Path):
    """`from pkg.c import Baz` inside pkg/a.py → IMPORTS edge to pkg/c.py."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "from pkg.c import Baz\n",
        "pkg/c.py": "class Baz:\n    pass\n",
    })
    index, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")

    resolved = [e for e in edges if e.kind == IMPORTS and not e.dst_id.startswith("external:")]
    assert len(resolved) == 1
    assert resolved[0].src_id == "file:pkg/a.py"
    assert resolved[0].dst_id == "file:pkg/c.py"


def test_external_import_falls_through(tmp_path: Path):
    """`from neo4j import GraphDatabase` → IMPORTS edge to :External."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "from neo4j import GraphDatabase\n",
    })
    index, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")

    imports = [e for e in edges if e.kind == IMPORTS]
    assert len(imports) == 1
    assert imports[0].dst_id == "external:neo4j"
    # The external flag is set in props so the loader can apply the right label.
    assert imports[0].props.get("external") is True


def test_dotted_relative_import_walks_up(tmp_path: Path):
    """`from ..b import Bar` inside pkg/sub/d.py → IMPORTS edge to pkg/b.py."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/b.py": "class Bar:\n    pass\n",
        "pkg/sub/__init__.py": "",
        "pkg/sub/d.py": "from ..b import Bar\n",
    })
    index, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")

    resolved = [e for e in edges if e.kind == IMPORTS and not e.dst_id.startswith("external:")]
    assert len(resolved) == 1
    assert resolved[0].src_id == "file:pkg/sub/d.py"
    assert resolved[0].dst_id == "file:pkg/b.py"


def test_import_of_subpackage_as_file(tmp_path: Path):
    """`from pkg.sub.d import X` — resolves pkg/sub/d.py as a .py file."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "from pkg.sub.d import X\n",
        "pkg/sub/__init__.py": "",
        "pkg/sub/d.py": "class X:\n    pass\n",
    })
    index, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")

    resolved = [e for e in edges if e.kind == IMPORTS and not e.dst_id.startswith("external:")]
    assert any(e.dst_id == "file:pkg/sub/d.py" for e in resolved)


def test_import_of_subpackage_as_init(tmp_path: Path):
    """`from pkg.sub import foo` — resolves pkg/sub/__init__.py when no pkg/sub.py."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "from pkg.sub import foo\n",
        "pkg/sub/__init__.py": "foo = 1\n",
    })
    index, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")

    resolved = [e for e in edges if e.kind == IMPORTS and not e.dst_id.startswith("external:")]
    assert any(e.dst_id == "file:pkg/sub/__init__.py" for e in resolved)


def test_walk_above_package_root_is_external(tmp_path: Path):
    """A relative import that walks too many dots (`from ....way_too_far`) should
    fall back to external rather than resolving to something outside the package."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "from ....way_too_far import X\n",
    })
    index, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")

    imports = [e for e in edges if e.kind == IMPORTS]
    assert len(imports) == 1
    # Either external, or resolved to something nonexistent (path-index miss → external).
    assert imports[0].dst_id.startswith("external:")


def test_bare_relative_from_import(tmp_path: Path):
    """`from . import b` resolves to pkg/__init__.py (the package module)."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "b = 1\n",
        "pkg/a.py": "from . import b\n",
    })
    index, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")

    resolved = [e for e in edges if e.kind == IMPORTS and not e.dst_id.startswith("external:")]
    assert any(e.dst_id == "file:pkg/__init__.py" for e in resolved)


def test_imports_symbol_edges_emitted(tmp_path: Path):
    """Each imported symbol gets its own IMPORTS_SYMBOL edge with the symbol
    name in props."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "from .b import Bar, Baz\n",
        "pkg/b.py": "class Bar: pass\nclass Baz: pass\n",
    })
    index, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")

    symbol_edges = [e for e in edges if e.kind == IMPORTS_SYMBOL]
    symbols = {e.props.get("symbol") for e in symbol_edges}
    assert "Bar" in symbols
    assert "Baz" in symbols


def test_import_statement_absolute(tmp_path: Path):
    """`import pkg.b` → IMPORTS edge to pkg/b.py (dotted_name import)."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "import pkg.b\n",
        "pkg/b.py": "x = 1\n",
    })
    index, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")

    resolved = [e for e in edges if e.kind == IMPORTS and not e.dst_id.startswith("external:")]
    assert any(e.dst_id == "file:pkg/b.py" for e in resolved)


def test_ts_import_unaffected_by_python_dispatch(tmp_path: Path):
    """Smoke test: a Resolver with no Python packages behaves exactly like
    before (no _is_python_file true-case, Python dispatch never fires).

    This protects the TS code path from the language-aware short-circuit we
    added in :meth:`Resolver.resolve`.
    """
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": "from .b import Bar\n",
        "pkg/b.py": "class Bar: pass\n",
    })
    pkg_config = load_python_package_config(tmp_path, tmp_path / "pkg")
    # Two resolvers: one aware of the Python package, one not.
    py_aware = Resolver(tmp_path, [pkg_config])
    no_pkg = Resolver(tmp_path, [])

    fileset = {f"pkg/{n}" for n in ("__init__.py", "a.py", "b.py")}
    py_aware.set_path_index(PathIndex(fileset))
    no_pkg.set_path_index(PathIndex(fileset))

    # Python-aware resolver resolves the relative import.
    assert py_aware.resolve("pkg/a.py", ".b") == "pkg/b.py"
    # No-package resolver falls into the TS code path and either returns
    # None (no .ts/.tsx extension candidates match) or a non-Python file.
    # Critically: it does NOT try Python rules and does NOT crash.
    result = no_pkg.resolve("pkg/a.py", ".b")
    # The TS path would try pkg/a/../.b + TS extensions; none exist, so None.
    # (We just want no crash and no accidental Python resolution.)
    assert result is None or not result.endswith(".py")


# ── Phase 4: method CALLS resolution (Python) ───────────────────────


def _calls_edges(edges):
    return [e for e in edges if e.kind == CALLS]


def test_self_call_resolves_typed(tmp_path: Path):
    """``self.foo()`` inside the same class → typed CALLS edge."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": (
            "class A:\n"
            "    def run(self):\n"
            "        self.foo()\n"
            "    def foo(self):\n"
            "        pass\n"
        ),
    })
    _, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")
    calls = _calls_edges(edges)
    assert any(
        e.src_id == "method:class:pkg/a.py#A#run"
        and e.dst_id == "method:class:pkg/a.py#A#foo"
        and e.props.get("confidence") == "typed"
        for e in calls
    ), f"expected typed self.foo() edge; got {calls}"


def test_super_call_resolves_to_parent(tmp_path: Path):
    """``super().run()`` resolves via ``class_extends`` to the parent method."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/base.py": (
            "class B:\n"
            "    def run(self):\n"
            "        pass\n"
        ),
        "pkg/child.py": (
            "from .base import B\n"
            "class A(B):\n"
            "    def run(self):\n"
            "        super().run()\n"
        ),
    })
    _, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")
    calls = _calls_edges(edges)
    assert any(
        e.src_id == "method:class:pkg/child.py#A#run"
        and e.dst_id == "method:class:pkg/base.py#B#run"
        and e.props.get("confidence") == "typed"
        for e in calls
    ), f"expected typed super().run() edge; got {calls}"


def test_cls_call_resolves_like_self(tmp_path: Path):
    """``cls.foo()`` inside a classmethod resolves to the enclosing class."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": (
            "class A:\n"
            "    @classmethod\n"
            "    def make(cls):\n"
            "        cls.foo()\n"
            "    @classmethod\n"
            "    def foo(cls):\n"
            "        pass\n"
        ),
    })
    _, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")
    calls = _calls_edges(edges)
    assert any(
        e.src_id == "method:class:pkg/a.py#A#make"
        and e.dst_id == "method:class:pkg/a.py#A#foo"
        and e.props.get("confidence") == "typed"
        for e in calls
    ), f"expected typed cls.foo() edge; got {calls}"


# ── Phase 4: function-to-function + module-level CALLS (issue #88) ──


def test_function_to_function_same_file_resolves(tmp_path: Path):
    """helper() called from run() in the same file produces a CALLS edge."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/a.py": (
            "def helper():\n"
            "    pass\n"
            "\n"
            "def run():\n"
            "    helper()\n"
        ),
    })
    _, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")
    calls = _calls_edges(edges)
    assert any(
        e.src_id == "func:pkg/a.py#run"
        and e.dst_id == "func:pkg/a.py#helper"
        for e in calls
    ), f"expected func-to-func CALLS edge; got {calls}"


def test_function_to_function_cross_file_resolves(tmp_path: Path):
    """helper() imported from another module produces cross-file CALLS edge."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/utils.py": "def helper():\n    pass\n",
        "pkg/main.py": (
            "from .utils import helper\n"
            "\n"
            "def run():\n"
            "    helper()\n"
        ),
    })
    _, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")
    calls = _calls_edges(edges)
    assert any(
        e.src_id == "func:pkg/main.py#run"
        and e.dst_id == "func:pkg/utils.py#helper"
        for e in calls
    ), f"expected cross-file func-to-func CALLS edge; got {calls}"


def test_module_level_call_to_function_resolves(tmp_path: Path):
    """Module-level main() call produces CALLS edge from file to function."""
    _build_pkg(tmp_path, {
        "pkg/__init__.py": "",
        "pkg/app.py": (
            "def main():\n"
            "    pass\n"
            "\n"
            'if __name__ == "__main__":\n'
            "    main()\n"
        ),
    })
    _, edges = _run_pipeline(tmp_path, "pkg", tmp_path / "pkg")
    calls = _calls_edges(edges)
    assert any(
        e.src_id == "file:pkg/app.py"
        and e.dst_id == "func:pkg/app.py#main"
        for e in calls
    ), f"expected module-level-to-func CALLS edge; got {calls}"
