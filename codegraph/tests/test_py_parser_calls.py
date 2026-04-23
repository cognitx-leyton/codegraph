"""Receiver-classification tests for :meth:`PyParser._classify_py_call`.

Each test parses a tiny synthetic Python source via ``tmp_path`` and asserts
the resulting ``result.method_calls`` tuples. Method-body, function-body, and
module-level calls are all emitted (issue #88).
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


def test_function_body_calls_emitted(tmp_path):
    """Function bodies now emit CALLS entries (issue #88)."""
    src = """
def outer():
    helper()
"""
    r = _parse_snippet(tmp_path, src)
    assert ("name", "", "helper") in _calls(r)


def test_function_body_attribute_call(tmp_path):
    """obj.method() inside a function body is classified correctly."""
    src = """
def run(svc):
    svc.execute()
"""
    r = _parse_snippet(tmp_path, src)
    assert ("name", "svc", "execute") in _calls(r)


def test_module_level_bare_call(tmp_path):
    """Bare call at module level emits a CALLS entry with file ID as caller."""
    src = """
main()
"""
    r = _parse_snippet(tmp_path, src)
    assert any(mid.startswith("file:") and t == "main"
                for mid, _k, _n, t in r.method_calls)


def test_module_level_if_main_call(tmp_path):
    """if __name__ == '__main__': main() emits a CALLS entry."""
    src = '''
def main():
    pass

if __name__ == "__main__":
    main()
'''
    r = _parse_snippet(tmp_path, src)
    file_calls = [(k, n, t) for mid, k, n, t in r.method_calls
                   if mid.startswith("file:")]
    assert ("name", "", "main") in file_calls


def test_module_level_attribute_call(tmp_path):
    """app.run() at module level."""
    src = """
app.run()
"""
    r = _parse_snippet(tmp_path, src)
    file_calls = [(k, n, t) for mid, k, n, t in r.method_calls
                   if mid.startswith("file:")]
    assert ("name", "app", "run") in file_calls


def test_module_level_nested_in_try(tmp_path):
    """Module-level call inside try/except."""
    src = """
try:
    setup()
except Exception:
    pass
"""
    r = _parse_snippet(tmp_path, src)
    file_calls = [(k, n, t) for mid, k, n, t in r.method_calls
                   if mid.startswith("file:")]
    assert ("name", "", "setup") in file_calls


def test_module_level_nested_in_elif(tmp_path):
    """Module-level call inside elif block."""
    src = """
if False:
    pass
elif True:
    configure()
"""
    r = _parse_snippet(tmp_path, src)
    file_calls = [(k, n, t) for mid, k, n, t in r.method_calls
                   if mid.startswith("file:")]
    assert ("name", "", "configure") in file_calls


def test_module_level_nested_in_finally(tmp_path):
    """Module-level call inside finally block."""
    src = """
try:
    pass
finally:
    teardown()
"""
    r = _parse_snippet(tmp_path, src)
    file_calls = [(k, n, t) for mid, k, n, t in r.method_calls
                   if mid.startswith("file:")]
    assert ("name", "", "teardown") in file_calls


def test_module_level_nested_in_for(tmp_path):
    """Module-level call inside for loop (issue #227)."""
    src = """
for plugin in plugins:
    register(plugin)
"""
    r = _parse_snippet(tmp_path, src)
    file_calls = [(k, n, t) for mid, k, n, t in r.method_calls
                   if mid.startswith("file:")]
    assert ("name", "", "register") in file_calls


def test_module_level_nested_in_while(tmp_path):
    """Module-level call inside while loop (issue #227)."""
    src = """
while not ready:
    setup()
"""
    r = _parse_snippet(tmp_path, src)
    file_calls = [(k, n, t) for mid, k, n, t in r.method_calls
                   if mid.startswith("file:")]
    assert ("name", "", "setup") in file_calls


def test_module_level_nested_in_match(tmp_path):
    """Module-level call inside match/case block (Python 3.10+)."""
    src = """
match command:
    case 'quit':
        shutdown()
    case 'help':
        show_help()
"""
    r = _parse_snippet(tmp_path, src)
    file_calls = [(k, n, t) for mid, k, n, t in r.method_calls
                   if mid.startswith("file:")]
    assert ("name", "", "shutdown") in file_calls
    assert ("name", "", "show_help") in file_calls


def test_function_body_caller_id_is_func(tmp_path):
    """Caller ID for function-body calls uses func: prefix."""
    src = """
def outer():
    helper()
"""
    r = _parse_snippet(tmp_path, src)
    assert any(mid == "func:snippet.py#outer" and t == "helper"
                for mid, _k, _n, t in r.method_calls)


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
