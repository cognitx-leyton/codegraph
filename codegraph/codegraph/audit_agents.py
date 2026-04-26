"""Registry of coding agents that ``codegraph audit`` can launch in headless mode.

Distinct from :mod:`codegraph.platforms` (which lists 14 install targets,
including IDE-only platforms like Kiro and Antigravity that have no headless
CLI mode). The audit registry is the subset that can be launched as a
subprocess with a prompt file and produce output without a human babysitting
each tool call.

Each :class:`AuditAgent` describes:

- ``binary`` — what to look for on PATH via :func:`shutil.which`.
- ``permission_bypass_args`` — flag(s) that suppress per-tool-call approval
  prompts. The user explicitly opted into bypass by running ``codegraph audit``;
  the ``--no-bypass`` CLI flag lets them opt back into interactive mode.
- ``headless_args`` — flag(s) that put the agent in non-interactive mode and
  make it accept the prompt as a positional argument (or via ``--prompt-file``).
  Always include the prompt-file token ``$PROMPT_FILE`` as a placeholder.
- ``unsafe_extra`` — opt-in extra flag for agents that have a "really bypass
  everything" mode separate from their normal headless flag. Currently only
  ``codex`` (``--full-auto`` is sandboxed; ``--dangerously-bypass-...`` skips
  the sandbox). Surfaces as ``codegraph audit --unsafe``.
- ``fallback_skill_path`` — for agents with no headless CLI (just Cursor today),
  the relative path of a skill / rules file we write so the user can invoke
  the audit interactively from inside the IDE.

The list intentionally does NOT include vscode, kiro, antigravity, copilot,
hermes, opencode-plugin-only, or trae — those have no documented headless
CLI as of 2026-04. Adding one is a one-entry change.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import Optional

# Sentinel placeholder substituted by audit.py at launch time.
PROMPT_FILE_TOKEN = "$PROMPT_FILE"


@dataclass(frozen=True)
class AuditAgent:
    """Describes how to launch one coding agent in headless audit mode."""

    name: str
    display_name: str
    binary: str
    headless_args: tuple[str, ...] = ()
    permission_bypass_args: tuple[str, ...] = ()
    unsafe_extra: tuple[str, ...] = ()
    fallback_skill_path: Optional[str] = None
    notes: str = ""

    def is_installed(self) -> bool:
        """True when the agent's binary is on PATH."""
        return shutil.which(self.binary) is not None

    def build_argv(
        self,
        prompt_file: str,
        bypass: bool = True,
        unsafe: bool = False,
    ) -> list[str]:
        """Return the argv list to launch this agent on *prompt_file*.

        Substitutes :data:`PROMPT_FILE_TOKEN` in ``headless_args``. When
        ``bypass`` is False, ``permission_bypass_args`` is omitted — the user
        will be prompted by the agent for each tool call. When ``unsafe`` is
        True, ``unsafe_extra`` flags are appended (currently only meaningful
        for codex's ``--dangerously-bypass-approvals-and-sandbox``).
        """
        argv: list[str] = [self.binary]
        if bypass:
            argv.extend(self.permission_bypass_args)
        if unsafe:
            argv.extend(self.unsafe_extra)
        for arg in self.headless_args:
            argv.append(arg.replace(PROMPT_FILE_TOKEN, prompt_file))
        # If the headless template doesn't reference the prompt file, append
        # it as a final positional. Covers the ``claude --print`` and
        # ``aider --message-file`` shapes uniformly.
        if not any(PROMPT_FILE_TOKEN in arg for arg in self.headless_args):
            argv.append(prompt_file)
        return argv


# ── Registry ────────────────────────────────────────────────────────


AUDIT_AGENTS: dict[str, AuditAgent] = {
    "claude": AuditAgent(
        name="claude",
        display_name="Claude Code",
        binary="claude",
        # `--print` exits after the first response. Combined with
        # `--output-format=stream-json` we can stream tool-use events back to
        # the user during the run. Prompt is read from stdin via shell pipe
        # in audit.py, but Claude also accepts a prompt as a positional arg.
        headless_args=("--print", "--output-format=stream-json", "--verbose"),
        permission_bypass_args=("--dangerously-skip-permissions",),
        notes="Reads prompt as final positional arg. Streams JSON events for live progress.",
    ),
    "codex": AuditAgent(
        name="codex",
        display_name="OpenAI Codex CLI",
        binary="codex",
        headless_args=("exec",),
        # --full-auto is the sandboxed bypass. The truly-no-guardrails version
        # is gated behind --unsafe at the codegraph CLI level.
        permission_bypass_args=("--full-auto",),
        unsafe_extra=("--dangerously-bypass-approvals-and-sandbox",),
        notes="Use --unsafe to drop the sandbox; default keeps it on.",
    ),
    "gemini": AuditAgent(
        name="gemini",
        display_name="Gemini CLI",
        binary="gemini",
        headless_args=("--prompt-file", PROMPT_FILE_TOKEN),
        permission_bypass_args=("--yolo",),
        notes="--yolo accepts every tool call without prompting.",
    ),
    "aider": AuditAgent(
        name="aider",
        display_name="Aider",
        binary="aider",
        # --no-auto-commits ensures the audit can't accidentally commit code.
        # Even though the audit prompt forbids writes, defence in depth.
        headless_args=("--message-file", PROMPT_FILE_TOKEN, "--no-auto-commits"),
        permission_bypass_args=("--yes-always",),
        notes="Default-yes mode; --no-auto-commits prevents accidental commits.",
    ),
    "opencode": AuditAgent(
        name="opencode",
        display_name="OpenCode",
        binary="opencode",
        headless_args=("run", "--prompt-file", PROMPT_FILE_TOKEN),
        permission_bypass_args=("--auto-approve",),
        notes="Verify --auto-approve flag name with `opencode run --help` if launch fails.",
    ),
    "droid": AuditAgent(
        name="droid",
        display_name="Factory Droid",
        binary="droid",
        headless_args=("run", "--prompt-file", PROMPT_FILE_TOKEN),
        permission_bypass_args=("--yes",),
        notes="Factory droid headless mode.",
    ),
    "cursor": AuditAgent(
        name="cursor",
        display_name="Cursor",
        binary="cursor",
        # Cursor has no documented headless CLI as of 2026-04. The audit
        # writes a .cursor/rules entry instead and prints instructions; the
        # build_argv path is unused (callers check fallback_skill_path first).
        headless_args=(),
        permission_bypass_args=(),
        fallback_skill_path=".cursor/rules/codegraph-audit.mdc",
        notes="No headless mode — audit writes a Cursor rules file and prints instructions.",
    ),
}


def detected_agents() -> list[AuditAgent]:
    """All registered agents whose binary is on PATH right now."""
    return [a for a in AUDIT_AGENTS.values() if a.is_installed()]


def get_agent(name: str) -> Optional[AuditAgent]:
    """Lookup by short name; returns ``None`` if unknown."""
    return AUDIT_AGENTS.get(name)
