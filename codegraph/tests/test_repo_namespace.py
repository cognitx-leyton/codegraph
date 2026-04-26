"""Tests for the ``repo`` namespace added by issue #263.

Verifies that all file-bearing node IDs embed the repo segment, that
``_file_from_id`` correctly strips it, and that two repos with identical
relative paths produce distinct IDs.
"""
from __future__ import annotations

import pytest

from codegraph.schema import (
    AtomNode,
    ClassNode,
    EndpointNode,
    FileNode,
    FunctionNode,
    GraphQLOperationNode,
    InterfaceNode,
    MethodNode,
    PackageNode,
    RouteNode,
)
from codegraph.loader import _file_from_id


# ── ID format tests ───────────────────────────────────────────────────


class TestFileNodeId:
    def test_default_repo(self):
        f = FileNode(path="src/app.py", package="pkg", language="py", loc=10)
        assert f.id == "file:default:src/app.py"
        assert f.repo == "default"

    def test_custom_repo(self):
        f = FileNode(path="src/app.py", package="pkg", language="py", loc=10, repo="my-repo")
        assert f.id == "file:my-repo:src/app.py"

    def test_two_repos_same_path_differ(self):
        f1 = FileNode(path="src/app.py", package="pkg", language="py", loc=10, repo="repo-a")
        f2 = FileNode(path="src/app.py", package="pkg", language="py", loc=10, repo="repo-b")
        assert f1.id != f2.id


class TestClassNodeId:
    def test_contains_repo(self):
        c = ClassNode(name="Foo", file="src/foo.py", repo="my-repo")
        assert c.id == "class:my-repo:src/foo.py#Foo"

    def test_default_repo(self):
        c = ClassNode(name="Foo", file="src/foo.py")
        assert c.id == "class:default:src/foo.py#Foo"


class TestFunctionNodeId:
    def test_contains_repo(self):
        fn = FunctionNode(name="bar", file="src/bar.py", repo="my-repo")
        assert fn.id == "func:my-repo:src/bar.py#bar"


class TestMethodNodeId:
    def test_inherits_repo_from_class_id(self):
        m = MethodNode(
            name="do_stuff",
            file="src/foo.py",
            class_id="class:my-repo:src/foo.py#Foo",
        )
        assert m.id == "method:class:my-repo:src/foo.py#Foo#do_stuff"


class TestInterfaceNodeId:
    def test_contains_repo(self):
        i = InterfaceNode(name="IFoo", file="src/foo.ts", repo="my-repo")
        assert i.id == "interface:my-repo:src/foo.ts#IFoo"


class TestEndpointNodeId:
    def test_contains_repo(self):
        ep = EndpointNode(
            method="GET", path="/api", handler="handle",
            file="src/ctrl.ts", controller_class="class:my-repo:src/ctrl.ts#Ctrl",
            repo="my-repo",
        )
        assert ep.id == "endpoint:GET:/api@my-repo:src/ctrl.ts#handle"


class TestGraphQLOperationNodeId:
    def test_contains_repo(self):
        gql = GraphQLOperationNode(
            name="getUser", op_type="Query", handler="getUser",
            return_type="User",
            file="src/user.ts", resolver_class="class:my-repo:src/user.ts#UserResolver",
            repo="my-repo",
        )
        assert gql.id == "gqlop:Query:getUser@my-repo:src/user.ts#getUser"


class TestAtomNodeId:
    def test_contains_repo(self):
        a = AtomNode(name="MY_CONST", file="src/const.py", family=True, repo="my-repo")
        assert a.id == "atom:my-repo:src/const.py#MY_CONST"


class TestPackageNodeId:
    def test_contains_repo(self):
        p = PackageNode(name="codegraph", framework="Python", repo="my-repo")
        assert p.id == "package:my-repo:codegraph"

    def test_default_repo(self):
        p = PackageNode(name="codegraph", framework="Python")
        assert p.id == "package:default:codegraph"


class TestRouteNodeId:
    def test_contains_repo(self):
        r = RouteNode(path="/api", component_name="App", file="src/routes.py", repo="my-repo")
        assert r.id == "route:/api@my-repo:src/routes.py"


# ── _file_from_id tests ──────────────────────────────────────────────


class TestFileFromId:
    def test_file_id(self):
        assert _file_from_id("file:my-repo:src/app.py") == "src/app.py"

    def test_class_id(self):
        assert _file_from_id("class:my-repo:src/foo.py#Foo") == "src/foo.py"

    def test_func_id(self):
        assert _file_from_id("func:my-repo:src/bar.py#bar") == "src/bar.py"

    def test_method_id(self):
        assert _file_from_id("method:class:my-repo:src/foo.py#Foo#do_stuff") == "src/foo.py"

    def test_iface_id(self):
        assert _file_from_id("interface:my-repo:src/foo.ts#IFoo") == "src/foo.ts"

    def test_atom_id(self):
        assert _file_from_id("atom:my-repo:src/const.py#MY_CONST") == "src/const.py"

    def test_endpoint_id(self):
        assert _file_from_id("endpoint:GET:/api@my-repo:src/ctrl.ts#handle") == "src/ctrl.ts"

    def test_gqlop_id(self):
        assert _file_from_id("gqlop:Query:getUser@my-repo:src/user.ts#getUser") == "src/user.ts"

    def test_singleton_returns_none(self):
        assert _file_from_id("hook:useEffect") is None
        assert _file_from_id("external:lodash") is None
        assert _file_from_id("dec:Injectable") is None

    def test_default_repo(self):
        assert _file_from_id("file:default:src/app.py") == "src/app.py"

    def test_route_id(self):
        assert _file_from_id("route:/api@my-repo:src/routes.py") == "src/routes.py"


# ── Backward compatibility ────────────────────────────────────────────


class TestBackwardCompat:
    def test_filenode_default_repo_when_missing(self):
        """Deserializing old cache entries (no ``repo`` key) falls back to 'default'."""
        f = FileNode(path="src/app.py", package="pkg", language="py", loc=10)
        assert f.repo == "default"
        assert "default" in f.id

    def test_classnode_default_repo(self):
        c = ClassNode(name="Foo", file="src/foo.py")
        assert c.repo == "default"


# ── Multi-repo isolation ─────────────────────────────────────────────


class TestMultiRepoIsolation:
    """Two repos with identical file paths produce wholly distinct ID spaces."""

    def _make_file(self, repo: str) -> FileNode:
        return FileNode(path="src/app.py", package="pkg", language="py", loc=10, repo=repo)

    def test_file_ids_differ(self):
        assert self._make_file("alpha").id != self._make_file("beta").id

    def test_class_ids_differ(self):
        c1 = ClassNode(name="Foo", file="src/foo.py", repo="alpha")
        c2 = ClassNode(name="Foo", file="src/foo.py", repo="beta")
        assert c1.id != c2.id

    def test_function_ids_differ(self):
        f1 = FunctionNode(name="bar", file="src/bar.py", repo="alpha")
        f2 = FunctionNode(name="bar", file="src/bar.py", repo="beta")
        assert f1.id != f2.id

    def test_package_ids_differ(self):
        p1 = PackageNode(name="codegraph", framework="Python", repo="alpha")
        p2 = PackageNode(name="codegraph", framework="Python", repo="beta")
        assert p1.id != p2.id
