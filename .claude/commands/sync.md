---
description: Merge PR and sync all branches (main, dev, release, hotfix)
argument-hint: [PR-number]
allowed-tools: Bash(git:*), Bash(gh:*)
---

# Sync Branches (Step 13)

**PR**: $ARGUMENTS (if empty, finds the most recent open PR)

Merge the PR and bring all protected branches up to date.

## Process

### 1. Find PR

```bash
# If argument given, use it. Otherwise find most recent.
gh pr list --base main --state open --limit 1
```

### 2. Merge PR

```bash
gh pr merge <N> --merge --admin
```

Uses `--admin` to bypass branch protection (repo admin required).

### 3. Sync dev to main

```bash
git fetch origin
git checkout dev
git pull origin dev
git merge origin/main --ff-only
git push origin dev
```

### 4. Sync release

```bash
git checkout release
git pull origin release --no-rebase --no-edit
git merge origin/main --no-edit
git push origin release
```

### 5. Sync hotfix

```bash
git checkout hotfix
git pull origin hotfix --no-rebase --no-edit
git merge origin/main --no-edit
git push origin hotfix
```

### 6. Return to dev

```bash
git checkout dev
```

### 7. Report

```
Branches Synced
---------------
┌──────────┬──────────┬─────────────────┐
│ Branch   │   SHA    │     State       │
├──────────┼──────────┼─────────────────┤
│ main     │ {sha}    │ ← merged PR    │
│ dev      │ {sha}    │ ← in sync      │
│ release  │ {sha}    │ ← merged main  │
│ hotfix   │ {sha}    │ ← merged main  │
└──────────┴──────────┴─────────────────┘

Done. All branches contain the latest work.
```
