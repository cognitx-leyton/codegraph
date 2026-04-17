---
description: Create a pull request from dev to release with release details
allowed-tools: Bash(git:*), Bash(gh:*), Bash(grep:*), Bash(curl:*)
---

# Create PR (Step 12 — final workflow step)

Create a pull request from `dev` to `release` with a full description of what was implemented.

## Process

### 1. Verify state

```bash
git branch --show-current   # must be dev
git status -s               # should be clean
git log --oneline release..dev # commits to include
```

If uncommitted changes exist: STOP, run `/commit` first.

### 2. Push dev

```bash
git push origin dev
```

### 3. Get PyPI version (if packaged)

```bash
PYPI_VERSION=$(curl -s https://pypi.org/pypi/cognitx-codegraph/json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])" 2>/dev/null || echo "not published")
```

### 4. Analyze commits

Review ALL commits between `release` and `dev`:
```bash
git log --oneline release..dev
git diff --stat release..dev
```

Identify: type of change (feat/fix/refactor), scope, key changes.

### 5. Create PR

```bash
gh pr create --base release --head dev --title "<type>: <concise description>" --body "$(cat <<'EOF'
## Summary
- <bullet 1: what changed>
- <bullet 2: what changed>
- <bullet 3: what changed>

## Test plan
- [x] Unit tests: {N} passed
- [x] Byte-compile clean
- [x] Code review: clean
- [x] Critique: PASS
- [x] Self-index verified
- [ ] Leytongo real-world test

## Package
PyPI: `cognitx-codegraph=={version}`
Install: `pip install cognitx-codegraph=={version}`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

### 6. Report

```
PR Created
----------
URL: <pr-url>
Title: <title>
Base: release ← dev
Commits: {N}
PyPI: {version}

Done. Workflow complete.
To sync other branches (main, hotfix), run /sync manually.
```
