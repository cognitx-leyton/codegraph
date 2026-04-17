---
description: Sync branches after a PR is merged — propagate hotfix to dev, main, release
argument-hint: [PR-number]
allowed-tools: Bash(git:*), Bash(gh:*)
---

# Sync Branches (standalone utility — not part of the workflow)

**PR**: $ARGUMENTS (if empty, finds the most recent merged PR)

After you approve and merge a PR into hotfix, run this to propagate changes to the other branches.

## Branch flow

```
hotfix (receives PRs from feature branches)
  ↓ sync
dev (development branch)
  ↓ sync
main (stable reference)
  ↓ sync
release (release branch)
```

## Process

### 1. Find the merged PR

```bash
# If argument given, use it. Otherwise find most recent merged PR to hotfix.
gh pr list --base hotfix --state merged --limit 1
```

### 2. Fetch latest

```bash
git fetch origin
```

### 3. Sync dev to hotfix

```bash
git checkout dev
git pull origin dev
git merge origin/hotfix --no-edit
git push origin dev
```

### 4. Sync main to dev

```bash
git checkout main
git pull origin main
git merge origin/dev --no-edit
git push origin main
```

### 5. Sync release to main

```bash
git checkout release
git pull origin release
git merge origin/main --no-edit
git push origin release
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
│ hotfix   │ {sha}    │ ← PR merged    │
│ dev      │ {sha}    │ ← synced       │
│ main     │ {sha}    │ ← synced       │
│ release  │ {sha}    │ ← synced       │
└──────────┴──────────┴─────────────────┘

Done. All branches contain the latest work.
```
