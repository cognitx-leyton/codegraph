"""Tests for resolver bug fixes: .js→.ts NodeNext remapping + cross-package alias scoping.

Bug 1: NodeNext-style imports (``import './foo.js'`` when source is ``foo.ts``)
were treated as external because the resolver tried ``foo.js.ts`` not ``foo.ts``.

Bug 2: ``@/*`` path aliases in multi-package repos resolved to the wrong
package because alias lookup iterated all packages without scoping to the
importer's own package first.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.resolver import (
    PathIndex,
    Resolver,
    load_package_config,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _write(root: Path, rel: str, content: str = "") -> None:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)


def _make_resolver(repo_root: Path, pkg_dirs: list[Path]) -> Resolver:
    """Build a Resolver with TS package configs + PathIndex from all files."""
    configs = [load_package_config(repo_root, d) for d in pkg_dirs]
    resolver = Resolver(repo_root, configs)
    files: set[str] = set()
    for d in pkg_dirs:
        for p in d.rglob("*"):
            if p.is_file():
                files.add(str(p.resolve().relative_to(repo_root)).replace("\\", "/"))
    resolver.set_path_index(PathIndex(files))
    return resolver


# ═══════════════════════════════════════════════════════════════════
# Bug 1: .js → .ts NodeNext remapping
# ═══════════════════════════════════════════════════════════════════


class TestJsToTsRemap:
    """Verify that NodeNext .js imports resolve to their .ts counterparts."""

    def test_relative_js_to_ts(self, tmp_path: Path):
        """``import './foo.js'`` resolves to ``foo.ts``."""
        pkg = tmp_path / "src"
        _write(pkg, "app.ts")
        _write(pkg, "foo.ts")
        # tsconfig with no aliases
        _write(pkg, "tsconfig.json", '{}')
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("src/app.ts", "./foo.js")
        assert hit == "src/foo.ts"

    def test_relative_jsx_to_tsx(self, tmp_path: Path):
        """``import './Bar.jsx'`` resolves to ``Bar.tsx``."""
        pkg = tmp_path / "src"
        _write(pkg, "index.ts")
        _write(pkg, "Bar.tsx")
        _write(pkg, "tsconfig.json", '{}')
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("src/index.ts", "./Bar.jsx")
        assert hit == "src/Bar.tsx"

    def test_relative_mjs_to_mts(self, tmp_path: Path):
        """``import './util.mjs'`` resolves to ``util.mts``."""
        pkg = tmp_path / "src"
        _write(pkg, "app.ts")
        _write(pkg, "util.mts")
        _write(pkg, "tsconfig.json", '{}')
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("src/app.ts", "./util.mjs")
        assert hit == "src/util.mts"

    def test_real_js_file_wins(self, tmp_path: Path):
        """If ``foo.js`` actually exists (no .ts counterpart), resolve to it."""
        pkg = tmp_path / "src"
        _write(pkg, "app.ts")
        _write(pkg, "legacy.js")  # real JS file, no .ts counterpart
        _write(pkg, "tsconfig.json", '{}')
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("src/app.ts", "./legacy.js")
        assert hit == "src/legacy.js"

    def test_missing_both_returns_none(self, tmp_path: Path):
        """If neither ``.js`` nor ``.ts`` exists, return ``None``."""
        pkg = tmp_path / "src"
        _write(pkg, "app.ts")
        _write(pkg, "tsconfig.json", '{}')
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("src/app.ts", "./missing.js")
        assert hit is None

    def test_aliased_js_to_ts(self, tmp_path: Path):
        """``@/utils/foo.js`` with alias ``@/* → ./src/*`` resolves to ``src/utils/foo.ts``."""
        pkg = tmp_path / "myapp"
        _write(pkg, "src/index.ts")
        _write(pkg, "src/utils/foo.ts")
        _write(pkg, "tsconfig.json", '''{
            "compilerOptions": {
                "paths": { "@/*": ["./src/*"] }
            }
        }''')
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("myapp/src/index.ts", "@/utils/foo.js")
        assert hit == "myapp/src/utils/foo.ts"

    def test_subdirectory_relative_js(self, tmp_path: Path):
        """``import '../routes/health.js'`` from a nested dir resolves correctly."""
        pkg = tmp_path / "src"
        _write(pkg, "controllers/user.ts")
        _write(pkg, "routes/health.ts")
        _write(pkg, "tsconfig.json", '{}')
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("src/controllers/user.ts", "../routes/health.js")
        assert hit == "src/routes/health.ts"


# ═══════════════════════════════════════════════════════════════════
# Bug 2: cross-package alias scoping
# ═══════════════════════════════════════════════════════════════════


class TestCrossPackageAlias:
    """Verify aliases resolve to the importer's own package first."""

    def _setup_multi_pkg(self, tmp_path: Path):
        """Two packages, both with ``@/* → ./src/*``, each with a ``utils/helper.ts``."""
        front = tmp_path / "front"
        back = tmp_path / "back"
        _write(front, "src/index.ts")
        _write(front, "src/utils/helper.ts", "// front helper")
        _write(front, "tsconfig.json", '''{
            "compilerOptions": { "paths": { "@/*": ["./src/*"] } }
        }''')
        _write(back, "src/index.ts")
        _write(back, "src/utils/helper.ts", "// back helper")
        _write(back, "tsconfig.json", '''{
            "compilerOptions": { "paths": { "@/*": ["./src/*"] } }
        }''')
        return front, back

    def test_front_resolves_to_own_package(self, tmp_path: Path):
        """Front-end ``@/utils/helper`` should resolve within ``front/src/``."""
        front, back = self._setup_multi_pkg(tmp_path)
        r = _make_resolver(tmp_path, [front, back])
        hit = r.resolve("front/src/index.ts", "@/utils/helper")
        assert hit == "front/src/utils/helper.ts"

    def test_back_resolves_to_own_package(self, tmp_path: Path):
        """Back-end ``@/utils/helper`` should resolve within ``back/src/``."""
        front, back = self._setup_multi_pkg(tmp_path)
        r = _make_resolver(tmp_path, [front, back])
        hit = r.resolve("back/src/index.ts", "@/utils/helper")
        assert hit == "back/src/utils/helper.ts"

    def test_cross_package_fallthrough(self, tmp_path: Path):
        """If file only exists in the *other* package, fallthrough still works."""
        front = tmp_path / "front"
        back = tmp_path / "back"
        _write(front, "src/index.ts")
        # front does NOT have utils/special.ts
        _write(front, "tsconfig.json", '''{
            "compilerOptions": { "paths": { "@/*": ["./src/*"] } }
        }''')
        _write(back, "src/utils/special.ts", "// only in back")
        _write(back, "tsconfig.json", '''{
            "compilerOptions": { "paths": { "@/*": ["./src/*"] } }
        }''')
        r = _make_resolver(tmp_path, [front, back])
        # front imports something only in back → still resolves via fallthrough
        hit = r.resolve("front/src/index.ts", "@/utils/special")
        assert hit == "back/src/utils/special.ts"

    def test_no_match_returns_none(self, tmp_path: Path):
        """Alias with no matching file in any package returns ``None``."""
        front, back = self._setup_multi_pkg(tmp_path)
        r = _make_resolver(tmp_path, [front, back])
        hit = r.resolve("front/src/index.ts", "@/nonexistent/module")
        assert hit is None

    def test_single_package_unchanged(self, tmp_path: Path):
        """Single-package repos continue to work exactly as before."""
        pkg = tmp_path / "app"
        _write(pkg, "src/index.ts")
        _write(pkg, "src/utils/helper.ts")
        _write(pkg, "tsconfig.json", '''{
            "compilerOptions": { "paths": { "@/*": ["./src/*"] } }
        }''')
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("app/src/index.ts", "@/utils/helper")
        assert hit == "app/src/utils/helper.ts"

    def test_same_basename_different_roots(self, tmp_path: Path):
        """Two packages both named ``src`` under different parents don't collide."""
        fe_src = tmp_path / "apps" / "frontend" / "src"
        be_src = tmp_path / "apps" / "backend" / "src"
        _write(fe_src, "index.ts")
        _write(fe_src, "utils/helper.ts", "// frontend")
        _write(fe_src, "tsconfig.json", '''{
            "compilerOptions": { "paths": { "@/*": ["./utils/*"] } }
        }''')
        _write(be_src, "index.ts")
        _write(be_src, "utils/helper.ts", "// backend")
        _write(be_src, "tsconfig.json", '''{
            "compilerOptions": { "paths": { "@/*": ["./utils/*"] } }
        }''')
        r = _make_resolver(tmp_path, [fe_src, be_src])
        # Frontend file should resolve to frontend's helper
        fe_hit = r.resolve("apps/frontend/src/index.ts", "@/helper")
        assert fe_hit == "apps/frontend/src/utils/helper.ts"
        # Backend file should resolve to backend's helper
        be_hit = r.resolve("apps/backend/src/index.ts", "@/helper")
        assert be_hit == "apps/backend/src/utils/helper.ts"
