---
description: File GitHub issues for enhancements or bugs discovered during implementation
allowed-tools: Bash(gh:*)
---

# File Issues (Step 11)

During implementation, you may discover:
- Enhancement ideas that are out of scope for the current work
- Bugs in unrelated code
- Missing features that would be nice to have
- Technical debt worth tracking

**Do NOT implement these.** File them as GitHub issues so they're tracked for future work.

## Process

### 1. Review discoveries

Look through:
- Deviations noted during `/implement`
- Suggestions from `/review-pr` that were out of scope
- Ideas surfaced during `/critique`
- Errors seen during `/test` that aren't blockers

### 2. For each discovery, create an issue

```bash
gh issue create --title "<type>: <concise title>" --body "$(cat <<'EOF'
## Context

Discovered during implementation of <current work>.

## Description

<What the issue is, with specifics>

## Suggested approach

<Brief idea of how to address it, if known>

## References

- Related file(s): `<path>`
- Related commit: `<sha>`
- Surfaced by: `/review-pr` | `/critique` | `/test`
EOF
)" --label "<enhancement|bug|tech-debt>"
```

### 3. Report

```
Issues Filed
-------------
- #N: <title> (enhancement)
- #N: <title> (bug)
- #N: <title> (tech-debt)

These are tracked for future work — not part of the current release.

Ready for: /create-pr
```

### Labels

| Label | When to use |
|-------|-------------|
| `enhancement` | New feature or capability |
| `bug` | Something broken in existing code |
| `tech-debt` | Refactoring, cleanup, performance |
| `documentation` | Missing or outdated docs |
