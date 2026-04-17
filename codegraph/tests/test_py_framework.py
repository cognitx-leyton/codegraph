"""Tests for Python + Fastify framework detection in :class:`codegraph.framework.FrameworkDetector`.

Builds synthetic package directories in ``tmp_path`` with characteristic
files / dependency declarations / code patterns and verifies that
``FrameworkDetector.detect()`` returns the correct ``FrameworkType``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.framework import FrameworkDetector, FrameworkType


# ── Helpers ──────────────────────────────────────────────────────────


def _write(root: Path, rel: str, content: str = "") -> None:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)


# ═══════════════════════════════════════════════════════════════════
# FastAPI
# ═══════════════════════════════════════════════════════════════════


class TestFastAPI:

    def test_pyproject_dependency(self, tmp_path: Path):
        """FastAPI detected via pyproject.toml dependency."""
        _write(tmp_path, "pyproject.toml", """\
[project]
name = "myapi"
dependencies = ["fastapi>=0.100", "uvicorn"]
""")
        _write(tmp_path, "main.py", """\
from fastapi import FastAPI
app = FastAPI()

@app.get("/")
def root():
    return {"msg": "hi"}
""")
        info = FrameworkDetector(tmp_path).detect()
        assert info.framework == FrameworkType.FASTAPI
        assert info.confidence >= 0.5

    def test_requirements_txt(self, tmp_path: Path):
        """FastAPI detected via requirements.txt."""
        _write(tmp_path, "requirements.txt", "fastapi==0.104.1\nuvicorn\npydantic\n")
        _write(tmp_path, "app.py", "from fastapi import FastAPI\napp = FastAPI()\n")
        info = FrameworkDetector(tmp_path).detect()
        assert info.framework == FrameworkType.FASTAPI

    def test_code_pattern_only(self, tmp_path: Path):
        """FastAPI detected from code patterns alone (no dependency file)."""
        _write(tmp_path, "main.py", """\
from fastapi import FastAPI
app = FastAPI()

@app.get("/users")
def list_users():
    return []

@app.post("/users")
def create_user():
    return {}
""")
        info = FrameworkDetector(tmp_path).detect()
        # Two pattern matches (from fastapi import + @app.get) = 30pts, above threshold
        assert info.framework == FrameworkType.FASTAPI
        assert info.confidence >= 0.25


# ═══════════════════════════════════════════════════════════════════
# Flask
# ═══════════════════════════════════════════════════════════════════


class TestFlask:

    def test_requirements_and_pattern(self, tmp_path: Path):
        """Flask detected via requirements.txt + code pattern."""
        _write(tmp_path, "requirements.txt", "flask==3.0\ngunicorn\n")
        _write(tmp_path, "app.py", """\
from flask import Flask
app = Flask(__name__)

@app.route("/hello")
def hello():
    return "Hello!"
""")
        info = FrameworkDetector(tmp_path).detect()
        assert info.framework == FrameworkType.FLASK
        assert info.confidence >= 0.5

    def test_wsgi_file(self, tmp_path: Path):
        """Flask detected via wsgi.py marker file + pattern."""
        _write(tmp_path, "wsgi.py", "from app import app\n")
        _write(tmp_path, "app.py", "from flask import Flask\napp = Flask(__name__)\n")
        info = FrameworkDetector(tmp_path).detect()
        assert info.framework == FrameworkType.FLASK


# ═══════════════════════════════════════════════════════════════════
# Django
# ═══════════════════════════════════════════════════════════════════


class TestDjango:

    def test_manage_py_and_settings(self, tmp_path: Path):
        """Django detected via manage.py + settings patterns."""
        _write(tmp_path, "manage.py", "#!/usr/bin/env python\nimport django\n")
        _write(tmp_path, "mysite/settings.py", """\
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
]
""")
        _write(tmp_path, "mysite/urls.py", """\
from django.urls import path
urlpatterns = [
    path('admin/', admin.site.urls),
]
""")
        info = FrameworkDetector(tmp_path).detect()
        assert info.framework == FrameworkType.DJANGO
        assert info.confidence >= 0.5

    def test_pyproject_dependency(self, tmp_path: Path):
        """Django detected via pyproject.toml dependency."""
        _write(tmp_path, "pyproject.toml", """\
[project]
name = "mysite"
dependencies = ["django>=4.2"]
""")
        _write(tmp_path, "manage.py", "import django\n")
        _write(tmp_path, "app/views.py", "from django.views import View\n")
        info = FrameworkDetector(tmp_path).detect()
        assert info.framework == FrameworkType.DJANGO


# ═══════════════════════════════════════════════════════════════════
# Fastify (TS/JS)
# ═══════════════════════════════════════════════════════════════════


class TestFastify:

    def test_package_json_dependency(self, tmp_path: Path):
        """Fastify detected via package.json dependency."""
        _write(tmp_path, "package.json", '{"dependencies": {"fastify": "^4.0.0"}}')
        _write(tmp_path, "src/app.ts", """\
import Fastify from 'fastify';
const fastify = Fastify();
fastify.get('/health', async () => ({ status: 'ok' }));
""")
        info = FrameworkDetector(tmp_path).detect()
        assert info.framework == FrameworkType.FASTIFY
        assert info.confidence >= 0.5

    def test_code_pattern(self, tmp_path: Path):
        """Fastify detected from code patterns."""
        _write(tmp_path, "package.json", '{"dependencies": {"fastify": "^4.0.0"}}')
        _write(tmp_path, "src/routes.ts", """\
import Fastify from 'fastify';
fastify.get('/users', getUsers);
fastify.post('/users', createUser);
""")
        info = FrameworkDetector(tmp_path).detect()
        assert info.framework == FrameworkType.FASTIFY


# ═══════════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════════


class TestEdgeCases:

    def test_no_framework(self, tmp_path: Path):
        """Pure Python library with no web framework → UNKNOWN."""
        _write(tmp_path, "pyproject.toml", """\
[project]
name = "mylib"
dependencies = ["requests", "pydantic"]
""")
        _write(tmp_path, "mylib.py", "import requests\n")
        info = FrameworkDetector(tmp_path).detect()
        assert info.framework == FrameworkType.UNKNOWN

    def test_python_only_no_package_json(self, tmp_path: Path):
        """Python-only repo with no package.json still detects framework."""
        _write(tmp_path, "requirements.txt", "fastapi\nuvicorn\n")
        _write(tmp_path, "main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
        info = FrameworkDetector(tmp_path).detect()
        assert info.framework == FrameworkType.FASTAPI

    def test_optional_deps_detected(self, tmp_path: Path):
        """Dependencies in [project.optional-dependencies] are also checked."""
        _write(tmp_path, "pyproject.toml", """\
[project]
name = "myapi"
dependencies = ["pydantic"]

[project.optional-dependencies]
web = ["fastapi", "uvicorn"]
""")
        _write(tmp_path, "main.py", "from fastapi import FastAPI\n")
        info = FrameworkDetector(tmp_path).detect()
        assert info.framework == FrameworkType.FASTAPI

    def test_mixed_fastapi_sqlalchemy(self, tmp_path: Path):
        """FastAPI + SQLAlchemy — FastAPI should win (higher score from route patterns)."""
        _write(tmp_path, "requirements.txt", "fastapi\nsqlalchemy\nuvicorn\n")
        _write(tmp_path, "main.py", """\
from fastapi import FastAPI
from sqlalchemy import create_engine
app = FastAPI()

@app.get("/items")
def get_items():
    return []
""")
        info = FrameworkDetector(tmp_path).detect()
        assert info.framework == FrameworkType.FASTAPI
