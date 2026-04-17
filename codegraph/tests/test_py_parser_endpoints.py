"""Tests for Python endpoint + ORM column emission in :mod:`codegraph.py_parser`.

Covers FastAPI / Flask route decorators → ``EndpointNode`` + edges,
and SQLAlchemy / Django ORM → ``ColumnNode`` + ``HAS_COLUMN`` edges.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.py_parser import PyParser
from codegraph.schema import EXPOSES, HANDLES, HAS_COLUMN


# ── Helpers ──────────────────────────────────────────────────────────


def _parse(tmp_path: Path, code: str, filename: str = "app.py"):
    """Write code to a temp file, parse it, return the ParseResult."""
    f = tmp_path / filename
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(code)
    parser = PyParser()
    return parser.parse_file(f, filename, "myapp", is_test=False)


# ═══════════════════════════════════════════════════════════════════
# FastAPI endpoints
# ═══════════════════════════════════════════════════════════════════


class TestFastAPIEndpoints:

    def test_function_endpoint(self, tmp_path: Path):
        """``@app.get("/users")`` on a top-level function → EndpointNode."""
        result = _parse(tmp_path, """\
from fastapi import FastAPI
app = FastAPI()

@app.get("/users")
def get_users():
    return []
""")
        assert len(result.endpoints) == 1
        ep = result.endpoints[0]
        assert ep.method == "GET"
        assert ep.path == "/users"
        assert ep.handler == "get_users"

    def test_multiple_endpoints(self, tmp_path: Path):
        """Multiple route decorators → multiple EndpointNode objects."""
        result = _parse(tmp_path, """\
from fastapi import FastAPI
app = FastAPI()

@app.get("/items")
def list_items():
    return []

@app.post("/items")
def create_item():
    return {}

@app.delete("/items/{id}")
def delete_item():
    pass
""")
        assert len(result.endpoints) == 3
        methods = {ep.method for ep in result.endpoints}
        assert methods == {"GET", "POST", "DELETE"}

    def test_router_decorator(self, tmp_path: Path):
        """``@router.post("/users")`` also detected."""
        result = _parse(tmp_path, """\
from fastapi import APIRouter
router = APIRouter()

@router.post("/users")
def create_user():
    return {}
""")
        assert len(result.endpoints) == 1
        assert result.endpoints[0].method == "POST"
        assert result.endpoints[0].path == "/users"

    def test_endpoint_edges(self, tmp_path: Path):
        """Each endpoint produces EXPOSES + HANDLES edges."""
        result = _parse(tmp_path, """\
@app.get("/health")
def health():
    return {"ok": True}
""")
        assert len(result.endpoints) == 1
        exposes = [e for e in result.edges if e.kind == EXPOSES]
        handles = [e for e in result.edges if e.kind == HANDLES]
        assert len(exposes) == 1
        assert len(handles) == 1
        # HANDLES links function → endpoint
        assert "health" in handles[0].src_id
        assert "health" in handles[0].dst_id

    def test_class_method_endpoint(self, tmp_path: Path):
        """Route decorator on a class method → EndpointNode with class as controller."""
        result = _parse(tmp_path, """\
class UserController:
    @app.get("/users")
    def list_users(self):
        return []
""")
        assert len(result.endpoints) == 1
        ep = result.endpoints[0]
        assert ep.method == "GET"
        assert "UserController" in ep.controller_class


# ═══════════════════════════════════════════════════════════════════
# Flask endpoints
# ═══════════════════════════════════════════════════════════════════


class TestFlaskEndpoints:

    def test_route_with_methods_kwarg(self, tmp_path: Path):
        """``@app.route("/items", methods=["POST"])`` → POST endpoint."""
        result = _parse(tmp_path, """\
from flask import Flask
app = Flask(__name__)

@app.route("/items", methods=["POST"])
def create_item():
    return {}
""")
        assert len(result.endpoints) == 1
        assert result.endpoints[0].method == "POST"
        assert result.endpoints[0].path == "/items"

    def test_route_default_get(self, tmp_path: Path):
        """``@app.route("/")`` without methods kwarg → defaults to GET."""
        result = _parse(tmp_path, """\
@app.route("/")
def index():
    return "Hello"
""")
        assert len(result.endpoints) == 1
        assert result.endpoints[0].method == "GET"

    def test_blueprint_route(self, tmp_path: Path):
        """``@bp.route("/users")`` on a blueprint."""
        result = _parse(tmp_path, """\
@bp.route("/users", methods=["GET"])
def list_users():
    return []
""")
        assert len(result.endpoints) == 1
        assert result.endpoints[0].method == "GET"


# ═══════════════════════════════════════════════════════════════════
# SQLAlchemy ORM
# ═══════════════════════════════════════════════════════════════════


class TestSQLAlchemyORM:

    def test_entity_detection(self, tmp_path: Path):
        """Class extending ``Base`` → ``is_entity=True``."""
        result = _parse(tmp_path, """\
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String)
""", "models.py")
        user_cls = [c for c in result.classes if c.name == "User"][0]
        assert user_cls.is_entity is True
        assert user_cls.table_name == "users"

    def test_column_nodes(self, tmp_path: Path):
        """Column assignments → ColumnNode objects."""
        result = _parse(tmp_path, """\
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String(50))
    email = Column(String)
""", "models.py")
        assert len(result.columns) == 3
        col_names = {c.name for c in result.columns}
        assert col_names == {"id", "name", "email"}
        # Type extraction
        id_col = [c for c in result.columns if c.name == "id"][0]
        assert id_col.type == "Integer"

    def test_has_column_edges(self, tmp_path: Path):
        """Each column produces a HAS_COLUMN edge."""
        result = _parse(tmp_path, """\
class User(Base):
    id = Column(Integer)
    name = Column(String)
""", "models.py")
        hc_edges = [e for e in result.edges if e.kind == HAS_COLUMN]
        assert len(hc_edges) == 2

    def test_relationship(self, tmp_path: Path):
        """``relationship("Address")`` → entry in result.relations."""
        result = _parse(tmp_path, """\
class User(Base):
    id = Column(Integer)
    addresses = relationship("Address")
""", "models.py")
        assert len(result.relations) == 1
        cls_name, rel_type, field, target = result.relations[0]
        assert cls_name == "User"
        assert rel_type == "relationship"
        assert field == "addresses"
        assert target == "Address"

    def test_foreign_key(self, tmp_path: Path):
        """``ForeignKey("users.id")`` → relation entry."""
        result = _parse(tmp_path, """\
class Address(Base):
    user_id = Column(Integer, ForeignKey("users.id"))
""", "models.py")
        assert len(result.relations) == 1
        _, rel_type, field, target = result.relations[0]
        assert rel_type == "ForeignKey"
        assert target == "users"

    def test_declarative_base(self, tmp_path: Path):
        """Class extending ``DeclarativeBase`` is also detected as entity."""
        result = _parse(tmp_path, """\
class Base(DeclarativeBase):
    pass

class Item(Base):
    id = Column(Integer)
""", "models.py")
        item_cls = [c for c in result.classes if c.name == "Item"][0]
        assert item_cls.is_entity is True


# ═══════════════════════════════════════════════════════════════════
# Django ORM
# ═══════════════════════════════════════════════════════════════════


class TestDjangoORM:

    def test_django_model_entity(self, tmp_path: Path):
        """Class extending ``models.Model`` → ``is_entity=True``."""
        result = _parse(tmp_path, """\
from django.db import models

class Article(models.Model):
    title = models.CharField(max_length=200)
    body = models.TextField()
""", "models.py")
        article = [c for c in result.classes if c.name == "Article"][0]
        assert article.is_entity is True

    def test_django_column_types(self, tmp_path: Path):
        """Django model fields → ColumnNode with type derived from field name."""
        result = _parse(tmp_path, """\
class Article(models.Model):
    title = models.CharField(max_length=200)
    count = models.IntegerField()
    active = models.BooleanField()
""", "models.py")
        assert len(result.columns) == 3
        types = {c.name: c.type for c in result.columns}
        assert types["title"] == "Char"
        assert types["count"] == "Integer"
        assert types["active"] == "Boolean"

    def test_django_foreign_key(self, tmp_path: Path):
        """``models.ForeignKey("auth.User")`` → relation entry."""
        result = _parse(tmp_path, """\
class Comment(models.Model):
    author = models.ForeignKey("auth.User")
""", "models.py")
        assert len(result.relations) == 1
        assert result.relations[0][3] == "auth"


# ═══════════════════════════════════════════════════════════════════
# Integration: FastAPI + SQLAlchemy golden path
# ═══════════════════════════════════════════════════════════════════


class TestIntegration:

    def test_fastapi_sqlalchemy_app(self, tmp_path: Path):
        """Realistic FastAPI app with SQLAlchemy models — full ParseResult check."""
        result = _parse(tmp_path, """\
from fastapi import FastAPI, APIRouter
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship

app = FastAPI()
router = APIRouter()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    email = Column(String)
    posts = relationship("Post")

class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    title = Column(String)
    user_id = Column(Integer, ForeignKey("users.id"))

@router.get("/users")
def list_users():
    return []

@router.post("/users")
def create_user():
    return {}

@router.get("/posts")
def list_posts():
    return []
""", "main.py")

        # Endpoints
        assert len(result.endpoints) == 3
        methods = sorted(ep.method for ep in result.endpoints)
        assert methods == ["GET", "GET", "POST"]

        # ORM entities
        user = [c for c in result.classes if c.name == "User"][0]
        post = [c for c in result.classes if c.name == "Post"][0]
        assert user.is_entity is True
        assert user.table_name == "users"
        assert post.is_entity is True
        assert post.table_name == "posts"

        # Columns: 3 for User + 3 for Post = 6
        assert len(result.columns) == 6

        # Relations: 1 relationship + 1 ForeignKey
        assert len(result.relations) == 2

        # Edge counts
        exposes = [e for e in result.edges if e.kind == EXPOSES]
        handles = [e for e in result.edges if e.kind == HANDLES]
        has_col = [e for e in result.edges if e.kind == HAS_COLUMN]
        assert len(exposes) == 3
        assert len(handles) == 3
        assert len(has_col) == 6
