# Plan: Rewrite .claude/ Commands for E2E Development Workflow

## Summary

Rewrite the `.claude/commands/` to match our actual e2e development workflow: preflight → issue → research → plan → implement → review → commit → critique → roadmap → package → test → issues → PR → sync. Delete unused agents (use built-in `feature-dev:code-reviewer` instead). Keep codegraph-specific commands unchanged. Create new commands for gaps in the workflow.

## Metadata

| Field | Value |
|-------|-------|
| Type | REFACTOR |
| Complexity | MEDIUM |
| Systems Affected | `.claude/commands/`, `.claude/agents/` |
| New Dependencies | None |

---

## What to KEEP unchanged

These codegraph-specific commands are working well and not part of the workflow rewrite:

| Command | Purpose |
|---------|---------|
| `/graph` | Read-only Cypher query |
| `/graph-refresh` | Re-index codegraph package |
| `/blast-radius` | Symbol dependency check |
| `/dead-code` | Orphan detection |
| `/trace-endpoint` | Endpoint call chain |
| `/who-owns` | File ownership |
| `/arch-check` | Architecture conformance |
| `/validate` | Compile + CLI sanity + tests |
| `/plan_local` | Create implementation plan (step 3 of workflow) |

## What to DELETE

| File | Reason |
|------|--------|
| `.claude/agents/code-reviewer.md` | Use built-in `feature-dev:code-reviewer` |
| `.claude/agents/code-simplifier.md` | Covered by review loop |
| `.claude/agents/comment-analyzer.md` | Covered by review loop |
| `.claude/agents/pr-test-analyzer.md` | Covered by review loop |
| `.claude/agents/silent-failure-hunter.md` | Covered by review loop |
| `.claude/agents/type-design-analyzer.md` | Covered by review loop |

## What to REWRITE

| Command | Current Problem | New Behavior |
|---------|----------------|--------------|
| `/implement` | Hardcoded for JS/TS (`pnpm`), writes to `.agents/`, creates feature branches | Python-native, uses `pytest`, works on `dev` branch, tracks tasks |
| `/commit` | 5 lines, says "no AI attribution" (wrong), no workflow | Conventional commits with `Co-Authored-By`, asks user for context |
| `/create-pr` | Generic, doesn't know `dev → main` flow | Handles `dev → main`, includes PyPI version, auto-merges with `--admin` |
| `/review-pr` | Spawns 6 custom agents | Uses built-in `feature-dev:code-reviewer`, runs until clean |

## What to CREATE

| Command | Purpose | Workflow Step |
|---------|---------|--------------|
| `/preflight` | Check Neo4j, .venv, tests, graph state | Step 0 |
| `/research` | Deep codebase + external research | Step 2 |
| `/critique` | Verify plan fully implemented | Step 7 |
| `/package` | Bump version, build, publish to PyPI | Step 9 |
| `/test` | Unit tests + real-world validation on codegraph + leytongo | Step 10 |
| `/sync` | Merge PR + sync all branches | Step 13 |

## What to LEAVE (not part of this rewrite)

| Command | Reason |
|---------|--------|
| `/prime` | Useful for context loading, occasionally used |
| `/prd` | PRD generation, separate from this workflow |
| `/rca` | Root cause analysis, standalone tool |
| `/create-command` | Meta tool for making new commands |
| `/create-rules` | CLAUDE.md management |
| `/check-ignores` | Standalone audit tool |

---

## Tasks

### Task 1: Delete unused agents

- **Files**: All 6 files in `.claude/agents/`
- **Action**: DELETE
- **Validate**: `ls .claude/agents/` should be empty or the directory removed

### Task 2: Rewrite `/preflight` (NEW — Step 0)

- **File**: `.claude/commands/preflight.md`
- **Action**: CREATE
- **Implement**:
  - Check Neo4j container running: `docker ps | grep codegraph-neo4j`
  - Check `.venv` exists and has codegraph installed: `.venv/bin/codegraph --help`
  - Run tests: `.venv/bin/python -m pytest tests/ -q`
  - Check graph has data: `.venv/bin/codegraph query "MATCH (n) RETURN count(n)"`
  - Check git state: branch, clean/dirty, ahead/behind
  - Report pass/fail for each with fix instructions

### Task 3: Rewrite `/research` (NEW — Step 2)

- **File**: `.claude/commands/research.md`
- **Action**: CREATE
- **Implement**:
  - Takes argument: issue number or topic description
  - If issue number: fetch with `gh issue view <N>`
  - Codegraph queries: blast radius, related files, dependencies
  - Use `/graph` queries to understand impact
  - If external docs needed: use NotebookLM CLI (`nlm`) or context7 MCP
  - Output: structured research summary with affected files, risks, and recommended approach

### Task 4: Rewrite `/implement` (Step 4)

- **File**: `.claude/commands/implement.md`
- **Action**: UPDATE (full rewrite)
- **Implement**:
  - Takes argument: path to plan file
  - Read plan, extract tasks
  - For each task: implement, run `validate` checks (compile + tests), fix if broken
  - Track progress with TaskCreate/TaskUpdate
  - No feature branches (work on `dev`)
  - Python-native: `pytest`, `python -m compileall`, no `pnpm`
  - No report files or plan archiving — just implement and validate

### Task 5: Rewrite `/review-pr` → `/review` (Step 5)

- **File**: `.claude/commands/review-pr.md`
- **Action**: UPDATE (full rewrite, rename conceptually to "review")
- **Implement**:
  - Use built-in `feature-dev:code-reviewer` agent
  - Also run codegraph checks: `/arch-check`, `/dead-code`
  - Loop: review → fix issues → re-review until clean
  - Report findings concisely, fix immediately
  - No custom agent spawning

### Task 6: Rewrite `/commit` (Step 6)

- **File**: `.claude/commands/commit.md`
- **Action**: UPDATE (full rewrite)
- **Implement**:
  - Stage relevant files (not `.claude/` local files)
  - Conventional prefix: `feat|fix|docs|refactor|test|chore(scope)`
  - Detailed commit body explaining "why"
  - Always include `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`
  - Show diff summary before committing
  - Use HEREDOC for message formatting

### Task 7: Rewrite `/critique` (NEW — Step 7)

- **File**: `.claude/commands/critique.md`
- **Action**: CREATE
- **Implement**:
  - Takes argument: path to plan file
  - Read the plan's acceptance criteria and tasks
  - For each criterion: verify it's met by checking the code/tests
  - Use codegraph queries to verify structural changes (new nodes, edges, endpoints)
  - Run test suite to verify functional correctness
  - Report: PASS (all criteria met) or FAIL (list gaps with specific unmet criteria)
  - If FAIL: output what needs to be done, ready for another `/implement` cycle

### Task 8: Rewrite `/package` (NEW — Step 9)

- **File**: `.claude/commands/package.md`
- **Action**: CREATE
- **Implement**:
  - Read current version from `pyproject.toml`
  - Bump patch version (0.1.x → 0.1.x+1)
  - Update description if needed
  - Build: `python -m build`
  - Upload: `twine upload dist/*`
  - Verify on PyPI: `curl -s https://pypi.org/pypi/cognitx-codegraph/json | python3 -c "..."`
  - Report: version published, PyPI URL

### Task 9: Rewrite `/test` (NEW — Step 10)

- **File**: `.claude/commands/test.md`
- **Action**: CREATE
- **Implement**:
  - **Unit tests**: `.venv/bin/python -m pytest tests/ -q`
  - **Byte-compile**: `python -m compileall codegraph/ -q`
  - **Install test**: Create temp venv, `pip install cognitx-codegraph==<version>`, verify `codegraph --help`
  - **Self-index**: Re-index codegraph's own code, check node/edge counts
  - **Real-world test**: Index leytongo at `~/Obsidian/SecondBrain/Leyton/by-country/Spain/by-product/leytongo/leytongo-mvp` (if it exists), report stats
  - **Smoke queries**: Run canonical queries against the indexed graph
  - Report: pass/fail for each stage

### Task 10: Create `/create-pr` rewrite (Step 12)

- **File**: `.claude/commands/create-pr.md`
- **Action**: UPDATE (full rewrite)
- **Implement**:
  - Always `dev → main`
  - Push `dev` if unpushed commits
  - Generate PR title from commits (conventional prefix)
  - Body: summary bullets, test plan, PyPI version link if packaged
  - Create with `gh pr create`
  - Report PR URL

### Task 11: Create `/sync` (NEW — Step 13)

- **File**: `.claude/commands/sync.md`
- **Action**: CREATE
- **Implement**:
  - Takes argument: PR number (optional, defaults to most recent)
  - Merge PR with `gh pr merge <N> --merge --admin`
  - Fast-forward `dev` to `main`
  - Merge `main` into `release` and `hotfix` (handling divergent histories)
  - Push all branches
  - Report: table of branch → SHA → state

---

## Implementation Order

Single-agent, sequential: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11

Delete agents first, then create/rewrite commands in workflow order.

---

## Acceptance Criteria

- [ ] All 6 agent files deleted from `.claude/agents/`
- [ ] 6 new commands created: `preflight`, `research`, `critique`, `package`, `test`, `sync`
- [ ] 4 commands rewritten: `implement`, `commit`, `create-pr`, `review-pr`
- [ ] All commands reference correct paths (`codegraph/`, `.venv/bin/`, `tests/`)
- [ ] No references to `pnpm`, `npm`, `.agents/`, JS/TS-specific tooling
- [ ] Each command is self-contained with clear frontmatter
- [ ] Codegraph-specific commands (`graph`, `blast-radius`, etc.) untouched
