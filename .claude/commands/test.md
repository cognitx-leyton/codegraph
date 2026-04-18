---
description: Run unit tests + real-world validation on codegraph and leytongo
argument-hint: [unit|install|self-index|leytongo|all]
allowed-tools: Bash, Read, Grep
---

# Test (Step 10)

**Scope**: $ARGUMENTS (default: all)

Run progressive validation — from unit tests through real-world indexing.

## Stage 1: Unit Tests

```bash
cd codegraph
.venv/bin/python -m pytest tests/ -q
python -m compileall codegraph/ -q
```

**Pass criteria**: All tests pass, zero warnings, byte-compile clean.

## Stage 2: Install Test

Test that the published package is installable with version assertion and retry for PyPI propagation lag:

```bash
LATEST=$(grep '^version' pyproject.toml | sed 's/.*"\(.*\)"/\1/')
MAX_ATTEMPTS=3
BACKOFF=30
INSTALL_OK=false

for attempt in $(seq 1 $MAX_ATTEMPTS); do
  _tmpdir=$(mktemp -d)
  TMPVENV="$_tmpdir/venv"
  python3 -m venv "$TMPVENV"
  "$TMPVENV/bin/pip" install "cognitx-codegraph[python]==$LATEST" --no-cache-dir -q

  INSTALLED=$("$TMPVENV/bin/pip" show cognitx-codegraph 2>/dev/null | grep '^Version:' | awk '{print $2}')
  INSTALLED=${INSTALLED:-NONE}
  rm -rf "$_tmpdir"

  if [ "$INSTALLED" = "$LATEST" ]; then
    echo "Install OK — version $INSTALLED verified (attempt $attempt/$MAX_ATTEMPTS)"
    INSTALL_OK=true
    break
  fi

  if [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
    echo "Attempt $attempt/$MAX_ATTEMPTS: expected $LATEST, got $INSTALLED. Retrying in ${BACKOFF}s..."
    sleep $BACKOFF
  else
    echo "Install FAILED — expected $LATEST but got $INSTALLED after $MAX_ATTEMPTS attempts"
    exit 1
  fi
done
```

**Pass criteria**: Installed version matches `pyproject.toml` version exactly. Retries up to 3 times with 30s backoff for PyPI propagation lag.

> **Note**: The `exit 1` ensures a non-zero exit in standalone / CI contexts. When run as a Claude Code slash command, Claude also reads the "Install FAILED" echo to determine the outcome.

## Stage 3: Self-Index (dogfood)

Re-index codegraph's own codebase and verify the graph:

```bash
cd codegraph
.venv/bin/codegraph index . -p codegraph -p tests --no-wipe --skip-ownership
```

Then verify key stats:
```bash
.venv/bin/codegraph query "MATCH (f:File) RETURN count(f) AS files"
.venv/bin/codegraph query "MATCH (c:Class) RETURN count(c) AS classes"
.venv/bin/codegraph query "MATCH (m:Method) RETURN count(m) AS methods"
.venv/bin/codegraph query "MATCH (e:Endpoint) RETURN count(e) AS endpoints"
```

**Pass criteria**: Files > 15, Classes > 30, Methods > 100. If endpoints were added, verify count > 0.

## Stage 4: Real-World Test (leytongo)

Index the leytongo MVP codebase to verify against a real-world project:

```bash
LEYTONGO="$HOME/Obsidian/SecondBrain/Leyton/by-country/Spain/by-product/leytongo/leytongo-mvp"
if [ -d "$LEYTONGO" ]; then
    cd codegraph
    .venv/bin/codegraph index "$LEYTONGO" -p "$LEYTONGO/leytongo-back" -p "$LEYTONGO/leytongo-front" --no-wipe --skip-ownership
else
    echo "SKIP: leytongo not found at $LEYTONGO"
fi
```

Then run smoke queries:
```bash
.venv/bin/codegraph query "MATCH (f:File) WHERE f.package CONTAINS 'leytongo' RETURN f.package, count(f) AS files ORDER BY files DESC"
.venv/bin/codegraph query "MATCH (c:Class) WHERE c.file CONTAINS 'leytongo' RETURN count(c) AS classes"
.venv/bin/codegraph query "MATCH ()-[r:IMPORTS]->() RETURN type(r), count(r) AS n"
```

**Pass criteria**: No crashes, files indexed > 100, imports resolved > 50%.

## Stage 5: Architecture Check

```bash
cd codegraph
.venv/bin/codegraph arch-check
```

**Pass criteria**: Exit 0 (no violations) on codegraph's own code.

## Report

```
Test Report
-----------
Unit tests:     {N} passed ✅ / ❌
Byte-compile:   clean ✅ / ❌
Install test:   OK ✅ / FAILED ❌
Self-index:     {N} files, {N} classes, {N} methods ✅ / ❌
Leytongo:       {N} files indexed ✅ / SKIPPED / ❌
Arch-check:     PASS ✅ / {N} violations ❌

Overall: PASS / FAIL — {issues to fix}

If PASS → Ready for: /create-pr
If FAIL → Fix issues, then /implement → /review-pr → /commit → /critique → /package → /test
```
