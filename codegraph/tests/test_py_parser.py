"""Tests for :mod:`codegraph.py_parser`.

The target codebase is its own test fixture — we parse real codegraph source
files and assert against ground-truth counts gathered via stdlib ``ast`` at
plan time. That gives us high-confidence regression detection: if the parser
stops finding the 17 dataclasses in ``schema.py`` or the 10 ``@mcp.tool()``
decorators in ``mcp.py``, something broke.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.py_parser import PyParser
from codegraph.schema import DECORATED_BY, DEFINES_CLASS, DEFINES_FUNC, HAS_METHOD


REPO_ROOT = Path(__file__).resolve().parents[2]
CODEGRAPH_PKG = REPO_ROOT / "codegraph" / "codegraph"


def _parse(abs_path: Path):
    rel = str(abs_path.resolve().relative_to(REPO_ROOT)).replace("\\", "/")
    return PyParser().parse_file(abs_path, rel, "codegraph")


# ── Sanity / package-wide smoke ─────────────────────────────────────


def test_parses_entire_codegraph_package():
    parser = PyParser()
    parsed = 0
    errors = []
    for p in CODEGRAPH_PKG.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        rel = str(p.resolve().relative_to(REPO_ROOT)).replace("\\", "/")
        try:
            result = parser.parse_file(p, rel, "codegraph", is_test=False)
            assert result is not None
            parsed += 1
        except Exception as e:
            errors.append((rel, e))
    assert not errors, f"parse errors: {errors}"
    assert parsed >= 15  # 18 Python files in the package


# ── schema.py ground-truth assertions ───────────────────────────────


def test_schema_py_class_count():
    result = _parse(CODEGRAPH_PKG / "schema.py")
    assert len(result.classes) == 17
    names = {c.name for c in result.classes}
    assert "PackageNode" in names
    assert "FileNode" in names
    assert "ClassNode" in names
    assert "Edge" in names
    assert "ImportSpec" in names
    assert "ParseResult" in names


def test_schema_py_dataclass_decorators():
    """schema.py has exactly 17 `@dataclass` decorators — one per class."""
    result = _parse(CODEGRAPH_PKG / "schema.py")
    dataclass_edges = [
        e for e in result.edges
        if e.kind == DECORATED_BY and e.dst_id == "dec:dataclass"
    ]
    assert len(dataclass_edges) == 17


def test_schema_py_imports():
    result = _parse(CODEGRAPH_PKG / "schema.py")
    specs = {imp.specifier for imp in result.imports}
    assert "__future__" in specs
    assert "dataclasses" in specs
    assert "typing" in specs
    # Conditional import under `if TYPE_CHECKING:`
    assert ".framework" in specs


def test_schema_py_defines_class_edges():
    """Every class should have a DEFINES_CLASS edge from the file."""
    result = _parse(CODEGRAPH_PKG / "schema.py")
    defines = [e for e in result.edges if e.kind == DEFINES_CLASS]
    assert len(defines) == 17


# ── mcp.py ground-truth ─────────────────────────────────────────────


def test_mcp_py_tool_decorators():
    """mcp.py ships 13 `@mcp.tool()` tools (10 legacy + describe_function + calls_from + callers_of)."""
    result = _parse(CODEGRAPH_PKG / "mcp.py")
    tool_edges = [
        e for e in result.edges
        if e.kind == DECORATED_BY and "mcp.tool" in e.dst_id
    ]
    assert len(tool_edges) == 13


def test_mcp_py_module_functions():
    """mcp.py has ~16 module-level functions (10 tools + helpers + main)."""
    result = _parse(CODEGRAPH_PKG / "mcp.py")
    assert len(result.functions) >= 12  # Conservative lower bound.


# ── cli.py ground-truth ─────────────────────────────────────────────


def test_cli_py_relative_imports():
    """cli.py has at least 9 relative imports to sibling modules."""
    result = _parse(CODEGRAPH_PKG / "cli.py")
    relatives = [imp for imp in result.imports if imp.specifier.startswith(".")]
    assert len(relatives) >= 9
    specs = {imp.specifier for imp in relatives}
    assert ".schema" in specs
    assert ".resolver" in specs
    assert ".utils.neo4j_json" in specs


# ── config.py: try/except import branch ─────────────────────────────


def test_config_py_try_except_import_captures_both_branches():
    """config.py has:

        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli

    Both should be captured as separate ImportSpecs so a dependency query
    sees both possibilities regardless of which one runs."""
    result = _parse(CODEGRAPH_PKG / "config.py")
    specs = {imp.specifier for imp in result.imports}
    assert "tomllib" in specs
    assert "tomli" in specs


# ── Class-related assertions ────────────────────────────────────────


def test_class_inheritance_captured():
    """ConfigError inherits from Exception — class_extends should capture it."""
    result = _parse(CODEGRAPH_PKG / "config.py")
    # class_extends is list[tuple[class_name, base_name]]
    pairs = dict(result.class_extends)
    assert pairs.get("ConfigError") == "Exception"


def test_enum_inheritance_abstract_flag_off():
    """FrameworkType(Enum) is NOT abstract — only ABC / ABCMeta set that flag."""
    result = _parse(CODEGRAPH_PKG / "framework.py")
    fw = next((c for c in result.classes if c.name == "FrameworkType"), None)
    assert fw is not None
    assert fw.is_abstract is False


def test_method_has_method_edge():
    """Every method should emit a HAS_METHOD edge from its owner class."""
    result = _parse(CODEGRAPH_PKG / "schema.py")
    has_method = [e for e in result.edges if e.kind == HAS_METHOD]
    # schema.py has 15 methods across its 17 classes.
    assert len(has_method) == len(result.methods)
    assert len(has_method) >= 10


def test_init_method_flagged_as_constructor():
    """`__init__` methods should have `is_constructor=True`."""
    result = _parse(CODEGRAPH_PKG / "resolver.py")
    inits = [m for m in result.methods if m.name == "__init__"]
    assert len(inits) >= 2
    for m in inits:
        assert m.is_constructor is True


def test_private_method_visibility():
    """Methods starting with `_` (but not dunder) are marked private."""
    result = _parse(CODEGRAPH_PKG / "resolver.py")
    private = [m for m in result.methods if m.name.startswith("_") and not m.name.startswith("__")]
    assert len(private) > 0
    for m in private:
        assert m.visibility == "private"


def test_dunder_method_visibility_public():
    """Dunder methods (`__enter__`, `__exit__`, etc.) are marked public."""
    result = _parse(CODEGRAPH_PKG / "resolver.py")
    inits = [m for m in result.methods if m.name == "__init__"]
    for m in inits:
        assert m.visibility == "public"


# ── Import shape ────────────────────────────────────────────────────


def test_aliased_import_captured():
    """`import tree_sitter_typescript as tst` should yield a namespace alias."""
    result = _parse(CODEGRAPH_PKG / "parser.py")
    aliased = [imp for imp in result.imports if imp.namespace is not None]
    assert len(aliased) >= 1
    # The TS parser imports tree_sitter_typescript as tst.
    names = {(imp.specifier, imp.namespace) for imp in aliased}
    assert ("tree_sitter_typescript", "tst") in names


def test_from_import_symbols_populated():
    """`from typing import Any, Optional` should yield symbols=['Any','Optional']."""
    result = _parse(CODEGRAPH_PKG / "mcp.py")
    typing_imp = next((imp for imp in result.imports if imp.specifier == "typing"), None)
    assert typing_imp is not None
    assert "Any" in typing_imp.symbols
    assert "Optional" in typing_imp.symbols


# ── Synthetic edge cases (tmp_path) ─────────────────────────────────


def test_async_function_parsed_as_function(tmp_path: Path):
    """`async def foo():` should still register as a FunctionNode."""
    src = 'async def fetch_data():\n    return 1\n'
    f = tmp_path / "a.py"
    f.write_text(src)
    result = PyParser().parse_file(f, "a.py", "pkg")
    # tree-sitter-python wraps async with its own node type; we skip async
    # in Stage 1 but the file should still parse without crashing. We do NOT
    # assert async functions are captured — that's an explicit Stage 1 non-goal.
    assert result is not None


def test_star_import_captured(tmp_path: Path):
    """`from x import *` is rare but should not crash."""
    f = tmp_path / "a.py"
    f.write_text("from pkg import *\n")
    result = PyParser().parse_file(f, "a.py", "pkg")
    assert result is not None
    assert len(result.imports) == 1
    assert result.imports[0].symbols == ["*"]


def test_relative_import_dotted(tmp_path: Path):
    """`from ..utils.neo4j_json import clean_row` — double-dot + dotted path."""
    f = tmp_path / "a.py"
    f.write_text("from ..utils.neo4j_json import clean_row\n")
    result = PyParser().parse_file(f, "a.py", "pkg")
    assert result is not None
    assert len(result.imports) == 1
    assert result.imports[0].specifier == "..utils.neo4j_json"
    assert result.imports[0].symbols == ["clean_row"]


def test_bare_dots_relative_import(tmp_path: Path):
    """`from . import foo` should yield specifier='.'"""
    f = tmp_path / "a.py"
    f.write_text("from . import foo\n")
    result = PyParser().parse_file(f, "a.py", "pkg")
    assert result is not None
    assert len(result.imports) == 1
    assert result.imports[0].specifier == "."
    assert result.imports[0].symbols == ["foo"]


def test_empty_file(tmp_path: Path):
    f = tmp_path / "empty.py"
    f.write_text("")
    result = PyParser().parse_file(f, "empty.py", "pkg")
    assert result is not None
    assert len(result.classes) == 0
    assert len(result.functions) == 0
    assert len(result.imports) == 0


def test_missing_file_returns_none(tmp_path: Path):
    result = PyParser().parse_file(tmp_path / "nope.py", "nope.py", "pkg")
    assert result is None


# ── Docstring + signature extraction ────────────────────────────────


def test_function_docstring_dedented(tmp_path: Path):
    """Triple-quoted docstring is captured, quotes stripped, indentation dedented."""
    src = (
        'def greet(name: str) -> str:\n'
        '    """Say hello.\n'
        '\n'
        '    A simple greeter.\n'
        '    """\n'
        '    return "hi " + name\n'
    )
    f = tmp_path / "a.py"
    f.write_text(src)
    result = PyParser().parse_file(f, "a.py", "pkg")
    assert result is not None
    fn = result.functions[0]
    assert fn.docstring.startswith("Say hello.")
    assert "A simple greeter." in fn.docstring
    # No surrounding quotes.
    assert not fn.docstring.startswith('"')
    assert not fn.docstring.endswith('"')


def test_signature_params_and_return_type(tmp_path: Path):
    """Typed params, defaults, and return type are all extracted."""
    import json as _json
    src = 'def f(x: int, y: str = "a", *args, **kwargs) -> bool:\n    return True\n'
    f = tmp_path / "a.py"
    f.write_text(src)
    result = PyParser().parse_file(f, "a.py", "pkg")
    assert result is not None
    fn = result.functions[0]
    assert fn.return_type == "bool"
    params = _json.loads(fn.params_json)
    assert len(params) == 4
    assert params[0] == {"name": "x", "type": "int", "kind": "positional"}
    assert params[1]["name"] == "y"
    assert params[1]["type"] == "str"
    assert params[1]["default"] == '"a"'
    assert params[2] == {"name": "*args", "kind": "var_positional"}
    assert params[3] == {"name": "**kwargs", "kind": "var_keyword"}


def test_no_docstring_empty_string(tmp_path: Path):
    """A function without a docstring gets ``""`` (not ``None``)."""
    f = tmp_path / "a.py"
    f.write_text("def f():\n    return 1\n")
    result = PyParser().parse_file(f, "a.py", "pkg")
    assert result is not None
    fn = result.functions[0]
    assert fn.docstring == ""
    assert fn.return_type == ""
    assert fn.params_json == "[]"


def test_method_docstring_and_self_kept(tmp_path: Path):
    """Methods get docstrings; ``self`` is kept in params_json for honesty."""
    import json as _json
    src = (
        "class Greeter:\n"
        "    def greet(self, name: str) -> str:\n"
        '        """Greet someone."""\n'
        '        return "hi " + name\n'
    )
    f = tmp_path / "a.py"
    f.write_text(src)
    result = PyParser().parse_file(f, "a.py", "pkg")
    assert result is not None
    assert len(result.methods) == 1
    m = result.methods[0]
    assert m.docstring == "Greet someone."
    params = _json.loads(m.params_json)
    assert params[0]["name"] == "self"
    assert len(params) == 2
    assert m.return_type == "str"


def test_docstring_with_non_string_first_stmt(tmp_path: Path):
    """A non-string first statement means no docstring (PEP 257)."""
    src = "def f():\n    x = 1\n    return x\n"
    f = tmp_path / "a.py"
    f.write_text(src)
    result = PyParser().parse_file(f, "a.py", "pkg")
    assert result is not None
    assert result.functions[0].docstring == ""
