---
description: Create a pull request from feature branch to hotfix with release details
allowed-tools: Bash(git:*), Bash(gh:*), Bash(grep:*), Bash(curl:*)
---

# Create PR (Step 12 — final workflow step)

Create a pull request from the current feature branch to `hotfix` with a full description of what was implemented.

## Process

### 1. Verify state

```bash
git branch --show-current   # must be a feature branch (feat/, fix/, chore/)
git status -s               # should be clean
git log --oneline hotfix..HEAD # commits to include
```

If uncommitted changes exist: STOP, run `/commit` first.
If on a protected branch (main/release/hotfix): STOP, wrong branch.

### 2. Push the feature branch

```bash
BRANCH=$(git branch --show-current)
git push origin "$BRANCH"
```

### 3. Get PyPI version (if packaged)

```bash
PYPI_VERSION=$(curl -s https://pypi.org/pypi/cognitx-codegraph/json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])" 2>/dev/null || echo "not published")
```

### 4. Analyze commits

Review ALL commits between `hotfix` and the feature branch:
```bash
BRANCH=$(git branch --show-current)
git log --oneline hotfix.."$BRANCH"
git diff --stat hotfix.."$BRANCH"
```

Identify: type of change (feat/fix/refactor), scope, key changes.

### 5. Comment on the source issue (if applicable)

If an issue number was mentioned, add an implementation summary:
```bash
gh issue comment <N> --body "## Implementation Complete
**Package:** cognitx-codegraph=={version}
### What was done
- <summary>
### Tests
- {N} tests passing
This issue will be automatically closed when the PR is merged."
```

### 6. Create PR

Include `Closes #N` in the body so GitHub auto-closes the issue on merge.
Do NOT manually close the issue.

```bash
BRANCH=$(git branch --show-current)
gh pr create --base hotfix --head "$BRANCH" --title "<type>: <concise description>" --body "$(cat <<'EOF'
Closes #<N>

## Summary
- <bullet 1: what changed>
- <bullet 2: what changed>

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

Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

### 7. Report

```
PR Created
----------
URL: <pr-url>
Title: <title>
Base: hotfix <- <feature-branch>
Commits: {N}
PyPI: {version}

Done. Workflow complete.
To sync other branches, run /sync manually.
```
