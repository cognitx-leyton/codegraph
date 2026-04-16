"""Receiver-classification tests for :meth:`PyParser._classify_py_call`.

Each test parses a tiny synthetic Python source via ``tmp_path`` and asserts
the resulting ``result.method_calls`` tuples. Only method-body calls are
emitted — module-level function bodies are intentionally skipped (the
resolver's Phase 4 can't wire them anyway).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.py_parser import PyParser


def _parse_snippet(tmp_path: Path, source: str):
    p = tmp_path / "snippet.py"
    p.write_text(source, encoding="utf-8")
    rel = "snippet.py"
    parser = PyParser()
    return parser.parse_file(p, rel, "pkg")


def _calls(result):
    # Return tuples stripped of caller_mid for easier assertion.
    return [(kind, name, target) for (_mid, kind, name, target) in result.method_calls]


def test_self_call_is_typed_this(tmp_path):
    src = """
class A:
    def run(self):
        self.foo()
    def foo(self):
        pass
"""
    r = _parse_snippet(tmp_path, src)
    assert ("this", "", "foo") in _calls(r)


def test_self_field_call_is_this_field(tmp_path):
    src = """
class A:
    def run(self):
        self.svc.execute()
"""
    r = _parse_snippet(tmp_path, src)
    assert ("this.field", "svc", "execute") in _calls(r)


def test_cls_call_maps_to_this(tmp_path):
    """``cls.foo()`` inside a classmethod invokes MRO like ``self.foo()``."""
    src = """
class A:
    @classmethod
    def make(cls):
        cls.foo()
"""
    r = _parse_snippet(tmp_path, src)
    assert ("this", "", "foo") in _calls(r)


def test_super_call_is_super(tmp_path):
    src = """
class A:
    def run(self):
        super().run()
"""
    r = _parse_snippet(tmp_path, src)
    assert ("super", "", "run") in _calls(r)


def test_bare_call_is_name(tmp_path):
    src = """
class A:
    def run(self):
        helper()
"""
    r = _parse_snippet(tmp_path, src)
    assert ("name", "", "helper") in _calls(r)


def test_object_attribute_call_is_name_with_receiver(tmp_path):
    src = """
class A:
    def run(self, obj):
        obj.do()
"""
    r = _parse_snippet(tmp_path, src)
    assert ("name", "obj", "do") in _calls(r)


def test_deep_chain_uses_last_segment_as_receiver(tmp_path):
    """``a.b.c.m()`` records ``c`` as the best-effort receiver name."""
    src = """
class A:
    def run(self, a):
        a.b.c.m()
"""
    r = _parse_snippet(tmp_path, src)
    assert ("name", "c", "m") in _calls(r)


def test_subscript_receiver_keeps_target_only(tmp_path):
    src = """
class A:
    def run(self, items):
        items[0].m()
"""
    r = _parse_snippet(tmp_path, src)
    assert ("name", "", "m") in _calls(r)


def test_call_result_receiver_keeps_target_only(tmp_path):
    src = """
class A:
    def run(self):
        get_obj().m()
"""
    r = _parse_snippet(tmp_path, src)
    calls = _calls(r)
    # Both the outer .m() and the bare get_obj() call should appear.
    assert ("name", "", "m") in calls
    assert ("name", "", "get_obj") in calls


def test_module_level_function_body_is_not_scanned(tmp_path):
    """Resolver can't wire module-level callers — so we don't emit from them."""
    src = """
def outer():
    helper()
"""
    r = _parse_snippet(tmp_path, src)
    assert _calls(r) == []


def test_comprehension_calls_emitted(tmp_path):
    """Descendant walk catches calls nested inside comprehensions."""
    src = """
class A:
    def run(self, items):
        [self.touch(x) for x in items]
"""
    r = _parse_snippet(tmp_path, src)
    assert ("this", "", "touch") in _calls(r)


def test_staticmethod_body_still_scanned(tmp_path):
    """No special-casing by decorator — static methods still emit calls."""
    src = """
class A:
    @staticmethod
    def helper():
        other()
"""
    r = _parse_snippet(tmp_path, src)
    assert ("name", "", "other") in _calls(r)
