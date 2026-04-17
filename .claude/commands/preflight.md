---
description: Pre-flight checks before starting work — Neo4j, venv, tests, graph, git
allowed-tools: Bash(docker:*), Bash(.venv/bin/*), Bash(python:*), Bash(git:*)
---

# Pre-flight Check (Step 0)

Run all checks before starting any implementation work. Report pass/fail for each.

## Checks

### 1. Git state
```bash
git branch --show-current
git status -s
git log --oneline -3
```
- Must be on `dev` branch
- Working tree should be clean (untracked `.claude/` files are OK)

### 2. Neo4j container
```bash
docker ps --format '{{.Names}} {{.Status}}' | grep codegraph-neo4j
```
- If not running: `cd codegraph && docker compose up -d`
- Wait for healthy: `curl -sf http://localhost:7475 > /dev/null`

### 3. Python venv
```bash
.venv/bin/codegraph --help > /dev/null 2>&1
```
- If missing: `python3 -m venv .venv && .venv/bin/pip install -e ".[python,mcp,test]"`

### 4. Test suite
```bash
.venv/bin/python -m pytest tests/ -q
```
- All tests must pass before starting new work

### 5. Graph state
```bash
.venv/bin/codegraph query "MATCH (n) RETURN count(n) AS nodes"
```
- If 0 nodes: suggest running `/graph-refresh`

## Report

```
Pre-flight Report
-----------------
Git branch:    dev ✅ / ❌ (on {branch})
Working tree:  clean ✅ / dirty ❌
Neo4j:         running ✅ / down ❌ (fixed ✅)
Python venv:   OK ✅ / missing ❌ (fixed ✅)
Tests:         {N} passed ✅ / {N} failed ❌
Graph:         {N} nodes ✅ / empty ❌

Ready to work: YES / NO — fix {issues} first
```
