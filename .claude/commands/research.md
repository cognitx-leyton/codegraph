---
description: Deep codebase + external research before planning an implementation
argument-hint: <issue-number | topic description>
allowed-tools: Bash(gh:*), Bash(.venv/bin/codegraph:*), Grep, Glob, Read, Agent, WebSearch, WebFetch
---

# Research (Step 2)

**Input**: $ARGUMENTS

Deep research before creating an implementation plan. Combines codegraph queries, codebase exploration, and external documentation research.

## Phase 1: Issue Context

If input is a number, fetch the GitHub issue:
```bash
gh issue view $ARGUMENTS
```

Extract: title, description, labels, linked PRs, comments.

If input is text, use it directly as the research topic.

## Phase 2: Codebase Impact Analysis

Use codegraph to understand what the change touches:

### 2.1 Find affected symbols
```
/graph "MATCH (c:Class) WHERE c.name CONTAINS '<keyword>' RETURN c.name, c.file"
/graph "MATCH (f:Function) WHERE f.name CONTAINS '<keyword>' RETURN f.name, f.file"
```

### 2.2 Blast radius
For each affected symbol, check who depends on it:
```
/blast-radius <symbol>
```

### 2.3 Related files
```
/graph "MATCH (f:File)-[r:IMPORTS_SYMBOL]->(g:File) WHERE g.path CONTAINS '<path>' RETURN f.path, r.symbol"
```

### 2.4 Architecture check
```
/arch-check
```
Note any existing violations that might interact with the change.

## Phase 3: Codebase Exploration

Use the Explore agent to:
- Read the files identified in Phase 2
- Understand existing patterns and conventions
- Identify test files that cover the affected code
- Note any related TODO/FIXME/HACK comments

## Phase 4: External Documentation (if needed)

If the issue involves external libraries, APIs, or frameworks:

### 4.1 Context7 (for library docs)
Use `context7` MCP to fetch current documentation for the relevant library.

### 4.2 NotebookLM (for deep research)
If complex research is needed:
```bash
nlm notebook list  # check existing notebooks
nlm notebook query <notebook-id> "<question>"
```

### 4.3 Web search (fallback)
Search for specific error messages, migration guides, or API references.

## Phase 5: Research Summary

Output a structured summary:

```markdown
## Research: <topic>

### Issue
<Issue title and key requirements>

### Affected Code
| File | Symbol | Impact |
|------|--------|--------|
| path | name | what changes |

### Blast Radius
- N files import the affected symbols
- N tests cover the affected code
- Key callers: <list>

### External Context
<Any library docs, API details, or migration notes>

### Risks
| Risk | Severity | Mitigation |
|------|----------|------------|
| ... | HIGH/MED/LOW | ... |

### Recommended Approach
<1-2 paragraphs on how to implement this>

### Ready for: /plan_local
```
