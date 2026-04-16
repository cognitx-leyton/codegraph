"""Per-package framework detection.

Scans a package directory (must contain ``package.json`` for most frameworks —
Odoo is the one exception) and returns a :class:`FrameworkInfo` describing the
detected framework, version, TypeScript usage, router, state management, UI
library, build tool, and package manager.

The detector is scored: file existence adds 30 points, matching ``package.json``
dependency adds 25, a code-regex hit adds 15. Below 25 total the framework is
marked ``UNKNOWN``. The score normalised to ``[0, 1]`` is surfaced as
:attr:`FrameworkInfo.confidence`.

Ported from ``agent-onboarding/architect/analyzer/framework_detector.py``
(Apache-2.0). Stripped: ``get_source_directories`` and
``get_component_file_extensions`` — codegraph drives its own walk in
:func:`codegraph.cli._run_index` and doesn't need the detector dictating where
to look.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterator, Optional


class FrameworkType(Enum):
    REACT = "react"
    REACT_TYPESCRIPT = "react-typescript"
    NEXTJS = "nextjs"
    VUE = "vue"
    VUE3 = "vue3"
    ANGULAR = "angular"
    SVELTE = "svelte"
    SVELTEKIT = "sveltekit"
    NESTJS = "nestjs"
    ODOO = "odoo"
    UNKNOWN = "unknown"


# Human-friendly display names — used for :Package.framework in Neo4j so that
# queries like `MATCH (:Package {framework:'Next.js'})` read naturally.
FRAMEWORK_DISPLAY = {
    FrameworkType.REACT: "React",
    FrameworkType.REACT_TYPESCRIPT: "React (TypeScript)",
    FrameworkType.NEXTJS: "Next.js",
    FrameworkType.VUE: "Vue",
    FrameworkType.VUE3: "Vue 3",
    FrameworkType.ANGULAR: "Angular",
    FrameworkType.SVELTE: "Svelte",
    FrameworkType.SVELTEKIT: "SvelteKit",
    FrameworkType.NESTJS: "NestJS",
    FrameworkType.ODOO: "Odoo",
    FrameworkType.UNKNOWN: "Unknown",
}


@dataclass
class FrameworkInfo:
    framework: FrameworkType
    version: Optional[str] = None
    typescript: bool = False
    styling: list[str] = field(default_factory=list)
    router: Optional[str] = None
    state_management: list[str] = field(default_factory=list)
    ui_library: Optional[str] = None
    build_tool: Optional[str] = None
    package_manager: Optional[str] = None
    confidence: float = 0.0

    @property
    def display_name(self) -> str:
        return FRAMEWORK_DISPLAY.get(self.framework, self.framework.value)


class FrameworkDetector:
    """Scored heuristic detector over ``package.json`` + config files + code."""

    FRAMEWORK_INDICATORS = {
        FrameworkType.NESTJS: {
            "files": ["nest-cli.json"],
            "dependencies": ["@nestjs/core", "@nestjs/common"],
            "patterns": [
                r"@Module\s*\(",
                r"@Injectable\s*\(",
                r"@Controller\s*\(",
            ],
        },
        FrameworkType.NEXTJS: {
            "files": ["next.config.js", "next.config.mjs", "next.config.ts", ".next"],
            "dependencies": ["next"],
            "patterns": [r"from\s+['\"]next", r"import.*from\s+['\"]next"],
        },
        FrameworkType.REACT: {
            "files": [],
            "dependencies": ["react", "react-dom"],
            "patterns": [r"from\s+['\"]react['\"]", r"import\s+React"],
        },
        FrameworkType.VUE3: {
            "files": ["vue.config.js", "vite.config.ts", "vite.config.js"],
            "dependencies": ["vue"],
            "patterns": [r"<script\s+setup", r"defineComponent", r"from\s+['\"]vue['\"]"],
        },
        FrameworkType.ANGULAR: {
            "files": ["angular.json", ".angular"],
            "dependencies": ["@angular/core", "@angular/cli"],
            "patterns": [r"@Component", r"@Injectable", r"@NgModule"],
        },
        FrameworkType.SVELTEKIT: {
            "files": ["svelte.config.js", "svelte.config.ts"],
            "dependencies": ["@sveltejs/kit"],
            "patterns": [r"<script.*lang=['\"]ts['\"]", r"from\s+['\"]svelte['\"]"],
        },
        FrameworkType.SVELTE: {
            "files": [],
            "dependencies": ["svelte"],
            "patterns": [r"\.svelte$", r"<script>.*</script>.*<style>"],
        },
        FrameworkType.ODOO: {
            "files": ["odoo-bin", "__manifest__.py", "__openerp__.py"],
            "dependencies": [],
            "patterns": [
                r"<odoo>",
                r"ir\.actions\.act_window",
                r"_name\s*=\s*['\"]\w+\.\w+['\"]",
            ],
        },
    }

    STYLING_INDICATORS = {
        "tailwind": ["tailwind.config.js", "tailwind.config.ts", "tailwindcss"],
        "css-modules": [r"\.module\.css$", r"\.module\.scss$"],
        "styled-components": ["styled-components"],
        "emotion": ["@emotion/react", "@emotion/styled"],
        "sass": ["sass", "node-sass"],
        "less": ["less"],
        "chakra": ["@chakra-ui/react"],
        "material-ui": ["@mui/material", "@material-ui/core"],
        "ant-design": ["antd"],
        "bootstrap": ["bootstrap", "react-bootstrap"],
    }

    ROUTER_INDICATORS = {
        "react-router": ["react-router", "react-router-dom"],
        "next/router": ["next/router", "next/navigation"],
        "vue-router": ["vue-router"],
        "@angular/router": ["@angular/router"],
        "svelte-routing": ["svelte-routing", "@sveltejs/kit"],
    }

    STATE_INDICATORS = {
        "redux": ["redux", "@reduxjs/toolkit", "react-redux"],
        "zustand": ["zustand"],
        "jotai": ["jotai"],
        "recoil": ["recoil"],
        "mobx": ["mobx", "mobx-react"],
        "pinia": ["pinia"],
        "vuex": ["vuex"],
        "ngrx": ["@ngrx/store"],
    }

    UI_LIBRARY_INDICATORS = {
        "material-ui": ["@mui/material", "@material-ui/core"],
        "ant-design": ["antd"],
        "chakra-ui": ["@chakra-ui/react"],
        "mantine": ["@mantine/core"],
        "shadcn": ["@radix-ui/react"],
        "headless-ui": ["@headlessui/react"],
        "bootstrap": ["react-bootstrap", "bootstrap-vue"],
        "vuetify": ["vuetify"],
        "primevue": ["primevue"],
        "element-plus": ["element-plus"],
        "ng-zorro": ["ng-zorro-antd"],
    }

    BUILD_TOOL_INDICATORS = {
        "vite": ["vite.config.js", "vite.config.ts", "vite"],
        "webpack": ["webpack.config.js", "webpack"],
        "turbopack": ["turbopack"],
        "esbuild": ["esbuild"],
        "rollup": ["rollup.config.js", "rollup"],
        "parcel": [".parcelrc", "parcel"],
    }

    def __init__(self, project_path: Path) -> None:
        self.project_path = Path(project_path)
        self._package_json: Optional[dict] = None
        self._files_cache: Optional[list[Path]] = None
        self._workspace_deps_cache: Optional[set[str]] = None
        self._workspace_pjs_cache: Optional[list[dict]] = None

    # ── monorepo walk-up ────────────────────────────────────────────────

    def _walk_up_to_repo_root(self, max_hops: int = 10) -> Iterator[Path]:
        """Yield ``project_path`` then each parent, stopping at a git root
        or the filesystem root.

        A directory is considered the git root if it contains a ``.git``
        entry (file or directory — git worktrees use a file). The iterator
        *yields* that git-root path before terminating. ``max_hops`` caps
        the walk at 10 — no real monorepo nests that deep, and this keeps
        pathological invocations bounded.
        """
        current = self.project_path
        for _ in range(max_hops):
            yield current
            if (current / ".git").exists():
                return
            parent = current.parent
            if parent == current:
                return
            current = parent

    # ── package.json / dependency helpers ───────────────────────────────

    @property
    def package_json(self) -> Optional[dict]:
        if self._package_json is None:
            p = self.project_path / "package.json"
            if p.exists():
                try:
                    self._package_json = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    self._package_json = None
        return self._package_json

    def _workspace_package_jsons(self) -> list[dict]:
        """Parse and cache every relevant ``package.json`` walking up.

        Order: own package.json first (most specific), then ancestor
        ``package.json`` files that declare a ``workspaces`` field. Parsed
        once on first access and reused by :attr:`_workspace_dependencies`
        and :meth:`_get_dependency_version`.

        The ``workspaces`` guard prevents leakage: if codegraph is run from a
        subdirectory of an unrelated enclosing project, that parent's deps
        won't be picked up unless it's explicitly a monorepo root.
        """
        if self._workspace_pjs_cache is not None:
            return self._workspace_pjs_cache

        pjs: list[dict] = []
        if self.package_json:
            # Deep-copy the own package.json so mutation of the cached list
            # can't corrupt self._package_json. Parent package.jsons (below)
            # are freshly parsed per walk-up call and don't need this.
            pjs.append(copy.deepcopy(self.package_json))

        for path in self._walk_up_to_repo_root():
            if path == self.project_path:
                continue
            pj_path = path / "package.json"
            if not pj_path.exists():
                continue
            try:
                pj = json.loads(pj_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if "workspaces" not in pj:
                continue
            pjs.append(pj)

        self._workspace_pjs_cache = pjs
        return pjs

    @property
    def _workspace_dependencies(self) -> set[str]:
        """Merged dep names from own + workspace-root ``package.json`` files."""
        if self._workspace_deps_cache is not None:
            return self._workspace_deps_cache

        merged: set[str] = set()
        for pj in self._workspace_package_jsons():
            for key in ("dependencies", "devDependencies", "peerDependencies"):
                section = pj.get(key)
                if isinstance(section, dict):
                    merged.update(section.keys())

        self._workspace_deps_cache = merged
        return merged

    @property
    def all_dependencies(self) -> set[str]:
        return self._workspace_dependencies

    def _get_dependency_version(self, dep: str) -> Optional[str]:
        """Return the version string for ``dep`` from the first
        ``package.json`` (own → workspace-root) that declares it."""
        for pj in self._workspace_package_jsons():
            for key in ("dependencies", "devDependencies", "peerDependencies"):
                section = pj.get(key)
                if isinstance(section, dict) and dep in section:
                    return section[dep]
        return None

    def _check_file_exists(self, filename: str) -> bool:
        return (self.project_path / filename).exists()

    def _check_dependency(self, dep: str) -> bool:
        return dep in self.all_dependencies

    # ── file scanning ───────────────────────────────────────────────────

    def _get_all_files(self) -> list[Path]:
        if self._files_cache is None:
            ignore = {
                "node_modules", ".git", ".next", "dist", "build",
                ".nuxt", ".svelte-kit", ".angular", "__pycache__",
            }
            files: list[Path] = []
            for item in self.project_path.rglob("*"):
                if item.is_file() and not any(part in ignore for part in item.parts):
                    files.append(item)
            self._files_cache = files
        return self._files_cache

    def _check_pattern_in_files(self, pattern: str, extensions: tuple[str, ...]) -> bool:
        regex = re.compile(pattern)
        for file_path in self._get_all_files():
            if file_path.suffix not in extensions:
                continue
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if regex.search(content):
                return True
        return False

    # ── per-aspect detection ────────────────────────────────────────────

    def _detect_typescript(self) -> bool:
        if self._check_file_exists("tsconfig.json") or self._check_file_exists("tsconfig.base.json"):
            return True
        if self._check_dependency("typescript"):
            return True
        for file_path in self._get_all_files():
            if file_path.suffix in (".ts", ".tsx"):
                return True
        return False

    def _detect_styling(self) -> list[str]:
        detected: set[str] = set()
        for name, indicators in self.STYLING_INDICATORS.items():
            for indicator in indicators:
                if indicator.startswith(r"\."):
                    regex = re.compile(indicator)
                    if any(regex.search(str(p)) for p in self._get_all_files()):
                        detected.add(name)
                        break
                elif self._check_file_exists(indicator) or self._check_dependency(indicator):
                    detected.add(name)
                    break
        return sorted(detected)

    def _detect_router(self) -> Optional[str]:
        for name, deps in self.ROUTER_INDICATORS.items():
            if any(self._check_dependency(d) for d in deps):
                return name
        return None

    def _detect_state_management(self) -> list[str]:
        detected: list[str] = []
        for name, deps in self.STATE_INDICATORS.items():
            if any(self._check_dependency(d) for d in deps):
                detected.append(name)
        return detected

    def _detect_ui_library(self) -> Optional[str]:
        for name, deps in self.UI_LIBRARY_INDICATORS.items():
            if any(self._check_dependency(d) for d in deps):
                return name
        return None

    def _detect_build_tool(self) -> Optional[str]:
        for name, indicators in self.BUILD_TOOL_INDICATORS.items():
            for indicator in indicators:
                if self._check_file_exists(indicator) or self._check_dependency(indicator):
                    return name
        return None

    def _detect_package_manager(self) -> Optional[str]:
        """Walk up from the package root looking for a lockfile.

        Monorepos store the lockfile at the repo root, not at each package
        root — so checking only :attr:`project_path` misses it. We walk up
        until a lockfile is found or we hit the git/filesystem root.
        """
        for path in self._walk_up_to_repo_root():
            if (path / "pnpm-lock.yaml").exists():
                return "pnpm"
            if (path / "yarn.lock").exists():
                return "yarn"
            if (path / "package-lock.json").exists():
                return "npm"
            if (path / "bun.lockb").exists() or (path / "bun.lock").exists():
                return "bun"
        return None

    # ── Odoo short-circuit ──────────────────────────────────────────────

    def _has_odoo_signature(self) -> bool:
        if self._check_file_exists("__manifest__.py") or self._check_file_exists("__openerp__.py"):
            return True
        for candidate in self.project_path.rglob("__manifest__.py"):
            if "node_modules" in candidate.parts:
                continue
            return True
        count = 0
        for file_path in self._get_all_files():
            if file_path.suffix != ".xml":
                continue
            try:
                snippet = file_path.read_text(encoding="utf-8", errors="ignore")[:2000]
            except OSError:
                continue
            if "<odoo>" in snippet or "ir.actions.act_window" in snippet:
                return True
            count += 1
            if count >= 30:
                break
        return False

    # ── main entry point ────────────────────────────────────────────────

    def detect(self) -> FrameworkInfo:
        if self._has_odoo_signature():
            return FrameworkInfo(
                framework=FrameworkType.ODOO,
                version=None,
                typescript=False,
                styling=[],
                router="odoo-menu-router",
                state_management=[],
                ui_library="odoo-web",
                build_tool=None,
                package_manager=None,
                confidence=0.95,
            )

        scores: dict[FrameworkType, float] = {ft: 0.0 for ft in FrameworkType}
        code_extensions = (".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte")

        for framework, indicators in self.FRAMEWORK_INDICATORS.items():
            for file_indicator in indicators["files"]:
                if self._check_file_exists(file_indicator):
                    scores[framework] += 30.0
            for dep in indicators["dependencies"]:
                if self._check_dependency(dep):
                    scores[framework] += 25.0
            for pattern in indicators["patterns"]:
                if self._check_pattern_in_files(pattern, code_extensions):
                    scores[framework] += 15.0

        best_framework = max(scores, key=scores.get)
        best_score = scores[best_framework]

        is_typescript = self._detect_typescript()
        if best_framework == FrameworkType.REACT and is_typescript:
            best_framework = FrameworkType.REACT_TYPESCRIPT

        if best_score < 25.0:
            best_framework = FrameworkType.UNKNOWN

        version: Optional[str] = None
        if best_framework in (FrameworkType.REACT, FrameworkType.REACT_TYPESCRIPT):
            version = self._get_dependency_version("react")
        elif best_framework == FrameworkType.NEXTJS:
            version = self._get_dependency_version("next")
        elif best_framework in (FrameworkType.VUE, FrameworkType.VUE3):
            version = self._get_dependency_version("vue")
        elif best_framework == FrameworkType.ANGULAR:
            version = self._get_dependency_version("@angular/core")
        elif best_framework in (FrameworkType.SVELTE, FrameworkType.SVELTEKIT):
            version = self._get_dependency_version("svelte")
        elif best_framework == FrameworkType.NESTJS:
            version = self._get_dependency_version("@nestjs/core")

        return FrameworkInfo(
            framework=best_framework,
            version=version,
            typescript=is_typescript,
            styling=self._detect_styling(),
            router=self._detect_router(),
            state_management=self._detect_state_management(),
            ui_library=self._detect_ui_library(),
            build_tool=self._detect_build_tool(),
            package_manager=self._detect_package_manager(),
            confidence=min(best_score / 100.0, 1.0),
        )
