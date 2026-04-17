---
description: Create implementation plan with codebase analysis
argument-hint: <feature description | path/to/prd.md>
---

# Implementation Plan Generator

**Input**: $ARGUMENTS

## Objective

Transform the input into a battle-tested implementation plan through codebase exploration, research, and pattern extraction.

**Core Principle**: PLAN ONLY - no code written. Create a context-rich document that enables one-pass implementation.

**Order**: CODEBASE FIRST → REUSE INVENTORY → RESEARCH IF NEEDED → DESIGN → GENERATE.

---

## Phase 1: PARSE

### Determine Input Type

| Input | Action |
|-------|--------|
| `.prd.md` file | Read PRD, extract next pending phase |
| Other `.md` file | Read and extract feature description |
| Free-form text | Use directly as feature input |
| Blank | Use conversation context |

### Extract Feature Understanding

- **Problem**: What are we solving?
- **User Story**: As a [user], I want to [action], so that [benefit]
- **Type**: NEW_CAPABILITY / ENHANCEMENT / REFACTOR / BUG_FIX
- **Complexity**: LOW / MEDIUM / HIGH

### Prior Plan Check

If other plans exist in `.agents/plans/`:
1. Read their summaries to understand what infrastructure they create
2. Note any shared files (e.g., `ViewTypeSwitcher.tsx` modified by multiple plans)
3. Reference prior plans explicitly: "Depends on: {plan}.plan.md creating {component}"
4. If a shared file will be modified by multiple plans, note the merge order

---

## Phase 2: EXPLORE

### Study the Codebase

Use the Explore agent to find:

1. **Similar implementations** - analogous features with file:line references
2. **Naming conventions** - actual examples from the codebase
3. **Error handling patterns** - how errors are created and handled
4. **Type definitions** - relevant interfaces and types
5. **Test patterns** - test file structure and assertion styles

### Document Patterns

| Category | File:Lines | Pattern |
|----------|------------|---------|
| NAMING | `path/to/file.ts:10-15` | {pattern description} |
| ERRORS | `path/to/file.ts:20-30` | {pattern description} |
| TYPES | `path/to/file.ts:1-10` | {pattern description} |
| TESTS | `path/to/test.ts:1-25` | {pattern description} |

---

## Phase 2.5: REUSE INVENTORY

Before designing anything new, create an explicit inventory of what ALREADY EXISTS that the new feature should reuse. This prevents double-building.

### Mandatory Checks:
1. **Existing hooks** — Search for hooks that already fetch/mutate the same data
2. **Existing components** — Search for UI components that render similar content
3. **Existing types** — Search for TypeScript interfaces the new feature should extend (not duplicate)
4. **Installed libraries** — Check package.json for libraries already available
5. **Existing patterns** — Find the closest analogous feature and note its exact file:line for each pattern

### Output Format:
| What Exists | File:Line | How New Feature Reuses It |
|-------------|-----------|---------------------------|
| `useUpdateRecord()` | `hooks/useRecords.ts:140` | Kanban drag calls this for optimistic update |
| `parseSelectOptions()` | `lib/selectOptions.ts:37` | Column headers + colors |
| `@dnd-kit/core` | `package.json` | Already installed, use for drag-and-drop |

If the inventory shows >60% of infrastructure exists, note this in the plan summary as "LOW effort — mostly wiring existing infrastructure."

---

## Phase 3: DISCOVER SKILLS

### Scan Available Skills

Check what skills are available in the project for agents to use:

1. **Project skills**: List directories in `.claude/skills/` — each directory with a `SKILL.md` is an available skill
2. **Plugin skills**: Check system-level skills available via the Skill tool (e.g., `frontend-design`, `webapp-testing`)

### Map Skills to Agent Roles

For each discovered skill, determine which agent role should use it:

| Skill Pattern | Agent Role | When to Use |
|---------------|-----------|-------------|
| `agent-browser` | tester-e2e | Always — E2E browser testing |
| `build-with-agent-team` | orchestrator | Always — the execution mechanism |
| `frontend-design` (if available) | frontend agent | When building UI components, pages, layouts |
| `webapp-testing` (if available) | tester-e2e | When testing web app with Playwright |
| Other project-specific skills | Map by relevance | Read SKILL.md to determine appropriate agent |

**Record the skill mapping** — it will be included in agent definitions and task annotations in the generated plan.

---

## Phase 4: ASSESS RESEARCH NEEDS

### Determine If Research Phase Is Needed

Research tasks produce reference docs in `.agents/docs/` that agents read before implementation. This is NOT always needed.

**Research IS needed when** (any of these):

| Trigger | Example | What to Research |
|---------|---------|-----------------|
| **Greenfield project** | No existing codebase | Framework patterns, library APIs, architecture conventions |
| **Unfamiliar external APIs/CLIs** | NLM CLI, Stripe API, unfamiliar SDK | Capture full API reference, document the specific commands/endpoints used |
| **New framework or major version** | Next.js 15, React 19, new library | Breaking changes, current patterns, migration notes |
| **Complex integration** | Multiple systems talking to each other | Data flow, protocol details, error handling across boundaries |
| **Team members need shared context** | 3+ agents working in parallel | Architecture decisions, contracts, shared conventions |

**Research is NOT needed when** (all of these):

- Existing codebase with established patterns (EXPLORE phase is sufficient)
- Well-known, stable libraries with no version surprises
- LOW complexity with < 5 tasks
- Single-agent work (no coordination needed)
- Enhancement or bug fix in familiar code

### License Gate (for any new npm dependency)

Before adding a new library to the plan:
1. Check the license on npm/GitHub (MIT, Apache-2.0 = OK; GPL, AGPL = BLOCK for commercial projects)
2. Check last release date (>2 years = maintenance risk)
3. Check weekly downloads (< 1K = adoption risk)
4. Document in plan: `| Library | License | Last Release | Downloads | Verdict |`

If a library fails the license check, find an MIT alternative or plan a custom build.

### If Research Needed: Plan Research Tasks

For each research area, plan a task that produces a doc in `.agents/docs/`:

| Research Area | Output File | Research Method |
|---------------|-------------|-----------------|
| External CLI/API reference | `.agents/docs/{tool}-reference.md` | Run `{tool} --help` / `--ai`, capture + annotate with project-specific usage |
| Framework patterns | `.agents/docs/{framework}-patterns.md` | context7 MCP (`query-docs`), web search, official docs |
| Library usage | `.agents/docs/{library}-patterns.md` | context7 MCP (`query-docs`), web search |
| Architecture decisions | `.agents/docs/architecture-decisions.md` | Synthesize from plan context — data flow, storage schema, error contracts, integration patterns |
| UI component reference | `.agents/docs/{ui-lib}-components.md` | context7 MCP, web search — document installed components and usage patterns |

**Research task structure:**
- Each research task produces exactly one `.agents/docs/{name}.md` file
- File should include: overview, project-specific subset (what we actually use), code snippets, gotchas
- Research tasks run BEFORE implementation tasks (blocking dependency)
- The agent that produces them (usually foundation/first-to-spawn) MUST complete them before other agents start

**If research NOT needed**: Skip this entirely — no `.agents/docs/` directory, no research tasks in the plan.

---

## Phase 5: DESIGN

### Dependency Principle

Default to ZERO new dependencies. Before recommending a new npm package:
1. Check if an installed library already covers the use case (check package.json)
2. Check if a custom implementation is feasible with what's available
3. Only add a new dependency if neither option works

In the plan, explicitly state: "New Dependencies: None" or "New Dependencies: {package} — needed because {reason}".

### Generalization Check

Before finalizing the design, ask:
- Is this feature specific to one use case, or could it serve many?
- Would a configurable/generic version take the same effort?
- Does a more general version already exist in the codebase?

If generalizing adds <30% more effort but serves 3x+ use cases → generalize.
Document the decision: "Generalized: Yes — {reason}" or "Specific: Yes — {reason}"

### Map the Changes

- What files need to be created?
- What files need to be modified?
- What's the dependency order?

### Identify Risks

| Risk | Mitigation |
|------|------------|
| {potential issue} | {how to handle} |

### Design Agent Team

Determine how to split work across Claude Agent Teams:

1. **Count independent workstreams** - frontend, backend, database, infra, etc.
2. **Map technology boundaries** - different languages/frameworks = different agents
3. **Identify the contract chain** - which agent produces interfaces others consume?

**Feature agents** (variable — based on workstreams):

| Feature Agents | When |
|----------------|------|
| 1 agent | LOW complexity, single system, < 5 tasks |
| 2 agents | Clear frontend/backend split |
| 3 agents | Full-stack (frontend + backend + database/infra) |
| 4+ agents | Large systems with many independent modules |

**Standing agents** (always present — in addition to feature agents):

| Agent | Role | Notes |
|-------|------|-------|
| `general` | Handles tasks that don't belong to a specific feature agent | Orchestrator or other agents delegate here for cross-cutting fixes, config, glue code. Guard against overloading — only use when no feature agent owns the work. |
| `tester-unit` | Unit tests, integration tests, type checking, lint | Writes and runs tests using the project's test runner (vitest, jest, pytest, cargo test, etc.). Validates after feature agents complete. |
| `tester-e2e` | End-to-end browser testing via agent-browser | Uses the `/agent-browser` skill. Opens the running app, walks through user flows, takes screenshots, validates UI behavior. Runs after feature agents and tester-unit. |

**Total team size** = feature agents + 3 standing agents.

For each feature agent, define: name, owned files/directories, off-limits files, key responsibilities, what contract they must publish before building, **which skills they should use**, and **which `.agents/docs/` files they must read before starting**.

---

## Phase 6: GENERATE

### Create Plan File

**Output path**: `.agents/plans/{kebab-case-name}.plan.md`

```bash
mkdir -p .agents/plans
```

```markdown
# Plan: {Feature Name}

## Summary

{One paragraph: What we're building and approach}

## User Story

As a {user type}
I want to {action}
So that {benefit}

## Metadata

| Field | Value |
|-------|-------|
| Type | {type} |
| Complexity | {LOW/MEDIUM/HIGH} |
| Systems Affected | {list} |
| New Dependencies | {None OR package — reason} |
| Generalized | {Yes — reason OR No — reason} |
{If prior plans exist:}
| Depends On | {plan-name.plan.md — what it creates} |

---

## Reuse Inventory

| What Exists | File:Line | How This Plan Reuses It |
|-------------|-----------|--------------------------|
| {hook/component/type/library} | {path:line} | {how} |

---

## Patterns to Follow

### {Pattern Name 1} (e.g., "View Type Integration")
```
// SOURCE: {file:lines}
// {What this pattern does and why it matters}
{actual code snippet — keep short, max 5 lines}
```

### {Pattern Name 2} (e.g., "Widget Registration")
```
// SOURCE: {file:lines}
{actual code snippet}
```

{Add 3-6 patterns. Name them by WHAT they accomplish, not generic categories.
Good: "Record Update with Optimistic Cache", "Select Options Color Parsing"
Bad: "Naming", "Error Handling", "Tests"}

---

## Files to Change

| File | Action | Purpose |
|------|--------|---------|
| `.agents/docs/{name}.md` | CREATE | {Research doc — only if research needed} |
| `path/to/file.ts` | CREATE | {why} |
| `path/to/other.ts` | UPDATE | {why} |

---

## Tasks

Execute in order. Each task is atomic and verifiable.

{If research is needed, include Research Phase tasks first:}

### Research Phase (run before implementation)

### Task R1: {Research area}

- **File**: `.agents/docs/{name}.md`
- **Action**: CREATE
- **Research via**: {context7 MCP / CLI --help / web search}
- **Implement**:
  - {What to research and document}
  - {Key sections to include}
  - {Project-specific annotations to add}
- **Validate**: File exists and covers all patterns needed by downstream agents

{Continue R2, R3... as needed}

---

### Implementation Phase

### Task 1: {Description}

- **File**: `path/to/file.ts`
- **Action**: CREATE / UPDATE
- **Why not UPDATE?**: {Only for CREATE — explain why no existing file can be extended}
- **Read first**: `path/to/context.ts:lines` — {what to learn from it}
- **Skill**: `/{skill-name}` — {when applicable, reference discovered skill and what it's used for}
- **Implement**: {what to do}
- **Mirror**: `path/to/example.ts:lines` - follow this exact pattern
- **Validate**: `{build command}`

### Task 2: {Description}

- **File**: `path/to/file.ts`
- **Action**: CREATE / UPDATE
- **Why not UPDATE?**: {Only for CREATE}
- **Read first**: `path/to/context.ts:lines` — {what to learn}
- **Implement**: {what to do}
- **Mirror**: `path/to/example.ts:lines`
- **Validate**: `{build command}`

{Continue for each task...}

---

## Validation

```bash
# Type check
{build command}

# Lint
{lint command}

# Tests
{test command}
```

---

## Agent Team

{Number} agents ({feature agent count} feature + 3 standing). Execute via `/build-with-agent-team .agents/plans/{name}.plan.md {number}`.

### Feature Agents

#### Agent: {name} (e.g., "frontend")

- **Owns**: `{directories/files this agent exclusively controls}`
- **Does NOT touch**: `{other agents' files}`
{If research docs exist:}
- **MUST read before starting**: {list of `.agents/docs/*.md` files relevant to this agent}
{If skills are mapped to this agent:}
- **Skill**: Uses `/{skill-name}` — {what it's used for}
- **Responsibilities**:
  - {What this agent builds — specific deliverables}
  - {Second deliverable}
- **Publishes contract**: {What interface/API/schema this agent defines for others}
- **Consumes contract from**: {Which agent's contract this agent depends on, or "none"}
- **Validation**: `{command this agent runs before reporting done}`

#### Agent: {name} (e.g., "backend")

- **Owns**: `{directories/files}`
- **Does NOT touch**: `{other agents' files}`
{If research docs exist:}
- **MUST read before starting**: {list of `.agents/docs/*.md` files relevant to this agent}
- **Responsibilities**:
  - {Deliverable 1}
  - {Deliverable 2}
- **Publishes contract**: {API contract, exact URLs, response shapes, status codes}
- **Consumes contract from**: {agent name}
- **Validation**: `{command}`

{Continue for each feature agent...}

### Standing Agents

#### Agent: general

- **Owns**: Files not owned by any feature agent (config, shared utilities, glue code)
- **Does NOT touch**: Files owned by feature agents unless explicitly delegated
- **Responsibilities**:
  - Cross-cutting fixes that span multiple agents' domains
  - Config and environment setup tasks
  - Glue code and integration wiring no feature agent owns
- **Delegation rules**: Orchestrator or feature agents delegate here ONLY when no feature agent owns the work. If a feature agent could do it, they should — this agent is not a dumping ground.
- **Validation**: `{build command}`

#### Agent: tester-unit

- **Owns**: `{test directories}` (e.g., `src/**/*.test.ts`, `tests/`)
- **Does NOT touch**: Source implementation files
- **Responsibilities**:
  - Write unit tests for new/changed code from feature agents
  - Write integration tests for cross-agent boundaries
  - Run full test suite and lint, report failures back to responsible agent
- **Runs after**: Feature agents complete their tasks
- **Validation**: `{test command}` and `{lint command}`

#### Agent: tester-e2e

- **Owns**: `{e2e test directory}` (e.g., `e2e/`, `playwright/`)
- **Does NOT touch**: Source implementation or unit test files
- **Responsibilities**:
  - End-to-end browser testing using the agent-browser skill
  - Open the running app, walk through user flows, take screenshots
  - Validate UI renders correctly, forms submit, navigation works
  - Report failures back to responsible feature agent with screenshots
- **Skills**:
  - Uses `/agent-browser` — `agent-browser open`, `agent-browser snapshot -i`, `agent-browser click`, etc.
  {If webapp-testing skill available:}
  - Uses `/webapp-testing` — Playwright-based toolkit for frontend verification
- **Runs after**: Feature agents and tester-unit complete
- **Validation**: All E2E user flows pass with screenshots captured

### Spawn Order

{If research needed:}
1. {First feature agent} — runs research tasks first, producing `.agents/docs/` reference files. Then publishes {contract type}. Other agents WAIT until research docs + initial contracts are ready.
{If research NOT needed:}
1. {First feature agent} — publishes {contract type} before others start
2. {Second feature agent} — receives contract from step 1, reads `.agents/docs/` if exists, publishes its own
3. {Continue for remaining feature agents...}
4. general — available from the start for cross-cutting work
5. tester-unit — spawned after feature agents complete implementation
6. tester-e2e — spawned after tester-unit passes, needs running app

### Cross-Cutting Concerns

| Concern | Owner | Detail |
|---------|-------|--------|
| {e.g., URL conventions} | {agent name} | {specifics} |
| {e.g., error response shapes} | {agent name} | {specifics} |

---

## Acceptance Criteria

The `/critique` command uses these criteria to verify the implementation is complete.
Vague criteria make critique useless — every criterion must be SPECIFIC and VERIFIABLE.

Group by feature area. Each criterion must state WHAT to check and HOW to verify it.

### {Feature Area 1} (e.g., "Resolver fixes")

- [ ] {Concrete behavior}: {verification method}
- [ ] {Edge case}: {specific input → expected output}
- [ ] {Structural change}: {codegraph query or file check to confirm}

### {Feature Area 2} (e.g., "Endpoint detection")

- [ ] {Concrete behavior}: {verification method}
- [ ] {Integration scenario}: {end-to-end flow that must work}

### Regression guards

- [ ] All existing {N} tests still pass
- [ ] New tests: ~{M} ({breakdown by area})
- [ ] Full test suite passes with 0 warnings
- [ ] Byte-compile clean: `python -m compileall codegraph/ -q`

### Examples of BAD vs GOOD criteria

BAD (too vague — critique agent can't verify):
- [ ] Tests pass
- [ ] Feature works
- [ ] Code is clean

GOOD (specific — critique agent can check each one):
- [ ] `import './foo.js'` resolves to `foo.ts` when `foo.ts` exists on disk
- [ ] `FrameworkType.FASTAPI` scores >= 0.5 against a pyproject.toml with `fastapi` dep
- [ ] `codegraph query "MATCH (e:Endpoint) RETURN count(e)"` returns > 0 after indexing a FastAPI app
- [ ] All existing 223 tests still pass + ~40 new tests added
```

---

## Phase 7: OUTPUT

```markdown
## Plan Created

**File**: `.agents/plans/{name}.plan.md`

**Summary**: {2-3 sentence overview}

**Scope**:
- {N} files to CREATE
- {M} files to UPDATE
- {K} total tasks ({R} research + {I} implementation)

**New Dependencies**: {None | package — reason}

**Key Reuse**:
- {What exists} at `{file:line}` — {how reused}
- {What exists} at `{file:line}` — {how reused}

**Research**: {Included — {N} reference docs in .agents/docs/ | Skipped — straightforward task with known patterns}

**Skills Assigned**:
- {skill name} → {agent name} ({which tasks})

**Agent Team**: {N} agents ({agent names})

**Run this to build**: `/build-with-agent-team .agents/plans/{name}.plan.md {N}`
```
