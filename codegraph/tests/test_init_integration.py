"""End-to-end integration tests for ``codegraph init``.

Scaffolds a synthetic repo in ``tmp_path``, runs the real ``codegraph init``
subcommand via subprocess, and verifies the full artifact set is produced.
Docker-dependent paths are gated behind a skipmark so the test stays useful
in environments without Docker.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _docker_available() -> bool:
    return shutil.which("docker") is not None


@pytest.fixture
def fake_monorepo(tmp_path: Path) -> Path:
    """Build a tiny TS+Python monorepo in tmp_path and init git."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)

    (tmp_path / "apps" / "web" / "src").mkdir(parents=True)
    (tmp_path / "apps" / "web" / "package.json").write_text('{"name":"web"}')
    (tmp_path / "apps" / "web" / "src" / "app.tsx").write_text("export const x = 1;")

    (tmp_path / "apps" / "api" / "src").mkdir(parents=True)
    (tmp_path / "apps" / "api" / "pyproject.toml").write_text('[project]\nname = "api"\n')
    (tmp_path / "apps" / "api" / "src" / "main.py").write_text(
        "class Foo:\n    def bar(self):\n        return 1\n"
    )
    return tmp_path


def test_init_scaffold_only_no_docker(fake_monorepo: Path):
    """``codegraph init --yes --skip-docker --skip-index`` writes all expected files."""
    result = subprocess.run(
        [sys.executable, "-m", "codegraph.cli", "init",
         "--yes", "--skip-docker", "--skip-index"],
        cwd=fake_monorepo, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r}\nstderr={result.stderr!r}"

    # Claude commands
    claude_dir = fake_monorepo / ".claude" / "commands"
    for cmd in ("graph.md", "graph-refresh.md", "arch-check.md",
                "blast-radius.md", "dead-code.md", "who-owns.md", "trace-endpoint.md"):
        assert (claude_dir / cmd).exists(), f"missing {cmd}"

    # Workflow
    workflow = fake_monorepo / ".github" / "workflows" / "arch-check.yml"
    assert workflow.exists()
    content = workflow.read_text()
    # Template substitution produced the detected packages.
    assert "-p apps/web" in content
    assert "-p apps/api" in content

    # Policies
    policies = fake_monorepo / ".arch-policies.toml"
    assert policies.exists()
    assert "policies.import_cycles" in policies.read_text()

    # Compose file (even though we skipped starting it)
    compose = fake_monorepo / "docker-compose.yml"
    assert compose.exists()
    expected_hash = hashlib.sha1(str(fake_monorepo.resolve()).encode()).hexdigest()[:8]
    expected_name = f"cognitx-codegraph-{fake_monorepo.name}-{expected_hash}"
    assert expected_name in compose.read_text()

    # CLAUDE.md
    claude_md = fake_monorepo / "CLAUDE.md"
    assert claude_md.exists()
    assert "codegraph knowledge graph" in claude_md.read_text()


@pytest.mark.skipif(not _docker_available(), reason="docker not installed")
@pytest.mark.slow
def test_init_full_flow_with_docker(fake_monorepo: Path):
    """Full end-to-end: scaffold + Neo4j + first index. Tears down the container on exit."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "codegraph.cli", "init", "--yes"],
            cwd=fake_monorepo, capture_output=True, text=True, timeout=300,
        )
        assert result.returncode == 0, (
            f"init failed.\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        # Container should be running
        ps = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True,
        )
        expected_hash = hashlib.sha1(str(fake_monorepo.resolve()).encode()).hexdigest()[:8]
        assert f"cognitx-codegraph-{fake_monorepo.name}-{expected_hash}" in ps.stdout
    finally:
        # Always tear down, even if the assertions above fail
        subprocess.run(
            ["docker", "compose", "-f", str(fake_monorepo / "docker-compose.yml"),
             "down", "-v"],
            capture_output=True,
        )
