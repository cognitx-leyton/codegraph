---
description: Verify that a plan was fully implemented — checks acceptance criteria against code
argument-hint: <path/to/plan.md>
allowed-tools: Read, Grep, Glob, Bash(.venv/bin/*), Bash(python:*), Agent
---

# Critique (Step 7)

**Plan**: $ARGUMENTS

Verify the plan was fully and correctly implemented. This is NOT a code review (that's `/review-pr`) — this checks **completeness** against the plan's specification.

## Phase 1: Load Plan

Read the plan and extract:
- **Tasks** — every task listed
- **Acceptance Criteria** — every checkbox
- **Files to Change** — every CREATE/UPDATE entry
- **Validation commands** — test/build commands specified

## Phase 2: Task Verification

For each task in the plan:

### 2.1 File exists / was modified
- CREATE tasks: verify the file exists
- UPDATE tasks: verify the file was modified (check git diff)

### 2.2 Implementation matches spec
- Read the file and verify the task's requirements are met
- Check that the specified patterns were followed
- Verify the "Implement" bullet points are all addressed

### 2.3 Codegraph structural verification (where applicable)

If the plan added new classes, functions, endpoints, or edges:
```bash
.venv/bin/codegraph query "MATCH (c:Class {name:'<expected>'}) RETURN c.name, c.file"
.venv/bin/codegraph query "MATCH (e:Endpoint) WHERE e.path = '<expected>' RETURN e.method, e.path"
```

Run `/graph-refresh` first if needed to ensure the graph reflects current code.

## Phase 3: Acceptance Criteria

For each acceptance criterion in the plan:
- Check if it's met by examining the code, tests, or running verification commands
- Mark PASS or FAIL with evidence

## Phase 4: Test Verification

```bash
cd codegraph
.venv/bin/python -m pytest tests/ -q       # all tests pass
python -m compileall codegraph/ -q          # byte-compile clean
```

Verify:
- New tests were written for new code
- Test count increased as expected
- No warnings

## Phase 5: Verdict

### If ALL criteria pass:

```
Critique: PASS
--------------
Tasks: {N}/{N} verified
Acceptance criteria: {N}/{N} met
Tests: {N} passed ({M} new)

Ready for: /package
```

### If ANY criteria fail:

```
Critique: FAIL
--------------
Tasks: {N}/{M} verified — {K} gaps
Acceptance criteria: {N}/{M} met

Gaps:
1. [TASK X] <what's missing>
2. [CRITERION Y] <what's not met>

Action: Run /implement to address the gaps, then /review-pr, /commit, and /critique again.
```

Do NOT proceed to `/package` on a FAIL. The implementation loop must repeat:
`/implement → /review-pr → /commit → /critique`
