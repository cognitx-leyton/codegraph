"""Tests for :mod:`codegraph.init`.

All tests scaffold into a ``tmp_path`` and run ``codegraph init`` in
non-interactive mode (``--yes`` equivalent), with Docker + indexing disabled
so the tests stay fast and pure. The end-to-end Docker path is covered by
``test_init_integration.py`` (skip-marked if Docker isn't available).
"""
from __future__ import annotations

import io
import re
import subprocess
from pathlib import Path

import pytest
import tomllib
import yaml
from rich.console import Console

from codegraph import init as init_module
from codegraph.init import (
    InitConfig,
    RepoShape,
    _detect_repo_shape,
    _find_git_root,
    _prompt_config,
    _render,
    _sanitize_container_segment,
    _scaffold_files,
    _template_vars,
    _warn_orphaned_containers,
    run_init,
)


# ── Helpers ─────────────────────────────────────────────────


def _make_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)


def _silent_console() -> Console:
    return Console(quiet=True)


# ── _find_git_root ──────────────────────────────────────────


def test_find_git_root_resolves_from_subdir(tmp_path: Path):
    _make_git_repo(tmp_path)
    nested = tmp_path / "deeply" / "nested" / "dir"
    nested.mkdir(parents=True)
    assert _find_git_root(nested).resolve() == tmp_path.resolve()


def test_find_git_root_errors_outside_repo(tmp_path: Path):
    # tmp_path is NOT a git repo yet.
    import typer
    with pytest.raises(typer.BadParameter, match="Not a git repository"):
        _find_git_root(tmp_path)


# ── _detect_repo_shape ──────────────────────────────────────


def test_detect_python_only(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    (tmp_path / "app.py").write_text("print('hi')")
    shape = _detect_repo_shape(tmp_path)
    assert "py" in shape.languages
    assert "ts" not in shape.languages


def test_detect_monorepo_candidates(tmp_path: Path):
    (tmp_path / "apps" / "web").mkdir(parents=True)
    (tmp_path / "apps" / "web" / "package.json").write_text("{}")
    (tmp_path / "apps" / "api").mkdir(parents=True)
    (tmp_path / "apps" / "api" / "pyproject.toml").write_text('[project]\nname = "api"\n')
    shape = _detect_repo_shape(tmp_path)
    assert "ts" in shape.languages and "py" in shape.languages
    assert "apps/web" in shape.package_candidates
    assert "apps/api" in shape.package_candidates


def test_detect_empty_repo(tmp_path: Path):
    shape = _detect_repo_shape(tmp_path)
    assert shape.languages == []
    assert shape.package_candidates == []


# ── _sanitize_container_segment ────────────────────────────


def test_sanitize_replaces_spaces_and_special_chars():
    assert _sanitize_container_segment("my project") == "my-project"
    assert _sanitize_container_segment("foo@bar!baz") == "foo-bar-baz"


def test_sanitize_collapses_repeated_dashes():
    assert _sanitize_container_segment("a - - b") == "a-b"


def test_sanitize_strips_leading_trailing():
    assert _sanitize_container_segment("-leading") == "leading"
    assert _sanitize_container_segment("trailing-") == "trailing"
    assert _sanitize_container_segment(".dotted.") == "dotted"


def test_sanitize_preserves_valid_names():
    assert _sanitize_container_segment("my-repo") == "my-repo"
    assert _sanitize_container_segment("my_repo.v2") == "my_repo.v2"


def test_sanitize_fallback_on_empty():
    assert _sanitize_container_segment("---") == "repo"
    assert _sanitize_container_segment("") == "repo"


# ── _template_vars ──────────────────────────────────────────


def test_template_vars_package_flags():
    config = InitConfig(
        packages=["apps/web", "apps/api"],
        cross_pairs=[("apps/web", "apps/api")],
        install_claude=True, install_ci=True, setup_neo4j=True,
        container_name="cognitx-codegraph-demo",
    )
    vars_ = _template_vars(config)
    assert vars_["PACKAGE_PATHS_FLAGS"] == "-p apps/web -p apps/api"
    assert '{ importer = "apps/web", importee = "apps/api" }' in vars_["CROSS_PAIRS_TOML"]
    assert vars_["CONTAINER_NAME"] == "cognitx-codegraph-demo"


def test_template_vars_no_cross_pairs():
    config = InitConfig(
        packages=["."], cross_pairs=[],
        install_claude=True, install_ci=True, setup_neo4j=True,
        container_name="cognitx-codegraph-demo",
    )
    vars_ = _template_vars(config)
    assert vars_["CROSS_PAIRS_TOML"] == ""


# ── _prompt_config container name ──────────────────────────


def test_container_name_includes_path_hash(tmp_path: Path):
    """Two repos with the same basename but different paths get different names."""
    path_a = tmp_path / "a" / "app"
    path_b = tmp_path / "b" / "app"
    path_a.mkdir(parents=True)
    path_b.mkdir(parents=True)

    cfg_a = _prompt_config(
        RepoShape(root=path_a), non_interactive=True, console=_silent_console(),
    )
    cfg_b = _prompt_config(
        RepoShape(root=path_b), non_interactive=True, console=_silent_console(),
    )

    assert cfg_a.container_name.startswith("cognitx-codegraph-app-")
    assert cfg_b.container_name.startswith("cognitx-codegraph-app-")
    assert cfg_a.container_name != cfg_b.container_name

    # Suffix is exactly 8 hex characters.
    suffix_a = cfg_a.container_name.rsplit("-", 1)[-1]
    assert re.fullmatch(r"[0-9a-f]{8}", suffix_a)


def test_container_name_is_deterministic(tmp_path: Path):
    """Same path produces the same container name on repeated calls."""
    shape = RepoShape(root=tmp_path)
    cfg1 = _prompt_config(shape, non_interactive=True, console=_silent_console())
    cfg2 = _prompt_config(shape, non_interactive=True, console=_silent_console())
    assert cfg1.container_name == cfg2.container_name


def test_container_name_sanitizes_special_chars(tmp_path: Path):
    """Directory with spaces/special chars produces a valid Docker name."""
    spaced = tmp_path / "my project"
    spaced.mkdir()
    cfg = _prompt_config(
        RepoShape(root=spaced), non_interactive=True, console=_silent_console(),
    )
    assert " " not in cfg.container_name
    assert re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", cfg.container_name)


def test_container_name_sanitizes_segment_value(tmp_path: Path):
    """Sanitized segment is 'my-project', not 'my project'."""
    spaced = tmp_path / "my project"
    spaced.mkdir()
    cfg = _prompt_config(
        RepoShape(root=spaced), non_interactive=True, console=_silent_console(),
    )
    assert "my-project" in cfg.container_name


# ── _warn_orphaned_containers ─────────────────────────────


def test_warn_orphaned_container_prints_warning(tmp_path: Path, monkeypatch):
    """Old-style container (no hash suffix) triggers a warning."""
    repo_name = tmp_path.name
    config = InitConfig(
        packages=["."], cross_pairs=[], install_claude=True,
        install_ci=True, setup_neo4j=True,
        container_name=f"cognitx-codegraph-{repo_name}-abcd1234",
    )
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a[0], 0, stdout=f"cognitx-codegraph-{repo_name}\n",
        ),
    )
    console = Console(record=True, file=io.StringIO())
    _warn_orphaned_containers(tmp_path, config, console)
    text = console.export_text()
    assert f"cognitx-codegraph-{repo_name}" in text
    assert "docker rm -f" in text


def test_warn_orphaned_container_no_false_positive(tmp_path: Path, monkeypatch):
    """Current container name must NOT be flagged as orphan."""
    repo_name = tmp_path.name
    current_name = f"cognitx-codegraph-{repo_name}-abcd1234"
    config = InitConfig(
        packages=["."], cross_pairs=[], install_claude=True,
        install_ci=True, setup_neo4j=True,
        container_name=current_name,
    )
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a[0], 0, stdout=f"{current_name}\n",
        ),
    )
    console = Console(record=True, file=io.StringIO())
    _warn_orphaned_containers(tmp_path, config, console)
    assert "Warning" not in console.export_text()


def test_warn_orphaned_container_ignores_other_repo(tmp_path: Path, monkeypatch):
    """Container from a different repo whose name is a superstring must not be flagged."""
    repo_name = tmp_path.name
    config = InitConfig(
        packages=["."], cross_pairs=[], install_claude=True,
        install_ci=True, setup_neo4j=True,
        container_name=f"cognitx-codegraph-{repo_name}-abcd1234",
    )
    # docker ps substring match might return a container from repo "myrepo-v2"
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a[0], 0,
            stdout=f"cognitx-codegraph-{repo_name}-v2-beef5678\n",
        ),
    )
    console = Console(record=True, file=io.StringIO())
    _warn_orphaned_containers(tmp_path, config, console)
    assert "Warning" not in console.export_text()


def test_warn_orphaned_container_docker_unavailable(tmp_path: Path, monkeypatch):
    """FileNotFoundError (docker not on PATH) must not crash."""
    config = InitConfig(
        packages=["."], cross_pairs=[], install_claude=True,
        install_ci=True, setup_neo4j=True,
        container_name="cognitx-codegraph-x-abcd1234",
    )

    def _raise(*a, **kw):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess, "run", _raise)
    console = Console(record=True, file=io.StringIO())
    _warn_orphaned_containers(tmp_path, config, console)
    assert console.export_text().strip() == ""


def test_warn_orphaned_container_docker_daemon_down(tmp_path: Path, monkeypatch):
    """CalledProcessError (daemon down) must not crash."""
    config = InitConfig(
        packages=["."], cross_pairs=[], install_claude=True,
        install_ci=True, setup_neo4j=True,
        container_name="cognitx-codegraph-x-abcd1234",
    )

    def _raise(*a, **kw):
        raise subprocess.CalledProcessError(1, "docker")

    monkeypatch.setattr(subprocess, "run", _raise)
    console = Console(record=True, file=io.StringIO())
    _warn_orphaned_containers(tmp_path, config, console)
    assert console.export_text().strip() == ""


# ── _render (template smoke) ────────────────────────────────


def test_render_arch_policies_is_valid_toml():
    config = InitConfig(
        packages=["apps/web"],
        cross_pairs=[("apps/web", "apps/api")],
        install_claude=True, install_ci=True, setup_neo4j=True,
        container_name="cognitx-codegraph-demo",
    )
    rendered = _render("arch-policies.toml", _template_vars(config))
    parsed = tomllib.loads(rendered)
    assert parsed["policies"]["cross_package"]["pairs"] == [
        {"importer": "apps/web", "importee": "apps/api"},
    ]


def test_render_workflow_is_valid_yaml():
    config = InitConfig(
        packages=["apps/web"], cross_pairs=[],
        install_claude=True, install_ci=True, setup_neo4j=True,
        container_name="cognitx-codegraph-demo",
    )
    rendered = _render("github/workflows/arch-check.yml", _template_vars(config))
    parsed = yaml.safe_load(rendered)
    # YAML parses `on:` as the boolean True key — match existing workflow.
    assert parsed["name"] == "arch-check"
    assert "arch-check" in parsed["jobs"]
    # Verify the template substitution produced correct flags.
    steps = parsed["jobs"]["arch-check"]["steps"]
    index_step = next(s for s in steps if s.get("name") == "Index repo")
    assert "-p apps/web" in index_step["run"]


# ── _scaffold_files end-to-end ──────────────────────────────


def test_scaffold_writes_expected_files(tmp_path: Path):
    _make_git_repo(tmp_path)
    config = InitConfig(
        packages=["src"], cross_pairs=[],
        install_claude=True, install_ci=True, setup_neo4j=True,
        container_name="cognitx-codegraph-demo",
        default_package_prefix="src/",
    )
    _scaffold_files(tmp_path, config, force=False, console=_silent_console())

    # All 7 claude commands
    cmd_dir = tmp_path / ".claude" / "commands"
    for cmd in ["graph.md", "graph-refresh.md", "blast-radius.md", "dead-code.md",
                "who-owns.md", "trace-endpoint.md", "arch-check.md"]:
        assert (cmd_dir / cmd).exists(), f"missing {cmd}"

    # Workflow + config + compose
    assert (tmp_path / ".github" / "workflows" / "arch-check.yml").exists()
    assert (tmp_path / ".arch-policies.toml").exists()
    assert (tmp_path / "docker-compose.yml").exists()

    # CLAUDE.md was created (didn't exist before)
    claude_md = tmp_path / "CLAUDE.md"
    assert claude_md.exists()
    assert "codegraph knowledge graph" in claude_md.read_text()


def test_scaffold_skips_existing_files_without_force(tmp_path: Path):
    _make_git_repo(tmp_path)
    (tmp_path / ".arch-policies.toml").write_text("# existing content\n")

    config = InitConfig(
        packages=["src"], cross_pairs=[],
        install_claude=False, install_ci=False, setup_neo4j=False,
        container_name="cognitx-codegraph-demo",
    )
    _scaffold_files(tmp_path, config, force=False, console=_silent_console())
    assert (tmp_path / ".arch-policies.toml").read_text() == "# existing content\n"


def test_scaffold_overwrites_existing_with_force(tmp_path: Path):
    _make_git_repo(tmp_path)
    (tmp_path / ".arch-policies.toml").write_text("# existing content\n")

    config = InitConfig(
        packages=["src"], cross_pairs=[],
        install_claude=False, install_ci=False, setup_neo4j=False,
        container_name="cognitx-codegraph-demo",
    )
    _scaffold_files(tmp_path, config, force=True, console=_silent_console())
    content = (tmp_path / ".arch-policies.toml").read_text()
    assert "# existing content" not in content
    assert "policies.import_cycles" in content


def test_scaffold_appends_to_existing_claude_md(tmp_path: Path):
    _make_git_repo(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("# My Project\n\nSome notes.\n")

    config = InitConfig(
        packages=["src"], cross_pairs=[],
        install_claude=False, install_ci=False, setup_neo4j=False,
        container_name="cognitx-codegraph-demo",
    )
    _scaffold_files(tmp_path, config, force=False, console=_silent_console())

    content = (tmp_path / "CLAUDE.md").read_text()
    assert "# My Project" in content              # existing preserved
    assert "codegraph knowledge graph" in content  # snippet appended


def test_scaffold_claude_md_append_is_idempotent(tmp_path: Path):
    _make_git_repo(tmp_path)
    config = InitConfig(
        packages=["src"], cross_pairs=[],
        install_claude=False, install_ci=False, setup_neo4j=False,
        container_name="cognitx-codegraph-demo",
    )
    _scaffold_files(tmp_path, config, force=False, console=_silent_console())
    first = (tmp_path / "CLAUDE.md").read_text()
    # Running it again must not duplicate the snippet.
    _scaffold_files(tmp_path, config, force=False, console=_silent_console())
    second = (tmp_path / "CLAUDE.md").read_text()
    assert first == second


def test_append_claude_md_crlf(tmp_path: Path):
    """CLAUDE.md with CRLF endings must be appended without corruption."""
    _make_git_repo(tmp_path)
    (tmp_path / "CLAUDE.md").write_bytes(b"# My Project\r\n\r\nSome notes.\r\n")

    config = InitConfig(
        packages=["src"], cross_pairs=[],
        install_claude=False, install_ci=False, setup_neo4j=False,
        container_name="cognitx-codegraph-demo",
    )
    _scaffold_files(tmp_path, config, force=False, console=_silent_console())

    with open(tmp_path / "CLAUDE.md", encoding="utf-8", newline="") as fh:
        content = fh.read()
    assert "# My Project" in content              # existing preserved
    assert "codegraph knowledge graph" in content  # snippet appended
    assert "\r\r" not in content                   # no double-CR corruption


def test_scaffold_respects_opt_outs(tmp_path: Path):
    _make_git_repo(tmp_path)
    config = InitConfig(
        packages=["src"], cross_pairs=[],
        install_claude=False, install_ci=False, setup_neo4j=False,
        container_name="cognitx-codegraph-demo",
    )
    _scaffold_files(tmp_path, config, force=False, console=_silent_console())
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".github").exists()
    assert not (tmp_path / "docker-compose.yml").exists()
    # But the policy config still lands (it's the authoritative tunable).
    assert (tmp_path / ".arch-policies.toml").exists()


# ── run_init full flow (docker + index disabled) ────────────


def test_run_init_non_interactive_happy_path(tmp_path: Path, monkeypatch):
    _make_git_repo(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    monkeypatch.chdir(tmp_path)

    exit_code = run_init(
        force=False, non_interactive=True,
        skip_docker=True, skip_index=True,
        console=_silent_console(),
    )
    assert exit_code == 0
    # Sanity check: scaffolder ran
    assert (tmp_path / ".arch-policies.toml").exists()
    assert (tmp_path / ".claude" / "commands" / "graph.md").exists()


def test_run_init_outside_git_repo(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exit_code = run_init(
        force=False, non_interactive=True,
        skip_docker=True, skip_index=True,
        console=_silent_console(),
    )
    assert exit_code == 1


def test_run_init_returns_1_when_first_index_fails(tmp_path: Path, monkeypatch):
    """run_init must return 1 when _run_first_index fails (issue #157)."""
    _make_git_repo(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
    monkeypatch.chdir(tmp_path)

    # Stub _run_first_index to simulate failure
    monkeypatch.setattr(init_module, "_run_first_index", lambda *a, **kw: False)
    # Stub _start_and_wait_for_neo4j to simulate success (so we reach _run_first_index)
    monkeypatch.setattr(init_module, "_start_and_wait_for_neo4j", lambda *a, **kw: True)

    exit_code = run_init(
        force=False, non_interactive=True,
        skip_docker=False, skip_index=False,
        console=_silent_console(),
    )
    assert exit_code == 1
