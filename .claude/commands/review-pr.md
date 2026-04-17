---
description: Code review using built-in reviewer + codegraph checks — loops until clean
allowed-tools: Read, Grep, Glob, Bash, Edit, Write, Agent
---

# Code Review (Step 5)

Review all uncommitted changes. Fix issues found. Re-review until clean.

## Review Loop

### Round N:

#### 1. Run code reviewer

Spawn the built-in `feature-dev:code-reviewer` agent on the changed files:
- Focus on: logic bugs, edge cases, security, inconsistencies with codebase patterns
- Only report HIGH confidence issues (>80%)
- Include file:line references

#### 2. Run codegraph checks

```bash
cd codegraph
.venv/bin/codegraph arch-check          # architecture conformance
```

Also run `/dead-code` to check for orphaned symbols introduced by the changes.

#### 3. Run test suite

```bash
cd codegraph
.venv/bin/python -m pytest tests/ -q
```

#### 4. Evaluate results

| Result | Action |
|--------|--------|
| Issues found | Fix them immediately, then go to Round N+1 |
| Tests failing | Fix the code or tests, then go to Round N+1 |
| Arch violations | Fix or document as acceptable, then go to Round N+1 |
| All clean | Exit loop |

### Exit condition

The review loop exits when ALL of these are true:
- Code reviewer reports 0 high-confidence issues
- `arch-check` passes (exit 0)
- All tests pass
- No new dead code introduced

## Report

```
Review Complete
---------------
Rounds: {N}
Issues found: {total across all rounds}
Issues fixed: {total fixed}
Tests: {N} passed
Arch-check: PASS

Ready for: /commit
```
