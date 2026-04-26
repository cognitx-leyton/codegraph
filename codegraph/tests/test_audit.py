"""Tests for :mod:`codegraph.audit` — agent-driven extraction self-check.

Network-free: every subprocess call (`codegraph query`, agent launch,
`gh issue create`) is monkeypatched out. Only the prompt assembly and
report parsing logic actually run.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from rich.console import Console

from codegraph import audit, audit_agents


def _quiet() -> Console:
    return Console(quiet=True)


# ── audit_agents registry ───────────────────────────────────────────


def test_registry_has_seven_agents() -> None:
    assert set(audit_agents.AUDIT_AGENTS.keys()) == {
        "claude", "codex", "gemini", "aider", "opencode", "droid", "cursor",
    }


def test_get_agent_known_and_unknown() -> None:
    assert audit_agents.get_agent("claude") is audit_agents.AUDIT_AGENTS["claude"]
    assert audit_agents.get_agent("nonsense") is None


def test_build_argv_includes_bypass_by_default() -> None:
    a = audit_agents.AUDIT_AGENTS["claude"]
    argv = a.build_argv("/tmp/p.md", bypass=True, unsafe=False)
    assert "--dangerously-skip-permissions" in argv
    assert argv[-1] == "/tmp/p.md"


def test_build_argv_omits_bypass_when_disabled() -> None:
    a = audit_agents.AUDIT_AGENTS["claude"]
    argv = a.build_argv("/tmp/p.md", bypass=False, unsafe=False)
    assert "--dangerously-skip-permissions" not in argv


def test_build_argv_substitutes_prompt_token() -> None:
    a = audit_agents.AUDIT_AGENTS["gemini"]
    argv = a.build_argv("/tmp/x.md", bypass=True)
    assert "/tmp/x.md" in argv
    # The token shouldn't survive substitution.
    assert audit_agents.PROMPT_FILE_TOKEN not in argv


def test_build_argv_unsafe_appends_codex_extra() -> None:
    a = audit_agents.AUDIT_AGENTS["codex"]
    argv = a.build_argv("/tmp/p.md", bypass=True, unsafe=True)
    assert "--dangerously-bypass-approvals-and-sandbox" in argv


def test_cursor_has_fallback_skill_path() -> None:
    a = audit_agents.AUDIT_AGENTS["cursor"]
    assert a.fallback_skill_path == ".cursor/rules/codegraph-audit.mdc"


# ── Prompt assembly ────────────────────────────────────────────────


def test_filter_inventory_keeps_baseline_when_no_frameworks_detected(monkeypatch) -> None:
    """No frameworks but Python files exist → baseline section kept."""
    out = audit._filter_inventory(set(), set())
    # No languages → both inventories included in full.
    assert "## Python" in out
    assert "## TypeScript / TSX" in out


def test_filter_inventory_python_baseline_only_when_no_py_framework() -> None:
    """Python files indexed but no FastAPI/Flask/Django → baseline-only Python section."""
    out = audit._filter_inventory(set(), {"py"})
    assert "## Python" in out
    assert "## TypeScript / TSX" not in out
    assert "Python (plain)" in out
    # Should NOT include framework-specific sections.
    assert "FastAPI" not in out
    assert "Django" not in out


def test_filter_inventory_includes_detected_python_framework() -> None:
    """FastAPI detected → FastAPI section included alongside the baseline."""
    out = audit._filter_inventory({"FastAPI"}, {"py"})
    assert "Python (plain)" in out
    assert "FastAPI" in out
    # Flask shouldn't appear (not detected).
    assert "Flask" not in out


def test_filter_inventory_includes_detected_ts_framework() -> None:
    out = audit._filter_inventory({"NestJS"}, {"ts"})
    assert "TypeScript" in out
    assert "NestJS" in out
    assert "Python" not in out


def test_filter_sections_keeps_typeorm_when_ts_present() -> None:
    """SQLAlchemy/TypeORM/GraphQL are dependency-driven, not FrameworkType-driven."""
    out = audit._filter_inventory({"NestJS"}, {"ts"})
    # TypeORM section should appear because it's in the always-keep alias set.
    assert "TypeORM" in out


def test_build_prompt_substitutes_all_placeholders(monkeypatch, tmp_path) -> None:
    """Every $VAR in the template must get substituted."""
    monkeypatch.setattr(audit, "_query_graph_json", lambda uri, c, console: [])
    agent = audit_agents.AUDIT_AGENTS["claude"]
    prompt = audit.build_prompt(tmp_path, agent, "bolt://x", _quiet())
    # No leftover placeholders.
    leftovers = re.findall(r"\$[A-Z_]+", prompt)
    assert leftovers == [], f"Unsubstituted placeholders: {leftovers}"
    # Spot-check substitutions.
    assert str(tmp_path) in prompt
    assert "claude" in prompt
    assert "bolt://x" in prompt


# ── Report parsing ─────────────────────────────────────────────────


def _write_report(p: Path, body: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_parse_report_returns_zero_for_no_issues(tmp_path) -> None:
    rep = _write_report(tmp_path / "r.md", "## Summary\n\nNo extraction issues found.\n")
    n, findings = audit.parse_report(rep)
    assert n == 0
    assert findings == []


def test_parse_report_extracts_issue_blocks(tmp_path) -> None:
    body = """\
## Summary

- Findings: 2

## Issue 1

**Category:** MISSING_NODE
**Severity:** high
**Construct:** NestJS @Controller

Source evidence: foo.ts:1

## Issue 2

**Category:** WRONG_PROPERTY
**Severity:** low
**Construct:** SQLAlchemy nullable flag
"""
    rep = _write_report(tmp_path / "r.md", body)
    n, findings = audit.parse_report(rep)
    assert n == 2
    assert findings[0].category == "MISSING_NODE"
    assert findings[0].severity == "high"
    assert findings[0].construct == "NestJS @Controller"
    assert findings[1].category == "WRONG_PROPERTY"
    assert findings[1].severity == "low"


def test_parse_report_handles_missing_file(tmp_path) -> None:
    n, findings = audit.parse_report(tmp_path / "nonexistent.md")
    assert n == 0
    assert findings == []


def test_parse_report_strips_pipe_alternatives_from_category(tmp_path) -> None:
    """Agents sometimes paste the schema literally; we take the first option."""
    body = """\
## Issue 1

**Category:** MISSING_EDGE | WRONG_PROPERTY
**Severity:** medium
"""
    rep = _write_report(tmp_path / "r.md", body)
    n, findings = audit.parse_report(rep)
    assert findings[0].category == "MISSING_EDGE"


# ── Agent selection (no real binary needed) ────────────────────────


def test_choose_agent_returns_named(monkeypatch) -> None:
    a = audit_agents.AUDIT_AGENTS["claude"]
    monkeypatch.setattr(audit_agents.AuditAgent, "is_installed", lambda self: True)
    chosen = audit.choose_agent(_quiet(), "claude", yes=True)
    assert chosen is a


def test_choose_agent_unknown_exits(monkeypatch) -> None:
    monkeypatch.setattr(audit_agents.AuditAgent, "is_installed", lambda self: True)
    with pytest.raises(SystemExit):
        audit.choose_agent(_quiet(), "nonsense-agent", yes=True)


def test_choose_agent_picks_only_detected_in_yes_mode(monkeypatch) -> None:
    """When only one agent is on PATH, --yes mode skips the prompt."""
    def fake_installed(self):
        return self.name == "gemini"
    monkeypatch.setattr(audit_agents.AuditAgent, "is_installed", fake_installed)
    chosen = audit.choose_agent(_quiet(), None, yes=True)
    assert chosen.name == "gemini"


def test_choose_agent_no_detected_exits(monkeypatch) -> None:
    monkeypatch.setattr(audit_agents.AuditAgent, "is_installed", lambda self: False)
    with pytest.raises(SystemExit):
        audit.choose_agent(_quiet(), None, yes=True)


# ── Lock verification ─────────────────────────────────────────────


def test_verify_lock_or_die_passes_on_clean_install(monkeypatch) -> None:
    """No tampering → no exit, no print."""
    audit.verify_lock_or_die(_quiet())


def test_verify_lock_or_die_recompute_path_calls_update(monkeypatch) -> None:
    """--recompute-lock skips the integrity check and just rewrites."""
    called = {"updated": False}
    def fake_update():
        called["updated"] = True
        return 0
    monkeypatch.setattr(audit, "_update_lock", fake_update)
    audit.verify_lock_or_die(_quiet(), recompute=True)
    assert called["updated"]


def test_verify_lock_or_die_dies_on_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(audit, "_check_lock", lambda: 1)
    with pytest.raises(SystemExit):
        audit.verify_lock_or_die(_quiet())
