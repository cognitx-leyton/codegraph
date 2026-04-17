---
description: Update ROADMAP.md with what was shipped this session
allowed-tools: Read, Edit, Bash(git:*)
---

# Update Roadmap (Step 8)

Update `ROADMAP.md` at the repo root to reflect what was just implemented.

## Process

### 1. Gather context

```bash
git log --oneline $(git describe --tags --abbrev=0 2>/dev/null || echo HEAD~10)..HEAD
git diff --stat $(git describe --tags --abbrev=0 2>/dev/null || echo HEAD~10)..HEAD
```

Read the current `ROADMAP.md`.

### 2. Update these sections

#### "TL;DR — where we are"
- Update branch state, test count, graph stats, package version

#### "Shipped since the last roadmap update"
- Add new commit list with descriptions
- Group by theme (like existing entries)

#### "Repository state"
- Update table: branch, unpushed commits, test count, last install

#### "What's next (ranked)"
- Move completed items out of "What's next"
- Re-rank remaining items if priorities shifted
- Add any new items discovered during implementation

#### "Known open questions"
- Remove resolved questions
- Add new questions surfaced during work

### 3. Update the header

```markdown
> **Last updated:** {today's date} after commits `{first}` → `{last}` ({summary}).
```

### 4. Do NOT update these sections
- "Session workflow conventions" — only update if a convention changed
- "Non-goals" — only update if something moved in/out of scope
- "Appendix" — auto-derived from code, update only if file structure changed

## Validate

Read the updated ROADMAP.md back and verify it's coherent — a fresh agent should be able to pick up work from it.
