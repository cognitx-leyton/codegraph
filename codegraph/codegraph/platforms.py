"""Platform install/uninstall — manage codegraph as always-on context for AI coding assistants.

Supports 14 platforms: Claude Code, Codex, OpenCode, Cursor, Gemini CLI,
GitHub Copilot CLI, VS Code Copilot Chat, Aider, OpenClaw, Factory Droid,
Trae, Kiro IDE, Google Antigravity, Hermes.

Each platform gets:
- A rules file (CLAUDE.md, AGENTS.md, GEMINI.md, etc.) with a ``## codegraph``
  section, OR a standalone file written to a platform-specific path.
- Optionally, a tool-call hook (PreToolUse, BeforeTool, or JS plugin).

Install is idempotent (safe to re-run). Uninstall removes only the codegraph
section/files, preserving other content.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib.resources import files as _pkg_files
from pathlib import Path
from string import Template

from rich.console import Console


_TEMPLATES_ROOT = _pkg_files("codegraph") / "templates"

# Marker used to detect/remove codegraph sections in shared files.
_SECTION_MARKER = "## codegraph"

# Manifest file that tracks which platforms are currently installed.
_MANIFEST_FILE = ".codegraph/platforms.json"


def _read_manifest(root: Path) -> set[str]:
    """Load the set of installed platform names from the manifest."""
    path = root / _MANIFEST_FILE
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    return set(data.get("installed", []))


def _write_manifest(root: Path, installed: set[str]) -> None:
    """Persist the set of installed platform names to the manifest."""
    path = root / _MANIFEST_FILE
    if not installed:
        if path.exists():
            path.unlink()
        # Remove empty .codegraph/ dir
        codegraph_dir = root / ".codegraph"
        if codegraph_dir.is_dir() and not any(codegraph_dir.iterdir()):
            codegraph_dir.rmdir()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"installed": sorted(installed)}, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )


def _other_installed_share_section(name: str, installed: set[str]) -> bool:
    """Return True if another installed platform shares the same rules section."""
    cfg = PLATFORMS.get(name)
    if cfg is None or cfg.rules_file is None:
        return False
    for other in installed - {name}:
        other_cfg = PLATFORMS.get(other)
        if other_cfg is None:
            continue
        if other_cfg.rules_file == cfg.rules_file and other_cfg.rules_marker == cfg.rules_marker:
            return True
    return False


# ── Platform config registry ──────────────────────────────────


@dataclass
class PlatformConfig:
    """Describes how to install codegraph for a single AI platform."""

    name: str
    display_name: str
    rules_file: str | None = None           # e.g. "CLAUDE.md", "AGENTS.md"
    rules_template: str | None = None       # template path under templates/
    rules_marker: str = _SECTION_MARKER
    standalone_rules: dict[str, str] | None = None  # {rel_path: template_name}
    hook_type: str | None = None            # "claude_pretool", "codex_pretool", etc.
    detect_hint: str | None = None          # dir/file that suggests platform is active


PLATFORMS: dict[str, PlatformConfig] = {
    "claude": PlatformConfig(
        name="claude",
        display_name="Claude Code",
        rules_file="CLAUDE.md",
        rules_template="claude-md-snippet.md",
        rules_marker="## Using the codegraph knowledge graph",
        hook_type="claude_pretool",
        detect_hint=".claude/",
    ),
    "codex": PlatformConfig(
        name="codex",
        display_name="Codex",
        rules_file="AGENTS.md",
        rules_template="platforms/rules-agents.md",
        hook_type="codex_pretool",
        detect_hint=".codex/",
    ),
    "opencode": PlatformConfig(
        name="opencode",
        display_name="OpenCode",
        rules_file="AGENTS.md",
        rules_template="platforms/rules-agents.md",
        hook_type="opencode_plugin",
        detect_hint=".opencode/",
    ),
    "cursor": PlatformConfig(
        name="cursor",
        display_name="Cursor",
        standalone_rules={".cursor/rules/codegraph.mdc": "platforms/rules-cursor.mdc"},
        detect_hint=".cursor/",
    ),
    "gemini": PlatformConfig(
        name="gemini",
        display_name="Gemini CLI",
        rules_file="GEMINI.md",
        rules_template="platforms/rules-gemini.md",
        hook_type="gemini_beforetool",
        detect_hint=".gemini/",
    ),
    "copilot": PlatformConfig(
        name="copilot",
        display_name="GitHub Copilot CLI",
        detect_hint=".copilot/",
    ),
    "vscode": PlatformConfig(
        name="vscode",
        display_name="VS Code Copilot Chat",
        rules_file=".github/copilot-instructions.md",
        rules_template="platforms/rules-vscode.md",
        detect_hint=".github/copilot-instructions.md",
    ),
    "aider": PlatformConfig(
        name="aider",
        display_name="Aider",
        rules_file="AGENTS.md",
        rules_template="platforms/rules-agents.md",
        detect_hint=".aider/",
    ),
    "claw": PlatformConfig(
        name="claw",
        display_name="OpenClaw",
        rules_file="AGENTS.md",
        rules_template="platforms/rules-agents.md",
        detect_hint=".openclaw/",
    ),
    "droid": PlatformConfig(
        name="droid",
        display_name="Factory Droid",
        rules_file="AGENTS.md",
        rules_template="platforms/rules-agents.md",
        detect_hint=".factory/",
    ),
    "trae": PlatformConfig(
        name="trae",
        display_name="Trae",
        rules_file="AGENTS.md",
        rules_template="platforms/rules-agents.md",
        detect_hint=".trae/",
    ),
    "kiro": PlatformConfig(
        name="kiro",
        display_name="Kiro IDE",
        standalone_rules={".kiro/steering/codegraph.md": "platforms/rules-kiro.md"},
        detect_hint=".kiro/",
    ),
    "antigravity": PlatformConfig(
        name="antigravity",
        display_name="Google Antigravity",
        standalone_rules={
            ".agents/rules/codegraph.md": "platforms/rules-antigravity.md",
            ".agents/workflows/codegraph.md": "platforms/rules-antigravity-workflow.md",
        },
        detect_hint=".agents/",
    ),
    "hermes": PlatformConfig(
        name="hermes",
        display_name="Hermes",
        rules_file="AGENTS.md",
        rules_template="platforms/rules-agents.md",
        detect_hint=".hermes/",
    ),
}


# ── Hook configs ──────────────────────────────────────────────

_CLAUDE_PRETOOL_HOOK = {
    "type": "command",
    "command": "cat codegraph-out/GRAPH_REPORT.md 2>/dev/null | head -50 || true",
    "matcher": "Glob|Grep",
}

_CODEX_PRETOOL_HOOK = {
    "type": "command",
    "command": "cat codegraph-out/GRAPH_REPORT.md 2>/dev/null | head -50 || true",
    "matcher": "Glob|Grep",
}

_GEMINI_BEFORETOOL_HOOK = {
    "type": "command",
    "command": "cat codegraph-out/GRAPH_REPORT.md 2>/dev/null | head -50 || true",
    "matcher": "read_file|list_directory",
}


# ── Template rendering ────────────────────────────────────────


def _render(template_rel: str, variables: dict[str, str]) -> str:
    """Load a packaged template and substitute vars."""
    text = (_TEMPLATES_ROOT / template_rel).read_text(encoding="utf-8")
    return Template(text).safe_substitute(variables)


# ── Section append/remove (generalized from init._append_claude_md) ───


def _append_section(
    target: Path,
    snippet: str,
    marker: str,
    console: Console,
) -> bool:
    """Append a marked section to a file. Returns True if written."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        with open(target, encoding="utf-8", newline="") as fh:
            existing = fh.read()
        if marker in existing:
            console.print(f"  [yellow]skip[/] {target} (already contains codegraph section)")
            return False
        with open(target, "w", encoding="utf-8", newline="") as fh:
            fh.write(existing.rstrip() + "\n\n" + snippet)
        console.print(f"  [green]appended[/] codegraph section to {target}")
        return True
    with open(target, "w", encoding="utf-8", newline="") as fh:
        fh.write(snippet)
    console.print(f"  [green]wrote[/] {target}")
    return True


def _remove_section(
    target: Path,
    marker: str,
    console: Console,
) -> bool:
    """Remove a marked section from a file. Returns True if removed."""
    if not target.exists():
        console.print(f"  [yellow]skip[/] {target} (not found)")
        return False
    content = target.read_text(encoding="utf-8")
    if marker not in content:
        console.print(f"  [yellow]skip[/] {target} (no codegraph section)")
        return False
    # Remove the section: from the marker heading to the next ## heading or EOF
    cleaned = re.sub(
        r"\n*" + re.escape(marker) + r"\n.*?(?=\n## |\Z)",
        "",
        content,
        flags=re.DOTALL,
    ).strip()
    if cleaned:
        target.write_text(cleaned + "\n", encoding="utf-8", newline="")
        console.print(f"  [green]removed[/] codegraph section from {target}")
    else:
        target.unlink()
        console.print(f"  [green]deleted[/] {target} (was codegraph-only)")
    return True


# ── JSON hook install/uninstall ───────────────────────────────


def _install_json_hook(
    path: Path,
    hook_config: dict,
    hook_event: str,
    console: Console,
) -> bool:
    """Install a codegraph hook into a JSON settings file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    settings: dict = {}
    if path.exists():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            settings = {}

    hooks = settings.setdefault("hooks", {})
    event_hooks = hooks.setdefault(hook_event, [])
    # Remove existing codegraph hooks, then add fresh
    hooks[hook_event] = [h for h in event_hooks if "codegraph" not in str(h)]
    hooks[hook_event].append(hook_config)
    path.write_text(
        json.dumps(settings, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    console.print(f"  [green]installed[/] {hook_event} hook in {path}")
    return True


def _uninstall_json_hook(
    path: Path,
    hook_event: str,
    console: Console,
) -> bool:
    """Remove codegraph hooks from a JSON settings file."""
    if not path.exists():
        return False
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False

    hooks = settings.get("hooks", {})
    event_hooks = hooks.get(hook_event, [])
    cleaned = [h for h in event_hooks if "codegraph" not in str(h)]
    if len(cleaned) == len(event_hooks):
        return False
    hooks[hook_event] = cleaned
    if not cleaned:
        del hooks[hook_event]
    if not hooks:
        del settings["hooks"]
    path.write_text(
        json.dumps(settings, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    console.print(f"  [green]removed[/] {hook_event} hook from {path}")
    return True


# ── OpenCode plugin install/uninstall ─────────────────────────


def _install_opencode_plugin(
    root: Path,
    template_vars: dict[str, str],
    console: Console,
) -> bool:
    """Write the OpenCode JS plugin and register it in opencode.json."""
    plugin_dir = root / ".opencode" / "plugins"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    plugin_path = plugin_dir / "codegraph.js"
    plugin_path.write_text(
        _render("platforms/hook-opencode.js", template_vars),
        encoding="utf-8",
        newline="",
    )
    console.print(f"  [green]wrote[/] {plugin_path}")

    # Register in opencode.json
    config_path = root / ".opencode" / "opencode.json"
    config: dict = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            config = {}
    plugins = config.setdefault("plugins", [])
    plugin_ref = "plugins/codegraph.js"
    if plugin_ref not in plugins:
        plugins.append(plugin_ref)
    config_path.write_text(
        json.dumps(config, indent=2) + "\n",
        encoding="utf-8",
        newline="",
    )
    console.print(f"  [green]registered[/] plugin in {config_path}")
    return True


def _uninstall_opencode_plugin(
    root: Path,
    console: Console,
) -> bool:
    """Remove the OpenCode JS plugin and deregister from opencode.json."""
    plugin_path = root / ".opencode" / "plugins" / "codegraph.js"
    if plugin_path.exists():
        plugin_path.unlink()
        console.print(f"  [green]deleted[/] {plugin_path}")

    config_path = root / ".opencode" / "opencode.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return True
        plugins = config.get("plugins", [])
        plugin_ref = "plugins/codegraph.js"
        if plugin_ref in plugins:
            plugins.remove(plugin_ref)
            config_path.write_text(
                json.dumps(config, indent=2) + "\n",
                encoding="utf-8",
                newline="",
            )
            console.print(f"  [green]deregistered[/] plugin from {config_path}")
    return True


# ── Standalone file install/uninstall ─────────────────────────


def _install_standalone(
    root: Path,
    rel_path: str,
    template_name: str,
    template_vars: dict[str, str],
    console: Console,
) -> bool:
    """Write a standalone rules file (cursor, kiro, antigravity)."""
    target = root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    content = _render(template_name, template_vars)
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if existing == content:
            console.print(f"  [yellow]skip[/] {target} (already installed)")
            return False
    target.write_text(content, encoding="utf-8", newline="")
    console.print(f"  [green]wrote[/] {target}")
    return True


def _uninstall_standalone(
    root: Path,
    rel_path: str,
    console: Console,
) -> bool:
    """Remove a standalone rules file."""
    target = root / rel_path
    if not target.exists():
        console.print(f"  [yellow]skip[/] {target} (not found)")
        return False
    target.unlink()
    console.print(f"  [green]deleted[/] {target}")
    return True


# ── Hook dispatch ─────────────────────────────────────────────


def _install_hooks_for_platform(
    root: Path,
    cfg: PlatformConfig,
    console: Console,
) -> None:
    """Install platform-specific hooks based on hook_type."""
    if cfg.hook_type == "claude_pretool":
        _install_json_hook(
            root / ".claude" / "settings.json",
            _CLAUDE_PRETOOL_HOOK, "PreToolUse", console,
        )
    elif cfg.hook_type == "codex_pretool":
        _install_json_hook(
            root / ".codex" / "hooks.json",
            _CODEX_PRETOOL_HOOK, "PreToolUse", console,
        )
    elif cfg.hook_type == "gemini_beforetool":
        _install_json_hook(
            root / ".gemini" / "settings.json",
            _GEMINI_BEFORETOOL_HOOK, "BeforeTool", console,
        )
    # opencode_plugin is handled separately in install_platform


def _uninstall_hooks_for_platform(
    root: Path,
    cfg: PlatformConfig,
    console: Console,
) -> None:
    """Remove platform-specific hooks based on hook_type."""
    if cfg.hook_type == "claude_pretool":
        _uninstall_json_hook(
            root / ".claude" / "settings.json", "PreToolUse", console,
        )
    elif cfg.hook_type == "codex_pretool":
        _uninstall_json_hook(
            root / ".codex" / "hooks.json", "PreToolUse", console,
        )
    elif cfg.hook_type == "gemini_beforetool":
        _uninstall_json_hook(
            root / ".gemini" / "settings.json", "BeforeTool", console,
        )


# ── Public API ────────────────────────────────────────────────


def install_platform(
    root: Path,
    name: str,
    *,
    template_vars: dict[str, str],
    console: Console,
) -> str:
    """Install codegraph for a single platform. Returns a status message."""
    cfg = PLATFORMS.get(name)
    if cfg is None:
        return f"[red]unknown platform: {name}[/]"

    actions: list[str] = []

    # Copilot has no rules file — just a reminder
    if name == "copilot":
        actions.append("reminder: configure codegraph MCP server in Copilot settings")
        console.print(f"  [cyan]info[/] {cfg.display_name}: no rules file; use the MCP server instead")
        return f"{cfg.display_name}: " + "; ".join(actions)

    # Rules file (append section to shared file)
    if cfg.rules_file and cfg.rules_template:
        snippet = _render(cfg.rules_template, template_vars)
        target = root / cfg.rules_file
        if _append_section(target, snippet, cfg.rules_marker, console):
            actions.append(f"rules → {cfg.rules_file}")

    # Standalone rules files
    if cfg.standalone_rules:
        for rel_path, tmpl in cfg.standalone_rules.items():
            if _install_standalone(root, rel_path, tmpl, template_vars, console):
                actions.append(f"rules → {rel_path}")

    # Hooks
    if cfg.hook_type == "opencode_plugin":
        _install_opencode_plugin(root, template_vars, console)
        actions.append("plugin → .opencode/plugins/codegraph.js")
    elif cfg.hook_type:
        _install_hooks_for_platform(root, cfg, console)
        actions.append(f"hook → {cfg.hook_type}")

    # Record this platform in the manifest (even when idempotent)
    installed = _read_manifest(root)
    installed.add(name)
    _write_manifest(root, installed)

    if not actions:
        return f"{cfg.display_name}: already installed"
    return f"{cfg.display_name}: " + "; ".join(actions)


def uninstall_platform(
    root: Path,
    name: str,
    *,
    console: Console,
) -> str:
    """Remove codegraph from a single platform. Returns a status message."""
    cfg = PLATFORMS.get(name)
    if cfg is None:
        return f"[red]unknown platform: {name}[/]"

    actions: list[str] = []

    if name == "copilot":
        return f"{cfg.display_name}: nothing to remove (no files installed)"

    # Rules file (remove section from shared file)
    installed = _read_manifest(root)
    if cfg.rules_file:
        target = root / cfg.rules_file
        if _other_installed_share_section(name, installed):
            console.print(f"  [yellow]skip[/] {target} (shared with other platforms)")
        elif _remove_section(target, cfg.rules_marker, console):
            actions.append(f"rules ← {cfg.rules_file}")

    # Standalone rules files
    if cfg.standalone_rules:
        for rel_path in cfg.standalone_rules:
            if _uninstall_standalone(root, rel_path, console):
                actions.append(f"rules ← {rel_path}")

    # Hooks
    if cfg.hook_type == "opencode_plugin":
        _uninstall_opencode_plugin(root, console)
        actions.append("plugin ← .opencode/plugins/codegraph.js")
    elif cfg.hook_type:
        _uninstall_hooks_for_platform(root, cfg, console)
        actions.append(f"hook ← {cfg.hook_type}")

    # Remove this platform from the manifest
    installed.discard(name)
    _write_manifest(root, installed)

    if not actions:
        return f"{cfg.display_name}: nothing to remove"
    return f"{cfg.display_name}: " + "; ".join(actions)


def install_all(
    root: Path,
    *,
    template_vars: dict[str, str],
    console: Console,
) -> list[str]:
    """Auto-detect platforms and install for each. Returns status messages."""
    results: list[str] = []
    for name, cfg in PLATFORMS.items():
        if cfg.detect_hint is None:
            continue
        hint_path = root / cfg.detect_hint
        if hint_path.exists():
            result = install_platform(
                root, name, template_vars=template_vars, console=console,
            )
            results.append(result)
    if not results:
        console.print("  [dim]no AI platforms detected[/]")
    return results
