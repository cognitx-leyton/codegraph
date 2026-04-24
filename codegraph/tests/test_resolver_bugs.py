"""Tests for resolver bug fixes.

Bug 1: NodeNext-style imports (``import './foo.js'`` when source is ``foo.ts``)
were treated as external because the resolver tried ``foo.js.ts`` not ``foo.ts``.

Bug 2: ``@/*`` path aliases in multi-package repos resolved to the wrong
package because alias lookup iterated all packages without scoping to the
importer's own package first.

Bug 3 (issue #15): Monorepo workspace imports (``import { X } from 'twenty-ui/display'``)
fell through to IMPORTS_EXTERNAL because the resolver had no mechanism to map
bare package names to filesystem paths.

Bug 4 (issue #15): ``_read_ts_paths()`` did not follow ``"extends"`` chains in
tsconfig.json, missing path aliases defined in parent configs.
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
        assert hit.path == "src/foo.ts"

    def test_relative_jsx_to_tsx(self, tmp_path: Path):
        """``import './Bar.jsx'`` resolves to ``Bar.tsx``."""
        pkg = tmp_path / "src"
        _write(pkg, "index.ts")
        _write(pkg, "Bar.tsx")
        _write(pkg, "tsconfig.json", '{}')
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("src/index.ts", "./Bar.jsx")
        assert hit.path == "src/Bar.tsx"

    def test_relative_mjs_to_mts(self, tmp_path: Path):
        """``import './util.mjs'`` resolves to ``util.mts``."""
        pkg = tmp_path / "src"
        _write(pkg, "app.ts")
        _write(pkg, "util.mts")
        _write(pkg, "tsconfig.json", '{}')
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("src/app.ts", "./util.mjs")
        assert hit.path == "src/util.mts"

    def test_real_js_file_wins(self, tmp_path: Path):
        """If ``foo.js`` actually exists (no .ts counterpart), resolve to it."""
        pkg = tmp_path / "src"
        _write(pkg, "app.ts")
        _write(pkg, "legacy.js")  # real JS file, no .ts counterpart
        _write(pkg, "tsconfig.json", '{}')
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("src/app.ts", "./legacy.js")
        assert hit.path == "src/legacy.js"

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
        assert hit.path == "myapp/src/utils/foo.ts"

    def test_subdirectory_relative_js(self, tmp_path: Path):
        """``import '../routes/health.js'`` from a nested dir resolves correctly."""
        pkg = tmp_path / "src"
        _write(pkg, "controllers/user.ts")
        _write(pkg, "routes/health.ts")
        _write(pkg, "tsconfig.json", '{}')
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("src/controllers/user.ts", "../routes/health.js")
        assert hit.path == "src/routes/health.ts"


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
        assert hit.path == "front/src/utils/helper.ts"

    def test_back_resolves_to_own_package(self, tmp_path: Path):
        """Back-end ``@/utils/helper`` should resolve within ``back/src/``."""
        front, back = self._setup_multi_pkg(tmp_path)
        r = _make_resolver(tmp_path, [front, back])
        hit = r.resolve("back/src/index.ts", "@/utils/helper")
        assert hit.path == "back/src/utils/helper.ts"

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
        assert hit.path == "back/src/utils/special.ts"

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
        assert hit.path == "app/src/utils/helper.ts"

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
        assert fe_hit.path == "apps/frontend/src/utils/helper.ts"
        # Backend file should resolve to backend's helper
        be_hit = r.resolve("apps/backend/src/index.ts", "@/helper")
        assert be_hit.path == "apps/backend/src/utils/helper.ts"


# ═══════════════════════════════════════════════════════════════════
# Bug 3: workspace (monorepo) package resolution (issue #15)
# ═══════════════════════════════════════════════════════════════════


class TestWorkspaceResolution:
    """Verify that bare workspace package imports resolve via package.json names."""

    def test_workspace_subpath_resolves(self, tmp_path: Path):
        """``import { X } from 'twenty-ui/display'`` resolves under the package's src/."""
        front = tmp_path / "front"
        ui = tmp_path / "twenty-ui"
        _write(front, "src/App.tsx")
        _write(front, "tsconfig.json", '{}')
        _write(front, "package.json", '{"name": "twenty-front"}')
        _write(ui, "src/display/index.ts")
        _write(ui, "tsconfig.json", '{}')
        _write(ui, "package.json", '{"name": "twenty-ui"}')
        r = _make_resolver(tmp_path, [front, ui])
        hit = r.resolve("front/src/App.tsx", "twenty-ui/display")
        assert hit.path == "twenty-ui/src/display/index.ts"

    def test_workspace_bare_import_resolves(self, tmp_path: Path):
        """``import X from 'twenty-ui'`` resolves to the package's src/index.ts."""
        front = tmp_path / "front"
        ui = tmp_path / "twenty-ui"
        _write(front, "src/App.tsx")
        _write(front, "tsconfig.json", '{}')
        _write(front, "package.json", '{"name": "twenty-front"}')
        _write(ui, "src/index.ts")
        _write(ui, "tsconfig.json", '{}')
        _write(ui, "package.json", '{"name": "twenty-ui"}')
        r = _make_resolver(tmp_path, [front, ui])
        hit = r.resolve("front/src/App.tsx", "twenty-ui")
        assert hit.path == "twenty-ui/src/index.ts"

    def test_workspace_nested_subpath(self, tmp_path: Path):
        """``import { Y } from 'twenty-shared/utils'`` resolves deeper sub-paths."""
        front = tmp_path / "front"
        shared = tmp_path / "twenty-shared"
        _write(front, "src/App.tsx")
        _write(front, "tsconfig.json", '{}')
        _write(front, "package.json", '{"name": "twenty-front"}')
        _write(shared, "src/utils/index.ts")
        _write(shared, "tsconfig.json", '{}')
        _write(shared, "package.json", '{"name": "twenty-shared"}')
        r = _make_resolver(tmp_path, [front, shared])
        hit = r.resolve("front/src/App.tsx", "twenty-shared/utils")
        assert hit.path == "twenty-shared/src/utils/index.ts"

    def test_workspace_no_src_dir_fallback(self, tmp_path: Path):
        """When no ``src/`` directory exists, resolve under the package root."""
        front = tmp_path / "front"
        lib = tmp_path / "mylib"
        _write(front, "src/App.tsx")
        _write(front, "tsconfig.json", '{}')
        _write(front, "package.json", '{"name": "front"}')
        # mylib has no src/ — files live at the root
        _write(lib, "utils/index.ts")
        _write(lib, "tsconfig.json", '{}')
        _write(lib, "package.json", '{"name": "mylib"}')
        r = _make_resolver(tmp_path, [front, lib])
        hit = r.resolve("front/src/App.tsx", "mylib/utils")
        assert hit.path == "mylib/utils/index.ts"

    def test_workspace_unknown_package_returns_none(self, tmp_path: Path):
        """Unknown package names fall through to None (external)."""
        front = tmp_path / "front"
        _write(front, "src/App.tsx")
        _write(front, "tsconfig.json", '{}')
        _write(front, "package.json", '{"name": "front"}')
        r = _make_resolver(tmp_path, [front])
        hit = r.resolve("front/src/App.tsx", "unknown-pkg/foo")
        assert hit is None

    def test_workspace_coexists_with_aliases(self, tmp_path: Path):
        """Aliases still resolve first; workspace is a fallback."""
        front = tmp_path / "front"
        ui = tmp_path / "twenty-ui"
        _write(front, "src/App.tsx")
        _write(front, "src/modules/display/index.ts")
        _write(front, "tsconfig.json", '''{
            "compilerOptions": { "paths": { "@/*": ["./src/modules/*"] } }
        }''')
        _write(front, "package.json", '{"name": "twenty-front"}')
        _write(ui, "src/display/index.ts")
        _write(ui, "tsconfig.json", '{}')
        _write(ui, "package.json", '{"name": "twenty-ui"}')
        r = _make_resolver(tmp_path, [front, ui])
        # @/display resolves via alias, NOT workspace
        alias_hit = r.resolve("front/src/App.tsx", "@/display")
        assert alias_hit.path == "front/src/modules/display/index.ts"
        # twenty-ui/display resolves via workspace
        ws_hit = r.resolve("front/src/App.tsx", "twenty-ui/display")
        assert ws_hit.path == "twenty-ui/src/display/index.ts"

    def test_workspace_with_js_remap(self, tmp_path: Path):
        """JS→TS remap works inside workspace sub-paths."""
        front = tmp_path / "front"
        ui = tmp_path / "twenty-ui"
        _write(front, "src/App.tsx")
        _write(front, "tsconfig.json", '{}')
        _write(front, "package.json", '{"name": "front"}')
        _write(ui, "src/display/Icon.ts")
        _write(ui, "tsconfig.json", '{}')
        _write(ui, "package.json", '{"name": "twenty-ui"}')
        r = _make_resolver(tmp_path, [front, ui])
        hit = r.resolve("front/src/App.tsx", "twenty-ui/display/Icon.js")
        assert hit.path == "twenty-ui/src/display/Icon.ts"

    def test_workspace_scoped_package(self, tmp_path: Path):
        """``@scope/name/sub`` resolves correctly for scoped npm names."""
        front = tmp_path / "front"
        shared = tmp_path / "shared"
        _write(front, "src/App.tsx")
        _write(front, "tsconfig.json", '{}')
        _write(front, "package.json", '{"name": "front"}')
        _write(shared, "src/utils/index.ts")
        _write(shared, "tsconfig.json", '{}')
        _write(shared, "package.json", '{"name": "@twenty/shared"}')
        r = _make_resolver(tmp_path, [front, shared])
        hit = r.resolve("front/src/App.tsx", "@twenty/shared/utils")
        assert hit.path == "shared/src/utils/index.ts"

    def test_workspace_scoped_bare_import(self, tmp_path: Path):
        """``@scope/name`` without sub-path resolves to the package root."""
        front = tmp_path / "front"
        shared = tmp_path / "shared"
        _write(front, "src/App.tsx")
        _write(front, "tsconfig.json", '{}')
        _write(front, "package.json", '{"name": "front"}')
        _write(shared, "src/index.ts")
        _write(shared, "tsconfig.json", '{}')
        _write(shared, "package.json", '{"name": "@twenty/shared"}')
        r = _make_resolver(tmp_path, [front, shared])
        hit = r.resolve("front/src/App.tsx", "@twenty/shared")
        assert hit.path == "shared/src/index.ts"


# ═══════════════════════════════════════════════════════════════════
# Bug 4: tsconfig "extends" chain (issue #15)
# ═══════════════════════════════════════════════════════════════════


class TestTsconfigExtends:
    """Verify that ``_read_ts_paths()`` follows tsconfig ``extends`` chains."""

    def test_extends_inherits_parent_paths(self, tmp_path: Path):
        """Child extends parent; parent has paths; child has none → parent paths resolve."""
        pkg = tmp_path / "app"
        _write(pkg, "tsconfig.base.json", '''{
            "compilerOptions": { "paths": { "@shared/*": ["./shared/*"] } }
        }''')
        _write(pkg, "tsconfig.json", '{ "extends": "./tsconfig.base.json" }')
        _write(pkg, "src/index.ts")
        _write(pkg, "shared/utils.ts")
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("app/src/index.ts", "@shared/utils")
        assert hit.path == "app/shared/utils.ts"

    def test_extends_child_overrides_parent(self, tmp_path: Path):
        """Both parent and child define ``@/*``; child wins."""
        pkg = tmp_path / "app"
        _write(pkg, "tsconfig.base.json", '''{
            "compilerOptions": { "paths": { "@/*": ["./parent-src/*"] } }
        }''')
        _write(pkg, "tsconfig.json", '''{
            "extends": "./tsconfig.base.json",
            "compilerOptions": { "paths": { "@/*": ["./child-src/*"] } }
        }''')
        _write(pkg, "src/index.ts")
        _write(pkg, "child-src/utils.ts")
        _write(pkg, "parent-src/utils.ts")
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("app/src/index.ts", "@/utils")
        assert hit.path == "app/child-src/utils.ts"

    def test_extends_chain_three_levels(self, tmp_path: Path):
        """Grandparent → parent → child; paths merge correctly."""
        pkg = tmp_path / "app"
        _write(pkg, "tsconfig.grandparent.json", '''{
            "compilerOptions": { "paths": { "@gp/*": ["./gp/*"] } }
        }''')
        _write(pkg, "tsconfig.parent.json", '''{
            "extends": "./tsconfig.grandparent.json",
            "compilerOptions": { "paths": { "@parent/*": ["./parent/*"] } }
        }''')
        _write(pkg, "tsconfig.json", '''{
            "extends": "./tsconfig.parent.json",
            "compilerOptions": { "paths": { "@child/*": ["./child/*"] } }
        }''')
        _write(pkg, "src/index.ts")
        _write(pkg, "gp/a.ts")
        _write(pkg, "parent/b.ts")
        _write(pkg, "child/c.ts")
        r = _make_resolver(tmp_path, [pkg])
        assert r.resolve("app/src/index.ts", "@gp/a").path == "app/gp/a.ts"
        assert r.resolve("app/src/index.ts", "@parent/b").path == "app/parent/b.ts"
        assert r.resolve("app/src/index.ts", "@child/c").path == "app/child/c.ts"

    def test_extends_missing_parent_graceful(self, tmp_path: Path):
        """Child extends nonexistent file → no crash, child paths still work."""
        pkg = tmp_path / "app"
        _write(pkg, "tsconfig.json", '''{
            "extends": "./nonexistent.json",
            "compilerOptions": { "paths": { "@/*": ["./src/*"] } }
        }''')
        _write(pkg, "src/index.ts")
        _write(pkg, "src/utils.ts")
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("app/src/index.ts", "@/utils")
        assert hit.path == "app/src/utils.ts"

    def test_extends_circular_reference_safe(self, tmp_path: Path):
        """A extends B extends A → no infinite loop."""
        pkg = tmp_path / "app"
        _write(pkg, "tsconfig.json", '''{
            "extends": "./tsconfig.other.json",
            "compilerOptions": { "paths": { "@a/*": ["./a/*"] } }
        }''')
        _write(pkg, "tsconfig.other.json", '''{
            "extends": "./tsconfig.json",
            "compilerOptions": { "paths": { "@b/*": ["./b/*"] } }
        }''')
        _write(pkg, "src/index.ts")
        _write(pkg, "a/x.ts")
        _write(pkg, "b/y.ts")
        r = _make_resolver(tmp_path, [pkg])
        # Both aliases should work despite the circular extends
        assert r.resolve("app/src/index.ts", "@a/x").path == "app/a/x.ts"
        assert r.resolve("app/src/index.ts", "@b/y").path == "app/b/y.ts"

    def test_extends_array(self, tmp_path: Path):
        """TypeScript 5.0+ supports ``"extends": [...]`` — all parents merge."""
        pkg = tmp_path / "app"
        _write(pkg, "tsconfig.base.json", '''{
            "compilerOptions": { "paths": { "@base/*": ["./base/*"] } }
        }''')
        _write(pkg, "tsconfig.paths.json", '''{
            "compilerOptions": { "paths": { "@extra/*": ["./extra/*"] } }
        }''')
        _write(pkg, "tsconfig.json", '''{
            "extends": ["./tsconfig.base.json", "./tsconfig.paths.json"],
            "compilerOptions": { "paths": { "@child/*": ["./child/*"] } }
        }''')
        _write(pkg, "src/index.ts")
        _write(pkg, "base/a.ts")
        _write(pkg, "extra/b.ts")
        _write(pkg, "child/c.ts")
        r = _make_resolver(tmp_path, [pkg])
        assert r.resolve("app/src/index.ts", "@base/a").path == "app/base/a.ts"
        assert r.resolve("app/src/index.ts", "@extra/b").path == "app/extra/b.ts"
        assert r.resolve("app/src/index.ts", "@child/c").path == "app/child/c.ts"


# ═══════════════════════════════════════════════════════════════════
# Bug 5: npm-hosted tsconfig presets (issue #104)
# ═══════════════════════════════════════════════════════════════════


class TestNpmTsconfigPresets:
    """Verify that npm-hosted tsconfig presets resolve from node_modules."""

    def test_scoped_npm_preset(self, tmp_path: Path):
        """``"extends": "@tsconfig/node20"`` resolves from node_modules."""
        pkg = tmp_path / "app"
        nm = pkg / "node_modules" / "@tsconfig" / "node20"
        nm.mkdir(parents=True)
        _write(nm, "tsconfig.json", '''{
            "compilerOptions": { "paths": { "@lib/*": ["./lib/*"] } }
        }''')
        _write(pkg, "tsconfig.json", '{ "extends": "@tsconfig/node20" }')
        _write(pkg, "src/index.ts")
        _write(pkg, "lib/utils.ts")
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("app/src/index.ts", "@lib/utils")
        assert hit.path == "app/lib/utils.ts"

    def test_unscoped_npm_preset(self, tmp_path: Path):
        """``"extends": "tsconfig-preset"`` resolves from node_modules."""
        pkg = tmp_path / "app"
        nm = pkg / "node_modules" / "tsconfig-preset"
        nm.mkdir(parents=True)
        _write(nm, "tsconfig.json", '''{
            "compilerOptions": { "paths": { "@preset/*": ["./preset/*"] } }
        }''')
        _write(pkg, "tsconfig.json", '{ "extends": "tsconfig-preset" }')
        _write(pkg, "src/index.ts")
        _write(pkg, "preset/foo.ts")
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("app/src/index.ts", "@preset/foo")
        assert hit.path == "app/preset/foo.ts"

    def test_missing_preset_graceful(self, tmp_path: Path):
        """Missing npm preset → no crash, child paths still work."""
        pkg = tmp_path / "app"
        _write(pkg, "tsconfig.json", '''{
            "extends": "@tsconfig/nonexistent",
            "compilerOptions": { "paths": { "@/*": ["./src/*"] } }
        }''')
        _write(pkg, "src/index.ts")
        _write(pkg, "src/utils.ts")
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("app/src/index.ts", "@/utils")
        assert hit.path == "app/src/utils.ts"

    def test_npm_preset_child_overrides(self, tmp_path: Path):
        """Child paths override npm preset paths for the same alias key."""
        pkg = tmp_path / "app"
        nm = pkg / "node_modules" / "@tsconfig" / "base"
        nm.mkdir(parents=True)
        _write(nm, "tsconfig.json", '''{
            "compilerOptions": { "paths": { "@/*": ["./from-preset/*"] } }
        }''')
        _write(pkg, "tsconfig.json", '''{
            "extends": "@tsconfig/base",
            "compilerOptions": { "paths": { "@/*": ["./from-child/*"] } }
        }''')
        _write(pkg, "src/index.ts")
        _write(pkg, "from-child/utils.ts")
        _write(pkg, "from-preset/utils.ts")
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("app/src/index.ts", "@/utils")
        assert hit.path == "app/from-child/utils.ts"

    def test_npm_preset_nested_node_modules(self, tmp_path: Path):
        """node_modules in a parent directory is found by walking up."""
        pkg = tmp_path / "app"
        # node_modules at tmp_path level, not inside pkg
        nm = tmp_path / "node_modules" / "@tsconfig" / "node20"
        nm.mkdir(parents=True)
        _write(nm, "tsconfig.json", '''{
            "compilerOptions": { "paths": { "@upper/*": ["./upper/*"] } }
        }''')
        _write(pkg, "tsconfig.json", '{ "extends": "@tsconfig/node20" }')
        _write(pkg, "src/index.ts")
        _write(pkg, "upper/a.ts")
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("app/src/index.ts", "@upper/a")
        assert hit.path == "app/upper/a.ts"

    def test_npm_preset_chained_extends(self, tmp_path: Path):
        """npm preset itself uses relative extends → both levels merge."""
        pkg = tmp_path / "app"
        nm = pkg / "node_modules" / "@tsconfig" / "node20"
        nm.mkdir(parents=True)
        _write(nm, "strict.json", '''{
            "compilerOptions": { "paths": { "@strict/*": ["./strict/*"] } }
        }''')
        _write(nm, "tsconfig.json", '''{
            "extends": "./strict.json",
            "compilerOptions": { "paths": { "@base/*": ["./base/*"] } }
        }''')
        _write(pkg, "tsconfig.json", '{ "extends": "@tsconfig/node20" }')
        _write(pkg, "src/index.ts")
        _write(pkg, "strict/a.ts")
        _write(pkg, "base/b.ts")
        r = _make_resolver(tmp_path, [pkg])
        assert r.resolve("app/src/index.ts", "@strict/a").path == "app/strict/a.ts"
        assert r.resolve("app/src/index.ts", "@base/b").path == "app/base/b.ts"

    def test_relative_extends_unchanged(self, tmp_path: Path):
        """Regression guard: relative extends still works after the npm branch."""
        pkg = tmp_path / "app"
        _write(pkg, "tsconfig.base.json", '''{
            "compilerOptions": { "paths": { "@shared/*": ["./shared/*"] } }
        }''')
        _write(pkg, "tsconfig.json", '{ "extends": "./tsconfig.base.json" }')
        _write(pkg, "src/index.ts")
        _write(pkg, "shared/utils.ts")
        r = _make_resolver(tmp_path, [pkg])
        hit = r.resolve("app/src/index.ts", "@shared/utils")
        assert hit.path == "app/shared/utils.ts"
