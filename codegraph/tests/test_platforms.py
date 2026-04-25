"""Tests for :mod:`codegraph.platforms` — platform install/uninstall.

All tests scaffold into ``tmp_path`` with a real ``git init``, so file
operations run against real files.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from rich.console import Console

from codegraph.platforms import (
    PLATFORMS,
    _SECTION_MARKER,
    _append_section,
    _remove_section,
    _install_json_hook,
    _uninstall_json_hook,
    install_all,
    install_platform,
    uninstall_platform,
)


# ── Helpers ─────────────────────────────────────────────────


def _make_git_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)


def _silent_console() -> Console:
    return Console(quiet=True)


def _default_vars() -> dict[str, str]:
    return {
        "NEO4J_BOLT_PORT": "7687",
        "NEO4J_HTTP_PORT": "7474",
        "PACKAGE_PATHS_FLAGS": "",
        "DEFAULT_PACKAGE_PREFIX": "",
        "CROSS_PAIRS_TOML": "",
        "CONTAINER_NAME": "codegraph-neo4j",
        "PIPX_VERSION": "0.2.0",
    }


# ── Platform registry sanity ──────────────────────────────


def test_platform_registry_has_14_entries():
    assert len(PLATFORMS) == 14


def test_all_platform_names_are_lowercase():
    for name in PLATFORMS:
        assert name == name.lower()


# ── AGENTS.md platforms (parametrized) ─────────────────────


_AGENTS_MD_PLATFORMS = ["codex", "opencode", "aider", "claw", "droid", "trae", "hermes"]


@pytest.mark.parametrize("platform", _AGENTS_MD_PLATFORMS)
def test_agents_md_install(tmp_path: Path, platform: str):
    _make_git_repo(tmp_path)
    result = install_platform(
        tmp_path, platform,
        template_vars=_default_vars(), console=_silent_console(),
    )
    assert "AGENTS.md" in result
    agents_md = tmp_path / "AGENTS.md"
    assert agents_md.exists()
    content = agents_md.read_text()
    assert _SECTION_MARKER in content
    assert "codegraph" in content
    assert "7687" in content


@pytest.mark.parametrize("platform", _AGENTS_MD_PLATFORMS)
def test_agents_md_idempotent(tmp_path: Path, platform: str):
    _make_git_repo(tmp_path)
    install_platform(
        tmp_path, platform,
        template_vars=_default_vars(), console=_silent_console(),
    )
    install_platform(
        tmp_path, platform,
        template_vars=_default_vars(), console=_silent_console(),
    )
    content = (tmp_path / "AGENTS.md").read_text()
    assert content.count(_SECTION_MARKER) == 1


@pytest.mark.parametrize("platform", _AGENTS_MD_PLATFORMS)
def test_agents_md_uninstall(tmp_path: Path, platform: str):
    _make_git_repo(tmp_path)
    install_platform(
        tmp_path, platform,
        template_vars=_default_vars(), console=_silent_console(),
    )
    result = uninstall_platform(tmp_path, platform, console=_silent_console())
    assert "AGENTS.md" in result
    # File should be deleted since it only had codegraph content
    assert not (tmp_path / "AGENTS.md").exists()


# ── Claude Code ────────────────────────────────────────────


def test_install_claude_creates_claude_md(tmp_path: Path):
    _make_git_repo(tmp_path)
    result = install_platform(
        tmp_path, "claude",
        template_vars=_default_vars(), console=_silent_console(),
    )
    assert "CLAUDE.md" in result
    claude_md = tmp_path / "CLAUDE.md"
    assert claude_md.exists()
    content = claude_md.read_text()
    assert "codegraph knowledge graph" in content


def test_install_claude_creates_pretool_hook(tmp_path: Path):
    _make_git_repo(tmp_path)
    install_platform(
        tmp_path, "claude",
        template_vars=_default_vars(), console=_silent_console(),
    )
    settings = tmp_path / ".claude" / "settings.json"
    assert settings.exists()
    data = json.loads(settings.read_text())
    assert "hooks" in data
    assert "PreToolUse" in data["hooks"]
    hooks = data["hooks"]["PreToolUse"]
    assert any("codegraph" in str(h) for h in hooks)


def test_install_claude_idempotent(tmp_path: Path):
    _make_git_repo(tmp_path)
    install_platform(
        tmp_path, "claude",
        template_vars=_default_vars(), console=_silent_console(),
    )
    install_platform(
        tmp_path, "claude",
        template_vars=_default_vars(), console=_silent_console(),
    )
    content = (tmp_path / "CLAUDE.md").read_text()
    assert content.count("## Using the codegraph knowledge graph") == 1


def test_uninstall_claude_removes_section_and_hook(tmp_path: Path):
    _make_git_repo(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("# My Project\n\nExisting content.\n")
    install_platform(
        tmp_path, "claude",
        template_vars=_default_vars(), console=_silent_console(),
    )
    uninstall_platform(tmp_path, "claude", console=_silent_console())
    claude_md = tmp_path / "CLAUDE.md"
    assert claude_md.exists()
    content = claude_md.read_text()
    assert "My Project" in content
    assert "codegraph knowledge graph" not in content
    # Verify hook was also removed
    settings = tmp_path / ".claude" / "settings.json"
    if settings.exists():
        data = json.loads(settings.read_text())
        pre_tool = data.get("hooks", {}).get("PreToolUse", [])
        assert not any("codegraph" in str(h) for h in pre_tool)


def test_install_claude_no_unresolved_vars(tmp_path: Path):
    """Regression test for #256: CLI install must resolve all template vars."""
    _make_git_repo(tmp_path)
    install_platform(
        tmp_path, "claude",
        template_vars=_default_vars(), console=_silent_console(),
    )
    content = (tmp_path / "CLAUDE.md").read_text()
    unresolved = re.findall(r'\$\{?[A-Z_]+\}?', content)
    assert unresolved == [], f"Unresolved template vars in CLAUDE.md: {unresolved}"


# ── Cursor ─────────────────────────────────────────────────


def test_install_cursor_creates_rule_file(tmp_path: Path):
    _make_git_repo(tmp_path)
    result = install_platform(
        tmp_path, "cursor",
        template_vars=_default_vars(), console=_silent_console(),
    )
    assert ".cursor/rules/codegraph.mdc" in result
    rule = tmp_path / ".cursor" / "rules" / "codegraph.mdc"
    assert rule.exists()
    content = rule.read_text()
    assert "alwaysApply: true" in content
    assert "codegraph" in content
    assert "7687" in content


def test_install_cursor_idempotent(tmp_path: Path):
    _make_git_repo(tmp_path)
    install_platform(
        tmp_path, "cursor",
        template_vars=_default_vars(), console=_silent_console(),
    )
    result = install_platform(
        tmp_path, "cursor",
        template_vars=_default_vars(), console=_silent_console(),
    )
    assert "already installed" in result


def test_uninstall_cursor_removes_file(tmp_path: Path):
    _make_git_repo(tmp_path)
    install_platform(
        tmp_path, "cursor",
        template_vars=_default_vars(), console=_silent_console(),
    )
    uninstall_platform(tmp_path, "cursor", console=_silent_console())
    assert not (tmp_path / ".cursor" / "rules" / "codegraph.mdc").exists()


# ── Gemini ─────────────────────────────────────────────────


def test_install_gemini_creates_gemini_md_and_hook(tmp_path: Path):
    _make_git_repo(tmp_path)
    result = install_platform(
        tmp_path, "gemini",
        template_vars=_default_vars(), console=_silent_console(),
    )
    assert "GEMINI.md" in result
    gemini_md = tmp_path / "GEMINI.md"
    assert gemini_md.exists()
    content = gemini_md.read_text()
    assert _SECTION_MARKER in content

    settings = tmp_path / ".gemini" / "settings.json"
    assert settings.exists()
    data = json.loads(settings.read_text())
    assert "BeforeTool" in data["hooks"]


def test_uninstall_gemini_removes_section_and_hook(tmp_path: Path):
    _make_git_repo(tmp_path)
    install_platform(
        tmp_path, "gemini",
        template_vars=_default_vars(), console=_silent_console(),
    )
    uninstall_platform(tmp_path, "gemini", console=_silent_console())
    assert not (tmp_path / "GEMINI.md").exists()
    # Verify hook was also removed
    settings = tmp_path / ".gemini" / "settings.json"
    if settings.exists():
        data = json.loads(settings.read_text())
        before_tool = data.get("hooks", {}).get("BeforeTool", [])
        assert not any("codegraph" in str(h) for h in before_tool)


# ── Kiro ───────────────────────────────────────────────────


def test_install_kiro_creates_steering_file(tmp_path: Path):
    _make_git_repo(tmp_path)
    result = install_platform(
        tmp_path, "kiro",
        template_vars=_default_vars(), console=_silent_console(),
    )
    assert ".kiro/steering/codegraph.md" in result
    kiro = tmp_path / ".kiro" / "steering" / "codegraph.md"
    assert kiro.exists()
    content = kiro.read_text()
    assert "inclusion: always" in content


def test_uninstall_kiro_removes_file(tmp_path: Path):
    _make_git_repo(tmp_path)
    install_platform(
        tmp_path, "kiro",
        template_vars=_default_vars(), console=_silent_console(),
    )
    uninstall_platform(tmp_path, "kiro", console=_silent_console())
    assert not (tmp_path / ".kiro" / "steering" / "codegraph.md").exists()


# ── Antigravity ────────────────────────────────────────────


def test_install_antigravity_creates_rules_and_workflow(tmp_path: Path):
    _make_git_repo(tmp_path)
    result = install_platform(
        tmp_path, "antigravity",
        template_vars=_default_vars(), console=_silent_console(),
    )
    assert ".agents/rules/codegraph.md" in result
    assert ".agents/workflows/codegraph.md" in result
    assert (tmp_path / ".agents" / "rules" / "codegraph.md").exists()
    assert (tmp_path / ".agents" / "workflows" / "codegraph.md").exists()


def test_uninstall_antigravity_removes_files(tmp_path: Path):
    _make_git_repo(tmp_path)
    install_platform(
        tmp_path, "antigravity",
        template_vars=_default_vars(), console=_silent_console(),
    )
    uninstall_platform(tmp_path, "antigravity", console=_silent_console())
    assert not (tmp_path / ".agents" / "rules" / "codegraph.md").exists()
    assert not (tmp_path / ".agents" / "workflows" / "codegraph.md").exists()


# ── VS Code ───────────────────────────────────────────────


def test_install_vscode_creates_copilot_instructions(tmp_path: Path):
    _make_git_repo(tmp_path)
    result = install_platform(
        tmp_path, "vscode",
        template_vars=_default_vars(), console=_silent_console(),
    )
    assert "copilot-instructions.md" in result
    target = tmp_path / ".github" / "copilot-instructions.md"
    assert target.exists()
    assert _SECTION_MARKER in target.read_text()


def test_install_vscode_creates_parent_dirs(tmp_path: Path):
    _make_git_repo(tmp_path)
    install_platform(
        tmp_path, "vscode",
        template_vars=_default_vars(), console=_silent_console(),
    )
    assert (tmp_path / ".github").is_dir()
    assert (tmp_path / ".github" / "copilot-instructions.md").exists()


# ── Codex hook ─────────────────────────────────────────────


def test_install_codex_creates_pretool_hook(tmp_path: Path):
    _make_git_repo(tmp_path)
    install_platform(
        tmp_path, "codex",
        template_vars=_default_vars(), console=_silent_console(),
    )
    hooks_file = tmp_path / ".codex" / "hooks.json"
    assert hooks_file.exists()
    data = json.loads(hooks_file.read_text())
    assert "PreToolUse" in data["hooks"]


# ── OpenCode plugin ────────────────────────────────────────


def test_install_opencode_creates_plugin(tmp_path: Path):
    _make_git_repo(tmp_path)
    install_platform(
        tmp_path, "opencode",
        template_vars=_default_vars(), console=_silent_console(),
    )
    plugin = tmp_path / ".opencode" / "plugins" / "codegraph.js"
    assert plugin.exists()
    assert "codegraph" in plugin.read_text()

    config = tmp_path / ".opencode" / "opencode.json"
    assert config.exists()
    data = json.loads(config.read_text())
    assert "plugins/codegraph.js" in data["plugins"]


def test_uninstall_opencode_removes_plugin(tmp_path: Path):
    _make_git_repo(tmp_path)
    install_platform(
        tmp_path, "opencode",
        template_vars=_default_vars(), console=_silent_console(),
    )
    uninstall_platform(tmp_path, "opencode", console=_silent_console())
    assert not (tmp_path / ".opencode" / "plugins" / "codegraph.js").exists()


# ── Copilot (no-op) ───────────────────────────────────────


def test_install_copilot_returns_reminder(tmp_path: Path):
    _make_git_repo(tmp_path)
    result = install_platform(
        tmp_path, "copilot",
        template_vars=_default_vars(), console=_silent_console(),
    )
    assert "MCP server" in result


# ── install --all ──────────────────────────────────────────


def test_install_all_detects_platforms(tmp_path: Path):
    _make_git_repo(tmp_path)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".cursor").mkdir()
    results = install_all(
        tmp_path, template_vars=_default_vars(), console=_silent_console(),
    )
    assert len(results) >= 2
    names = " ".join(results)
    assert "Claude Code" in names
    assert "Cursor" in names


def test_install_all_skips_absent_platforms(tmp_path: Path):
    _make_git_repo(tmp_path)
    results = install_all(
        tmp_path, template_vars=_default_vars(), console=_silent_console(),
    )
    assert len(results) == 0


# ── Edge cases ─────────────────────────────────────────────


def test_install_agents_md_preserves_existing_sections(tmp_path: Path):
    _make_git_repo(tmp_path)
    (tmp_path / "AGENTS.md").write_text("## my-tool\n\nSome existing rules.\n")
    install_platform(
        tmp_path, "codex",
        template_vars=_default_vars(), console=_silent_console(),
    )
    content = (tmp_path / "AGENTS.md").read_text()
    assert "## my-tool" in content
    assert _SECTION_MARKER in content


def test_uninstall_deletes_empty_agents_md(tmp_path: Path):
    _make_git_repo(tmp_path)
    install_platform(
        tmp_path, "codex",
        template_vars=_default_vars(), console=_silent_console(),
    )
    uninstall_platform(tmp_path, "codex", console=_silent_console())
    assert not (tmp_path / "AGENTS.md").exists()


def test_uninstall_preserves_other_sections_in_agents_md(tmp_path: Path):
    _make_git_repo(tmp_path)
    (tmp_path / "AGENTS.md").write_text("## other-tool\n\nOther rules.\n")
    install_platform(
        tmp_path, "codex",
        template_vars=_default_vars(), console=_silent_console(),
    )
    uninstall_platform(tmp_path, "codex", console=_silent_console())
    agents = tmp_path / "AGENTS.md"
    assert agents.exists()
    content = agents.read_text()
    assert "## other-tool" in content
    assert _SECTION_MARKER not in content


def test_install_json_hook_preserves_existing_hooks(tmp_path: Path):
    settings = tmp_path / "settings.json"
    existing = {"hooks": {"PreToolUse": [{"command": "other-tool"}]}}
    settings.write_text(json.dumps(existing))
    _install_json_hook(settings, {"command": "codegraph"}, "PreToolUse", _silent_console())
    data = json.loads(settings.read_text())
    hooks = data["hooks"]["PreToolUse"]
    assert len(hooks) == 2
    assert any("other-tool" in str(h) for h in hooks)
    assert any("codegraph" in str(h) for h in hooks)


def test_uninstall_json_hook_preserves_other_hooks(tmp_path: Path):
    settings = tmp_path / "settings.json"
    existing = {"hooks": {"PreToolUse": [
        {"command": "other-tool"},
        {"command": "codegraph"},
    ]}}
    settings.write_text(json.dumps(existing))
    _uninstall_json_hook(settings, "PreToolUse", _silent_console())
    data = json.loads(settings.read_text())
    hooks = data["hooks"]["PreToolUse"]
    assert len(hooks) == 1
    assert "other-tool" in str(hooks[0])


def test_unknown_platform_returns_error(tmp_path: Path):
    result = install_platform(
        tmp_path, "nonexistent",
        template_vars=_default_vars(), console=_silent_console(),
    )
    assert "unknown platform" in result


def test_template_vars_substitution(tmp_path: Path):
    _make_git_repo(tmp_path)
    custom_vars = {"NEO4J_BOLT_PORT": "9999"}
    install_platform(
        tmp_path, "codex",
        template_vars=custom_vars, console=_silent_console(),
    )
    content = (tmp_path / "AGENTS.md").read_text()
    assert "9999" in content
    assert "$NEO4J_BOLT_PORT" not in content


# ── _append_section / _remove_section unit tests ──────────


def test_append_section_creates_new_file(tmp_path: Path):
    target = tmp_path / "TEST.md"
    result = _append_section(target, "## codegraph\n\nContent.\n", _SECTION_MARKER, _silent_console())
    assert result is True
    assert target.exists()
    assert _SECTION_MARKER in target.read_text()


def test_append_section_appends_to_existing(tmp_path: Path):
    target = tmp_path / "TEST.md"
    target.write_text("# Existing\n\nOld content.\n")
    _append_section(target, "## codegraph\n\nNew.\n", _SECTION_MARKER, _silent_console())
    content = target.read_text()
    assert "# Existing" in content
    assert _SECTION_MARKER in content


def test_append_section_is_idempotent(tmp_path: Path):
    target = tmp_path / "TEST.md"
    _append_section(target, "## codegraph\n\nContent.\n", _SECTION_MARKER, _silent_console())
    result = _append_section(target, "## codegraph\n\nContent.\n", _SECTION_MARKER, _silent_console())
    assert result is False
    assert target.read_text().count(_SECTION_MARKER) == 1


def test_remove_section_removes_content(tmp_path: Path):
    target = tmp_path / "TEST.md"
    target.write_text("# Title\n\n## codegraph\n\nGraph stuff.\n")
    result = _remove_section(target, _SECTION_MARKER, _silent_console())
    assert result is True
    content = target.read_text()
    assert "# Title" in content
    assert _SECTION_MARKER not in content


def test_remove_section_deletes_codegraph_only_file(tmp_path: Path):
    target = tmp_path / "TEST.md"
    target.write_text("## codegraph\n\nOnly codegraph content.\n")
    _remove_section(target, _SECTION_MARKER, _silent_console())
    assert not target.exists()


def test_remove_section_preserves_other_sections(tmp_path: Path):
    target = tmp_path / "TEST.md"
    target.write_text("## other\n\nOther stuff.\n\n## codegraph\n\nGraph stuff.\n")
    _remove_section(target, _SECTION_MARKER, _silent_console())
    content = target.read_text()
    assert "## other" in content
    assert "Other stuff" in content
    assert _SECTION_MARKER not in content


def test_remove_section_codegraph_before_other_section(tmp_path: Path):
    """Removing codegraph when it's the FIRST section must not leave leading blank lines."""
    target = tmp_path / "TEST.md"
    target.write_text("## codegraph\n\nGraph stuff.\n\n## other\n\nOther stuff.\n")
    _remove_section(target, _SECTION_MARKER, _silent_console())
    content = target.read_text()
    assert _SECTION_MARKER not in content
    assert "## other" in content
    assert "Other stuff" in content
    # Must not start with blank lines
    assert not content.startswith("\n")
