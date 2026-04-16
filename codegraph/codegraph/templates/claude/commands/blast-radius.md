---
allowed-tools: Bash(codegraph query:*), Bash(codegraph query:*), Bash(.venv/bin/codegraph query:*)
description: Show everything that depends on a symbol (class / function / method) — run before renaming, deleting, or moving
---

## Usage

```
/blast-radius <SymbolName>
```

Returns every site that would break (or need updating) if you changed the named symbol. Unions five edge kinds in a single query:

| Edge | Captures |
|---|---|
| `IMPORTS_SYMBOL` | Files that explicitly import the symbol by name |
| `CALLS` | Methods that call a method of that name (typed or name-based resolution) |
| `EXTENDS` | Subclasses that'd break if the base changes |
| `INJECTS` | NestJS DI consumers |
| `RENDERS` | React components that render the symbol |

Run it **before** any rename / move / delete. If nothing comes back, the symbol is safe to touch. If many callers come back, you're probably looking at a staged migration.

## What this does

```bash
codegraph query "
MATCH (caller:File)-[r:IMPORTS_SYMBOL]->(source:File)
WHERE r.symbol = '$ARGUMENTS'
RETURN 'IMPORTS_SYMBOL' AS edge, caller.path AS caller, '' AS caller_sym, source.path AS defined_in, r.symbol AS symbol
UNION ALL
MATCH (caller:Method)-[c:CALLS]->(target:Method)
WHERE target.name = '$ARGUMENTS'
RETURN 'CALLS' AS edge, caller.file AS caller, caller.name AS caller_sym, target.file AS defined_in, target.name AS symbol
UNION ALL
MATCH (sub:Class)-[:EXTENDS]->(parent:Class)
WHERE parent.name = '$ARGUMENTS'
RETURN 'EXTENDS' AS edge, sub.file AS caller, sub.name AS caller_sym, parent.file AS defined_in, parent.name AS symbol
UNION ALL
MATCH (consumer:Class)-[:INJECTS]->(injected:Class)
WHERE injected.name = '$ARGUMENTS'
RETURN 'INJECTS' AS edge, consumer.file AS caller, consumer.name AS caller_sym, injected.file AS defined_in, injected.name AS symbol
UNION ALL
MATCH (parent:Function)-[:RENDERS]->(child:Function)
WHERE child.name = '$ARGUMENTS'
RETURN 'RENDERS' AS edge, parent.file AS caller, parent.name AS caller_sym, child.file AS defined_in, child.name AS symbol
LIMIT 200
"
```

The `--json` flag is optional; add it for machine-parseable output. The default-rendered Rich table is easier to eyeball.

## Caveats

- **Name collisions are a feature.** If two classes share a name in different packages, both show up. That's usually what you want when assessing blast radius.
- **Python CALLS is method-only.** The resolver wires Python `CALLS` edges from method bodies; module-level function → method calls aren't tracked (Stage 1 limitation). Callers that live in a top-level function may be missed.
- **Aliased re-exports.** If `pkg/__init__.py` re-exports `Foo` and another file does `from pkg import Foo`, the `IMPORTS_SYMBOL` edge points at the re-export, not the original definition — you'll see both in the blast-radius output.
- **200-row limit.** Raise the `LIMIT 200` at the bottom of the query if you hit it on a very-central symbol.

## After running

If the result is large, group by `edge` in your head to attack the migration in waves:
1. Start with `EXTENDS` — subclasses break at class-definition time
2. Then `INJECTS` — DI wiring is surgical
3. Then `IMPORTS_SYMBOL` — mechanical find-and-replace
4. Then `CALLS` — last, because fixing callers often requires the new signature to already exist
