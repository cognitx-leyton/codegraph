# Platform integrations

Reference for `codegraph install <platform>` and `codegraph uninstall <platform>`. These two Typer sub-apps wire codegraph into 14 AI coding assistants by writing rules files and tool-call hooks into the repo, then tracking what was installed in `.codegraph/platforms.json` so partial uninstalls can preserve shared content.

For the post-`init` workflow ("I just ran `codegraph init`, now how do I add Codex too?") see `docs/init.md` § "Adding more AI platforms after init". This doc is the depth: what gets written, where, and why.

## 1. Overview

`codegraph install <platform>` performs three operations, each conditional on the platform's config:

1. **Write a rules file.** Either a new section appended to a shared markdown file (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.github/copilot-instructions.md`) under a section marker like `## codegraph`, or a standalone file at a platform-specific path (`.cursor/rules/codegraph.mdc`, `.kiro/steering/codegraph.md`, `.agents/rules/codegraph.md`).
2. **Install a tool-call hook.** A small JSON entry in the platform's settings file that runs `cat codegraph-out/GRAPH_REPORT.md | head -50` before file-reading tool calls (`Glob`, `Grep`, `read_file`, `list_directory`). Three platforms get this: Claude Code, Codex, and Gemini CLI. OpenCode gets a JS plugin that does the same thing through its plugin API.
3. **Track the install.** Append the platform name to `installed` in `.codegraph/platforms.json`. This is what makes `codegraph uninstall` selective — when a section in `AGENTS.md` is shared by Codex and Aider, uninstalling Codex alone leaves the section intact.

Install is idempotent. Re-running `codegraph install claude` on a repo that already has the section is a no-op; re-running it after upgrading codegraph re-renders the section template with current values (ports, package paths). The manifest is updated either way.

| Platform | Subcommand | Rules file | Hook target |
|---|---|---|---|
| Claude Code | `claude` | `CLAUDE.md` (section) | `.claude/settings.json` `PreToolUse` |
| Codex | `codex` | `AGENTS.md` (section) | `.codex/hooks.json` `PreToolUse` |
| OpenCode | `opencode` | `AGENTS.md` (section) | `.opencode/plugins/codegraph.js` |
| Cursor | `cursor` | `.cursor/rules/codegraph.mdc` (standalone) | — |
| Gemini CLI | `gemini` | `GEMINI.md` (section) | `.gemini/settings.json` `BeforeTool` |
| GitHub Copilot CLI | `copilot` | — | — |
| VS Code Copilot Chat | `vscode` | `.github/copilot-instructions.md` (section) | — |
| Aider | `aider` | `AGENTS.md` (section) | — |
| OpenClaw | `claw` | `AGENTS.md` (section) | — |
| Factory Droid | `droid` | `AGENTS.md` (section) | — |
| Trae | `trae` | `AGENTS.md` (section) | — |
| Kiro IDE | `kiro` | `.kiro/steering/codegraph.md` (standalone) | — |
| Google Antigravity | `antigravity` | `.agents/rules/codegraph.md` + `.agents/workflows/codegraph.md` (standalone, two files) | — |
| Hermes | `hermes` | `AGENTS.md` (section) | — |

`codegraph install --all` walks every platform's `detect_hint` directory (e.g. `.claude/`, `.cursor/`, `.codex/`) and installs anything that already has a config dir on disk. If you've never used a given agent in this repo, `--all` skips it. The Copilot CLI subcommand is unique: it writes nothing — it just prints a reminder that codegraph should be added as an MCP server in Copilot's own settings.

## 2. Per-platform reference

### Claude Code (`codegraph install claude`)

- **Rules file:** Section appended to `CLAUDE.md` under the marker `## Using the codegraph knowledge graph`. If the file already exists and contains other content, codegraph appends after a blank line, never clobbering. If the marker is already present, the install is a no-op.
- **Template:** `codegraph/templates/claude-md-snippet.md`. Resolves `$NEO4J_BOLT_PORT`, `$PACKAGE_PATHS_FLAGS`, `$CONTAINER_NAME`. Documents `/graph`, `/graph-refresh`, `/blast-radius`, `/dead-code`, `/who-owns`, `/trace-endpoint`, `/arch-check`.
- **Hook:** A `PreToolUse` entry is written into `.claude/settings.json` that runs `cat codegraph-out/GRAPH_REPORT.md 2>/dev/null | head -50 || true` before any `Glob` or `Grep` tool call. The hook is matched on `Glob|Grep`. Existing non-codegraph hooks in the file are preserved. If `.claude/settings.json` doesn't exist, it's created with just the codegraph hook.
- **Detection hint for `--all`:** `.claude/`.

Sample of the `CLAUDE.md` section that gets written (variables resolved for a repo named `myapp` with one package `src/`):

```markdown
## Using the codegraph knowledge graph

This repo is indexed into a local Neo4j via **codegraph** (`pipx install cognitx-codegraph`). Run `codegraph init` if you haven't yet. The graph is reachable at `bolt://localhost:7687`. Claude Code has slash commands wired to it — use them.

### `/graph <cypher>` — read-only Cypher queries
…
```

### Codex (`codegraph install codex`)

- **Rules file:** Section appended to `AGENTS.md` under the marker `## codegraph`. Shared with Aider, OpenClaw, Factory Droid, Trae, Hermes, OpenCode — see "Shared `AGENTS.md` section" below.
- **Template:** `codegraph/templates/platforms/rules-agents.md`. Resolves `$NEO4J_BOLT_PORT`.
- **Hook:** `PreToolUse` entry in `.codex/hooks.json`, same `Glob|Grep` matcher and same `cat … GRAPH_REPORT.md` command as the Claude hook.
- **Detection hint for `--all`:** `.codex/`.

### OpenCode (`codegraph install opencode`)

- **Rules file:** Same `AGENTS.md` section as Codex.
- **Plugin:** `codegraph/templates/platforms/hook-opencode.js` is rendered into `.opencode/plugins/codegraph.js` (with `$NEO4J_BOLT_PORT` substituted). The plugin name is `codegraph`, version `1.0.0`, and it pushes a system message before `read_file`, `list_directory`, `glob`, `grep` tool calls.
- **Plugin registration:** `.opencode/plugins/codegraph.js` is registered as `plugins/codegraph.js` in `.opencode/opencode.json` under the `plugins` array. Existing plugins in the array are preserved.
- **Detection hint for `--all`:** `.opencode/`.

### Cursor (`codegraph install cursor`)

- **Rules file:** Standalone file at `.cursor/rules/codegraph.mdc`. Cursor reads every `.mdc` under `.cursor/rules/` automatically.
- **Template:** `codegraph/templates/platforms/rules-cursor.mdc`. Includes Cursor frontmatter (`description`, `alwaysApply: true`) so the rule applies to every conversation.
- **Hook:** None.
- **Detection hint for `--all`:** `.cursor/`.

### Gemini CLI (`codegraph install gemini`)

- **Rules file:** Section appended to `GEMINI.md` under the marker `## codegraph`.
- **Template:** `codegraph/templates/platforms/rules-gemini.md`. Resolves `$NEO4J_BOLT_PORT`. Same content as `rules-agents.md` modulo the heading.
- **Hook:** `BeforeTool` entry in `.gemini/settings.json`. The matcher is Gemini-specific (`read_file|list_directory`) since Gemini CLI's tool names differ from Claude's.
- **Detection hint for `--all`:** `.gemini/`.

### GitHub Copilot CLI (`codegraph install copilot`)

- **Rules file:** None. Copilot CLI does not yet have a project-level rules file.
- **Hook:** None.
- **What it actually does:** Prints `reminder: configure codegraph MCP server in Copilot settings` and adds the platform name to the manifest. Codegraph itself ships an MCP server (see `docs/mcp.md`); Copilot users wire it up through Copilot's own settings UI, not via codegraph.
- **Detection hint for `--all`:** `.copilot/`.

### VS Code Copilot Chat (`codegraph install vscode`)

- **Rules file:** Section appended to `.github/copilot-instructions.md` under the marker `## codegraph`. VS Code Copilot reads this file by convention.
- **Template:** `codegraph/templates/platforms/rules-vscode.md`. Same content as the generic `rules-agents.md` template; named separately so it can drift if VS Code's expectations change.
- **Hook:** None.
- **Detection hint for `--all`:** `.github/copilot-instructions.md` (the file itself, not a directory).

### Kiro IDE (`codegraph install kiro`)

- **Rules file:** Standalone file at `.kiro/steering/codegraph.md`. Kiro's "steering" directory is the equivalent of Cursor's rules.
- **Template:** `codegraph/templates/platforms/rules-kiro.md`. Includes Kiro frontmatter `inclusion: always`.
- **Hook:** None.
- **Detection hint for `--all`:** `.kiro/`.

### Google Antigravity (`codegraph install antigravity`)

- **Rules file:** Two standalone files. Antigravity is the only platform that writes both a rules file and a workflow file:
  - `.agents/rules/codegraph.md` — the same rules content as the other AGENTS.md-equivalent platforms.
  - `.agents/workflows/codegraph.md` — a numbered four-step workflow ("Before structural edits, check blast radius… After code changes, update the graph… Verify conformance… Prefer Cypher over grep").
- **Templates:** `codegraph/templates/platforms/rules-antigravity.md` and `codegraph/templates/platforms/rules-antigravity-workflow.md`.
- **Hook:** None.
- **Detection hint for `--all`:** `.agents/`.

### Shared `AGENTS.md` section: Aider, OpenClaw, Factory Droid, Trae, Hermes (and Codex, OpenCode)

Seven platforms write the exact same `## codegraph` section to `AGENTS.md`:

| Subcommand | Display name | Detect hint |
|---|---|---|
| `aider` | Aider | `.aider/` |
| `claw` | OpenClaw | `.openclaw/` |
| `droid` | Factory Droid | `.factory/` |
| `trae` | Trae | `.trae/` |
| `kiro` (no — see above; Kiro is standalone) | — | — |
| `hermes` | Hermes | `.hermes/` |
| `codex` | Codex | `.codex/` |
| `opencode` | OpenCode | `.opencode/` |

All seven use `codegraph/templates/platforms/rules-agents.md` and the marker `## codegraph`. The content is short (10 lines): one paragraph stating the bolt URL, then four bullets ("before answering architecture questions, run `codegraph query`…", "use `arch-check` for conformance…", "after structural changes, run `codegraph index . --since HEAD~1`…", "prefer Cypher over grep"). Codex and OpenCode add a hook on top of the shared section; the others install the section only.

Because the section is shared, `codegraph uninstall codex` does **not** remove the section from `AGENTS.md` if Aider (or any of the others) is still installed — see § "Shared sections and uninstall" below.

## 3. Template variables

Every template runs through `string.Template.safe_substitute` with the dict built by `_build_install_vars` in `cli.py`, which delegates to `build_template_vars` in `init.py`. Both `codegraph init` and `codegraph install` use the same builder, so values are consistent across init-time and post-init installs.

| Variable | Source | Example |
|---|---|---|
| `$NEO4J_BOLT_PORT` | `CODEGRAPH_NEO4J_BOLT_PORT` env var, else `7687` (the default in `init._DEFAULT_BOLT_PORT`). | `7687` |
| `$NEO4J_HTTP_PORT` | `init._DEFAULT_HTTP_PORT`, currently always `7474`. Install does not currently override it from the environment. | `7474` |
| `$PACKAGE_PATHS_FLAGS` | `" ".join(f"-p {p}" for p in config.packages)`. Empty string if no packages are configured. | `-p src/server -p src/web` |
| `$CONTAINER_NAME` | `derive_container_name(root)` in `init.py`: `cognitx-codegraph-<sanitized-dir>-<8-hex-of-sha1(abspath)>`. Deterministic per absolute path, so two clones of the same repo in different directories get distinct container names. | `cognitx-codegraph-myapp-3a8f1d2c` |
| `$DEFAULT_PACKAGE_PREFIX` | First configured package + `/`, or empty string when the first package is `.`. Used in slash-command templates that grep within the primary package. | `src/server/` |
| `$CROSS_PAIRS_TOML` | Cross-package boundary policy entries for `.arch-policies.toml`. Always empty during `install` (cross-pairs are gathered only by the interactive `init` flow); kept in the dict so templates that reference it don't break. | `""` |
| `$PIPX_VERSION` | Hard-coded `"0.2.0"` in `_build_install_vars`. Used in CI workflow templates; not referenced by any platform rules file today. | `0.2.0` |

`safe_substitute` means an unrecognised `$VAR` in a template passes through unchanged rather than raising — useful for templates that contain literal `$` characters in shell snippets.

## 4. Manifest and uninstall

### `.codegraph/platforms.json`

A single-key JSON document tracking installed platforms. Format:

```json
{
  "installed": ["claude", "codex"]
}
```

Written every time `install_platform` succeeds. The list is sorted on write. The file is created on the first install and removed when the last platform is uninstalled (so you don't end up with an empty `.codegraph/` directory).

### Section markers

Shared markdown files use the section heading itself as the marker:

- `CLAUDE.md` → `## Using the codegraph knowledge graph`
- `AGENTS.md` → `## codegraph`
- `GEMINI.md` → `## codegraph`
- `.github/copilot-instructions.md` → `## codegraph`

`_remove_section` in `platforms.py` strips from the marker heading down to the next `## ` heading or end-of-file. Anything above the marker and anything after the next sibling heading is preserved untouched. If the file becomes empty (codegraph was the only content), the file is deleted.

The current implementation does not use sentinel comments like `<!-- codegraph:begin -->` — those exist for a different feature (the `codegraph stats --update` placeholder substitution in `cli.py`) and aren't part of platform installs. Editing inside the codegraph section by hand is therefore risky: an uninstall will treat from the heading to the next `## ` as codegraph-owned and remove it.

### Shared sections and uninstall

Before removing a section, `_other_installed_share_section` checks whether any other entry in the manifest points at the same `(rules_file, rules_marker)` pair. If so, the file is left alone and the console prints `skip … (shared with other platforms)`. The manifest entry for the uninstalled platform is still removed; only the file is preserved. A subsequent uninstall of the last sharer will then remove the section.

Standalone files (`.cursor/rules/codegraph.mdc`, `.kiro/steering/codegraph.md`, `.agents/rules/codegraph.md`, `.agents/workflows/codegraph.md`, `.opencode/plugins/codegraph.js`) are never shared — each is owned by exactly one platform — so uninstall always deletes them.

### Hooks on uninstall

`_uninstall_json_hook` walks the JSON settings file's `hooks` array for the relevant event (`PreToolUse` for Claude/Codex, `BeforeTool` for Gemini), removes any entry whose stringified form contains `codegraph`, and rewrites the file. If that empties the event array, the event key is dropped; if that empties the `hooks` object, the whole key is dropped. Other hooks the user has configured by hand are preserved.

For OpenCode, `_uninstall_opencode_plugin` deletes `.opencode/plugins/codegraph.js` and removes `plugins/codegraph.js` from the `plugins` array in `.opencode/opencode.json`.

### `codegraph uninstall --all`

Not currently implemented as a top-level flag — the install sub-app has a `--all` callback, the uninstall sub-app does not. To remove everything, iterate the platforms in the manifest and run `codegraph uninstall <name>` for each.

## 5. Common workflows

### "I use Claude Code primarily, but also want Codex"

```bash
codegraph install claude
codegraph install codex
```

Result: `CLAUDE.md` gets the rich Claude section, `AGENTS.md` gets the shared section, `.claude/settings.json` and `.codex/hooks.json` both get tool-call hooks, and `.codegraph/platforms.json` lists both.

### "I'm switching from Cursor to Claude Code"

```bash
codegraph uninstall cursor
codegraph install claude
```

`uninstall cursor` deletes `.cursor/rules/codegraph.mdc` and removes `cursor` from the manifest. `install claude` then writes `CLAUDE.md` and the `.claude/settings.json` hook.

### "I want everything that's already configured in this repo"

```bash
codegraph install --all
```

For each platform, `install_all` checks whether the platform's `detect_hint` (e.g. `.cursor/`, `.codex/`, `.gemini/`) exists. If yes, it installs that platform. If no `detect_hint` matches anything in the repo, the command prints `no AI platforms detected` and exits.

### "I added Aider to a repo that already has Codex installed"

```bash
codegraph install aider
```

The `## codegraph` section in `AGENTS.md` is already present (Codex put it there). The marker check in `_append_section` short-circuits and prints `skip AGENTS.md (already contains codegraph section)`. Aider gets added to the manifest.

### "I want to remove everything codegraph wrote"

```bash
for p in $(jq -r '.installed[]' .codegraph/platforms.json); do
  codegraph uninstall "$p"
done
```

When the last platform is uninstalled, `.codegraph/platforms.json` is removed, and `.codegraph/` is rmdir'd if it's empty.

## 6. Troubleshooting

**"Hook didn't fire / agent isn't loading the section."**
Most agents read these files at session start. Restart the agent after install. For Claude Code: close the conversation and start a new one (`/clear` may not be enough). For Cursor: reload the workspace. For VS Code Copilot Chat: reload window.

**"Rules file conflicts with my own content."**
Codegraph only writes inside the section bounded by the marker heading and the next `## ` heading. Anything above the marker stays intact, anything after the next sibling heading stays intact. To customise: edit between those bounds, but be aware that the next `codegraph install` (which is idempotent only when the marker is present and unchanged) will skip the file rather than overwriting your edits — re-running install does not re-render the section. To force a re-render, manually delete the section first.

**"Container port already in use" / Bolt URL in the rules file is wrong.**
The `$NEO4J_BOLT_PORT` baked into the rules file comes from `CODEGRAPH_NEO4J_BOLT_PORT` (env var) or `init._DEFAULT_BOLT_PORT` (currently `7687`). To bind to a different port, re-run `codegraph init --bolt-port 7690 --http-port 7475 --force` first; the new port is then propagated to subsequent `install` runs. For an already-installed platform, manually delete the codegraph section and re-run `codegraph install <platform>`.

**"Manifest is out of sync with disk."**
If you hand-edited `CLAUDE.md` to remove the section but the manifest still lists `claude`, run `codegraph install claude` to re-write the section, then `codegraph uninstall claude` to remove both the section and the manifest entry. There is no `codegraph install --reset` today.

**"`codegraph install --all` did nothing."**
`install_all` only fires for platforms whose `detect_hint` exists on disk. If you've never opened the repo in any agent, no `.claude/`, `.cursor/`, `.gemini/`, etc. exist yet. Either open the agent once to create its config dir, or install the specific platform by name (e.g. `codegraph install claude`).

**"OpenCode plugin isn't loading."**
Check that `.opencode/plugins/codegraph.js` exists and that `.opencode/opencode.json` has `"plugins": ["plugins/codegraph.js"]`. Both are written by `install opencode`. If only one is present (e.g. the `.opencode/opencode.json` was manually rewritten), re-run `codegraph install opencode`.

**"Copilot CLI install didn't write anything."**
That's expected. `copilot` is the one platform with no rules file and no hook. The install just prints a reminder to wire up the codegraph MCP server in Copilot's own settings UI. See `docs/mcp.md` for the MCP server.
