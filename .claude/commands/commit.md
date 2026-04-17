---
description: Create atomic commit with conventional prefix and Co-Authored-By
argument-hint: [files...]
allowed-tools: Bash(git:*)
---

# Commit (Step 6)

Create an atomic commit for the current changes.

**Files to include**: $ARGUMENTS (if empty, include all relevant modified/new files)

## Process

### 1. Review what's being committed

```bash
git status -s
git diff --stat
git diff --cached --stat
```

Show the user a summary of changes before proceeding.

### 2. Stage files

```bash
git add <specific files>
```

**Do NOT stage**:
- `.claude/settings.local.json`
- `.claude/agents/` (user-local)
- `.claude/skills/` (user-local)
- `.env`, credentials, secrets
- `.superset/`

### 3. Write commit message

Format:
```
<type>(<scope>): <concise description of WHY>

<Detailed body explaining what changed and the motivation.
Reference issue numbers if applicable.>

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

**Type**: `feat` | `fix` | `docs` | `refactor` | `test` | `chore`
**Scope**: the module or area changed (e.g., `parser`, `resolver`, `cli`, `mcp`)

### 4. Commit

Use HEREDOC for proper formatting:
```bash
git commit -m "$(cat <<'EOF'
<type>(<scope>): <description>

<body>

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
EOF
)"
```

### 5. Confirm

```bash
git log --oneline -1
git status -s
```

Report: commit SHA, message summary, remaining uncommitted files (if any).
