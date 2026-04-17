---
description: Bump version, build wheel, and publish to PyPI
allowed-tools: Bash(python:*), Bash(.venv/bin/*), Bash(grep:*), Bash(curl:*)
---

# Package (Step 9)

Bump the patch version, build the wheel + sdist, and publish to PyPI.

## Process

### 1. Read current version

```bash
grep '^version' pyproject.toml
```

### 2. Bump patch version

Increment the patch number: `0.1.X` → `0.1.X+1`

Edit `pyproject.toml` to update the version.

### 3. Build

```bash
cd codegraph
rm -f dist/*
.venv/bin/python -m build
ls dist/
```

Verify both `.whl` and `.tar.gz` are produced.

### 4. Upload to PyPI

```bash
.venv/bin/twine upload dist/*
```

Uses credentials from `~/.pypirc`. If upload fails, check:
- Token is valid
- Version doesn't already exist on PyPI

### 5. Verify on PyPI

```bash
curl -s https://pypi.org/pypi/cognitx-codegraph/json | python3 -c "
import sys, json
d = json.load(sys.stdin)
v = d['info']['version']
print(f'Latest version on PyPI: {v}')
print(f'URL: https://pypi.org/project/cognitx-codegraph/{v}/')
"
```

### 6. Report

```
Package Published
-----------------
Version: 0.1.{N}
PyPI: https://pypi.org/project/cognitx-codegraph/0.1.{N}/
Wheel: cognitx_codegraph-0.1.{N}-py3-none-any.whl

Install: pip install cognitx-codegraph==0.1.{N}
         pipx install "cognitx-codegraph[python,mcp]==0.1.{N}"

Ready for: /test
```
