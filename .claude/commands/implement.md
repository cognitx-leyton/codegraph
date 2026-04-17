---
description: Execute an implementation plan with validation loops
argument-hint: <path/to/plan.md>
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent
---

# Implement Plan (Step 4)

**Plan**: $ARGUMENTS

## Phase 1: Load

Read the plan file and extract:
- **Tasks** — ordered list of what to implement
- **Files to Change** — CREATE/UPDATE list
- **Patterns to Mirror** — code references to follow
- **Acceptance Criteria** — what "done" looks like
- **Validation** — how to verify

If plan not found:
```
Error: Plan not found at $ARGUMENTS
Create one first: /plan_local "feature description"
```

## Phase 2: Verify Starting State

```bash
git branch --show-current   # must be a feature branch (feat/, fix/, chore/)
git status -s               # should be clean
```

If on a protected branch (main/release/hotfix/dev): STOP, wrong branch.
If dirty: warn user, don't proceed until resolved.

## Phase 3: Execute

For each task in the plan, in order:

### 3.1 Read Context
- Read the **Mirror** / **Read first** references from the plan
- Understand the pattern before writing code

### 3.2 Implement
- Make the change as specified in the task
- Follow the mirrored pattern exactly

### 3.3 Validate Immediately

After EVERY file change:
```bash
cd codegraph && python -m compileall codegraph/ -q   # syntax check
.venv/bin/python -m pytest tests/ -q                  # tests
```

If validation fails:
1. Read the error
2. Fix the issue
3. Re-run validation
4. Only proceed to next task when passing

### 3.4 Track Progress

Use TaskCreate/TaskUpdate to track each task. Mark in_progress when starting, completed when done.

```
Task 1: UPDATE codegraph/resolver.py ✅
Task 2: CREATE tests/test_new.py ✅
Task 3: UPDATE codegraph/cli.py ⏳ (in progress)
```

If you deviate from the plan, note what changed and why.

## Phase 4: Final Validation

After all tasks complete:
```bash
cd codegraph
python -m compileall codegraph/ -q        # byte-compile
.venv/bin/python -m pytest tests/ -q      # full test suite
.venv/bin/codegraph --help                # CLI sanity
```

All must pass with zero errors.

## Phase 5: Report

```
Implementation Complete
-----------------------
Plan: {plan-path}
Tasks: {N}/{N} completed
Tests: {N} passed, {N} new
Deviations: {none | list}

Ready for: /review-pr
```
