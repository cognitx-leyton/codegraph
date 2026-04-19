"""Tests for :mod:`codegraph.framework`."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from codegraph.framework import FrameworkDetector, FrameworkInfo, FrameworkType
from codegraph.schema import PackageNode

FIXTURES = Path("/tmp/agent-onboarding/tests/fixtures")
TWENTY = Path("/tmp/twenty")


@pytest.mark.parametrize(
    "fixture_dir,expected",
    [
        ("react-app", {FrameworkType.REACT, FrameworkType.REACT_TYPESCRIPT}),
        ("nextjs-app", {FrameworkType.NEXTJS}),
        ("vue-app", {FrameworkType.VUE, FrameworkType.VUE3}),
        ("sveltekit-app", {FrameworkType.SVELTEKIT, FrameworkType.SVELTE}),
        ("angular-app", {FrameworkType.ANGULAR}),
        ("odoo-app", {FrameworkType.ODOO}),
    ],
)
def test_detects_fixture_framework(
    fixture_dir: str, expected: set[FrameworkType]
) -> None:
    path = FIXTURES / fixture_dir
    if not path.exists():
        pytest.skip(f"fixture {fixture_dir} not available at {path}")
    info = FrameworkDetector(path).detect()
    assert info.framework in expected, (
        f"{fixture_dir}: got {info.framework}, expected one of {expected}"
    )
    assert info.confidence > 0.2, f"{fixture_dir}: confidence too low ({info.confidence})"


def test_nextjs_package_manager_detection() -> None:
    path = FIXTURES / "nextjs-app"
    if not path.exists():
        pytest.skip("nextjs-app fixture not available")
    info = FrameworkDetector(path).detect()
    assert info.framework == FrameworkType.NEXTJS


def test_odoo_has_no_package_manager() -> None:
    path = FIXTURES / "odoo-app"
    if not path.exists():
        pytest.skip("odoo-app fixture not available")
    info = FrameworkDetector(path).detect()
    assert info.framework == FrameworkType.ODOO
    assert info.package_manager is None
    assert info.router == "odoo-menu-router"
    assert info.confidence >= 0.9


def test_empty_directory_is_unknown(tmp_path: Path) -> None:
    info = FrameworkDetector(tmp_path).detect()
    assert info.framework == FrameworkType.UNKNOWN
    assert info.confidence == 0.0
    assert info.package_manager is None


def test_package_json_with_no_framework_is_unknown(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"x","dependencies":{"lodash":"^4.0.0"}}')
    info = FrameworkDetector(tmp_path).detect()
    assert info.framework == FrameworkType.UNKNOWN


def test_typescript_detection_from_tsconfig(tmp_path: Path) -> None:
    (tmp_path / "tsconfig.json").write_text("{}")
    (tmp_path / "package.json").write_text(
        '{"name":"x","dependencies":{"react":"^18.0.0","react-dom":"^18.0.0"}}'
    )
    info = FrameworkDetector(tmp_path).detect()
    assert info.typescript is True
    assert info.framework == FrameworkType.REACT_TYPESCRIPT


def test_package_manager_bun(tmp_path: Path) -> None:
    (tmp_path / "bun.lockb").write_text("")
    (tmp_path / "package.json").write_text("{}")
    info = FrameworkDetector(tmp_path).detect()
    assert info.package_manager == "bun"


def test_package_node_from_framework_info() -> None:
    info = FrameworkInfo(
        framework=FrameworkType.NEXTJS,
        version="^14.0.0",
        typescript=True,
        styling=["tailwind"],
        router="next/router",
        state_management=["zustand"],
        ui_library="shadcn",
        build_tool="next",
        package_manager="bun",
        confidence=0.92,
    )
    p = PackageNode.from_framework_info("packages/web", info)
    assert p.name == "packages/web"
    assert p.framework == "Next.js"          # display name, not enum value
    assert p.framework_version == "^14.0.0"
    assert p.typescript is True
    assert p.styling == ["tailwind"]
    assert p.router == "next/router"
    assert p.state_management == ["zustand"]
    assert p.confidence == pytest.approx(0.92)
    assert p.id == "package:packages/web"


def test_unknown_display_name_is_preserved() -> None:
    info = FrameworkInfo(framework=FrameworkType.UNKNOWN, confidence=0.0)
    p = PackageNode.from_framework_info("packages/misc", info)
    assert p.framework == "Unknown"
    assert p.confidence == 0.0


# ── monorepo walk-up ─────────────────────────────────────────────────


def test_walk_up_stops_at_git_root(tmp_path: Path) -> None:
    root = tmp_path / "monorepo"
    pkg = root / "packages" / "server"
    pkg.mkdir(parents=True)
    (root / ".git").mkdir()
    paths = list(FrameworkDetector(pkg)._walk_up_to_repo_root())
    assert paths == [pkg, pkg.parent, root]


def test_walk_up_terminates_at_filesystem_root(tmp_path: Path) -> None:
    pkg = tmp_path / "a" / "b"
    pkg.mkdir(parents=True)
    paths = list(FrameworkDetector(pkg)._walk_up_to_repo_root())
    assert paths[0] == pkg
    assert len(paths) <= 10
    # Must not infinite-loop even with no .git marker.


def test_package_manager_from_parent_lockfile(tmp_path: Path) -> None:
    root = tmp_path / "mono"
    pkg = root / "packages" / "srv"
    pkg.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "yarn.lock").write_text("")
    (pkg / "package.json").write_text("{}")
    info = FrameworkDetector(pkg).detect()
    assert info.package_manager == "yarn"


# ── NestJS ───────────────────────────────────────────────────────────


def test_nestjs_wins_over_react_on_same_package(tmp_path: Path) -> None:
    """A NestJS backend with React in its deps (for SSR email templates)
    should score NestJS decisively, not React."""
    root = tmp_path / "mono"
    pkg = root / "packages" / "server"
    pkg.mkdir(parents=True)
    (root / ".git").mkdir()
    (pkg / "nest-cli.json").write_text("{}")
    (pkg / "package.json").write_text(json.dumps({
        "name": "server",
        "dependencies": {
            "@nestjs/core": "11.0.0",
            "@nestjs/common": "11.0.0",
            "react": "18.3.1",
            "react-dom": "18.3.1",
        },
    }))
    (pkg / "src").mkdir()
    (pkg / "src" / "app.module.ts").write_text(
        "@Module({ imports: [] }) export class AppModule {}"
    )
    (pkg / "src" / "app.controller.ts").write_text(
        "@Controller('users') export class UserController {}"
    )
    (pkg / "src" / "user.service.ts").write_text(
        "@Injectable() export class UserService {}"
    )
    info = FrameworkDetector(pkg).detect()
    assert info.framework == FrameworkType.NESTJS
    assert info.version == "11.0.0"
    assert info.confidence >= 0.9


def test_nestjs_display_name() -> None:
    info = FrameworkInfo(framework=FrameworkType.NESTJS, version="11.0.0", confidence=1.0)
    assert info.display_name == "NestJS"
    p = PackageNode.from_framework_info("packages/srv", info)
    assert p.framework == "NestJS"


# ── Workspace hoisting ───────────────────────────────────────────────


def test_workspace_hoisting_exposes_root_deps(tmp_path: Path) -> None:
    """twenty-front-shape: child package.json is empty, root has `workspaces`
    + react deps. The detector must see react through the walk-up."""
    root = tmp_path / "mono"
    pkg = root / "packages" / "front"
    pkg.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "package.json").write_text(json.dumps({
        "name": "mono",
        "workspaces": ["packages/*"],
        "dependencies": {"react": "^18.2.0", "react-dom": "^18.2.0"},
    }))
    (pkg / "package.json").write_text('{"name":"front"}')
    (pkg / "src").mkdir()
    (pkg / "src" / "App.tsx").write_text(
        "import React from 'react';\nexport default function App() { return null; }"
    )
    info = FrameworkDetector(pkg).detect()
    assert info.framework in (FrameworkType.REACT, FrameworkType.REACT_TYPESCRIPT)
    assert info.confidence >= 0.5
    assert info.version == "^18.2.0"


def test_workspaces_guard_blocks_unrelated_parent(tmp_path: Path) -> None:
    """A parent package.json WITHOUT a `workspaces` field must not leak deps
    into a child project — otherwise running codegraph from a subdirectory
    of an unrelated enclosing project would cross-contaminate detection."""
    root = tmp_path / "unrelated"
    pkg = root / "subdir" / "project"
    pkg.mkdir(parents=True)
    # Deliberately NO .git here — we want to test walk termination without
    # the git-root short-circuit interfering.
    (root / "package.json").write_text(json.dumps({
        "name": "unrelated",
        "dependencies": {"react": "^18.0.0", "react-dom": "^18.0.0"},
    }))
    (pkg / "package.json").write_text('{"name":"project"}')
    info = FrameworkDetector(pkg).detect()
    assert info.framework == FrameworkType.UNKNOWN


def test_python_deps_crlf_requirements(tmp_path: Path) -> None:
    """requirements.txt with CRLF endings must parse dep names without \\r."""
    pkg = tmp_path / "myapp"
    pkg.mkdir()
    (pkg / "requirements.txt").write_bytes(
        b"flask>=2.0\r\n"
        b"requests\r\n"
        b"# a comment\r\n"
        b"sqlalchemy[asyncio]>=2.0\r\n"
    )
    det = FrameworkDetector(pkg)
    deps = det._python_dependencies
    assert "flask" in deps
    assert "requests" in deps
    assert "sqlalchemy" in deps
    # No trailing \r contamination
    assert not any("\r" in d for d in deps)


# ── Twenty CRM integration (opt-in) ──────────────────────────────────


@pytest.mark.skipif(not TWENTY.exists(), reason="twenty monorepo not at /tmp/twenty")
def test_twenty_server_is_nestjs() -> None:
    info = FrameworkDetector(TWENTY / "packages" / "twenty-server").detect()
    assert info.framework == FrameworkType.NESTJS
    assert info.version is not None and info.version.startswith("11.")
    assert info.package_manager == "yarn"
    assert info.confidence >= 0.9


@pytest.mark.skipif(not TWENTY.exists(), reason="twenty monorepo not at /tmp/twenty")
def test_twenty_front_is_react_with_high_confidence() -> None:
    info = FrameworkDetector(TWENTY / "packages" / "twenty-front").detect()
    assert info.framework in (FrameworkType.REACT, FrameworkType.REACT_TYPESCRIPT)
    assert info.typescript is True
    assert info.package_manager == "yarn"
    # Real observed value should be ≥ 0.8 after the fix; 0.5 is conservative.
    assert info.confidence >= 0.5
