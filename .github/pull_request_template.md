<!-- PR template — ensures every PR links its issue so GitHub auto-closes it on merge. -->

Closes #

## Summary

<!-- Brief description of what this PR does and why. -->

## Checklist

- [ ] PR title uses conventional commits (`feat(scope)`, `fix(scope)`, `docs(scope)`, etc.)
- [ ] Tests pass: `cd codegraph && .venv/bin/python -m pytest tests/ -q`
- [ ] Arch-check passes: `cd codegraph && codegraph arch-check`
