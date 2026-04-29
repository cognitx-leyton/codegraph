# codegraph — Roadmap & Session Handoff

> **Purpose of this document.** Capture enough context for a fresh agent session (or a human returning after time away) to continue work on codegraph without re-deriving state from scratch. Separate from the user-facing roadmap bullets in `README.md`, which stay short and pitch-oriented.
>
> **Last updated:** 2026-04-29 after `2038f73` — feat(transcribe): add `--transcribe-language` flag and language-keyed cache (closes #281 / #292). Language param threaded through `transcribe()`, `config.py`, `cli.py`; cache key now includes `model_size` + `language`. 1084 tests pass. v0.1.112.

---

## Docs sweep — 2026-04-25 (hotfix)

Catch-up pass that synchronises all user-facing docs with the current codebase after ~250 closed issues. No code changes; docs only.

**Updated files:**
- `codegraph/README.md` — full rewrite from a 34-line stub to a complete CLI / MCP / schema / extras / platforms reference. Documents all 16 CLI subcommands (`init`, `index`, `query`, `validate`, `arch-check`, `wipe`, `stats`, `export`, `benchmark`, `report`, `watch`, `hook`, `install`, `uninstall`, `repl`), all 16 MCP tools incl. `describe_group` / `find_function` / `calls_from` / `callers_of` and the 2 write tools, all 14 install platforms, all 7 optional extras, the `--update` / `--since` incremental modes, edge confidence + `:EdgeGroup` hyperedges, links into `docs/` for deep dives.
- `codegraph/docs/init.md` — adds `--bolt-port` / `--http-port` flags, custom-port section, container-name derivation (`derive_container_name(root)` = sanitised dir + 8-char SHA1), full template-var list (7 keys), `codegraph install <platform>` post-init wiring, manifest-aware uninstall that preserves shared `AGENTS.md` sections, orphaned-container warning, `.codegraph-cache/` auto-`.gitignore` entry.
- `codegraph/codegraph/templates/claude-md-snippet.md` — adds auto-rebuild section (`hook install`, `watch`, `index --update`).
- `ROADMAP.md` — this entry.

**Verified accurate (no edits needed):**
- `codegraph/docs/arch-policies.md` — already covers all 5 built-in policies, `[[suppress]]` syntax, scoping, exit codes, custom-policy authoring, and worked examples.
- `codegraph/docs/confidence.md` — already documents `EXTRACTED` / `INFERRED` / `AMBIGUOUS` taxonomy with per-edge-kind tables and querying examples.
- `codegraph/docs/hyperedges.md` — already covers `:EdgeGroup` / `:MEMBER_OF` model, both kinds (`protocol_implementers`, `community`), `describe_group` MCP tool, and the extension recipe.

**Note on naming:** the `analyze.py` module ships Leiden community detection but is exposed as `codegraph report` on the CLI (no `codegraph analyze` subcommand). The `--no-analyze` flag on `codegraph index` controls whether `report` runs after indexing. README now says `codegraph report`.

---

## TL;DR — where we are

- **Branch:** `archon/task-feat-issue-281-whisper-language-flag`. Closes issues #281 + #292 — exposes `--transcribe-language` CLI flag for Whisper (previously hardcoded `"en"`); fixes cache key to include `model_size` + `language` so stale hits from different language/model combos are impossible. Config field `transcribe_language` wired through TOML → `CodegraphConfig` → `_run_index()` → `transcribe()`. v0.1.112.
- **Tests:** 1084 passing, 11 skipped, 0 warnings. Run via `.venv/bin/python -m pytest tests/ -q` from `codegraph/`.
- **Open PR:** [cognitx-leyton/codegraph#287](https://github.com/cognitx-leyton/codegraph/pull/287) — epic summary table, `Closes #271`, targets `main`.
- **Graph indexed:** Twenty CRM is currently loaded into the local Neo4j container at `bolt://localhost:7688` (13,473 files, 2,559 classes, 6,088 methods, 5,562 CALLS, 6,708 hook usages, 4,593 RENDERS).
- **MCP server:** 15 read-only tools (incl. new `describe_group`) + **2 write tools** (`wipe_graph`, `reindex_file`) gated by `--allow-write` flag + **29 prompt templates** (all Cypher blocks from `queries.md` auto-registered via `_register_query_prompts()`). `codegraph-mcp` console script registered. Smoke-tested via raw JSON-RPC.
- **Package:** `cognitx-codegraph` v0.1.105 in `pyproject.toml`. Wheel + sdist build cleanly. **Not yet on PyPI** — needs one-time operational setup (Trusted Publisher registration). `release.yml` now waits for propagation and smoke-tests the published version.
- **Resolver:** Workspace import resolution now handles bare package names and subpath imports for monorepos (`twenty-ui/display` → `packages/twenty-ui/src/display/index.ts`). Scoped npm packages (`@scope/pkg/sub`) resolved correctly. `tsconfig.json` `"extends"` chains followed recursively (including TS 5.0+ array form). Estimated ~8,081 previously-unresolved Twenty workspace imports now route correctly.
- **CI:** `.github/workflows/arch-check.yml` — every PR to `main` spins up Neo4j, indexes, runs `codegraph arch-check`, fails on architecture violations. Verified live on PR #8 (42s, exit 0).
- **Onboarding:** `codegraph init` scaffolds everything needed to dogfood codegraph in any repo. Live-tested against 3 fixtures including the real Twenty monorepo (13k files indexed end-to-end).
- **Python Stage 2:** FastAPI / Flask / Django / SQLAlchemy framework detection + `:Endpoint` nodes. `/trace-endpoint` now works against Python repos.
- **Incremental re-indexing:** `codegraph index --since <git-ref>` diffs git, cleans stale subgraphs, and upserts only touched files. Implies `--no-wipe`. REPL supports `index --since HEAD~1`. Non-code files (`.md`, `.json`, `.yml`, etc.) are now filtered from the diff before processing.

---

## Shipped since the last roadmap update (commit `2038f73`)

### feat(transcribe) — `--transcribe-language` flag and language-keyed cache (issues #281 + #292)

- `2038f73 feat(transcribe)` — Four source files changed, 5 new tests:

  **Modified files:**

  1. **`codegraph/codegraph/transcribe.py`** — Added `language: str | None = None` param to `transcribe()`. Removed hardcoded `language="en"` so Whisper falls back to auto-detect when no language is specified. Cache path helpers (`_transcript_cache_path`, `_get_cached_transcript`, `_put_cached_transcript`) now include `model_size` and `language` in the filename: `{hash}_{model_size}_{language_or_auto}.txt`. Fixes the stale-cache bug (#292) where transcribing the same audio with a different model or language could silently return a cached result from a prior run.

  2. **`codegraph/codegraph/config.py`** — Added `transcribe_language: str | None = None` field to `CodegraphConfig`. Parses `[transcribe] language` from `codegraph.toml` / `pyproject.toml`. Wired through `merge_cli_overrides` so TOML defaults can be overridden by the CLI flag.

  3. **`codegraph/codegraph/cli.py`** — Added `--transcribe-language` Typer option to `index`. Threaded through `_run_index()` signature and body. Precedence: CLI flag > TOML config > `None` (Whisper auto-detect). Passes `language=` to `_get_cached_transcript`, `_transcribe`, and `_put_cached_transcript`.

  4. **`codegraph/tests/test_transcribe.py`** — 5 new tests:
     - `test_transcribe_language_forwarded` — language kwarg is forwarded to `faster_whisper`.
     - `test_transcribe_default_language_is_none` — default language is `None` (auto-detect), not `"en"`.
     - `test_cache_isolation_by_language` — `"en"` and `"fr"` transcriptions get separate cache files; no cross-contamination.
     - `test_cache_isolation_auto_detect` — `None` (auto) and `"en"` are separate cache entries.
     - `test_cache_isolation_by_model_size` — `"base"` and `"large-v3"` produce separate cache files.

  **Code review (1 issue found and fixed during review pass):**
  - `[BUG]` `cli.py:466-472` — `transcribe_language` was passed to both `merge_cli_overrides` AND resolved again via `or` fallback — two redundant mechanisms for the same precedence logic. Fixed: removed the redundant `merge_cli_overrides` param; kept the simpler `or` fallback (matches how other per-run params work in `_run_index`).

  **Validation:** 1084 tests pass (5 new), 11 skipped, 0 failures. Byte-compile clean. Arch-check: 4/4 PASS.

```
2038f73  feat(transcribe): add --transcribe-language flag and language-keyed cache (#281)
5dd9655  feat(doc-parser): add setext/tilde heading support with fenced-code backtracking fix (#307)
```

---

## Shipped since `5dd9655`

### feat(doc-parser) — setext/tilde heading support with fenced-code backtracking fix (issue #278)

- `5dd9655 feat(doc-parser)` — Three source files changed, 2 new fixtures:

  **Modified files:**

  1. **`codegraph/codegraph/doc_parser.py`** — Three changes:
     - `_FENCED_CODE_RE` rewritten as two alternation branches (one for backtick, one for tilde), excluding the fence character from the info string (`[^\n`]*` / `[^\n~]*`) to prevent regex backtracking. Added `\`*` / `~*` after the closing backreference so a closing fence can be longer than the opening one (CommonMark §4.5). Previously a 4-backtick opening could be spuriously closed by a 3-backtick line, producing false positive headings between the fake close and the real close.
     - New `_SETEXT_HEADING_RE` constant — matches setext headings (`===` / `---` underline, min 3 chars), capturing the preceding content line.
     - `extract_markdown()` now builds a unified heading list from both ATX (`_HEADING_RE`) and setext (`_SETEXT_HEADING_RE`) matches, sorted by document position. ATX match start positions collected into a set to skip any setext match whose start position collides with an ATX heading (prevents duplicates when `# Title` is followed by `===`).

  2. **`codegraph/tests/test_doc_parser_markdown.py`** — 6 new tests:
     - `test_extract_markdown_tilde_fence_ignored` — tilde fences strip fake headings inside.
     - `test_extract_markdown_mixed_fences` — both backtick + tilde fences stripped.
     - `test_extract_markdown_setext_headings` — setext-only document extracts correctly.
     - `test_extract_markdown_mixed_atx_setext` — mixed styles returned in document order.
     - `test_extract_markdown_setext_section_index_sequential` — indices are sequential.
     - `test_extract_markdown_thematic_break_not_heading` — `---` after blank line is not a heading.

  **New files:**

  3. **`codegraph/tests/fixtures/markdown/setext.md`** — setext-only fixture.
  4. **`codegraph/tests/fixtures/markdown/mixed-headings.md`** — ATX + setext interleaved fixture.

  **Code review (2 bugs found and fixed during review pass):**
  - `[BUG]` `_FENCED_CODE_RE` with `{3,}` allowed backreference to capture fewer characters than the opening fence, so a 4-backtick opening matched a 3-backtick close → false positive headings. Fixed with fence-char exclusion in info string + separate alternation branches.
  - `[BUG]` ATX heading `# Title` followed by `===` matched both `_HEADING_RE` and `_SETEXT_HEADING_RE`, producing duplicate entries (`Title` + `# Title`). Fixed by collecting ATX match positions and skipping colliding setext matches.

  **Validation:** 1079 tests pass (6 new), 11 skipped, 0 failures. Byte-compile clean.

```
5dd9655  feat(doc-parser): add setext/tilde heading support with fenced-code backtracking fix
187a956  fix(schema): normalize Unicode before slug hashing (#306)
```

---

## Shipped since `5067452`

### fix(schema) — normalize Unicode before slug hashing (issue #277)

- `5067452 fix(schema)` — Two files changed (1 new test file, 1 modified):

  **Modified files:**

  1. **`codegraph/codegraph/schema.py`** — Added `import hashlib` + `import unicodedata`. Rewrote `_slug()`:
     - NFKD-normalises input (`unicodedata.normalize('NFKD', text)`), encodes to ASCII with `errors='ignore'` to transliterate accented characters (`café` → `cafe`, `naïve résumé` → `naive resume`, `Ñoño` → `nono`).
     - Falls back to a deterministic `sha256(nfkd_normalised_bytes).hexdigest()[:8]` when the ASCII result would be empty (CJK scripts, empty string, whitespace-only input) — ensures IDs remain stable and non-empty.
     - Hash computed over the NFKD-normalised form (not the original) so canonically-equivalent Unicode inputs (precomposed vs. decomposed) always produce the same ID.

  **New files:**

  2. **`codegraph/tests/test_schema.py`** (16 tests) — Covers:
     - ASCII passthrough, dots/dashes preservation.
     - Accented transliteration: `café`, `naïve résumé`, `Ñoño`.
     - CJK hash fallback, empty string, whitespace-only.
     - Hash uniqueness: different CJK strings → different hashes.
     - Determinism: same input always produces same output.
     - No forbidden chars (`#`, `:`, space) in any output.
     - Canonical Unicode equivalence (precomposed `が` vs. decomposed `か`+dakuten → same ID).
     - Node ID integration for `ConceptNode`, `DecisionNode`, `RationaleNode`.

  **Code review (1 issue found and fixed):**
  - `[BUG]` Hash fallback was hashing `text.encode()` (original) instead of `normalised.encode()` — canonically-equivalent Unicode pairs (precomposed vs. decomposed) produced different hashes → fixed; hash now computed over NFKD-normalised bytes. Tests updated to assert the normalised hash + added `test_slug_canonical_equivalence`.

  **Known limitations (out of scope for #277):**
  - Mixed ASCII+non-ASCII slug collision: `"api_世界"` → `"api"` equals `"api_你好"` → `"api"`. Would need a hash-suffix design.
  - German `ß` doesn't fully decompose under NFKD (`"Straße"` → `"strae"`). Would need `unidecode` library.

  - **Validation:** 1073 tests pass (16 new), 11 skipped, 0 failures. Byte-compile clean. Arch-check: 4/4 PASS.

```
5067452  fix(schema): normalize Unicode before slug hashing so canonical equivalents map to the same ID
65a104a  docs(schema): fix stale Cypher patterns to use id-based lookups (closes #272)
```

---

## Shipped since `ea07455`

### docs — fix stale Cypher patterns to use id-based lookups (issue #272)

- `65a104a docs(schema)` — Docs-only fix. No Python files touched. 6 tasks across 4 doc files + 2 live command syncs:

  **Files updated:**
  1. **`codegraph/codegraph/templates/claude/commands/graph.md`** (+ live sync) — 3x `File {path: '...'}` patterns rewritten to `File {id: 'file:codegraph:...'}` id-based lookups, matching the schema change from issue #273 where path stopped being the primary key.
  2. **`codegraph/codegraph/templates/claude/commands/who-owns.md`** (+ live sync) — Added Cypher comment noting that `path` usage is intentional (`$ARGUMENTS` is user-supplied input, not a node lookup).
  3. **`codegraph/queries.md`** — Updated comment: notes `id` is the primary key, `path` is a secondary property.
  4. **`codegraph/docs/schema.md`** — Four sub-fixes:
     - Constraint table: `:File` constraint changed from `path` → `id`; secondary indexes listed as `path, package, repo`; `:Package` constraint changed from `name` → `id`.
     - FileNode properties table: added `id` (primary key, `file:{repo}:{rel_path}`) and `repo` rows.
     - PackageNode properties table: added `id` and `repo` rows; `name` column no longer labelled "Unique".
     - Interface Cypher query: added comment explaining `i.file` stores path, not id — lookup still correct because it's a property filter not a node merge.

  **Code review (2 issues found post-initial-implementation and fixed):**
  - `[INCONSISTENCY]` PackageNode properties table missing `id` + `repo` rows after constraint table was updated → added.
  - `[INCONSISTENCY]` PackageNode `name` column still labelled "Unique" despite constraint change → label removed.

  **Validation:** 1057 tests pass, 11 skipped, 0 failures. Byte-compile clean. Arch-check: 4/4 PASS.

```
65a104a  docs(schema): fix stale Cypher patterns to use id-based lookups (closes #272)
b2cd9fa  feat(graphify-parity): close epic #271 — multimodal ingestion, multi-repo, UX polish + version bump 0.1.112
```

### epic #271 closeout — graphify parity (no code, GitHub ops only)

- All 8 sub-issues (#263 schema-namespacing, #264 PDF ingestion, #265 markdown semantic extraction, #266 vision extraction, #267 audio transcription, #268 clone command, #269 parse-result validator, #270 graph HTML polish) closed with references to their implementing commits.
- Epic issue #271 closed with a summary comment linking all 8 sub-issues.
- PR #287 created targeting `main` with epic summary table.
- Arch-check: 4/4 PASS. Tests: 1057/1057 PASS.
- 9 new findings from the consolidated code review noted above (8 → "Known open questions", 3 pre-existing trackers #277/#278/#285 already open). **#277 now closed** (`5067452`). **#278 now closed** (`5dd9655`).

```
19376d7  feat(export): polish graph HTML — community toggle, convex hull, search UX
776bf01  feat(validate): add parse-result validator to catch malformed extractions before Neo4j load (#284)
b691de1  feat(clone): add codegraph clone command to index remote Git repos (#283)
a4bb1a2  feat(audio): Whisper-based audio/video transcription (#267) (#282)
b7f331e  fix(audio): wire TRANSCRIBED_FROM edge into loader and CLI emission
3dde404  feat(audio): Whisper-based audio/video transcription with DocumentNode extraction
a6c9221  feat(vision): image/vision semantic extraction with ILLUSTRATES_CONCEPT edges (#280)
d2e6f06  feat(semantic): markdown semantic extraction — Concept, Decision, Rationale nodes (#279)
38bd173  feat(docs): PDF document ingestion with outline and page-based section extraction (#276)
6990e71  fix(schema): namespace all node IDs with repo to prevent cross-repo overwrite (#273)
743c02f  chore: bump version to 0.1.103
0c659f3  fix: 5 issues uncovered by the 0.1.102 e2e run
c289630  chore: bump version to 0.1.102
87a0e9a  feat(audit): codegraph audit — agent-driven extraction self-check
11135f9  fix(init): align _DEFAULT_BOLT_PORT/_DEFAULT_HTTP_PORT to 7688/7475 + bump 0.1.101
137812e  chore: bump version to 0.1.100
1cd47f3  feat(init): shared codegraph-neo4j container with auto-detect, auto-start, Docker preflight
0f3480a  docs: refresh top-level README, add CHANGELOG, ship 5 deep-dive doc files
f887f70  refactor(install): deduplicate template-var logic into init.py (issue #259)
6a359f0  fix(install): preserve shared AGENTS.md sections during partial uninstall (#261, closes #257)
9fae95b  fix(install): resolve template variables in platform install content (#260, closes #256)
d27301c  feat(install): add multi-platform codegraph install command (#258, closes #48)
d2f08e4  feat(schema): add edge-level confidence labels to CALLS, IMPORTS, and resolver edges (#255)
906983c  feat(schema): add hyperedge EdgeGroup for protocol-implementer sets (#254)
e0a172d  feat(analyze): add Leiden community detection and graph analysis (#253)
9f42190  feat(benchmark): add token-reduction benchmark command (#252)
85b18f2  feat(export): add interactive HTML and GraphML graph export command (#251)
343878b  feat(cache): prune stale cache entries after manifest save (#250)
33ddbe7  feat(init): append .codegraph-cache/ to .gitignore on codegraph init (#249)
c4571c6  feat(cache): SHA-256 content-addressed cache for incremental indexing (#46) (#248)
3f394de  fix(test): add watchdog to test extra so test_watch.py tests pass
```

### export — graph HTML viewer polish (issue #270)

- `19376d7 feat(export)` — Two files changed (0 new, 2 updated):

  **Updated files:**

  1. **`codegraph/codegraph/export.py`** — Three functions updated:

     - **`to_html()`** — Partitions `EdgeGroup` nodes and `MEMBER_OF` edges out of the vis.js render (EdgeGroup synthetic nodes were showing as dangling vertices). Builds per-community sidebar HTML: one checkbox + HSL-coloured swatch per community, with `html.escape()` + `_js_safe()` on community labels to prevent XSS. Stats line counts only regular (non-EdgeGroup) nodes.

     - **`_community_css()`** (new helper) — Inline CSS block for the sidebar: `#sidebar` toggle button, `#communities` collapsible section with `#communities:empty { display: none; }` guard (prevents empty padding/border when no communities exist).

     - **`_html_script()`** — Three features added:
       - **Community filter toggles**: `change` handler on each checkbox. `cb` variable used consistently throughout (avoids `this` vs. `cb` ambiguity inside nested callbacks). Unchecking a community hides all member nodes via `nodes.update({hidden: true})`.
       - **Convex hull overlays**: inline Graham-scan (~25 lines JS, no external dependency). Rendered via vis.js `afterDrawing` canvas hook. Semi-transparent `hsla` fills (alpha 0.12) and strokes (alpha 0.3), padded 20px outward from centroid. Skips communities with <3 hull points (e.g. collinear layouts).
       - **Diacritic-insensitive search**: `stripDiacritics()` helper using `String.prototype.normalize('NFD')` + Unicode combining-marks regex. Applied to both the search query and node labels/titles so accented characters match their base form.

  2. **`codegraph/tests/test_export.py`** — Two fixtures + five tests added:
     - `community_result` fixture — `ParseResult` with two community `EdgeGroup` nodes + `MEMBER_OF` edges.
     - `html_with_communities` fixture — calls `to_html()` on the above.
     - `test_to_html_community_checkboxes` — verifies `class="community-item"` items present.
     - `test_to_html_community_colors` — verifies `hsl(` colour swatches in sidebar.
     - `test_to_html_no_edgegroup_in_vis` — verifies EdgeGroup label absent from vis.js `nodes` array.
     - `test_to_html_no_communities_graceful` — verifies no sidebar checkboxes when no communities.
     - `test_to_html_community_label_escaped` — verifies `<script>` in community label is HTML-escaped.

  **Code review (2 issues found and fixed):**
  - `[BUG]` Empty `#communities` div rendered padding + border when no communities → fixed with `#communities:empty { display: none; }` CSS rule.
  - `[STYLE]` `this.checked` / `this.dataset.community` mixed with `cb.checked` in same handler → normalised to `cb.*` throughout.

  **Pre-existing pattern noted (out of scope):** search-clear resets `hidden: false` on ALL nodes, including community-hidden ones — same behaviour as the legend toggle. Not fixed here.

  - **Validation:** 1056 tests pass (5 new), 11 skipped, 0 failures. Byte-compile clean. Arch-check: 4/4 policies pass.

### validate — parse-result validator before Neo4j load (issue #269)

- `e2ee2fb feat(validate)` — Three files changed (2 new, 1 updated):

  **New files:**

  1. **`codegraph/codegraph/parse_validator.py`** (~200 LOC) — Validation module. `VALID_EDGE_KINDS` (49 entries: 48 schema constants + `__STATS__` sentinel). `VALID_CONFIDENCE_LABELS` (`EXTRACTED`, `INFERRED`, `AMBIGUOUS`). `SYNTHETIC_ID_PREFIXES` (`external:`, `dec:`, `hook:`, `edgegroup:`) — these reference no on-disk node, so dangling-ref checks skip them. `validate_parse_result(result)` performs per-file validation: duplicate node IDs, edges whose `src_id`/`dst_id` reference an unknown node, edges with an unrecognised `kind`, edges with an invalid `confidence` label or `confidence_score` outside `[0.0, 1.0]`. `validate_cross_file_edges(edges, all_node_ids)` validates resolver-emitted cross-file edges against the full global node pool; skips `__STATS__` sentinel edges. `assert_valid(...)` raises `ValueError` with all error messages joined — used by strict mode.

  2. **`codegraph/tests/test_parse_validator.py`** (20 tests) — Covers all 5 error classes (duplicate ID, dangling src/dst, unknown edge kind, invalid confidence label, out-of-range confidence score), all 4 synthetic prefix types accepted without false positives, `assert_valid` raise/pass behaviour, cross-file validation with global pool, `__STATS__` sentinel skipping, integration self-parse of real source files producing zero errors.

  **Updated files:**

  3. **`codegraph/codegraph/cli.py`** — Added `--strict-validate` flag (default: off) to `codegraph index`. Per-file validation runs after each parse, before `index_obj.add(result)`. Cross-file validation runs after `link_cross_file()`, before Neo4j write. Default mode: log warnings and continue. Strict mode: aggregate all errors across all files then raise `ConfigError` (exits cleanly with code 1). Cached results skip re-validation (errors were already reported on the original parse). Import added between `.ownership` and `.parser` (alphabetical order preserved).

  **Code review (2 issues found and fixed):**
  - `[STYLE]` `from .parse_validator` import placed after `.schema`, breaking alphabetical ordering → moved between `.ownership` and `.parser`.
  - `[LINT]` `FunctionNode` and `MethodNode` imported but unused in `test_parse_validator.py` → removed.

  **Pre-existing bug discovered (out of scope — separate issue):** `py_parser.py:482` emits `dst_id=f"col:{cls.id}#..."` but `ColumnNode.id` returns `f"column:{cls.id}#..."`. The `col:` vs `column:` prefix mismatch means HAS_COLUMN edges have dangling `dst_id` on Python ORM codebases. The validator correctly flags this. Not fixed here.

  - **Validation:** 1051 tests pass (20 new), 11 skipped, 0 failures. Byte-compile clean.

### clone — index remote Git repos by URL (issue #268)

- `0728528 feat(clone)` + `7cb1fdd fix(clone)` — Three files changed (2 new, 1 updated):

  **New files:**

  1. **`codegraph/codegraph/clone.py`** (~200 LOC) — Core clone module. `parse_github_url(url)` parses both HTTPS (`https://github.com/owner/repo`) and SSH (`git@github.com:owner/repo`) GitHub URL forms into an `(owner, repo)` tuple; raises `ValueError` on unrecognised shapes. `cache_dir(owner, repo)` returns `~/.codegraph/repos/<owner>/<repo>` — persistent cross-session repo cache. `clone_or_pull(url, dest, *, full_clone, quiet)` either runs `git clone --depth 1` (shallow by default; `--full-clone` omits `--depth 1`) or `git pull --ff-only` when the destination already exists. `run_clone(url, *, packages, full_clone, json_output, neo4j_uri, neo4j_user, neo4j_password, repo_name)` orchestrates: parse URL → clone/pull → auto-detect packages from config when none supplied → delegate to `_run_index()`. Connection errors from `_run_index()` are caught as `(ServiceUnavailable, AuthError)` and exit with code 2.

  2. **`codegraph/tests/test_clone.py`** (25 tests) — All git operations mocked via `unittest.mock.patch`. Covers: 9 URL parsing tests (HTTPS, SSH, trailing `.git`, port in URL, non-GitHub host, malformed inputs); 3 cache directory tests (path shape, owner/repo isolation); 5 git operation tests (fresh clone, cached pull, `--full-clone` omits `--depth 1`, pull failure raises `RuntimeError`, non-zero exit code); 7 integration tests for `run_clone()` (happy path with `repo` kwarg assertion, custom packages override, no packages falls back to config, `ServiceUnavailable` exits with code 2).

  **Updated files:**

  3. **`codegraph/codegraph/cli.py`** — Thin `@app.command() def clone(...)` Typer wrapper. Options: `url` positional, `--package/-p` (repeatable), `--full-clone`, `--json`, Neo4j `--uri`/`--user`/`--password`. No post-index export/benchmark/analyze post-processing (those remain `codegraph index`-only for now).

  **Code review (7 issues found and fixed):**
  - `[BUG]` `no_export`, `no_benchmark`, `no_analyze` accepted by `run_clone()` but never used → removed from function signature and CLI wrapper.
  - `[BUG]` `except Exception` in connection-error path too broad → narrowed to `(ServiceUnavailable, AuthError)` matching `index` command.
  - `[LINT]` `CodegraphConfig` imported but unused in `clone.py` → removed.
  - `[LINT]` `MagicMock` imported but unused in `test_clone.py` → removed.
  - `[TEST GAP]` `test_happy_path` didn't verify `repo` kwarg pointed to cache dir → added `assert call_kw["repo"] == CLONE_CACHE_ROOT / "nestjs" / "nest"`.
  - `[TEST GAP]` No test for `ServiceUnavailable` from `_run_index` → added `test_connection_error_returns_exit_2`.
  - `[TEST GAP]` (Pre-existing review fix) Dead CLI flags `--no-export/--no-benchmark/--no-analyze` removed from wrapper.

  - **Validation:** 977 tests pass (25 new), 13 skipped, 0 failures. Byte-compile clean. Arch-check: skipped (Neo4j not running in worktree).

### audio — Whisper-based audio/video transcription (issue #267)

- `3dde404 feat(audio)` + `b7f331e fix(audio)` — Seven files changed (3 new, 4 updated):

  **New files:**

  1. **`codegraph/codegraph/transcribe.py`** (~248 LOC) — Core transcription module. `load_model(device, compute_type)` instantiates a `faster_whisper.WhisperModel` (model size `base`); auto-selects `cuda`/`float16` when CUDA available, else `cpu`/`int8`. `transcribe(path, rel, repo_name, model, cache_dir)` returns a `(DocumentNode, str)` pair — one `DocumentNode` plus the full transcript text. SHA-256 content-addressed cache via `_file_content_hash(path)` (chunked 1 MB reads — safe on the 500 MB limit). Cache stores `{id, path, repo, transcript, indexed_at}` as JSON keyed by `{sha256}:{rel}:{repo}`. 500 MB size guard raises `ValueError` on oversized files. Supported extensions: `.wav`, `.mp3`, `.m4a`, `.ogg`, `.flac`, `.mp4`, `.mov`, `.mkv`, `.webm`, `.avi`. Optional-import guard converts missing `faster_whisper` into a user-friendly `ImportError` message rather than a raw traceback. `faster_whisper` and `yt_dlp` are optional-imported at call time (not module import time) so the rest of codegraph works without the extra installed.

  2. **`codegraph/tests/test_transcribe.py`** (14 tests) — All tests mock `faster_whisper.WhisperModel` so the suite runs without the package installed. Covers: `DocumentNode` field presence, transcript text output, ID format (`doc:{repo}:{rel}`), 500 MB size guard, missing `faster_whisper` guard, cache hit/miss round-trip, `TRANSCRIBED_FROM` schema constant presence, extension list completeness.

  3. **`codegraph/tests/fixtures/audio/sample.wav`** — 1-second silence WAV at 44.1 kHz (16 KB). Used as the live fixture for all `transcribe` tests.

  **Updated files:**

  4. **`codegraph/codegraph/schema.py`** — Added `TRANSCRIBED_FROM = "TRANSCRIBED_FROM"` edge constant (Phase 14). Kept as a schema constant for future use; no edges of this type are currently written to Neo4j (media files never get `:File` nodes, so a back-edge target would not exist).

  5. **`codegraph/codegraph/cli.py`** — Added `--extract-audio` flag to `codegraph index`. Auto-enables `--extract-docs` (so `DocumentNode` loading is wired). Validates `faster_whisper` availability at startup; converts `ImportError` to `ConfigError` (caught by CLI, exits cleanly). Calls `load_model()` once before the loop (not per file). Media walk globs all supported extensions, applies `exclude_dirs` + `ignore_filter`. Per-file error handling: one file failure doesn't abort the batch. `audio_count` only printed in summary when > 0.

  6. **`codegraph/codegraph/loader.py`** — `TRANSCRIBED_FROM` imported from schema (present for completeness; not yet wired to a write path since no `:File` target nodes exist for media files).

  7. **`codegraph/pyproject.toml`** — Added `[transcribe]` optional extra (`faster-whisper>=1.0`, `yt-dlp>=2024.1`). Added `faster-whisper` to `[test]` extra so `test_transcribe.py` can mock it.

  **Code review (6 issues found and fixed):**
  - `[CRITICAL]` `TRANSCRIBED_FROM` edges targeted non-existent `:File` nodes — media files never get `FileNode` entries, so all edges would be silently dropped by Neo4j MATCH → removed edge creation from CLI; removed from loader dict/loop. Schema constant kept for future use.
  - `[HIGH]` Unused `Edge` and `TRANSCRIBED_FROM` imports in `transcribe.py` → removed dead imports.
  - `[HIGH]` `WhisperModel` re-instantiated per file in CLI loop — seconds of model loading per file → extracted `load_model()` function; CLI calls once, passes `model` param to `transcribe()`.
  - `[HIGH]` `_file_content_hash` read up to 500 MB into memory via `read_bytes()` → changed to chunked 1 MB reads.
  - `[HIGH]` Missing `faster-whisper` + `--extract-audio` → unhandled `ImportError` raw traceback → wrapped `load_model()` call in try/except, converts to `ConfigError` (caught by CLI).
  - `[MEDIUM]` Unused `load_model` import in test file → removed.

  - **Validation:** 1006 tests pass (14 new), 11 skipped, 0 failures. Byte-compile clean. Arch-check: 4/4 policies pass.

### vision — image/vision semantic extraction with ILLUSTRATES_CONCEPT edges (issue #266)

- `66f70cd feat(vision)` — Seven files changed (4 new, 3 updated):

  **New files:**

  1. **`codegraph/codegraph/vision_extract.py`** (~220 LOC) — Claude vision API integration. `VisionCache` (alias of `SemanticCache`) keyed by file SHA-256 + `rel` + `repo_name`. `_MEDIA_TYPES` dict maps extension → MIME type (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`). `_file_content_hash(path)` reads the file and returns its SHA-256 hex digest. `extract_vision(image_path, rel, repo_name, api_key)` encodes the image as base64, calls the Anthropic API with the `vision.md` prompt, and parses the structured response into a list of `Edge` objects with `kind=ILLUSTRATES_CONCEPT`. `_parse_vision_response()` extracts headings-delimited concept sections and returns one `Edge` per concept. 20 MB size guard raises `ValueError` on oversized files.

  2. **`codegraph/codegraph/templates/semantic/vision.md`** — Prompt template for image concept extraction. Instructs the model to identify concepts illustrated or referenced in the image (diagrams, architecture charts, screenshots, wireframes). Strict output schema with `## Concepts` section; anti-hallucination constraints.

  3. **`codegraph/tests/test_vision_extract.py`** (18 tests) — Covers happy path (concept count, edge kind, target ID format), cache hit/miss, oversized file guard, unsupported extension guard, API key validation, `_parse_vision_response` with fence stripping, empty response, SHOWS_ARCHITECTURE constant presence, base64 encoding round-trip.

  4. **`codegraph/tests/fixtures/images/sample.png`** — 1×1 white PNG (~68 bytes). Used as the live fixture for all `vision_extract` tests.

  **Updated files:**

  5. **`codegraph/codegraph/schema.py`** — Added `ILLUSTRATES_CONCEPT = "ILLUSTRATES_CONCEPT"` and `SHOWS_ARCHITECTURE = "SHOWS_ARCHITECTURE"` edge constants (Phase 13).

  6. **`codegraph/codegraph/loader.py`** — Added `ILLUSTRATES_CONCEPT` to the edge-label map and the write loop so vision edges are persisted to Neo4j. Import ordering corrected (alphabetical).

  7. **`codegraph/codegraph/cli.py`** — Added `--extract-images` flag to `codegraph index` (implies `--extract-docs` and requires `ANTHROPIC_API_KEY`). Image walk globs `**/*.{png,jpg,jpeg,gif,webp}`, applies `exclude_dirs` + `ignore_filter`. Vision extraction dispatches per-file with per-file error handling. `img_count` only printed in summary when > 0. Edge kind comparison uses `ILLUSTRATES_CONCEPT` constant (not string literal).

  **Code review (3 issues found and fixed):**
  - `[IMPORT ORDER]` `loader.py` — `ILLUSTRATES_CONCEPT` inserted between `DocumentNode` and `DocumentSectionNode` breaking alphabetical order → moved after `DocumentSectionNode`.
  - `[UX]` `cli.py` summary printed `"+ 0 image(s)"` even when `--extract-images` was not used → moved image count into a conditional (`if img_count`).
  - `[ROBUSTNESS]` `cli.py` vision summary used string literal `'ILLUSTRATES_CONCEPT'` for edge kind check → replaced with the imported constant.

  - **Validation:** 992 tests pass (18 new), 11 skipped, 0 failures. Byte-compile clean. Arch-check: 4/4 policies pass.

### docs — markdown semantic extraction via Claude API (issue #265)

- `57b1a4a feat(docs)` — Fifteen files changed (7 new, 8 updated):

  **New files:**

  1. **`codegraph/codegraph/semantic_extract.py`** (~270 LOC) — Claude API integration. `SemanticCache` (SHA-256 content hash + `rel` + `repo_name` → cached `SemanticResult`). `SemanticResult` dataclass (fields: `concepts: list[ConceptNode]`, `decisions: list[DecisionNode]`, `rationales: list[RationaleNode]`). `extract_semantics(content, rel, repo_name, api_key)` calls the Anthropic API with `max_tokens=2048`, parses the structured YAML-like response, and returns a `SemanticResult`. `_parse_response()` strips fenced code blocks, extracts headings-delimited sections, and maps them to node dataclasses. `_slugify(text)` normalises free-text LLM output into safe node-ID segments. `rationale_index` field disambiguates multiple rationales for the same decision.

  2. **`codegraph/codegraph/templates/semantic/extract.md`** — Prompt template for concept/decision/rationale extraction. Instructs the model to identify concepts (named entities/abstractions), decisions (architectural/design choices with explicit rationale), and rationale nodes (the "why" behind each decision). Includes strict output schema and anti-hallucination constraints.

  3. **`.env.example`** — Documents `ANTHROPIC_API_KEY` requirement for `--extract-markdown`.

  4. **`codegraph/tests/fixtures/markdown/concepts.md`** — Fixture with headings + concept-dense text.
  5. **`codegraph/tests/fixtures/markdown/decisions.md`** — Fixture with explicit architectural decisions.
  6. **`codegraph/tests/fixtures/markdown/empty.md`** — Zero-content fixture.
  7. **`codegraph/tests/fixtures/markdown/no-headings.md`** — Flat prose, no Markdown headings.

  8. **`codegraph/tests/test_doc_parser_markdown.py`** (10 tests) — Deterministic markdown extraction: `extract_markdown()` returns `(DocumentNode, list[DocumentSectionNode])`, section IDs are sequential, headings inside fenced code blocks are not extracted, repo-namespaced IDs (`doc:repo:path` / `docsec:repo:path#0`), ISO-8601 `indexed_at`, path consistency.

  9. **`codegraph/tests/test_semantic_extract.py`** (14 tests) — Semantic extraction with mocked Anthropic client: happy path (concept/decision/rationale counts), `rationale_index` uniqueness, degenerate fence stripping, cache hit/miss, empty-response handling, API key validation (whitespace rejected), `_slugify` output, `SemanticCache.cache_key` includes `rel` and `repo_name` (prevents cross-file cache collisions).

  **Updated files:**

  10. **`codegraph/codegraph/schema.py`** — Added `ConceptNode` (fields: `id`, `name`, `description`, `repo`, `path`), `DecisionNode` (fields: `id`, `title`, `description`, `repo`, `path`), `RationaleNode` (fields: `id`, `rationale_index`, `text`, `repo`, `path`, `decision_id`). All IDs embed `_slugify(name/title)` + hash suffix for safety. Added edge constants: `DOCUMENTS_CONCEPT`, `DECIDES`, `JUSTIFIES`, `SEMANTICALLY_SIMILAR_TO`.

  11. **`codegraph/codegraph/doc_parser.py`** — Added `extract_markdown(path, repo_name)` function. Heading-based section extraction (`##`-level headings split sections). Fenced code block stripping before heading detection (headings inside ` ```...``` ` blocks are ignored). Returns `(DocumentNode, list[DocumentSectionNode])`.

  12. **`codegraph/codegraph/loader.py`** — Added `ConceptNode`, `DecisionNode`, `RationaleNode` constraints and indexes. Added `concepts`, `decisions`, `rationales` fields to `LoadStats`. Added `_write_concepts()`, `_write_decisions()`, `_write_rationales()`, `_write_semantic_edges()` helpers. Fixed `wipe_scoped` to also clean up Document, DocumentSection, Concept, Decision, Rationale nodes (closes #274). Used labeled MATCH in `_write_semantic_edges` for query performance.

  13. **`codegraph/codegraph/cli.py`** — Added `--extract-markdown` flag (requires `ANTHROPIC_API_KEY`). API key validated (rejects whitespace-only). Markdown walk runs under `--extract-docs` (globs `**/*.md`, applies `exclude_dirs` + `ignore_filter`). Semantic extraction dispatches per-file with per-file error handling (one file failure doesn't abort the batch). Cache key includes `rel` + `repo_name` to prevent cross-file collisions. Semantic nodes threaded into `loader.load()`.

  14. **`codegraph/pyproject.toml`** — Added `[semantic]` extra (`anthropic>=0.40`). Added `anthropic` to `[test]` extra.

  15. **`codegraph/docs/schema.md`** + **`codegraph/docs/cli.md`** — Documented all 5 new node types (Document, DocumentSection, Concept, Decision, Rationale), 6 new edge types, Phase 11/12 indexing, and `--extract-docs` / `--extract-markdown` / `--repo-name` CLI flags.

  **Code review (8 issues found and fixed across two rounds):**
  - `[HIGH]` `cli.py` name collision: `extract_markdown` bool shadowed by function import of the same name → renamed import to `extract_markdown_doc`.
  - `[HIGH]` Cache key omitted `rel` and `repo_name` → cross-file cache collisions possible → added both to `SemanticCache.cache_key()`.
  - `[HIGH]` Free-text LLM output used raw in node IDs (concept names could contain `#`, `:`, spaces) → `_slugify()` normalises to safe segments; hash suffix added for disambiguation.
  - `[MEDIUM]` `RationaleNode` had no disambiguator when a document has multiple rationales for the same decision → `rationale_index: int` field added.
  - `[MEDIUM]` `semantic_extract.py` fence stripping raised `ValueError` on degenerate ` ``` ` without closing fence → replaced with regex substitution.
  - `[MEDIUM]` `_get_score` used name-based matching for rationales (fragile on LLM paraphrase) → replaced with index-based matching.
  - `[MEDIUM]` `_write_semantic_edges` in loader used unlabeled `MATCH (n)` (full scan) → replaced with label-aware MATCH per edge kind.
  - `[LOW]` `loader.py` `_write_rationales` omitted `rationale_index` from the Cypher SET → added.

  - **Validation:** 974 tests pass (24 new), 11 skipped, 0 failures. Byte-compile clean. Arch-check: 4/4 policies pass.

### docs — PDF document ingestion with outline and page-based section extraction (issue #264)

- `260394c feat(docs)` — Seven files changed (3 new, 4 updated):

  **New files:**

  1. **`codegraph/codegraph/doc_parser.py`** (~230 LOC) — PDF extraction module. `extract_pdf(path, repo_name)` returns a `(DocumentNode, list[DocumentSectionNode])` pair. `_sections_from_outline()` splits content by PDF bookmarks (each bookmark → one `DocumentSectionNode` with the page's extracted text). `_sections_from_pages()` falls back to one section per page when no outline is present. Size guard: files >50 MB are skipped with a warning. Encrypted PDFs: `reader.decrypt("")` attempted; failure raises `ValueError`. Empty-text pages are silently skipped (sequential `section_index` counter prevents ID gaps — one bug found and fixed during review). ISO-8601 `indexed_at` timestamp on every `DocumentNode`. Repo-namespaced IDs: `doc:{repo}:{path}` / `docsec:{repo}:{path}#{section_index}`.

  2. **`codegraph/tests/test_doc_parser.py`** (8 tests) — Covers basic extraction (DocumentNode fields, section count), section IDs sequential, repo namespacing, missing `pypdf` error, ISO-8601 timestamp, path consistency (all sections share doc's path).

  3. **`codegraph/tests/fixtures/docs/sample.pdf`** — 3-page PDF with outline bookmarks (~3 KB), generated from `fpdf2`. Used as the live fixture for all `doc_parser` tests.

  **Updated files:**

  4. **`codegraph/codegraph/schema.py`** — Added `DocumentNode` dataclass (fields: `id`, `path`, `repo`, `page_count`, `title`, `indexed_at`) and `DocumentSectionNode` dataclass (fields: `id`, `doc_id`, `path`, `repo`, `section_index`, `heading`, `text_sample`). Added `HAS_SECTION = "HAS_SECTION"` and `REFERENCES_DOCUMENT = "REFERENCES_DOCUMENT"` edge constants.

  5. **`codegraph/codegraph/loader.py`** — Added `DocumentNode` / `DocumentSectionNode` constraints and indexes in `init_schema()`. Added `documents: int` and `document_sections: int` to `LoadStats`. Added `documents` / `document_sections` params to `load()`. Added `_write_documents(session, documents, document_sections)` helper with batched MERGE for both node types plus `HAS_SECTION` relationship.

  6. **`codegraph/codegraph/cli.py`** — Added `--extract-docs` flag (opt-in, defaults `False`) to `codegraph index`. PDF walk block added to `_run_index()`: globs `**/*.pdf`, applies `exclude_dirs` and `ignore_filter`, calls `extract_pdf()` per file, aggregates results. `documents` / `document_sections` counts propagated through `_flatten_load_stats()` and `_print_load_stats_dict()`.

  7. **`codegraph/pyproject.toml`** — Added `docs = ["pypdf>=4.0"]` optional extra. Added `pypdf` to the `test` extra so tests can import it without `[docs]`.

  **Code review (1 bug found and fixed):**
  - `[BUG]` `_sections_from_pages` used page enumeration index (`idx`) as `section_index`. When empty pages are skipped, this produced non-sequential IDs (e.g. `#0, #2`), breaking the sequential contract and leaving orphan ID slots → replaced `idx` with a `seq` counter that only increments when a section is emitted.

  - **Validation:** 945 tests pass (8 new), 11 skipped, 0 failures. Byte-compile clean. Arch-check: 4/4 policies pass (1 skipped).

### schema — repo-namespaced node IDs to prevent cross-repo overwrite (issue #263)

- `9d19261 feat(schema)` — Nine production files changed, nine test files updated, one new test file:

  **Root cause.** When two repos are indexed into the same Neo4j instance (e.g. a monorepo + a library), `MERGE (f:File {path: $path})` collides on any file that shares a relative path (`src/index.ts`). The same problem existed for `Class`, `Function`, `Method`, `Interface`, `Endpoint`, `Atom`, and `GraphQLOperation` nodes keyed on `#`-qualified paths. The fix namespaces every file-bearing ID with a `repo` segment.

  **New ID format.** All IDs that embed a file path gain a `repo:` segment:
  - `file:myrepo:src/index.ts` (was `file:src/index.ts`)
  - `class:myrepo:src/index.ts#UserService` (was `class:src/index.ts#UserService`)
  - `method:class:myrepo:src/index.ts#UserService#create` (unchanged outer prefix)
  - `endpoint:POST:/users@myrepo:src/ctrl.ts#create` (was `endpoint:POST:/users@src/ctrl.ts#create`)
  - `gqlop:query:ListUsers@myrepo:src/res.ts#listUsers`
  - `route:`, `atom:`, `func:`, `interface:` — same pattern

  **`--repo-name` CLI flag.** New optional flag on `codegraph index` and `codegraph watch`. Defaults to the directory name of the indexed root. Validated to reject `:` and `#` characters that would break ID parsing. Forwarded through `_run_index` → parsers → loader → watcher rebuild subprocess.

  **Files changed:**

  1. **`codegraph/codegraph/schema.py`** — Added `repo: str = "default"` field to `FileNode`, `ClassNode`, `FunctionNode`, `MethodNode`, `InterfaceNode`, `EndpointNode`, `AtomNode`, `GraphQLOperationNode`, `RouteNode`. Each node's `id` property now embeds `self.repo`. `PackageNode.id` uses `f"package:{self.repo}:{self.name}"`.

  2. **`codegraph/codegraph/loader.py`** — All `MERGE` statements that previously keyed on `{path:}` now key on `{id:}` (the repo-namespaced ID). `_file_from_id()` updated to strip the repo segment when extracting the raw file path from any ID shape (handles `file:`, `class:`, `method:`, `endpoint:`, `gqlop:`, `route:` prefixes). `init_schema()` runs a migration step that adds `file_path` as a non-unique index on `:File` after dropping the old unique path constraint. `wipe_scoped()` returns file IDs (not paths) for `delete_file_subgraph()`. Added `file_path` index to `_INDEXES` for legacy-path queries.

  3. **`codegraph/codegraph/cli.py`** — `--repo-name` option on `index` and `watch` sub-commands. Validation guard raises `ConfigError` on `:` or `#` in the value. `effective_repo_name` derived from folder name when flag omitted. File ID construction in incremental-wipe path updated.

  4. **`codegraph/codegraph/resolver.py`** — All cross-file ID constructions (`f"class:{rel}#..."`, `f"func:{rel}#..."`, etc.) updated to embed `repo`. `_caller_id_for_fn` gains a `repo` param. `_find_class` returns raw paths; callers construct the namespaced ID.

  5. **`codegraph/codegraph/py_parser.py`** — `parse_file()` accepts `repo_name: str = "default"`. `FileNode`, `ClassNode`, `FunctionNode`, `MethodNode`, `EndpointNode`, `AtomNode` all receive `repo=repo_name`.

  6. **`codegraph/codegraph/parser.py`** (TS) — Same treatment: `parse_file()` accepts `repo_name`, all node constructors in `_Walker` receive `repo=self.result.file.repo`. `_extract_routes()` also updated.

  7. **`codegraph/codegraph/mcp.py`** — `reindex_file()` constructs a `file_id = f"file:{repo}:{rel}"` and uses `{id: $fid}` for all node `MATCH`/`MERGE` Cypher instead of `{path: $path}`. Parser calls forward `repo_name=repo`.

  8. **`codegraph/codegraph/repl.py`** — `--repo-name` parsed and forwarded to `_run_index`.

  9. **`codegraph/codegraph/watch.py`** — `repo_name` threaded through `run_watch` → `watch` → `_rebuild` → subprocess CLI `--repo-name` flag.

  **New test file:**

  - **`codegraph/tests/test_repo_namespace.py`** (31 tests) — Covers: `file:`, `class:`, `method:`, `endpoint:`, `gqlop:`, `atom:`, `interface:`, `route:` ID format; `_file_from_id` for all prefix shapes including nested `method:class:`; backward-compat IDs without repo segment (defensive path); multi-repo isolation (same path, two repos → two distinct file IDs); `PackageNode` repo isolation; `--repo-name` validation (rejects `:` and `#`).

  **Existing test files updated** (8 files) — Updated hardcoded IDs in `test_incremental.py`, `test_loader_partitioning.py`, `test_loader_pairing.py`, `test_wipe_scoped.py`, `test_confidence.py`, `test_framework.py`, `test_py_parser_calls.py`, `test_py_resolver.py` to include `default:` repo segment.

  **Code review (4 issues found and fixed):**
  - `[MEDIUM]` `_extract_routes()` created `RouteNode` without `repo` → added `repo_name` param, passed from call site.
  - `[MEDIUM]` No validation on `--repo-name` for `:` or `#` chars → added `ConfigError` guard.
  - `[MEDIUM]` Missing `file_path` index after migration drops old uniqueness constraint → added `CREATE INDEX file_path` to `_INDEXES`.
  - `[LOW]` `AtomNode(family="constant")` in test → corrected to `family=True`.

  - **Validation:** 937 tests pass (31 new), 11 skipped, 0 failures. Byte-compile clean. Arch-check: exit 0.

### init — shared codegraph-neo4j container with auto-detect and auto-start

- `1cd47f3 feat(init)` — `codegraph init` now scaffolds a shared `codegraph-neo4j` container (deterministic name across all repos on the machine) rather than one per project. `docker ps` auto-detect: if the container is already running (from another project's init), init skips the `docker run` step and reuses it. Auto-start: if the container exists but is stopped, init runs `docker start codegraph-neo4j`. Docker preflight check included. `--bolt-port` / `--http-port` flags let teams override the default `7688/7475` when those ports are taken.

- `11135f9 fix(init)` — `_DEFAULT_BOLT_PORT` and `_DEFAULT_HTTP_PORT` constants aligned to `7688` and `7475` everywhere (previously `7687`/`7474` in some paths). `NEO4J_BOLT_PORT` and `NEO4J_HTTP_PORT` env-var reads updated to match.

### fix — 5 issues uncovered by the 0.1.102 e2e run

- `0c659f3 fix` — Five separate regressions surfaced during an end-to-end run against a real repo and fixed in a single commit:
  1. `loader.py` — stale `{path: $path}` in one `_write_ownership` query missed by the id-migration sweep.
  2. `resolver.py` — `_resolve_call_target_class` built IDs using bare path (missing repo) in one branch.
  3. `mcp.py` — `reindex_file` EXPOSES edge used `file:` prefix instead of full `file:repo:path` ID.
  4. `cli.py` — `delete_file_subgraph` called with raw path instead of file ID in incremental wipe.
  5. `watch.py` — subprocess CLI call omitted `--repo-name` flag when repo was inferred from folder name.

### audit — agent-driven extraction self-check (`codegraph audit`)

New top-level CLI subcommand and supporting modules. Sibling of `validate` (graph-shape sanity) and `arch-check` (policy gating). Solves a different problem: per-codebase parser bugs that no fixture-based unit test will find — e.g. "this repo uses NestJS but for some custom-decorator reason 5 of the 47 controllers didn't get an `:Endpoint` node".

**Flow.** Verify prompt-template lock → pick agent (interactive or `--agent`) → assemble prompt (filtered to detected frameworks, with sample files + Cypher catalogue) → launch the agent in headless + permission-bypass mode → parse the agent's `codegraph-out/audit-report.md` → optionally `gh issue create --label codegraph-audit`. Read-only at every step; never modifies graph or source.

**Files added:**
- `codegraph/codegraph/audit.py` — orchestrator. Lock check, agent selection, prompt assembly with `string.Template`, subprocess launch, report parsing (`## Issue N` blocks → `AuditFinding` dataclass), `gh issue create` shell-out. `AuditReport` dataclass with `to_json()`.
- `codegraph/codegraph/audit_agents.py` — 7-entry registry: `claude` / `codex` / `gemini` / `aider` / `opencode` / `droid` / `cursor`. `AuditAgent` dataclass holds `binary`, `headless_args`, `permission_bypass_args`, `unsafe_extra` (for codex's no-sandbox flag), `fallback_skill_path` (only Cursor uses it). `build_argv()` composes the launch line.
- `codegraph/codegraph/audit_prompt_lint.py` — three-layer integrity. Lock-file generator (`--update-lock` / `--check-lock`), URL-diff lint (no new external URLs in prompt files), suspicious-call-site lint (no new shell-execution call sites in `audit.py` / `audit_agents.py`), line-count-growth cap (50%). Suspicious patterns are obfuscated at runtime so the source file itself doesn't trip security scanners.
- `codegraph/codegraph/templates/audit/audit-prompt.md` — the master prompt. Seven mandatory sections: role, inputs available, inputs forbidden, extraction inventory (placeholder), files to spot-check (placeholder), methodology (triangulation pass), output schema (machine-parseable), hard non-goals, anti-injection clause.
- `codegraph/codegraph/templates/audit/inventory-python.md` + `inventory-typescript.md` — per-framework inventory snippets. Filtered at runtime to detected frameworks via `MATCH (p:Package) RETURN DISTINCT p.framework`. ~3-5x token reduction vs dumping everything.
- `codegraph/codegraph/templates/audit/cypher-checks.md` — catalogue of triangulation Cypher queries the agent runs.
- `codegraph/codegraph/templates/audit/report-template.md` — skeleton.
- `codegraph/codegraph/templates/audit/.lock` — SHA-256 hashes of all sibling files. Verified at runtime; refuses to launch on mismatch.
- `.github/workflows/audit-prompt-integrity.yml` — CI gate triggered on PRs touching the audit prompt or launcher. Posts a sticky reviewer warning, runs `--check-lock` and `--check-diff`. Defence in depth alongside CODEOWNERS.
- Tests: `tests/test_audit.py` (24 cases), `tests/test_audit_prompt_lint.py` (13 cases). All offline — no agent binaries required, no network.

**Files modified:**
- `codegraph/codegraph/cli.py` — `@app.command() def audit(...)` registration with 11 flags (`--agent`, `--list-agents`, `--print-prompt-only`, `--gh-issue/--no-gh-issue`, `--bypass/--no-bypass`, `--unsafe`, `--timeout`, `--recompute-lock`, `--yes`, `--json`, `--repo`, `--uri`).
- `CODEOWNERS` (root) — explicit entries for `codegraph/codegraph/templates/audit/**`, `audit.py`, `audit_agents.py`, `audit_prompt_lint.py`, and the integrity workflow. Branch-protection "Require code owner review" forces a notification on every change.
- `codegraph/pyproject.toml` — added `templates/audit/.lock` to `[tool.setuptools.package-data]` so the wheel ships the lock file (hidden filename, no `*.lock` glob match).
- `codegraph/README.md`, `codegraph/docs/cli.md`, `CHANGELOG.md` — user-facing docs.

**Permission-bypass philosophy.** The user explicitly opted into bypass by running `codegraph audit`. Without it, the agent would prompt for every `Read` and every `codegraph query` — defeating the unattended audit. Default ON. `--no-bypass` for paranoid users; `--unsafe` is a separate codex-only escape hatch (`--full-auto` is sandboxed; `--dangerously-bypass-approvals-and-sandbox` is not).

**Why not auto-PR?** User stated preference: they have their own implementation workflow and want to triage findings as GitHub issues, not bulk-merge LLM-generated patches.

**Tests:** 867 passing → 904 passing (+37 new). 11 skipped, 0 warnings. ~8s suite.

### install — deduplicate template-var logic into init.py (issue #259)

- `f887f70 refactor(install)` — Three files changed:

  **`codegraph/codegraph/init.py`**:
  - Added `from collections.abc import Sequence` import (alphabetically ordered with other stdlib `from` imports).
  - Added `derive_container_name(root: Path) -> str` public helper (line 59). Encapsulates `_sanitize_container_segment(root.name) + "-" + sha1(str(root.resolve()).encode())[:8]`. Single authoritative definition; previously this formula was duplicated inline in `_prompt_config` and independently in `_build_install_vars` in `cli.py`.
  - Added `build_template_vars(*, root, bolt_port, http_port, package_paths_flags, default_package_prefix, cross_pairs_toml, pipx_version) -> dict[str, str]` public helper (line 255). Returns the full 7-key dict expected by all platform install templates: `NEO4J_BOLT_PORT`, `NEO4J_HTTP_PORT`, `PACKAGE_PATHS_FLAGS`, `DEFAULT_PACKAGE_PREFIX`, `CONTAINER_NAME`, `CROSS_PAIRS_TOML`, `PIPX_VERSION`. Ports default to `DEFAULT_BOLT_PORT` / `DEFAULT_HTTP_PORT` constants when not overridden.
  - `_template_vars(root, config)` refactored to a thin 5-line wrapper over `build_template_vars`.
  - `_prompt_config` updated to call `derive_container_name(root)` instead of inline SHA1 logic.

  **`codegraph/codegraph/cli.py`**:
  - `_build_install_vars(root)` rewritten to delegate to `build_template_vars()` + `derive_container_name()`. Port env-var overrides (`CODEGRAPH_NEO4J_BOLT_PORT`, `CODEGRAPH_NEO4J_HTTP_PORT`) now `int()`-converted (fail-fast on invalid input; default path is safe).
  - Removed `import hashlib` (no longer needed — SHA1 logic lives in `derive_container_name`).

  **`codegraph/tests/test_init.py`**:
  - Added `derive_container_name` and `build_template_vars` to imports.
  - 5 new tests:
    - `test_derive_container_name_is_deterministic` — same root produces same name across two calls.
    - `test_derive_container_name_differs_by_path` — two different roots produce different names.
    - `test_build_template_vars_returns_all_keys` — all 7 expected keys present.
    - `test_build_template_vars_cross_pairs` — `CROSS_PAIRS_TOML` propagated correctly.
    - `test_build_template_vars_custom_ports` — custom bolt/http ports override defaults.

  **Bug fix:** `codegraph install` now consistently uses `DEFAULT_BOLT_PORT` / `DEFAULT_HTTP_PORT` from `init.py` constants when env vars are absent, rather than the previously hardcoded string literals. Eliminates a latent port inconsistency when custom ports were configured.

  **Code review (1 issue found and fixed):**
  - `[STYLE]` `from collections.abc import Sequence` inserted after `from string import Template` — out of alphabetical order → moved before `from dataclasses import ...`.

  - **Validation:** 807 tests pass (5 new), 11 skipped, 0 failures. Byte-compile clean. Arch-check: 4/4 policies pass (1 skipped).

### install — preserve shared AGENTS.md sections during partial uninstall (issue #257)

- `f321b8f fix(install)` — Two files changed:

  **`codegraph/codegraph/platforms.py`**:
  - Added `_MANIFEST_FILE = ".codegraph/platforms.json"` constant.
  - Added `_read_manifest(root) -> set[str]` — reads the manifest JSON into a set of platform names; returns empty set if file is absent or corrupt.
  - Added `_write_manifest(root, platforms: set[str])` — writes the set to JSON; removes the file and its parent directory when the set is empty (clean teardown).
  - Added `_other_installed_share_section(root, name) -> bool` — reads the manifest and checks if any other installed platform shares the same `rules_file` + `rules_marker` as the named platform.
  - Updated `install_platform()` to call `_write_manifest()` on every install (including idempotent re-installs) so the manifest always reflects current state. Manifest write is placed before the "already installed" early-return so even a second install of a platform is properly tracked.
  - Updated `uninstall_platform()` to call `_other_installed_share_section(root, name)` before removing a shared rules section. If another platform still needs the section, removal is skipped with a `[yellow]` warning. The platform is always removed from the manifest regardless.

  **`codegraph/tests/test_platforms.py`** — 5 new tests:
  - `test_uninstall_one_agents_md_platform_preserves_section_for_others` — codex installed alongside aider; uninstalling codex preserves AGENTS.md section; return value does not include "AGENTS.md".
  - `test_uninstall_all_agents_md_platforms_removes_section` — both platforms uninstalled; section removed; manifest file cleaned up.
  - `test_manifest_written_on_install` — manifest created and contains platform name after first install.
  - `test_manifest_cleaned_up_after_last_uninstall` — manifest file absent after last platform uninstalled.
  - `test_uninstall_without_manifest_still_removes_section` — backwards compatibility: uninstall works correctly when no manifest exists (pre-manifest installs).

  **Code review (2 issues found and fixed):**
  - `[MISSING TEST]` `test_uninstall_one_agents_md_platform_preserves_section_for_others` didn't assert the return value — added assertion that `"AGENTS.md"` not in actions list.
  - `[MISSING TEST]` `test_uninstall_all_agents_md_platforms_removes_section` didn't assert manifest cleanup — added `assert not manifest_path.exists()`.

  - **Validation:** 802 tests pass (5 new), 11 skipped, 0 failures. Byte-compile clean. Arch-check: 4/4 policies pass (1 skipped).

### install — resolve all template variables in `codegraph install claude` (issue #256)

- `ea07455 fix(install)` — Three files changed:

  **`codegraph/codegraph/cli.py`**:
  - Added `import hashlib`.
  - Added `_build_install_vars(root)` helper that loads `CodegraphConfig`, derives `PACKAGE_PATHS_FLAGS` (joined `-p` flags from `config.packages`), `DEFAULT_PACKAGE_PREFIX` (first package or `"codegraph"`), `CONTAINER_NAME` (repo name + 8-char path hash), and provides defaults for `CROSS_PAIRS_TOML`, `NEO4J_HTTP_PORT`, `PIPX_VERSION`.
  - Updated `_install_callback` and `_make_install_cmd` to call `_build_install_vars(root)` instead of the inline `{"NEO4J_BOLT_PORT": ...}` one-key dict. Fixes the regression where 6 of 7 template variables were left unresolved as literal `$VAR` strings in the rendered CLAUDE.md.

  **`codegraph/tests/test_platforms.py`**:
  - Expanded `_default_vars()` from 1 key to the full 7-key dict matching all template variables.
  - Added `test_install_claude_no_unresolved_vars` regression test — asserts that no `$VAR` literals remain in the rendered CLAUDE.md after install.
  - Moved `import re` to module level (was inline inside the test function — style inconsistency found during code review).

  **Code review (1 issue found and fixed):**
  - `[LINT]` `import re` was inside the test function body instead of at module level → moved to top-level imports.

  - **Validation:** 797 tests pass (1 new), 11 skipped, 0 failures. Byte-compile clean. Arch-check: 4/4 policies pass (1 skipped).

### install — multi-platform codegraph install command (issue #48)

- `ff0b9e7 feat(install)` — Eleven files created, three updated:

  **New files:**

  1. **`codegraph/codegraph/platforms.py`** (~380 LOC) — Platform registry + install/uninstall logic. `PlatformConfig` dataclass (fields: `name`, `hint_dirs`, `rules_file`, `template`, `hook_file`, `hook_type`, `section_marker`). 14 platform entries: `claude`, `codex`, `opencode`, `cursor`, `gemini`, `copilot`, `vscode`, `aider`, `claw`, `droid`, `trae`, `kiro`, `antigravity`, `hermes`. `_append_section(path, marker, content)` — idempotent section append (no-ops if marker already present). `_remove_section(path, marker)` — strips only the managed `## codegraph` section, preserves all other content, strips leading blank lines correctly. `install_platform(root, name)` / `uninstall_platform(root, name)` — dispatches per platform type: JSON hook injection (claude, gemini), AGENTS.md section (codex, opencode, aider, claw, droid, trae, hermes), `.mdc` rules file (cursor), standalone rules file (kiro, antigravity, vscode, copilot). `install_all(root)` — auto-detects active platforms via hint directories and installs all matching. `list_platforms()` — returns all 14 names.

  2–9. **`codegraph/codegraph/templates/platforms/`** — 8 rule templates:
     - `rules-agents.md` — shared AGENTS.md codegraph section (codex, opencode, aider, claw, droid, trae, hermes)
     - `rules-gemini.md` — `GEMINI.md` section
     - `rules-cursor.mdc` — `.cursor/rules/codegraph.mdc` (Cursor rule format)
     - `rules-kiro.md` — `.kiro/steering/codegraph.md`
     - `rules-antigravity.md` — `.antigravity/codegraph.md`
     - `rules-antigravity-workflow.md` — `.antigravity/workflows/codegraph-query.md`
     - `rules-vscode.md` — `.github/copilot-instructions.md` section
     - `hook-opencode.js` — `.opencode/hooks/codegraph.js` JS hook

  10. **`codegraph/tests/test_platforms.py`** (58 tests) — Covers install/uninstall for all 14 platforms, idempotency, `_remove_section` edge cases (codegraph first, codegraph last, codegraph before other section), `install_all` detection logic, hook content assertions, uninstall hook removal verification.

  **Updated files:**

  11. **`codegraph/codegraph/cli.py`** — Added `install_app` and `uninstall_app` Typer sub-apps. `install_app` exposes one command per platform (14 total) + `codegraph install --all` which calls `install_all()`. `uninstall_app` mirrors it. Both registered on the main `app`.

  12. **`codegraph/codegraph/init.py`** — Added `install_platforms: list[str]` field to `InitConfig`. Non-interactive path defaults to `["claude"]` (backward compatible). Interactive path adds a platform selection prompt after the hooks step. `run_init()` calls `install_platform(root, name)` for each selected platform after `_scaffold_files()`.

  13. **`codegraph/pyproject.toml`** — Added `"templates/**/*.mdc"` to `package_data` (`.md` and `.js` patterns already existed) so the Cursor `.mdc` template ships in the wheel.

  **Code review (5 issues found and fixed):**
  - `[BUG]` `_remove_section` left leading blank lines when codegraph was the first section → `.strip()` instead of `.rstrip()`.
  - `[LINT]` Unused `field` import in `platforms.py:19` → removed.
  - `[MISSING TEST]` `test_uninstall_claude_removes_section_and_hook` didn't verify `.claude/settings.json` hook removal → added assertion.
  - `[MISSING TEST]` `test_uninstall_gemini_removes_section_and_hook` didn't verify `.gemini/settings.json` hook removal → added assertion.
  - `[MISSING TEST]` No test for `_remove_section` when codegraph appears before another section → added `test_remove_section_codegraph_before_other_section`.

  - **Validation:** 796 tests pass (58 new), 11 skipped, 0 failures. Byte-compile clean. Arch-check: 4/4 policies pass. `codegraph install --help` lists all 14 platforms + `--all` flag.

### schema — edge confidence labels on CALLS, IMPORTS, and resolver edges (issue #38)

- `248af58 feat(schema)` — Fifteen files changed (2 new, 13 updated):

  **New files:**

  1. **`codegraph/tests/test_confidence.py`** (10 tests) — Covers `Edge` dataclass defaults (`confidence="EXTRACTED"`, `confidence_score=1.0`), cache-round-trip preservation, and per-strategy confidence assignments (`self`/`super`/bare-function → `EXTRACTED/1.0`, `direct`/`relative` → `EXTRACTED/1.0`, `barrel` → `INFERRED/0.8`, `alias` → `INFERRED/0.9`, `workspace` → `INFERRED/0.85`, `CALLS_ENDPOINT` URL-pattern matching → `INFERRED/0.7`, `RENDERS` JSX component resolution → `INFERRED/0.8`).

  2. **`codegraph/docs/confidence.md`** — New feature documentation: motivation, two-tier taxonomy (`EXTRACTED` / `INFERRED`), per-edge-type classification table, Cypher examples, MCP `calls_from` confidence field.

  **Updated files:**

  3. **`codegraph/codegraph/schema.py`** — Added `confidence: str = "EXTRACTED"` and `confidence_score: float = 1.0` fields to `Edge` dataclass. Both preserved through `parse_result_to_dict` / `parse_result_from_dict` cache serialisation.

  4. **`codegraph/codegraph/resolver.py`** — Added `ResolveResult(path, strategy)` namedtuple; `resolve()` now returns `Optional[ResolveResult]` (was `Optional[str]`). Added `_strategy_confidence(strategy)` helper mapping resolution strategy → `(confidence, confidence_score)`. All cross-file edge-emission sites updated to call `_strategy_confidence` and set confidence fields: IMPORTS (6 strategies), CALLS (direct AST hit vs. class-resolution fallback), CALLS_ENDPOINT (`INFERRED/0.7`), RENDERS (`INFERRED/0.8`), USES_HOOK (`EXTRACTED/0.9`). All other edges (EXTENDS, IMPLEMENTS, INJECTS, MEMBER_OF, etc.) default to `EXTRACTED/1.0` via dataclass defaults. Renamed `props["confidence"]` → `props["resolution"]` on CALLS edges (resolving a naming collision introduced by the new `confidence` field).

  5. **`codegraph/codegraph/loader.py`** — Every `MERGE` in `_write_edges()`, `_write_belongs_to()`, `_write_test_edges()`, `_write_per_file_extras()`, `_write_structural_edges()`, `_write_edge_groups()`, and the ownership edges now uses a named rel variable (`[rel:TYPE]`) and appends `SET rel.confidence = $confidence, rel.confidence_score = $confidence_score` after the MERGE. Structural edges (DEFINES_CLASS, DEFINES_FUNC, HAS_METHOD, etc.) default to `EXTRACTED/1.0`.

  6. **`codegraph/codegraph/validate.py`** — Renamed stale `{confidence:'typed'}` Cypher filter → `{resolution:'typed'}` (3 occurrences).

  7. **`codegraph/codegraph/mcp.py`** — `calls_from` and `callers_of` depth-1 queries now use `[r:CALLS]` named rel variable and return `r.confidence AS confidence, r.confidence_score AS confidence_score`. `reindex_file` edge MERGEs updated to set confidence.

  8. **`codegraph/codegraph/analyze.py`** — MEMBER_OF MERGE updated to `[rel:MEMBER_OF]` + confidence SET (was the only structural MERGE that had escaped the loader update).

  9. **`codegraph/queries.md`** — Stale `{confidence:'typed'}` example in section 8 corrected to `{resolution:'typed'}`.

  10–15. **`codegraph/tests/test_loader_partitioning.py`**, **`test_py_resolver.py`**, **`test_resolver_bugs.py`**, **`test_loader_pairing.py`**, **`test_edgegroup.py`**, **`test_analyze.py`**, **`test_mcp.py`** — Updated to unwrap `ResolveResult.path`, assert named rel variables in captured Cypher, and assert `confidence`/`confidence_score` appear in edge payloads.

  **Code review (8 issues found, 3 real bugs fixed):**
  - `[HIGH]` `validate.py:345` — stale `{confidence:'typed'}` Cypher would return 0 rows → renamed to `{resolution:'typed'}`.
  - `[HIGH]` `analyze.py:458` — MEMBER_OF MERGE missing `[rel:]` variable + confidence SET → added.
  - `[MEDIUM]` `queries.md:121` — stale `{confidence:'typed'}` example query → renamed.
  - `[ACCEPTED]` DISTINCT with `r.confidence` in `calls_from`/`callers_of` — no real dedup issue for depth-1 queries.
  - `[ACCEPTED]` Confidence levels for `_find_class` edges and `USES_OPERATION` — explicit plan decisions.
  - `[ACCEPTED]` `USES_HOOK` score 0.9 — plan decision.

  - **Validation:** 738 tests pass (12 new), 11 skipped, 0 failures. Arch-check: 4/4 policies pass (1 skipped).

### schema — hyperedge :EdgeGroup for protocol-implementer sets (issue #39)

- `a6bcbe6 feat(schema)` — Seven files changed (2 new, 5 updated):

  **New files:**

  1. **`codegraph/tests/test_edgegroup.py`** (12 tests) — Covers `EdgeGroupNode` schema dataclass, `MEMBER_OF` edge constant, resolver protocol-implementer group emission, loader `_write_edge_groups()` persistence and stale-group cleanup, incremental-mode MEMBER_OF survival after DETACH DELETE, and `describe_group()` MCP tool.

  2. **`codegraph/docs/hyperedges.md`** — New feature documentation: motivation, schema, Cypher examples, and limitations.

  **Updated files:**

  3. **`codegraph/codegraph/schema.py`** — Added `EdgeGroupNode` dataclass (fields: `id`, `kind`, `label`, `member_ids: list[str]`) and `MEMBER_OF = "MEMBER_OF"` edge-type constant.

  4. **`codegraph/codegraph/resolver.py`** — Added protocol-implementer grouping post-pass in `link_cross_file()`. After all edges are resolved, classes that implement the same protocol are collected into an `EdgeGroupNode`. Return type changed from `list[Edge]` to `tuple[list[Edge], list[EdgeGroupNode]]`.

  5. **`codegraph/codegraph/cli.py`** — Unpacks the new tuple return from `link_cross_file()`; passes `edge_groups` list to `loader.load()`.

  6. **`codegraph/codegraph/loader.py`** — Added `_write_edge_groups(session, edge_groups)` with `MERGE`-based upsert and stale-group cleanup (deletes `EdgeGroup` nodes whose `member_ids` no longer match). Added `edge_groups` and `member_of_edges` stats counters. Fixed incremental-mode bug: `MEMBER_OF` edges for unchanged files were being lost after `DETACH DELETE` of stale subgraphs — now re-written unconditionally after each incremental pass.

  7. **`codegraph/codegraph/mcp.py`** — Added `describe_group(group_id)` MCP tool (tool #17). Returns group label, kind, member count, and the list of member node IDs from the graph.

  8. **`codegraph/queries.md`** — Section 13: Hyperedges / group relationships. Three Cypher examples: list all groups, members of a specific group, find nodes belonging to multiple groups.

  - **Validation:** 726 tests pass (12 new), 10 skipped, 0 failures. Byte-compile clean. Arch-check: 4/4 policies pass.

### analyze — Leiden community detection and graph analysis (issue #42)

- `c8d4ad2 feat(analyze)` — Seven files changed (3 new, 4 updated):

  **New files:**

  1. **`codegraph/codegraph/analyze.py`** (~310 LOC) — Core analysis module. `read_graph(driver, scope)` fetches all nodes + edges from Neo4j into a `networkx.MultiDiGraph`. `partition_graph(G)` runs Leiden community detection (via `graspologic`) with an edge-count guard to handle the `EmptyNetworkError` on single-node or no-edge graphs. `compute_metrics(G, partition)` computes betweenness centrality (approximate, with `EmptyNetworkError` guard), degree centrality, and identifies bridge nodes (nodes whose removal increases connected components). `surprising_connections(G, partition)` returns cross-community edges ranked by a scoring function that rewards cross-package (+2) and unexpected structural coupling (high shared betweenness); deduplicates per unordered pair, keeping highest-scoring edge. `suggest_questions(G, partition, metrics)` generates high-value Cypher questions for the detected communities and bridges; `node_to_cid` map is hoisted outside the loop (O(n) not O(n²)). `persist_communities(driver, partition, metrics)` writes `community_id`, `betweenness_centrality`, and `degree_centrality` back to nodes using UNWIND batching (2 queries total regardless of graph size). `AnalysisResult` dataclass holds all outputs. `run_analysis(driver, scope)` is the CLI entry point.

  2. **`codegraph/codegraph/report.py`** (~100 LOC) — Rich console printer. `print_analysis_summary(result)` renders community table (id, size, top 3 nodes by betweenness), bridge nodes, surprising connections, and suggested Cypher questions. `print_analysis_verbose(result)` adds full community membership and per-node centrality scores. `write_analysis_json(result, path)` serialises `AnalysisResult` to JSON. Imports wrapped in `try/except ImportError` for user-friendly error when `[analyze]` extra not installed.

  3. **`codegraph/tests/test_analyze.py`** (18 tests) — Fixture-based, no Neo4j or real graph required. Covers `read_graph` (scoped + unscoped), `partition_graph` (multi-node, single-node edge-case, empty graph), `compute_metrics` (bridge detection, centrality), `surprising_connections` (cross-package boost, dedup keeps highest score), `suggest_questions`, `persist_communities` (UNWIND query shape), `run_analysis` happy path. All tests guarded via `pytest.importorskip("networkx")` / `pytest.importorskip("graspologic")`.

  **Updated files:**

  4. **`codegraph/pyproject.toml`** — Added `analyze` optional extra: `graspologic>=3.4; python_version < '3.13'`, `networkx>=3.0`. Install via `pip install "codegraph[analyze]"`.

  5. **`codegraph/codegraph/config.py`** — Added `analyze: bool = True` field to `CodegraphConfig`. Parsed from `[analyze]` key in `codegraph.toml` / `pyproject.toml`. `merge_cli_overrides` honours `--no-analyze` flag.

  6. **`codegraph/codegraph/loader.py`** — Added `EdgeGroup` constraint + index on `(source_id, target_id, edge_type)` — ensures no duplicate structural edges survive a reload. Added `community_id`, `betweenness_centrality`, `degree_centrality` property constraints to `File`/`Class`/`Function`/`Method` nodes.

  7. **`codegraph/codegraph/cli.py`** — Added `--no-analyze` flag to `codegraph index`; auto-runs `run_analysis` after successful index (failures are warnings, never blocking). Scope auto-resolved from config (mirrors benchmark/export pattern: `load_config` → `merge_cli_overrides`). Added `codegraph report` standalone subcommand with `--json`, `--verbose`, `--scope`, `--out` flags (mirrors `codegraph benchmark` pattern). Eager `from analyze import ...` guarded with try/except + user-friendly error when `[analyze]` extra not installed.

  **Code review (13 issues found, 11 fixed):**
  - `[HIGH]` `networkx` missing from test extra → `pytest.importorskip("networkx")` guards in every test.
  - `[MEDIUM]` Unbatched `persist_communities` (N+2 queries per community) → UNWIND batching (2 queries total).
  - `[MEDIUM]` `node_to_cid` rebuilt per `suggest_questions` loop iteration → hoisted outside loop.
  - `[MEDIUM]` `surprising_connections` dedup dropped higher-scoring edges → `best_per_pair` dict keeps highest.
  - `[MEDIUM]` Auto-analyze scope not resolved from config → mirrors `load_config`/`merge_cli_overrides` pattern.
  - `[MEDIUM]` No test for `read_graph` → added 2 tests (scoped + unscoped).
  - `[LOW]` Unused `import os` → removed.
  - `[LOW]` CALLS mislabeled as "rare edge type" → removed CALLS bonus, renamed to "structural coupling".
  - `[LOW]` Small-graph threshold too aggressive → min threshold raised to 6.
  - `[LOW]` Eager import in `report` subcommand without error handling → try/except with friendly message.
  - `[ACCEPTED]` Thread-unsafe stdout redirect in `report` — CLI-only tool, acceptable.
  - `[ACCEPTED]` `config.analyze` field not gating auto-step — consistent with export/benchmark (no config field gates auto-steps); available for programmatic use.
  - `[ACCEPTED]` Bare `except Exception: pass` on betweenness — degenerate graph guard; betweenness is non-critical.

  - **Validation:** 732 tests pass (18 new), 10 skipped, 0 failures. Byte-compile clean. Arch-check: 4/4 policies pass. `codegraph analyze --help` and `codegraph report --help` verified. Edge-count guard confirmed by single-node test.

### benchmark — token-reduction benchmark command (issue #43)

- `09f9d8a feat(benchmark)` — Four files changed (2 new, 2 updated):

  **New files:**

  1. **`codegraph/codegraph/benchmark.py`** (~300 LOC) — Core benchmark module. `_estimate_tokens(text)` uses tiktoken (BPE) if available, otherwise chars/4 fallback. `count_corpus_tokens(paths)` tallies total tokens across source files. `_BENCHMARK_QUERIES` — 8 canonical Cypher queries (class overview, method signature, callers-of, package overview, endpoint mapping, class hierarchy, file structure, interface contracts). `_format_context_block(records)` renders query results as a compact text block. `BenchmarkResult` dataclass: stores `corpus_tokens`, `context_tokens`, `reduction_pct`, `query_results`, and an `ok` property (True when `reduction_pct >= min_reduction`). `to_json()` explicitly includes `ok` in the dict (not just dataclass fields via `asdict`). `run_benchmark(driver, scope, min_reduction)` runs all 8 queries in a single Neo4j session (not one per query). `print_benchmark_summary()` / `print_benchmark_verbose()` Rich console printers. `write_benchmark_json()` file writer.

  2. **`codegraph/tests/test_benchmark.py`** (17 tests) — Token estimation (chars/4 and tiktoken branches, guarded by `skipif(_USING_TIKTOKEN)`), context formatting, corpus counting, `run_benchmark` with fake drivers (happy path, empty graph, partial queries), `BenchmarkResult` serialisation (`ok` present in JSON), CLI subcommand (`--json`, `--min-reduction` pass/fail, service unavailable), benchmark.json file writing.

  **Updated files:**

  3. **`codegraph/codegraph/cli.py`** — Added `benchmark` subcommand (mirrors arch-check pattern): `--json`, `--verbose`, `--min-reduction` (default 80%), `--scope`/`--no-scope`, `--out`. Integrated benchmark into `codegraph index` as a non-fatal post-index step (prints summary by default); suppressed with new `--no-benchmark` flag. Failures emit a warning, never block the index.

  4. **`codegraph/pyproject.toml`** — Added `benchmark` optional extra with `tiktoken>=0.7`. Install via `pip install "codegraph[benchmark]"`.

  **Code review (4 issues found and fixed):**
  - `[BUG]` `BenchmarkResult.to_json()` used `asdict()` which excludes `@property ok` — JSON output missing `ok` key → construct dict explicitly with `d["ok"] = self.ok`.
  - `[CLEANUP]` Unused `from typing import Any` import in `benchmark.py` → removed.
  - `[CODE QUALITY]` `run_benchmark()` opened 8 separate Neo4j sessions (one per query) → moved session creation outside the loop (matches `arch_check.py` pattern).
  - `[TEST BUG]` Token estimator tests hard-coded chars/4 expectations — would fail if tiktoken installed → added `skipif(_USING_TIKTOKEN)` guards + tokenizer-agnostic test variants.

  - **Validation:** 714 tests pass (17 new), 10 skipped, 0 failures. Byte-compile clean. Arch-check: 4/4 policies pass (scoped to codegraph+tests). `codegraph benchmark --help` and `codegraph index --help` verified.

### export — interactive HTML + GraphML graph export command (issue #44)

- `6c45b48 feat(export)` — Five files changed (3 new, 2 updated):

  **New files:**

  1. **`codegraph/codegraph/export.py`** (~340 LOC) — Core export module. `dump_graph(driver, scope, max_nodes)` fetches nodes+edges from Neo4j; `to_html(nodes, edges, max_nodes)` renders a self-contained HTML page with a vendored vis-network graph (14 colour groups by label); `to_json(nodes, edges)` dumps JSON; `to_graphml(nodes, edges)` serialises to GraphML using `xml.dom.minidom` + `quoteattr` for XSS-safe attribute values; `to_cypher(nodes, edges)` emits `MERGE` statements. Convenience `*_from_driver` wrappers round-trip through `dump_graph`. `_js_safe()` escapes all `<` as `\u003c` so embedded JSON can't break out of a `<script>` block.

  2. **`codegraph/codegraph/templates/vis-network.min.js`** — Vendored vis-network v9.1.9 (689 KB). Self-contained, zero CDN dependency; HTML output works offline.

  3. **`codegraph/tests/test_export.py`** (19 tests) — Fixture-based, no Neo4j required. Covers `dump_graph` (happy + too-many-nodes), `to_html` (script tag, colour map, XSS, max-nodes guard), `to_json`, `to_graphml` (structure, quote-in-ID regression), `to_cypher`, `_js_safe`, `to_html_from_driver`, `to_graphml_from_driver`.

  **Updated files:**

  4. **`codegraph/codegraph/cli.py`** — Added `codegraph export` subcommand with `--out`, `--html/--no-html`, `--json-export/--no-json-export`, `--graphml`, `--cypher`, `--scope`, `--max-nodes` flags. Added `--no-export` flag to `codegraph index`; on successful index, auto-runs HTML export (failures are warnings, never blocking). `MAX_NODES_FOR_VIZ` dead import removed; `max_nodes` threaded as a parameter to `to_html` to avoid thread-unsafe global mutation.

  5. **`codegraph/pyproject.toml`** — Added `"templates/**/*.js"` to `package_data` so the vendored JS ships in the wheel.

  **Code review (4 issues found and fixed):**
  - `[HIGH]` GraphML XML injection — `xml_escape()` didn't escape `"` in attribute values → switched to `xml.sax.saxutils.quoteattr()`.
  - `[HIGH]` Thread-unsafe global mutation of `MAX_NODES_FOR_VIZ` to override limit → added `max_nodes` parameter to `to_html()`.
  - `[MEDIUM]` Dead import `MAX_NODES_FOR_VIZ` in `cli.py` → removed.
  - `[MEDIUM]` HTML-too-large error silently swallowed in `--json` mode → added `warnings` list to JSON output.

  - **Validation:** 695 tests pass (19 new), 10 skipped, 0 failures. `python -m compileall` clean. Arch-check: 4/4 policies pass. `codegraph export --help` and `codegraph index --help` verified.

### cache — prune stale cache entries after manifest save (issue #247)

- `28f816f feat(cache)` — Two files changed (1 updated, 1 updated):

  **Updated files:**

  1. **`codegraph/codegraph/cache.py`** — Added `AstCache.prune_stale(old_manifest, new_manifest) -> int` method (~12 LOC). Computes `set(old_manifest.values()) - set(new_manifest.values())` (stale content hashes) then unlinks the corresponding `.json` files from the cache directory. Tolerates missing files via `except OSError: pass`. Returns count of actually-deleted files.

  2. **`codegraph/codegraph/cli.py`** — Calls `cache.prune_stale(cached_manifest, manifest)` after `save_manifest`, guarded by `max_files is None` (same guard as save) to avoid false deletions when `--max-files` truncates. Appends `{pruned} pruned` to the existing cache log line.

  **New tests (`codegraph/tests/test_cache.py`, lines 165–196)** — 3 new tests:
  - `test_prune_stale_removes_orphan_entries` — orphan `.json` removed, survivor preserved, return value == 1.
  - `test_prune_stale_no_op_when_manifests_equal` — identical manifests → returns 0, no files removed.
  - `test_prune_stale_tolerates_missing_file` — stale hash with no on-disk file → no crash, returns 0.

  **Code review (0 issues):** Path traversal risk assessed (hash values are SHA-256 hex digests — no path separators). Ordering is correct (save_manifest before prune_stale — on crash during prune, manifest is intact and orphans are harmless debris). Guard `max_files is None` consistent with save guard.

  - **Validation:** 676 tests pass, 10 skipped, 0 failures. Arch-check: 4/4 policies pass (1 skipped).

### init — append `.codegraph-cache/` to `.gitignore` on `codegraph init` (issue #246)

- `2ecf12a feat(init)` — Three files changed (2 updated, 0 new):

  **Updated files:**

  1. **`codegraph/codegraph/init.py`** — Added `_ensure_gitignore_entry(root, console)` helper (~30 LOC, mirrors `_append_claude_md` pattern). Creates `.gitignore` if absent; appends `# codegraph\n.codegraph-cache/` with blank-line separator if the entry is missing; skips silently if already present. Handles missing trailing newline. Called unconditionally from `_scaffold_files()` after the CLAUDE.md append step.

  2. **`codegraph/tests/test_init.py`** — 4 new unit tests + 2 assertion additions:
     - `test_scaffold_creates_gitignore_with_cache_entry` — no pre-existing `.gitignore`; file created with entry.
     - `test_scaffold_appends_cache_entry_to_existing_gitignore` — pre-existing entries preserved; new entry appended.
     - `test_scaffold_gitignore_cache_entry_is_idempotent` — second `_scaffold_files()` call produces identical content (no duplication).
     - `test_scaffold_gitignore_no_trailing_newline` — handles `.gitignore` with missing trailing `\n`.
     - Added `.gitignore` content assertion to `test_init_scaffold_only_no_docker` (integration).
     - Added `.gitignore` content assertion to `test_run_init_non_interactive_happy_path`.

  **Code review (0 issues):** Match logic uses `line.strip() == entry` so commented lines don't false-match. Trailing newline detection consistent with `_append_claude_md`. Empty-file cosmetic quirk (two leading newlines) matches existing codebase behaviour — not fixed.

  - **Validation:** 673 tests pass, 10 skipped, 0 failures. Arch-check: 4/4 policies pass (1 skipped). `codegraph init` in a fresh tmp dir now creates `.gitignore` containing `.codegraph-cache/`.

### cache — SHA-256 content-addressed AST cache for `--update` flag (issue #46)

- `2b0d78a feat(cache)` — Six files changed (2 new, 4 updated):

  **New files:**

  1. **`codegraph/codegraph/cache.py`** (~130 LOC) — `AstCache` class backed by a `.codegraph-cache/` directory. `file_content_hash(path)` computes SHA-256 of file bytes. `get(path, content_hash)` deserialises a cached `ParseResult` if the stored hash matches; returns `None` on miss or corrupt entry. `put(path, content_hash, result)` atomically writes via `.tmp` file (renamed on success; cleaned up on failure). `invalidate(path)` removes a single entry. `clear()` removes all cached entries and the manifest, including any orphan `.tmp` files. Cache directory defaults to `<repo>/.codegraph-cache/`; added to `.gitignore`.

  2. **`codegraph/tests/test_cache.py`** (11 tests) — `file_content_hash` basic hash, same-content idempotency, changed-content diff. `AstCache.get` miss (no file), hit (valid cache), stale (hash mismatch), corrupt (malformed JSON). `AstCache.put` round-trip, atomic-write failure cleanup. `AstCache.invalidate`. `AstCache.clear` (removes entries + manifest).

  **Updated files:**

  3. **`codegraph/codegraph/schema.py`** — Added `parse_result_to_dict(result)` and `parse_result_from_dict(d)` serialisation helpers. All node/edge dataclasses serialise to plain `dict` (JSON-safe). Round-trip tested via `test_cache.py`.

  4. **`codegraph/codegraph/cli.py`** — Added `--update` flag to `codegraph index`. Mutually exclusive with `--since` (raises `ConfigError`). When `--update` is set: instantiates `AstCache`, checks SHA-256 before parsing each file (cache hit skips tree-sitter entirely), writes result to cache after a parse, skips `deleted_files` stale-subgraph cleanup when `--max-files` is active to avoid false deletions. `--update` implies `--no-wipe`.

  5. **`codegraph/tests/test_incremental.py`** — 3 new integration tests: `--update` skips unchanged files on second run, `--update` re-parses files whose content changed, `--update` + `--since` raises an error.

  6. **`.gitignore`** — Added `.codegraph-cache/` entry.

  **Code review (8 issues found and fixed):**
  - `[HIGH]` `--since` + `--update` not mutually exclusive → added `ConfigError` guard.
  - `[MEDIUM]` `.codegraph-cache/` not in `.gitignore` → added.
  - `[MEDIUM]` `put()` left orphan `.tmp` on serialisation failure → added try/except cleanup.
  - `[MEDIUM]` `max_files` truncation caused false "deleted" entries → skip deletion when `--max-files` set.
  - `[LOW]` `clear()` didn't remove `.tmp` files → added `*.tmp` glob.
  - `[LOW]` Unnecessary `# type: ignore` and `# noqa: F811` → removed.
  - `[MEDIUM]` No test for corrupt cache entry → added `test_cache_get_corrupt_file_returns_none`.
  - `[LOW]` `clear()` test didn't verify manifest removal → added assertion.

  - **Validation:** 667 tests pass, 10 skipped, 0 failures. Byte-compile clean. Arch-check: 4/4 policies pass (1 skipped). `codegraph index --help` shows `--update` flag.

### test — add watchdog to test extra so test_watch.py tests pass

- `3f394de fix(test)` — One file changed:

  **`codegraph/pyproject.toml`** — Added `watchdog>=4.0` to the `[test]` optional extra so that `pip install "codegraph[test]"` pulls in watchdog and `test_watch.py` doesn't skip. Previously watchdog was only in `[watch]`, causing CI environments that install `[test]` to skip all 19 watch tests silently.

### watch + hooks — `codegraph watch` and `codegraph hook` commands (issue #47)

- `be939bc feat(watch,hooks)` — Six files changed (4 new, 2 updated):

  **New files:**

  1. **`codegraph/codegraph/hooks.py`** (~190 LOC) — Git hook install/uninstall/status. `git_root()` walks up from CWD; `hooks_dir()` returns `.git/hooks/`. `install(repo, hooks)` writes marker-delimited `### codegraph:begin/end ###` sections into each hook script — idempotent (replaces existing section on re-run), preserves foreign content, inserts shebang + `set -e` when creating fresh. `uninstall(repo, hooks)` strips only the managed section. `status(repo)` reports installed/not-installed per hook. All three raise `RuntimeError` outside a git repo. Interpreter is detected from `sys.executable`. Rebase/merge guard (`ORIG_HEAD`/`MERGE_HEAD`) skips re-indexing when git is mid-operation.

  2. **`codegraph/codegraph/watch.py`** (~130 LOC) — Watchdog-based file watcher with debounce. `WATCH_EXTENSIONS = {".py", ".ts", ".tsx"}`. `_RebuildHandler` (subclasses `FileSystemEventHandler`) filters events by extension and dotpath; accumulates pending paths; after `debounce_s` seconds of quiet calls `_rebuild()`. `_rebuild()` spawns `codegraph index <repo> --since HEAD --json [--uri ...] [--user ...] [--password ...] [-p ...]` as a subprocess — all connection params and package filters forwarded. `watch()` starts the Observer; `run_watch()` is the CLI entry point. Import guard: `watchdog` import is deferred inside functions so the module can be imported without `watchdog` installed (enables testing without the extra).

  3. **`codegraph/tests/test_hooks.py`** (~160 LOC, 19 tests) — `git_root`, `hooks_dir`, install (fresh/idempotent/append to existing), uninstall (clean section / preserve foreign content), status (installed/not-installed), error cases (non-git dir, missing `.git/hooks`).

  4. **`codegraph/tests/test_watch.py`** (~140 LOC, 19 tests + 1 new param-forwarding test) — constants, `_RebuildHandler` filtering (accept/reject by extension / dotpath / directory events), debounce logic, rebuild subprocess invocation, connection param forwarding (`--uri`/`--user`/`--password`/`-p` reach the subprocess), import guard.

  **Updated files:**

  5. **`codegraph/codegraph/cli.py`** — Added `hook` Typer sub-app with three commands (`hook install`, `hook uninstall`, `hook status`). Each wraps the corresponding `hooks.*` function and catches `RuntimeError` cleanly (exit code 1 + error message) rather than tracebacks. Added `watch` command with `--debounce / --package / --uri / --user / --password` options; all connection params forwarded through to `_rebuild()`.

  6. **`codegraph/codegraph/init.py`** — Added `install_hooks: bool = True` to `InitConfig`. Interactive prompt added after Neo4j setup step. `run_init()` calls `hooks.install()` after `_scaffold_files()` when `config.install_hooks` is `True`. Wrapped in try/except to gracefully handle non-git repos.

  **Code review (3 issues found and fixed):**
  - `[HIGH]` `--uri/--user/--password/--package` silently ignored by `codegraph watch` — `_rebuild()` now accepts and forwards all connection params + package filters to the subprocess command.
  - `[MEDIUM]` `codegraph hook install/uninstall` produced Python tracebacks outside a git repo — wrapped in `try/except RuntimeError` with clean error message + exit code 1.
  - `[LOW]` Unused `MagicMock` import in `test_hooks.py` — removed.

  **`pyproject.toml`** — Added `watch = ["watchdog>=4.0"]` optional extra. Install via `pip install "codegraph[watch]"`.

  - **Validation**: 652 tests pass, 0 failures, byte-compile clean. `codegraph hook --help` shows install/uninstall/status. `codegraph watch --help` shows all expected options.

### mcp — fix README MCP tool table to document all 16 tools (issue #237)

- `730122e docs(mcp)` — One file changed: **`README.md`**

  Three targeted edits with zero code changes:

  1. **Fixed intro count** — "Five tools" → "16 tools" on the paragraph introducing the quick-reference table (line 117). The number "Five" was left over from an early draft and had fallen far behind the actual tool count.

  2. **Updated `callers_of_class` signature** — Added `file` and `limit` params to match PR #242 (shipped in `435f007`). Old row showed `callers_of_class(class_name, max_depth)`, correct signature is `callers_of_class(class_name, file, max_depth, limit)`.

  3. **Added 5 missing tool rows** — `describe_function(name, file, limit)`, `calls_from(name, file, max_depth, limit)`, `callers_of(name, file, max_depth, limit)`, `reindex_file(path, package)`, `wipe_graph(confirm)`. Table now has 16 rows matching all 16 `@mcp.tool()` decorators in `mcp.py`.

  - **Validation**: All 16 tool signatures verified against `mcp.py` source. "16 tools" appears on lines 117 and 138. Table row order follows registration order in `mcp.py` (read tools first, then write tools). Write tools note `--allow-write` requirement. Code review: 0 issues. Tests: 613 passed, 10 skipped. Arch-check: 4/4 policies pass (1 skipped).

### mcp — add class_name to find_function results (issue #241)

- `b133484 feat(mcp)` — Two files changed:

  1. **`codegraph/codegraph/mcp.py`** — Added `OPTIONAL MATCH (c:Class)-[:HAS_METHOD]->(n)` between the main `MATCH`/`WHERE` clause and the `RETURN` in `find_function`. Projected `c.name AS class_name` in the `RETURN` clause. Standalone functions return `class_name: null`; methods return the owning class name. Uses `OPTIONAL MATCH` (not `MATCH`) so functions with no owning class still appear in results.

  2. **`codegraph/tests/test_mcp.py`** — Updated `test_find_function_happy_path`: mock data for the Function row now includes `class_name: None`, mock data for the Method row includes `class_name: "RequestParser"`. Added assertions `assert out[0]["class_name"] is None` and `assert out[1]["class_name"] == "RequestParser"`.

  - **Code review**: 0 issues. Tests: 613 passed, 10 skipped, 1 deselected. Arch-check: 4/4 policies pass (1 skipped).

### mcp — add file filter and limit params to callers_of_class (issues #64 + #239)

- `435f007 feat(mcp)` — Two files changed:

  1. **`codegraph/codegraph/mcp.py`** — Added `file: Optional[str] = None` parameter to `callers_of_class` for class-name disambiguation (closes #64). Added `limit: int = 50` parameter with `_validate_limit()` guard to cap result sets (closes #239). Rewrote Cypher to split `MATCH` + `WHERE $file IS NULL OR target.file = $file` (mirrors `callers_of` pattern). Added `LIMIT {limit}` to the `ORDER BY` clause. Threaded `file=file` into `_run_read` bind params.

  2. **`codegraph/tests/test_mcp.py`** — Three tests updated/added:
     - Updated `test_callers_of_class_default_depth` to assert `file: None` in default params.
     - `test_callers_of_class_with_file_filter` — asserts `file` param reaches Cypher bind params.
     - `test_callers_of_class_rejects_bad_limit` — asserts `limit=0` returns a validation error.

  - **Code review**: 0 issues. Tests: 613 passed (2 new), 10 skipped. Arch-check: 4/4 policies pass (1 skipped).

### mcp — add limit parameter to describe_function (issue #67)

- `bfa427b fix(mcp)` — Two files changed:

  1. **`codegraph/codegraph/mcp.py`** — Added `limit: int = 50` parameter to `describe_function`. Guarded with existing `_validate_limit()`. Added `LIMIT {limit}` to the Cypher query. Matches the bounded-result-set pattern already in `find_function`, `calls_from`, `find_class`, and every other multi-row tool.

  2. **`codegraph/tests/test_mcp.py`** — Two new tests:
     - `test_describe_function_rejects_bad_limit` — verifies `limit=0` returns an error dict.
     - `test_describe_function_interpolates_custom_limit` — verifies `limit=10` appears in the generated Cypher.

  - **Code review**: 0 issues. Tests: 611 passed (2 new), 0 failures. Arch-check: 4/4 policies pass (1 skipped).

### mcp — add find_function tool (issue #68)

- `ab23363 feat(mcp)` — Four files changed:

  1. **`codegraph/codegraph/mcp.py`** — New `find_function(name_pattern, limit)` tool inserted after `find_class` (line 524). Cypher: `MATCH (n) WHERE (n:Function OR n:Method) AND n.name CONTAINS $name_pattern RETURN DISTINCT labels(n)[0] AS kind, n.name, n.file, n.docstring, n.return_type ORDER BY n.file, n.name LIMIT {limit}`. Returns `kind` (discriminates `Function` vs `Method`), `name`, `file`, `docstring`, `return_type`. Backed by existing `func_name` and `method_name` indexes (loader.py:121-122). Uses same `_validate_limit()` guard and `$name_pattern` bind parameter as sibling tools — no injection surface.

  2. **`codegraph/tests/test_mcp.py`** — 3 dedicated tests: `test_find_function_happy_path` (Cypher content + param assertions), `test_find_function_rejects_empty_pattern`, `test_find_function_rejects_bad_limit`. `find_function` lambda added to both `test_new_tools_surface_client_error` and `test_new_tools_surface_service_unavailable` parametrized lists.

  3. **`codegraph/tests/test_py_parser.py`** — Tool decorator count bumped 15 → 16.

  4. **`codegraph/tests/test_loader_partitioning.py`** — Function decorator count bumped 15 → 16.

  - **Code review**: 0 issues. Tests: 609 passed (5 new), 10 skipped, 1 deselected. Arch-check: 4/4 policies pass (1 skipped).

### mcp — loosen queries.md count assertion to tolerate additions (issue #69)

- `5573811 test(mcp)` — One file changed:

  1. **`codegraph/tests/test_mcp.py`** (lines 719–724) — Three-line change:
     - Updated docstring: "exactly 29 entries" → "at least 29 entries and include known blocks".
     - Changed count assertion from `== 29` to `>= 29` — tolerates future additions to `queries.md` without breaking CI, still catches accidental mass deletions.
     - Added smoke-check: `assert "schema-overview" in names` — verifies `_register_query_prompts()` actually parsed `queries.md` (anchored to `## Schema overview` at line 10, which `_slugify` converts to `"schema-overview"` — independently tested at line 761).

  - **Code review**: 0 issues. Tests: 604 passed, 10 skipped. Arch-check: 4/4 policies pass (1 skipped).

### mcp — push query_graph limit into Cypher to avoid fetching all rows (issues #71 + #65)

- `fa1a439 fix(mcp)` — Two files changed:

  1. **`codegraph/codegraph/mcp.py`** — Added `limit: int | None = None` keyword-only parameter (after `*`) to `_run_read()`. Records are now sliced (`records = records[:limit]` guarded by `if limit is not None`) *before* `clean_row()` is called in the comprehension, so discarded rows are never deserialised or serialised. Updated `query_graph()` from `_run_read(cypher)[:limit]` to `_run_read(cypher, limit=limit)`. All 14 existing `_run_read()` call sites use `**params` as keyword args — the `*` separator is fully backwards-compatible.

  2. **`codegraph/tests/test_mcp.py`** — Strengthened `test_query_graph_respects_limit` to assert the *correct* first N rows are returned (not just the count). Added `test_run_read_limit_slices_before_clean` (verifies `clean_row` is called exactly `limit` times, not N-then-slice) and `test_run_read_no_limit_returns_all` (verifies `limit=None` default returns all rows).

  - **Code review**: 0 issues. Tests: 604 passed (2 new + 1 strengthened), 10 skipped. Arch-check: 4/4 policies pass (1 skipped).

---

## Previously shipped (through commit `88eeabb`)

### init — sanitize directory names with special chars in container names (issue #74)

- `b4d8a25 fix(init)` — Two files changed:

  1. **`codegraph/codegraph/init.py`** — Added `import re`. Added `_sanitize_container_segment(name: str) -> str` helper that: replaces any character not in `[a-zA-Z0-9_.-]` with `-`; collapses consecutive `-` into one; strips leading/trailing `-` and `.`; falls back to `"repo"` if the result is empty. Applied at both container-name construction call sites — `_prompt_config` (segment before hash suffix) and `_warn_orphaned_containers` (old-scheme prefix comparison). Closes issue #74.

  2. **`codegraph/tests/test_init.py`** — Added `_sanitize_container_segment` to imports. 5 unit tests: spaces/special chars replaced with `-`, consecutive dashes collapsed, leading/trailing dashes/dots stripped, valid name passes through unchanged, empty-after-strip falls back to `"repo"`. 2 integration tests through `_prompt_config`: container name with a special-char dir is Docker-valid (`re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*", ...)`), and the segment value matches `_sanitize_container_segment(root.name)`.

  - **Code review**: 0 issues. Tests: 602 passed (7 new), 10 skipped. Arch-check: 4/4 policies pass (1 skipped).

### init — warn on orphaned containers from pre-0.1.10 naming scheme (issue #75)

- `797fe52 feat(init)` — Two files changed:

  1. **`codegraph/codegraph/init.py`** — Added `_warn_orphaned_containers(root, config, console)` that runs `docker ps --filter name=cognitx-codegraph-{repo_name}`, strips any container matching the current `config.container_name` (hash-suffixed), and also filters out false positives from other repos whose names are superstrings of the old prefix (e.g. `cognitx-codegraph-myrepo-v2`). Uses exact prefix match (`name == old_prefix`) rather than just `!= config.container_name`. Prints a yellow Rich warning with `docker rm -f` instructions per orphan. Silently ignores `FileNotFoundError` (no docker) and `CalledProcessError` (daemon down). Called from `run_init()` after `InitConfig` is built, gated on `config.setup_neo4j and not skip_docker`.

  2. **`codegraph/tests/test_init.py`** — 5 new unit tests: orphan name triggers warning, current container not flagged, superstring from other repo not flagged (false-positive regression), `FileNotFoundError` handled silently, `CalledProcessError` handled silently.

  - **Code review**: 1 issue found (`name != config.container_name` was too broad — substring match from `docker ps --filter` could flag other repos' containers) and fixed to exact `name == old_prefix`. Tests: 595 passed (10 skipped). Arch-check: 4/4 policies pass (1 skipped).

### init — custom Neo4j ports + fix silent integration-test failure (issues #80 / #73)

- `5d62ff8 feat(init)` — Three files changed:

  1. **`codegraph/codegraph/init.py`** — Added `bolt_port: int | None = None` and `http_port: int | None = None` to both `_prompt_config()` and `run_init()`. Values are threaded into `InitConfig` using `bolt_port if bolt_port is not None else _DEFAULT_BOLT_PORT` (not `or`, which would mishandle port 0). `_template_vars()` already reads `config.bolt_port`/`config.http_port` — no further change needed.

  2. **`codegraph/codegraph/cli.py`** — Added `--bolt-port` and `--http-port` `Optional[int]` Typer options (default `None`) to the `init` command, passed through to `run_init()`.

  3. **`codegraph/tests/test_init_integration.py`** — Added `_TEST_BOLT_PORT = 17687` / `_TEST_HTTP_PORT = 17474` constants. `test_init_full_flow_with_docker` now passes `--bolt-port 17687 --http-port 17474`, isolating the test from any existing Neo4j instance on default ports 7687/7474.

  - **Code review**: 1 issue found (`bolt_port or default` used truthiness — silently reverts on port 0) and fixed to `is not None` guard. Tests: 590 passed (10 skipped, 1 deselected). Arch-check: 4/4 policies pass (1 skipped).

### arch-check — configurable orphan exclusions in orphan_detection policy (issue #87)

- `c086f71 feat(arch_config)` — Five files changed:

  1. **`codegraph/codegraph/arch_config.py`** — Added `exclude_prefixes: list[str]` (default `["test_"]`) and `exclude_names: list[str]` (default `["setup_module", "teardown_module", "setUpModule", "tearDownModule"]`) to `OrphanDetectionConfig`. Extended `_parse_orphan_detection()` with validation for both new list[str] fields — wrong types raise `ConfigError`, non-string elements raise `ConfigError`, empty lists allowed (user explicitly opts out of all exclusions).

  2. **`codegraph/codegraph/arch_check.py`** — Replaced hardcoded `'test_'` / `['setup_module', ...]` string literals in both `_check_orphans()` and `_count_unsuppressed_orphans()` with `$exclude_prefixes` / `$exclude_names` Cypher parameters threaded from `OrphanDetectionConfig`. Params now pass through `params` dict to `s.run()` in both count and sample queries.

  3. **`codegraph/tests/test_arch_config.py`** — +8 new tests: custom values round-trip, empty lists allowed, wrong type (string instead of list) rejected, non-string elements rejected; updated defaults test.

  4. **`codegraph/tests/test_arch_check.py`** — +4 new tests: custom prefixes/names appear in Cypher params, empty lists produce empty params, class query exclusion; updated existing pytest entry points test.

  5. **`codegraph/docs/arch-policies.md`** — Documented new fields in both Configuration and full-schema sections; added unittest example (`exclude_prefixes = ["test_"]`, `exclude_names = ["setUp", "tearDown"]`). Fixed `...` placeholder that would inject a literal string as an exclude name.

  - **Tests**: 590 passed (12 new: +8 config, +4 arch_check), 10 skipped, 0 failures. Code review: 1 issue found (`...` TOML placeholder) and fixed. Arch-check: 4/4 policies pass (1 skipped).

### Python parser — walk for/while loops and match statements in _walk_top_stmt (issue #229)

- `34e4c96 fix(py_parser)` — Two files changed:

  1. **`codegraph/codegraph/py_parser.py`**:
     - Added `"for_statement"`, `"while_statement"`, and `"match_statement"` to the compound-statement tuple in `_walk_top_stmt`. The recursion pattern `for c in node.children: self._walk_top_stmt(c)` is safe — loop variable/condition children fall through harmlessly; only `block` descendants produce actual call/import matches.
     - Updated inline comment and `walk_module` docstring to reflect all handled statement types including loops and match.

  2. **`codegraph/tests/test_py_parser_calls.py`** — 2+ new tests covering calls inside `for` loops, `while` loops, and `match` statements at module scope.

  - **Tests**: 578 passed at time of fix, 10 skipped, 0 failures. Code review: 1 issue found (stale comment) and fixed. Arch-check: 4/4 policies pass (1 skipped).

### Python parser — CALLS edges from function bodies + module-level code (issue #88)

- `2ab4cfb feat(py_parser)` — Six files changed:

  1. **`codegraph/codegraph/py_parser.py`**:
     - `_scan_body_for_calls` widened to accept any caller (`MethodNode | FunctionNode`) instead of only `MethodNode` — duck-typed on `.id`.
     - `_handle_function` now calls `_scan_body_for_calls(fn, node)` after endpoint detection, mirroring the existing method-body pattern. Emits `CallEdge` with `func:<file>#<name>` caller IDs.
     - `_walk_top_stmt` handles `expression_statement` at module scope — scans for call expressions and emits module-level `CallEdge` with `file:<path>` as the caller.
     - Compound statement recursion in `_walk_top_stmt` extended to include `elif_clause` and `finally_clause` (previously only `else_clause`, `except_clause`, and `block` were handled — calls inside `elif`/`finally` were silently dropped).

  2. **`codegraph/codegraph/resolver.py`**:
     - Phase 4 (`_resolve_calls`) gains a fallback: when class-based resolution returns no match and `recv_kind == "name"` with no receiver, calls the new `_resolve_call_target_func` helper.
     - `_resolve_call_target_func(call, idx)` — 3-step resolution: (1) same-file `FunctionNode` by name, (2) imported symbol in the same file, (3) unique global function name across the whole index. Returns the first match or `None`.

  3. **`codegraph/tests/test_py_parser_calls.py`** — 9 new tests (replaced 1 negative test + 8 new): function body calls, attribute calls on functions, module-level bare/if-main/attribute/try-nested/elif-nested/finally-nested calls, `func:` prefix verification.

  4. **`codegraph/tests/test_py_resolver.py`** — 3 new resolver integration tests: same-file func→func, cross-file func→func, module-level file→func CALLS edge.

  5. **`codegraph/docs/arch-policies.md`**:
     - Replaced stale Python code block referencing `CROSS_PACKAGE_PAIRS` constant in "What it detects" with the correct `.arch-policies.toml` TOML syntax (closes #86/#83).
     - Replaced stale "Extending the rule set" section (which pointed to editing `arch_check.py`) with correct `.arch-policies.toml` instructions.
     - Removed "Python module-level callers aren't tracked" false-positive caveat (feature now shipped).

  6. **`codegraph/codegraph/templates/claude/commands/dead-code.md`** — Removed "Python module-level callers aren't tracked" false-positive caveat.

  - **Tests**: 574 passed, 10 skipped, 0 failures. Code review: 1 issue found (missing `elif_clause`/`finally_clause` handlers) and fixed. Arch-check: 4/4 policies pass (1 skipped).

### arch-check — fix orphan limit param passed only to sample query (issue #90)

- `1d900d5 fix(arch_check)` — One file changed:

  1. **`codegraph/codegraph/arch_check.py`** — In `_check_orphans()`:
     - Removed `$limit` from the shared params dict used by both count and sample queries.
     - Pass `limit` only to the sample query that actually contains `LIMIT $limit`.

     The `count_cypher` query has no `LIMIT` clause and was receiving a spurious `$limit` parameter. Aligns `_check_orphans` with the count/sample param-split pattern already used by sibling policies.

  - **Tests**: 563 passed at time of fix. PR #226.

- `3c9d5fa` — PR #225 merged (`archon/task-fix-issue-93`). Version bumped to v0.1.72 (`826bb89`).

---

### arch-check — exact suppression counts via Cypher COUNT filter (issue #93)

- `archon/task-fix-issue-93` — Two files changed:

  1. **`codegraph/codegraph/arch_check.py`** — Added `_count_unsuppressed()` dispatcher function + 5 per-policy filtered count builders (`_count_unsuppressed_coupling`, `_count_unsuppressed_cross_package`, `_count_unsuppressed_layer_bypass`, `_count_unsuppressed_orphans`, `_count_unsuppressed_import_cycles`). Each mirrors the original `_check_*` count query but adds `WHERE NOT ... IN $suppressed_keys` clauses so the Neo4j engine filters suppressed rows before counting. Returns `None` for custom policies (fallback). Refactored `_apply_suppressions()` with new optional `driver=`, `scope=`, `config=` kwargs; when driver is available, calls `_count_unsuppressed()` for exact remaining counts instead of relying on sample-subtraction heuristics. Moved `_apply_suppressions` call inside the `try` block in `run_arch_check()` so the driver is still open, passing `driver=`, `scope=`, `config=`.

  2. **`codegraph/tests/test_arch_check.py`** — 15 new tests:
     - 8 `_count_unsuppressed` unit tests (one per built-in policy + custom returns `None` + scope threading)
     - 4 `_apply_suppressions` scenario tests (issue #93 exact count, partial count, custom policy fallback, driver path sets no `incomplete_suppression_coverage` flag)
     - 1 integration test `test_run_arch_check_suppression_exact_count_integration` (50 violations, all suppressed, count=0)
     - Updated 2 existing integration tests to handle filtered count queries in the fake driver

  - **Tests**: 82/82 in `test_arch_check.py` (15 new), 573/573 full suite, 0 failures. Code review: 0 issues. Arch-check: 4/4 policies pass (1 skipped).

### arch-check — validate suppression policy names at config load time (issue #94)

- `b0e8739 fix(arch-check)` — Three files changed:

  1. **`codegraph/codegraph/arch_config.py`** — Extracted `BUILTIN_POLICIES: frozenset[str]` as a module-level constant (the 5 built-in policy names: `import_cycles`, `cross_package_imports`, `controller_repo_bypass`, `orphan_nodes`, `layer_violations`). Added `import difflib`. `_parse_suppressions()` gains a `valid_policies: frozenset[str]` parameter; for each entry, if `entry["policy"]` is not in `valid_policies`, a `ConfigError` is raised — with a "did you mean `<X>`?" hint when `difflib.get_close_matches` finds a close match (cutoff=0.6), or a full list of known policies otherwise. `load_arch_config()` computes `valid_policies = BUILTIN_POLICIES | frozenset(c.name for c in custom)` and threads it into the `_parse_suppressions()` call.

  2. **`codegraph/tests/test_arch_config.py`** — Four new tests:
     - `test_suppression_typo_policy_rejected_with_suggestion`: `"import_cycle"` → suggests `"import_cycles"`.
     - `test_suppression_unknown_policy_rejected_with_known_list`: `"totally_bogus"` → no close match, full list shown.
     - `test_suppression_custom_policy_name_accepted`: custom policy `"no_fat_files"` in both `[[policy]]` and `[[suppress]]` loads cleanly.
     - `test_suppression_typo_of_custom_policy_rejected`: `"no_fat_file"` (off-by-one) is caught as unknown with a suggestion.

  - **Tests**: 57/57 in `test_arch_config.py` (4 new), 560/560 full suite (pre-#93), 0 failures. Code review: 0 issues. Arch-check: 4/4 policies pass (1 skipped).

- `bbc12fd` — PR #224 merged (`archon/task-fix-issue-94`). Version bumped to v0.1.71 (`e1bdcd0`).

---

## Previously shipped (through commit `c1ed081`)

### Loader — add `interface:` to `_FILE_BEARING_PREFIXES` (issue #96)

- `c1ed081 fix(loader)` — Three files changed:

  1. **`codegraph/codegraph/loader.py`** — Added `"interface:"` to `_FILE_BEARING_PREFIXES` (line 65). The generic `_file_from_id()` path-extraction logic (`rest.split("#", 1)[0]`) already handles `interface:<path>#<name>` without special-casing; the prefix was simply absent from the list, so interface node IDs returned `None` from `_file_from_id()` and were silently excluded from `touched_files`. This caused incremental re-indexing to skip cleaning stale interface subgraphs entirely.

  2. **`codegraph/tests/test_incremental.py`** — Added `("interface:codegraph/cli.py#IFoo", "codegraph/cli.py")` as a new parametrize entry to `test_file_from_id` (line 425), covering the new prefix alongside existing `class:`, `func:`, `method:`, `atom:`, `endpoint:`, `gqlop:`, and `file:` entries.

  3. **`codegraph/tests/test_mcp.py`** — Fixed secondary bug: `iface:` typo (line 1070) → `interface:` to match the `InterfaceNode.id` property format defined in `schema.py`. The old `iface:` prefix never existed in any schema dataclass and would never have matched a real node in the graph.

  - **Completeness check:** All file-bearing `id` prefixes in `schema.py` are now present in `_FILE_BEARING_PREFIXES`. Zero remaining `iface:` occurrences in the codebase.
  - **Tests**: 556 passed (1 new parametrize entry), 0 failures. Code review: 0 issues. Arch-check: 4/4 policies pass (1 skipped).

- `b5bccba` — PR #222 merged (`archon/task-fix-issue-220`). Version bumped to v0.1.69 (`80acca4`).

---

## Previously shipped (through commit `2083622`)

### Loader — fix READS_ATOM/WRITES_ATOM stats using DB-wide count (issue #220)

- `2083622 fix(loader)` — Two files changed:

  1. **`codegraph/codegraph/loader.py`** — Replaced two `session.run("MATCH ()-[r:READS_ATOM]->() RETURN count(r)")` / `WRITES_ATOM` equivalent DB-wide count queries in `_write_per_file_extras()` with `len(atom_reads)` / `len(atom_writes)`. All 25 other edge types in the function already used `len()` of the batch list; these two were anomalous holdovers that reported the global Neo4j total instead of edges created this run — causing inflated stats in incremental mode.

  2. **`codegraph/tests/test_incremental.py`** — New `test_per_file_extras_atom_stats_use_len_not_db_count` test: sets up a two-file `ParseResult` (a.py has 1 atom_read + 1 atom_write; b.py has 1 atom_read + 0 atom_writes), loads with only `a.py` touched, asserts `stats.edges[READS_ATOM] == 1` and `stats.edges[WRITES_ATOM] == 1`. Uses the existing `captured_runs` fixture and `FakeCtx` pattern.

  - **Tests**: 555 passed (1 new), 0 failures. Code review: 0 issues. Arch-check: 4/4 policies pass (1 skipped).

- `a97cf5f` — PR #221 merged (`archon/task-fix-issue-97`). Version bumped to v0.1.68 (`1420d26`).

---

## Previously shipped (through commit `f937391`)

### Loader — skip per-file extras for untouched files in incremental mode (issue #97)

- `f937391 fix(loader)` — Two files changed:

  1. **`codegraph/codegraph/loader.py`** — Added `touched_files: set[str] | None = None` parameter to `_write_per_file_extras()` (line 797). Immediately after the `for rel, result in file_results.items():` loop header, a guard `if touched_files is not None and rel not in touched_files: continue` skips writing env reads, event handlers, and event emissions for files that were not touched in the current incremental run. The parameter is forwarded from `load()` at the single call site (line 485). When `touched_files` is `None` (full index), the helper behaves as before.

  2. **`codegraph/tests/test_incremental.py`** — New `test_load_touched_files_filters_per_file_extras` test: sets up a two-file `ParseResult`, marks only one file as touched, asserts that only `READS_ENV` Cypher for the touched file appears in the captured batch runs. Uses the existing `captured_runs` fixture and `FakeCtx` pattern.

  - **Tests**: 554 passed (1 new), 0 failures. Code review: 0 issues. Arch-check: 4/4 policies pass (1 skipped).

- `9ff85c7` — PR #219 merged (`archon/task-fix-issue-98`). Version bumped to v0.1.67 (`de077d9`).

---

## Previously shipped (through commit `e944b8c`)

### CLI — incremental mode filtered non-code files from git diff (issue #98)

- `21cb2c9 fix(cli)` — Two files changed:

  1. **`codegraph/codegraph/cli.py`** — Added `_CODE_EXTENSIONS = frozenset((".py", ".ts", ".tsx"))` module-level constant (mirrors `allowed_suffixes` in `_run_index`). In `_git_changed_files()`, both `modified` and `deleted` are now filtered via set-comprehension using `os.path.splitext` before being returned. This prevents files like `README.md`, `package.json`, or `.github/workflows/ci.yml` from being passed to the index/clean pipeline — where they'd either silently no-op or trigger unnecessary graph lookups.

  2. **`codegraph/tests/test_incremental.py`** — New `test_git_diff_filters_non_code_extensions` test: 6-file fake diff (`.md`, `.json`, `.yml` mixed with `.py`, `.ts`, `.tsx`), asserts only the 3 code-file paths survive. Follows the existing `monkeypatch` pattern of `test_git_diff_parses_modified_and_deleted`.

  - **Tests**: 553 passed (1 new), 0 failures. Code review: 0 issues. Arch-check: 4/4 policies pass (1 skipped).

- `232290b` — PR #218 merged (`archon/task-fix-issue-100`). Version bumped to v0.1.66 (`bae64c2`).

---

## Previously shipped (through commit `e944b8c`)

### Loader — column filter IndexError on malformed `entity_id` (issue #100)

- `e944b8c fix(loader)` — Two files changed:

  1. **`codegraph/codegraph/loader.py`** — The column filter in `load()` that restricts incremental writes to touched files used an unsafe expression `c.entity_id.split("#")[0].split(":", 1)[1]`. For IDs without a `:` prefix (e.g. `"malformed_no_colon"`) this raised `IndexError`. Replaced with a call to the existing `_file_from_id()` helper, which handles all prefix formats (`class:`, `method:`, nested `method:class:`) and returns `None` for malformed IDs. Since `None in touched_files` (a `set[str]`) evaluates to `False`, malformed columns are safely excluded without crashing. Also fixes a latent bug: the old `split(":", 1)[1]` on `"method:class:a.py#Cls#run"` would produce `"class:a.py"` instead of `"a.py"` — `_file_from_id()` handles the nested-prefix case correctly.

  2. **`codegraph/tests/test_incremental.py`** — New `test_load_touched_files_filters_columns` test covers 3 cases: valid column in a touched file (included), valid column in an untouched file (excluded), malformed column without `:` separator (excluded without `IndexError`). Uses the existing `captured_runs` fixture and `FakeCtx` pattern.

  - **Tests**: 552 passed (1 new), 0 failures. Code review: 0 issues. Arch-check: 4/4 policies pass (1 skipped).

- `5f152cc` — PR #217 merged (`archon/task-fix-issue-104`). Version bumped to v0.1.65 (`c9e7fe5`).

### Resolver — npm tsconfig presets resolved from `node_modules` (issue #104)

- `ec94bff fix(resolver)` — Two files changed:

  1. **`codegraph/codegraph/resolver.py`** — New helper `_resolve_npm_tsconfig(start_dir: Path, package_name: str) -> Optional[Path]` walks up parent directories from `start_dir` looking for `node_modules/<package_name>/tsconfig.json`, returning the first match or `None`. The `_read_ts_paths()` extends loop is split into two branches: strings starting with `./`, `../`, or `/` use the existing relative/absolute resolution logic; anything else (bare package names like `@tsconfig/node20`, `tsconfig-node20`) calls `_resolve_npm_tsconfig()` with graceful `None` → `continue` fallback when the preset isn't installed in `node_modules`.

  2. **`codegraph/tests/test_resolver_bugs.py`** — New `TestNpmTsconfigPresets` class with 7 tests: scoped preset (`@tsconfig/node20`), unscoped preset (`tsconfig-node20`), missing preset (graceful skip), child tsconfig overrides preset values, nested `node_modules` in parent directory, chained extends within preset, and relative-extends regression guard.

  - **Tests**: 551 passed (7 new), 0 failures. Code review: 0 issues. Arch-check: 4/4 policies pass (1 skipped).

- `4a357a8` — PR #216 merged (`archon/task-fix-issue-214`). Version bumped to v0.1.64 (`0c61c05`).

---

## Previously shipped (through commit `8caf408`)

### arch-check — explicit `disabled` field on `PolicyResult` (issue #214)

- `8caf408 feat(arch-check)` — Adds `disabled: bool = False` to the `PolicyResult` dataclass (after `detail`, before `suppressed_count`). The `_disabled()` helper now sets `disabled=True` on its returned `PolicyResult`. Two call sites in `_render()` that previously used fragile string matching (`"(disabled" in p.detail`) are replaced with clean boolean checks:

  1. **Mark logic** (line 649): `if p.disabled:` replaces `if "(disabled" in p.detail:`.
  2. **Summary count filter** (line 716): `if not p.disabled` replaces `if "(disabled" not in p.detail`.

  - `_apply_suppressions` is unaffected: disabled policies always have `sample=[]` and hit the early-return path at line 584, preserving the original `PolicyResult` object (including `disabled=True`) without constructing a new one.
  - **Tests** (`tests/test_arch_check.py`): 4 edits — `test_policy_result_defaults` asserts `p.disabled is False`; `test_run_arch_check_with_disabled_policy_emits_skip_marker` asserts `cycles.disabled is True`; `test_render_summary_excludes_disabled_policies` sets `disabled=True` on both disabled `PolicyResult` fixtures; `test_arch_report_to_json_is_valid_and_contains_ok_flag` asserts `"disabled"` key present in JSON output. 544 tests pass. Code review: 0 issues. Arch-check: 3/3 policies pass (2 skipped).

- `5b68407` — PR #215 merged (`archon/task-fix-issue-113`). Version bumped to v0.1.63 (`2b8e0b6`).

---

## Previously shipped (through commit `0dba0bb`)

### arch-check — fix rendering when sample is empty + exclude disabled policies from summary (issues #113, #107)

- `0dba0bb fix(arch-check)` — Two fixes to `arch_check.py` `_render()`:

  1. **Issue #113 — empty sample with violations still renders:** The guard `if p.passed or not p.sample: continue` silently swallowed policies where all sampled rows were suppressed (`sample=[]`) but `violation_count > 0`. Guard changed to `if p.passed or (not p.sample and p.violation_count == 0): continue`. When `sample=[]` and `violation_count > 0`, a fallback line is printed: `<PolicyName> — N violation(s) beyond the sample window (all sampled rows were suppressed)`.

  2. **Issue #107 — disabled policies excluded from summary count:** The `passed/total` summary previously counted disabled policies in both numerator and denominator, showing e.g. `5/5 policies passed` when 2 were disabled. Now `active = [p for p in report.policies if "(disabled" not in p.detail]` filters them out; disabled count reported as `(N skipped)`. Mirrors the existing `"(disabled"` string convention already used at line 647 for the SKIP mark.

  - **Tests** (`tests/test_arch_check.py`): 2 new tests — `test_render_violation_section_when_sample_empty_but_violations_exist` (verifies fallback message renders); `test_render_summary_excludes_disabled_policies` (verifies disabled policies don't inflate count). ANSI codes stripped via `re.sub` because Rich's `highlight=True` injects codes around numbers. 542 → 544 tests pass, byte-compile clean. Arch-check: 3/3 policies pass (2 skipped).

### arch-check — custom policies honour `sample_limit` and support `$scope` (issues #116, #91, #108)

- Shipped in `475eb4f` (previous session); PR #213 merged as `f366968`. Version bumped to v0.1.62 (`cc34e46`).

---

## Previously shipped (through commit `d1526b8`)

### arch-check — custom policies honour `sample_limit` and support `$scope` (issues #116, #91, #108)

- `475eb4f fix(arch-check)` — Three grouped fixes to how custom `[[policies.custom]]` entries are evaluated:

  1. **Issue #116 — `sample_limit` threading:** `_check_custom()` in `arch_check.py` now accepts `sample_limit: int` (forwarded from `_run_all`) and passes `limit=sample_limit` to every `session.run()` call. Custom policies using `LIMIT $limit` in `sample_cypher` now respect the value from `[settings] sample_limit = N` in the policy file. Previously `$limit` was always unbound, causing a Neo4j parameter error.

  2. **Issues #91/#108 — `$scope` injection:** `_check_custom()` now also accepts `scope: list[str]` and passes `scope=scope` to both the count and sample `s.run()` calls. Users can reference `$scope` in their Cypher (e.g. `WHERE ANY(p IN $scope WHERE f.path STARTS WITH p)`) to honour the same `--scope` filtering as built-in policies. Passing `scope=[]` (no scope set) is safe — any `$scope` reference that isn't used silently receives an unused param.

  3. **Parse-time warning for hardcoded LIMIT:** `_parse_custom()` in `arch_config.py` now emits a `UserWarning` when a custom `sample_cypher` string matches `LIMIT\s+\d+` (a literal integer limit rather than `$limit`). Message: `"Custom policy '…': sample_cypher contains a hardcoded LIMIT — use LIMIT $limit to respect settings.sample_limit"`. Non-breaking; existing policies continue to work.

  - **Docs** (`docs/arch-policies.md`): All 3 custom policy Cypher examples updated `LIMIT 10` → `LIMIT $limit`. Rules section now documents the `$limit` and `$scope` parameters available in custom Cypher.
  - **Tests** (`tests/test_arch_check.py`): 2 new tests — `test_check_custom_passes_limit_param` (asserts `limit=5` forwarded to `session.run()`); `test_check_custom_passes_scope_param` (asserts `scope=["pkg/"]` forwarded). Existing fixture updated `LIMIT 10` → `LIMIT $limit`.
  - **Tests** (`tests/test_arch_config.py`): 2 new tests — `test_custom_hardcoded_limit_emits_warning` (asserts `UserWarning` on `LIMIT 10`); `test_custom_parameterised_limit_no_warning` (asserts no warning on `LIMIT $limit`). Existing fixtures updated. `import warnings` moved to module level.
  - Code review: 1 style issue found and fixed (`import warnings` inside function body → module level). 542 tests pass, byte-compile clean. Version bumped to v0.1.61 (`0273558`). PR #212 merged as `6058fac`. Arch-check: 5/5 policies pass.

---

## Previously shipped (through commit `11bea30`)

```
11bea30 test(template-sync): add drift detection test for .claude/commands templates
5f125a8 Merge pull request #211 from cognitx-leyton/archon/task-fix-issue-139
bfb4f97 chore: bump version to 0.1.60
```

### Template sync — drift detection test + graph.md fix (issue #136)

- `11bea30 test(template-sync)` — Two changes:
  1. **`.claude/commands/graph.md` drift fix** — Removed a stray line ("The graph is currently indexed for...") that appeared after the `<!-- codegraph:stats-end -->` marker but was not present in the bundled template at `codegraph/codegraph/templates/commands/graph.md`. The extra line was added during a prior `codegraph init` stats-injection pass that wrote outside the marker bounds.
  2. **`tests/test_template_sync.py` (new)** — Parametrized pytest suite that verifies 5 literal command templates (`arch-check.md`, `blast-radius.md`, `graph.md`, `trace-endpoint.md`, `who-owns.md`) stay in sync between `codegraph/codegraph/templates/commands/` (source of truth) and `.claude/commands/` (live copies). The stats section between `<!-- codegraph:stats-begin -->` and `<!-- codegraph:stats-end -->` is normalized with a regex before comparison so per-repo stats don't cause false failures. On mismatch, the error message includes the `diff` command to reproduce. Code review identified and fixed 2 issues: unnecessary `Path()` wrapping of `Traversable` (breaks zip-installed packages) and missing `encoding="utf-8"` on `read_text()` calls (codebase convention). Test count: 533 → 538. Version bumped to v0.1.60 (`bfb4f97`). PR #211 merged as `5f125a8`. Arch-check: 5/5 policies pass.

---

## Previously shipped (through commit `7190e84`)

```
7190e84 fix(stats): prevent multi-label nodes from inflating node counts
db2d9f8 Merge pull request #210 from cognitx-leyton/archon/task-fix-issue-208
cad4684 chore: bump version to 0.1.59
```

### Stats — fix multi-label node miscount in `stats` and `describe_schema` (issue #139)

- `7190e84 fix(stats)` — The `_query_graph_stats` Cypher in `cli.py` used `labels(n)[0]` to pick one label per node. Nodes carrying multiple labels (e.g. `:Function:Method`) were counted once per label that happened to land in index 0, silently inflating totals. Fix replaces `labels(n)[0]` with `UNWIND labels(n) AS label WHERE label IN $known_labels` in both the scoped and unscoped branches. A `known_labels` parameter (from `_LABEL_MAP.values()`) is threaded into both `params` dicts. The same pattern was applied to `describe_schema` in `mcp.py` (no `$known_labels` filter there — generic tool, no filtering needed). `labels(n)[0]` at `mcp.py:614` (`get_function_details`) is a single-node kind identifier, not a count aggregation — left untouched.
  - **Tests** (`tests/test_stats.py`): 1 new test — `test_query_graph_stats_multi_label_nodes` verifies that nodes with unknown labels (`TestFile`, `Component`) don't leak into the output dict, and that known-label counts are correct. `UNWIND`/`known_labels` structural assertions added to `test_query_graph_stats_no_scope` and `test_query_graph_stats_with_scope`. Test count: 532 → 533. Version bumped to v0.1.59 (`cad4684`). PR #210 merged as `db2d9f8`. Arch-check: 5/5 policies pass. Code review: 0 issues.

---

## Previously shipped (through commit `02a007d`)

```
02a007d fix(cli): catch Neo4j connection and auth errors in wipe and index commands
cf63c7c Merge pull request #209 from cognitx-leyton/archon/task-fix-issue-147
1612e70 fix(validate): wrap driver usage in try/finally to prevent leak on error
b19ed9e revert(workflow): remove auto-merge — PR approval stays manual
8e5e028 chore: bump version to 0.1.58
```

### CLI — catch Neo4j errors in `wipe` and `index`; fix `validate` driver leak (issues #208 + #147)

- `1612e70 fix(validate)` — `validate()` in `cli.py` now wraps driver usage in `try/finally` so `driver.close()` is guaranteed even when `run_validation()` raises. Previously the driver was leaked on error paths.

- `02a007d fix(cli)` — Completes the Neo4j error-handling sweep started in #147. The final two commands (`wipe` and `index`) were missing `ServiceUnavailable` / `AuthError` catch blocks:
  - `wipe()` — `except (ServiceUnavailable, AuthError)` added between the `try` body and `finally: loader.close()`. Calls `_emit_error(as_json, "connection", str(e))` + `raise typer.Exit(code=2)`. The `finally` still fires after `raise`.
  - `index()` — third `except` clause added after `ConfigError` / `IgnoreConfigError`. Same pattern. `ServiceUnavailable` / `AuthError` propagate from `_run_index()` → `loader.init_schema()` / `.wipe()` / `.load()` through the inner `finally: loader.close()` first, then caught by the new outer `except`.
  - **Tests** (`tests/test_cli_neo4j_errors.py`): `_FakeLoader` helper class added; 4 new tests — `test_wipe_service_unavailable_json`, `test_wipe_auth_error_json`, `test_index_service_unavailable_json`, `test_index_auth_error_json`. Stale module docstring fixed. Test count: 528 → 532.
  - All 6 Neo4j-touching CLI commands now emit clean JSON/Rich error messages instead of raw tracebacks. Arch-check: 5/5 policies pass. Version bumped to v0.1.58 (`8e5e028`). PR #209 merged as `cf63c7c`.

### Workflow — remove auto-merge

- `b19ed9e revert(workflow)` — Removed auto-merge behaviour from the PR workflow. PR approval stays manual.

---

## Previously shipped (through commit `529b70c`)

```
dc51b95 test(stats): add failure-path and lifecycle tests for _query_graph_stats
a91fe4c Merge pull request #204 from cognitx-leyton/archon/task-fix-issue-151
e60a0db chore: bump version to 0.1.56
```

### Tests — failure-path and lifecycle coverage for `_query_graph_stats` (issue #148)

- `dc51b95 test(stats)` — Added 5 new test functions to `tests/test_stats.py` (23 → 28 tests), covering previously-untested failure and lifecycle paths for `_query_graph_stats` and the `stats` CLI command:
  - `test_query_graph_stats_empty_results` — all node counts are `0` and `edges == {}` when Neo4j returns no rows.
  - `test_query_graph_stats_session_raises` — exception from `session.run()` propagates; `_query_graph_stats` has no internal `try/except`.
  - `test_query_graph_stats_driver_closed_on_success` — documents the lifecycle contract: `_query_graph_stats` does NOT close the driver (it doesn't own it).
  - `test_stats_cli_closes_driver_on_neo4j_error` — verifies the `try/finally` block in `stats()` (`cli.py:891-898`) calls `driver.close()` even when the session raises.
  - `test_stats_cli_closes_driver_on_success` — verifies `driver.close()` is called via `finally` on the happy path too.
  - No production code changes. Uses the same `_constant_driver` / generator-throw pattern established in `test_arch_check.py`. Code review: 0 issues. Arch-check: 5/5 policies pass. 519 tests pass, byte-compile clean. Version bumped to v0.1.56 (`e60a0db`). PR #204 merged as `a91fe4c`.

---

## Previously shipped (through commit `8f3280d`)

```
55f9d52 refactor(cli): move _LABEL_MAP to module level
d17e8ac Merge pull request #203 from cognitx-leyton/archon/task-fix-issue-154
b65e385 chore: bump version to 0.1.55
```

### CLI — `_LABEL_MAP` promoted to module level (issues #151 + #142)

- `55f9d52 refactor(cli)` — Moved `_LABEL_MAP` (a `dict[str, str]` mapping stat node-label keys to display names) from a local variable inside `_query_graph_stats()` to a module-level constant in `cli.py`, placed immediately after the related `_STAT_NODE_LABELS` tuple (line 463). The dict is read-only inside the function (only `.get()` calls, no mutation), so the scope change is safe under CPython's GIL. No behaviour change. Code review: 0 issues. Arch-check: 5/5 policies pass. 514 tests pass, byte-compile clean. Closes #151 and its exact duplicate #142. Version bumped to v0.1.55 (`b65e385`). PR #203 merged as `d17e8ac`.

---

## Previously shipped (through commit `4b2600b`)

```
b788e81 fix(release): add CDN propagation retry loop for PyPI installs
cb10f67 Merge pull request #202 from cognitx-leyton/archon/task-fix-issue-157
5ec5087 chore: bump version to 0.1.54
42134e8 chore: add Dependabot version updates
c26365c fix(workflow): stronger group-issues prompt — never return empty, show reasoning
aac2c07 Merge pull request #201 from cognitx-leyton/dev
```

### Release — CDN propagation wait + install retry backoff (issues #154 + #81)

- `b788e81 fix(release)` — Two improvements to `.github/workflows/release.yml`:
  - **Issue #81 — CDN polling (Phase 2 propagation wait):** After the existing JSON-API poll (Phase 1, up to 300 s), a new Phase 2 extracts the `.whl` URL from the PyPI metadata response using `python3` inline and polls `files.pythonhosted.org` with HEAD requests for up to 120 s. Falls back gracefully (emits `::warning::`, continues) if no wheel exists (sdist-only publish) or if CDN times out — the retry loop handles remaining lag.
  - **Issue #154 — Install retry loop:** Replaced the single-attempt "Verify PyPI install" step with a 5-attempt loop using exponential backoff (30 → 60 → 120 → 240 s). Each attempt tears down and recreates `/tmp/verify-venv`, installs with `--no-cache-dir` to force CDN re-fetch, and runs `codegraph --help` as a smoke test. On final failure, emits `::error::` and exits `1`.
  - Code review identified and fixed 2 issues: `next()` with no default (raised `StopIteration` if no wheel existed) → replaced with `next(..., None)` + conditional print; missing POSIX trailing newline.
  - No Python source files changed. No test changes needed. Arch-check: N/A. Version bumped to v0.1.54 (`5ec5087`). PR #202 (issue #157 — init exit-code fix) merged as `cb10f67`.

### Workflow — group-issues prompt hardening

- `c26365c fix(workflow)` — Strengthened the `group-issues` Claude Code workflow prompt to never return an empty result and to show its grouping reasoning. Prevents silent no-ops on workflows that call the grouper when no issues match.

### Dependabot

- `42134e8 chore` — Added Dependabot version-update config (`.github/dependabot.yml`) to auto-PR GitHub Actions version bumps.

---

## Previously shipped (through commit `9b9d102`)

```
9b9d102 fix(init): return exit code 1 when first index fails during non-interactive init
e06c881 Merge pull request #197 from cognitx-leyton/archon/task-fix-issue-195
da18675 chore: bump version to 0.1.53
2c8ba38 docs(roadmap): update session handoff
```

### Init — fix silent exit 0 when first index fails in non-interactive mode (issue #157)

- `9b9d102 fix(init)` — `run_init()` in `init.py` now captures the return value of `_run_first_index()`. When it returns `False` (a `CalledProcessError` during the index run), the function calls `_print_next_steps()` (so the user still sees guidance) and returns `1`. Previously the return value was discarded and the function always exited `0`, masking a failed index. The guard `config.packages` on the call site (line 429) ensures `_run_first_index` is only invoked when packages exist, so `False` from that call always means a real failure (not the soft "no packages" skip). **1 new test** `test_run_init_returns_1_when_first_index_fails` in `tests/test_init.py`: monkeypatches `_start_and_wait_for_neo4j → True` and `_run_first_index → False`, asserts `run_init()` returns `1`. Code review: 0 issues. Arch-check: 5/5 policies pass. Test count: 513 → 514. Version bumped to v0.1.53 (`da18675`). PR #197 (issue #195 — loader EXPOSES batch split) merged as `e06c881`.

---

## Previously shipped (through commit `8841d2e`)

```
8841d2e fix(loader): split endpoint EXPOSES batch by class-level vs file-level
b735f5c Merge pull request #196 from cognitx-leyton/archon/task-fix-issue-194
4ffa216 chore: bump version to 0.1.52
6048f96 chore: bump version to 0.1.51
f6554b5 docs(roadmap): update session handoff
```

### Loader — fix file-level EXPOSES edges silently dropped during full index (issue #195)

- `8841d2e fix(loader)` — The single endpoint UNWIND in `loader.py` (`_write_endpoints`, lines 390–413) was split into two complementary `_run()` batches. **Class-level batch**: filters rows where `r.controller_class` does NOT start with `"file:"`, matches `(c:Class {id: r.cls})`, and MERGEs `[:EXPOSES]->(ep)`. **File-level batch**: filters rows where `r.controller_class` starts with `"file:"`, strips the prefix, matches `(f:File {path: r.fpath})`, and MERGEs `[:EXPOSES]->(ep)`. Root cause: the old single-path Cypher always used `MATCH (c:Class {id: r.cls})`, which silently produced 0 matches for file-scoped endpoints (no owning class node), so their EXPOSES edges were never written. **2 new tests** in `tests/test_loader_partitioning.py`: `test_load_file_level_endpoint_exposes` confirms file-level endpoints route through `File {path:}` match; `test_load_class_level_endpoint_exposes` is a regression guard confirming class-level endpoints still use `Class {id:}` match. Code review: 3 style issues found and fixed (duplicate import merged, `is False` → `not`, weak negative assertion simplified). Arch-check: 5/5 policies pass. Test count: 511 → 513. PR #196 (issue #194 `mcp.py` companion fix) merged as `b735f5c`. Version bumped to v0.1.52 (`4ffa216`).

---

## Previously shipped (through commit `75af831`)

```
75af831 fix(mcp): handle file-level EXPOSES edges via File path match in reindex_file
b757dfd Merge pull request #193 from cognitx-leyton/archon/task-fix-issue-190
31d723c chore: bump version to 0.1.50
d454e93 docs(roadmap): update session handoff
```

### MCP — fix file-level EXPOSES edge write in reindex_file (issue #194)

- `75af831 fix(mcp)` — `reindex_file()` in `mcp.py` now correctly handles file-level endpoint EXPOSES edges. Previously, after the issue #190 fix removed `EXPOSES` from `_EDGE_WHITELIST` (intending to handle it inline), file-level endpoints (those whose `controller_class` starts with `"file:"`) lost their EXPOSES edge entirely — they had no owning class, so the class-level inline path didn't apply and the generic loop no longer covered them. Fix: **(1)** The inline endpoint-creation block now branches on `controller_class.startswith("file:")` — file-level endpoints use `MATCH (f:File {path: $file_path}) MERGE (f)-[:EXPOSES]->(ep)` while class-level endpoints continue to use `MATCH (c:Class {id: $class_id}) MERGE (c)-[:EXPOSES]->(ep)`. **(2)** `EXPOSES` removed from `_EDGE_WHITELIST` — both branches now write the edge inline. **(3)** `EXPOSES` removed from the `from schema import` list. Comment updated to list EXPOSES alongside HAS_METHOD, RESOLVES, HAS_COLUMN as edge types excluded from the generic loop. **1 new test** `test_reindex_file_file_level_exposes_edge` in `tests/test_mcp.py`: creates a File + Function + Endpoint result with `controller_class="file:/app/routes.py"`, confirms the Cypher contains `MATCH (f:File {path: '/app/routes.py'})` and uses `[:EXPOSES]`. Existing test `test_reindex_file_structural_edges_not_doubled` updated to assert `"EXPOSES"` is NOT in the generic edge loop. Code review: 0 issues. Arch-check: 5/5 policies pass. Test count: 510 → 511. Version bumped to v0.1.50 (`31d723c`). PR #193 merged (`b757dfd`).

---

## Previously shipped (through commit `abc6776`)

```
abc6776 fix(mcp): remove duplicate structural edge writes in reindex_file
db92a5c Merge pull request #191 from cognitx-leyton/archon/task-fix-issue-188
589b1e2 chore: bump version to 0.1.49
7106cbc docs(roadmap): update session handoff
ec10b5c fix(schema,mcp): rename DEFINES_INTERFACE → DEFINES_IFACE and remove duplicate edge writes
223685e Merge pull request #189 from cognitx-leyton/archon/task-fix-issue-161
a6aa05b chore: bump version to 0.1.48
a1130c8 docs(roadmap): update session handoff
54d2100 fix(loader): simplify delete cascade to avoid stale child nodes
8012478 Merge pull request #187 from cognitx-leyton/archon/task-fix-issue-170
0c24335 chore: bump version to 0.1.47
a8c6b3f docs(roadmap): update session handoff
d91b45e fix(ownership): use unit separator (0x1f) instead of pipe to delimit git log fields
186dc7e chore: bump version to 0.1.46
34b79bb Merge pull request #186 from cognitx-leyton/archon/task-fix-issue-175
9192514 fix(ownership): prevent rooted CODEOWNERS pattern false-positives on sibling dirs
79bc84d chore: bump version to 0.1.45
ef625a0 feat(workflow): fix-and-file replaces file-issues — fix small bugs inline
c3c5f48 Merge pull request #184 from cognitx-leyton/dev
32cb8f1 Merge pull request #185 from cognitx-leyton/archon/task-fix-issue-181
5d01a60 fix(ownership): harden ownership contract to never return None
4b6c9fd chore: bump version to 0.1.44
bbb0d38 chore(workflow): tell reviewer the code was written by Codex
4f719eb Merge pull request #183 from cognitx-leyton/dev
258aa02 Merge remote-tracking branch 'origin/main' into hotfix
07ac776 Merge pull request #182 from cognitx-leyton/archon/task-fix-issue-176
8cf1fcc docs(roadmap): update session handoff
a1d7cb9 fix(ownership): return empty list instead of empty dict on all error paths
7fc679d Merge pull request #177 from cognitx-leyton/archon/task-fix-issue-172
efdf8f2 Merge remote-tracking branch 'origin/main' into hotfix
6b76e9b Merge pull request #178 from cognitx-leyton/dev
a8a5a53 fix(workflow): close-fixed-issues also catches out-of-scope + orphaned done
eab0758 docs(roadmap): update session handoff
573b86d test(ownership): add pattern-matching and edge-case coverage for issue #172
45b24b9 Merge pull request #173 from cognitx-leyton/archon/task-fix-issue-167
0205114 chore: bump version to 0.1.42
fb98121 docs(roadmap): update session handoff
22d4608 fix(ownership): catch OSError in _parse_codeowners and fix log prefix
2be77af Merge pull request #169 from cognitx-leyton/archon/task-fix-issue-162
cafff46 chore: bump version to 0.1.41
c08ef3e docs(roadmap): fix placeholder commit hash in session handoff
c4bb818 docs(roadmap): update session handoff
fix(ownership): encoding strictness, silent-failure logging, and tests (issues #158, #159, #162)
10f77a0 Merge remote-tracking branch 'origin/main' into hotfix
06d2236 Merge pull request #165 from cognitx-leyton/dev
968c9d7 fix(workflow): final-gate always reinstalls deps before testing
615bc05 Merge remote-tracking branch 'origin/main' into hotfix
e420b74 Merge pull request #164 from cognitx-leyton/dev
072fa76 feat(workflow): group similar issues, close fixed issues, idle timeouts
3a5ffe9 Merge pull request #163 from cognitx-leyton/archon/task-fix-issue-155
c475011 chore: bump version to 0.1.40
1cf1384 docs(roadmap): update session handoff
db3291e fix(crlf): normalise CRLF line endings across all file-read paths
fa90f98 Merge pull request #156 from cognitx-leyton/archon/task-fix-issue-152
dfaba1f chore: bump version to 0.1.39
3b320b4 docs(roadmap): update session handoff
6ea3c20 fix(stats): handle CRLF line endings in stat placeholder replacement
9a86b8a Merge pull request #153 from cognitx-leyton/archon/task-fix-issue-149
d182dce chore: bump version to 0.1.38
a5d0b5f docs(roadmap): update session handoff
5888953 test(stats): extend _format_stat_line tests for interfaces and endpoints
a64088f Merge pull request #150 from cognitx-leyton/archon/task-fix-issue-143
92f0c67 chore: bump version to 0.1.37
f8653a3 docs(roadmap): update session handoff
7815b72 fix(stats): tighten scoped edge counts to AND logic, add --include-cross-scope-edges flag
60745ba Merge pull request #146 from cognitx-leyton/archon/task-fix-issue-144
210a1f5 chore: bump version to 0.1.36
df49d03 docs(roadmap): update session handoff
37d71a2 test(stats): add auto-scope edge-case for stats command
76a4574 Merge pull request #145 from cognitx-leyton/archon/task-fix-issue-140
31ec89f chore: bump version to 0.1.35
1e53a80 docs(roadmap): update session handoff
8da989a test(stats): add edge-case coverage for stats command
32d66d4 Merge pull request #141 from cognitx-leyton/archon/task-fix-issue-137
7958de3 chore: bump version to 0.1.34
3b2f52a docs(roadmap): update session handoff
de21f68 feat(cli): add codegraph stats subcommand with scope filtering and --update flag
de41ee2 Merge pull request #138 from cognitx-leyton/archon/task-fix-issue-123
737f89e chore: bump version to 0.1.33
e185737 docs(roadmap): update session handoff
623dc8c docs(stats): update codebase stats to reflect current graph state
5299144 Merge pull request #135 from cognitx-leyton/archon/task-fix-issue-133
edd3ae2 chore: bump version to 0.1.32
a797178 docs(roadmap): update session handoff
59c916a docs(test): fix install-test retry documentation and add scope filter
2efe9b7 Merge pull request #134 from cognitx-leyton/archon/task-fix-issue-131
ab2a0a1 chore: bump version to 0.1.31
d4a50c3 docs(roadmap): update session handoff
61de3b1 docs(github): add pull request template
a4fa7d8 Merge pull request #132 from cognitx-leyton/archon/task-fix-issue-124
b876054 chore: bump version to 0.1.30
2391bfc docs(roadmap): update session handoff
581d9db Merge pull request #130 from cognitx-leyton/archon/task-fix-issue-126
82ec7d3 chore: bump version to 0.1.29
d5fdc80 docs(roadmap): update session handoff
5b6af3c fix(test): use pip show instead of importlib to verify installed version
5f18867 Merge pull request #129 from cognitx-leyton/archon/task-fix-issue-127
42fa4f3 chore: bump version to 0.1.28
ffd2009 docs(roadmap): update session handoff
af36698 fix(test): add exit 1 to install-retry loop on final failure
639b279 Merge pull request #128 from cognitx-leyton/archon/task-fix-issue-124
000fd94 chore: bump version to 0.1.27
55f192c docs(roadmap): update session handoff
1d538fa fix(test): resolve install-test flakiness and version hardcode
4768f69 Merge pull request #125 from cognitx-leyton/archon/task-fix-issue-121
9b79c9a chore: bump version to 0.1.26
3961abd docs(roadmap): update session handoff
039497d fix(ci): align arch-check workflow paths with pyproject.toml auto-scope
3d69ec3 Merge pull request #122 from cognitx-leyton/archon/task-fix-issue-119
eb4a4c8 chore: bump version to 0.1.25
2f525f5 docs(roadmap): update session handoff
e40fcec fix(arch-check): set correct package paths in pyproject.toml auto-scope
8df3c62 Merge pull request #120 from cognitx-leyton/archon/task-fix-issue-117
8898ae2 chore: bump version to 0.1.24
40f6f58 docs(roadmap): update session handoff
d04af53 fix(arch-config): use fully-qualified policy paths in validation error messages
5765b4e Merge pull request #118 from cognitx-leyton/archon/task-fix-issue-114
aaea980 chore: bump version to 0.1.23
32839a8 docs(roadmap): update session handoff
2103d57 feat(arch-check): make sample_limit configurable via [settings] in .arch-policies.toml
c23923b Merge pull request #115 from cognitx-leyton/archon/task-fix-issue-111
d263cdf chore: bump version to 0.1.22
e246ced docs(roadmap): update session handoff
082c943 test(arch-check): assert and test the incomplete→not-passed invariant
14bd396 Merge pull request #112 from cognitx-leyton/archon/task-fix-issue-109
e31c2a2 chore: bump version to 0.1.21
e0951c6 docs(roadmap): update session handoff
28a5eda fix(arch-check): warn when suppression coverage is partial due to sample truncation
30d13d9 Merge pull request #110 from cognitx-leyton/archon/task-fix-issue-105
5013666 chore: bump version to 0.1.20
d7d4172 docs(roadmap): update session handoff
ae21e20 feat(arch-check): auto-scope from config packages, add --no-scope flag
325f4ff Merge pull request #106 from cognitx-leyton/archon/task-fix-issue-105
1d9154f chore: bump version to 0.1.19
1ca7de2 docs(roadmap): update session handoff
c6460d2 fix(resolver): handle scoped npm packages and tsconfig extends array
92b58fe Merge pull request #103 from cognitx-leyton/archon/task-feat-issue-14-mcp-write-tools
8cf25f7 chore: bump version to 0.1.18
e94a436 docs(roadmap): update session handoff
daae936 feat(mcp): add write tools for reindexing and edge loading
aa48cd0 Merge pull request #99 from cognitx-leyton/archon/task-feat-issue-13-incremental-reindex
149b955 chore:          bump version to 0.1.17
6d9c028 docs(roadmap):  update session handoff
06e9873 feat(incremental): add --since flag for incremental re-indexing
7327e46 Merge pull request #95 from cognitx-leyton/archon/task-feat-issue-23-arch-check-suppression
87b6997 chore:          bump version to 0.1.16
7290c13 docs(roadmap):  update session handoff
9d05a44 feat(arch-check): add inline suppression for false-positive violations
508826e Merge pull request #92 from cognitx-leyton/archon/task-feat-issue-22-arch-check-scope
7c95ac2 chore:          bump version to 0.1.15
aff9f10 docs(roadmap):  update session handoff
9ebc0e4 feat(arch-check): add --scope flag to filter policies by path prefix
4956838 Merge pull request #89 from cognitx-leyton/archon/task-feat-issue-17-orphan-detection
1b27921 fix(arch-check): exclude pytest entry points from orphan_detection function query
d171787 chore:          bump version to 0.1.14
78fb177 docs(roadmap):  update session handoff
2dd72b7 feat(arch-check): add orphan_detection policy to surface unreachable nodes
9c4130d Merge pull request #85 from cognitx-leyton/archon/task-feat-issue-16-coupling-ceiling
ad9ccac chore:          bump version to 0.1.13
62ded5a docs(roadmap):  update session handoff
4213450 feat(arch-check): add coupling_ceiling policy to cap inbound imports (#16)
6c23313 Merge pull request #82 from cognitx-leyton/archon/task-chore-issue-24-pypi-propagation-delay
ec54142 chore:          bump version to 0.1.12
ce1d179 docs(roadmap):  update session handoff
dd17072 chore(ci):      add PyPI propagation wait and smoke test to release workflow (#24)
995e47e Merge pull request #79 from cognitx-leyton/archon/task-chore-issue-19-arch-policies-versioning
732ce1d chore:          bump version to 0.1.11
bc70d01 chore(arch-config): add schema_version field to arch-policies config (#19)
5d88fac chore:          bump version to 0.1.10
3f8551c Merge pull request #76 from cognitx-leyton/archon/task-fix-issue-18-container-name-collision
ee2ac35 fix(init):      prevent container name collision via project-path hash suffix (#18)
8c5396c Merge pull request #72 from cognitx-leyton/archon/task-chore-issue-32-query-graph-dedup
0cad8af chore:          bump version to 0.1.9
6d9205b chore(mcp):     deduplicate query_graph error-handling into _run_read (#32)
27d4fec chore:          bump version to 0.1.8
e77e3cd Merge pull request #70 from cognitx-leyton/archon/task-chore-issue-31-missing-mcp-tests
939dfc3 test(mcp):      add 15 missing MCP tool tests for full coverage (#31)
8556630 chore:          bump version to 0.1.7
e500554 Merge pull request #66 from cognitx-leyton/archon/task-fix-issue-33-max-depth-bounds
6b74617 fix(mcp):       reject bool values for max_depth in callers_of_class, calls_from, callers_of (#33)
619923e chore:          bump version to 0.1.6
87623d9 chore:          bump version to 0.1.5
6fe0730 fix(mcp):       reject bool and out-of-range limit in query_graph (#30)
11f02cb chore:          bump version to 0.1.4
fa031dd fix(mcp):       catch CypherSyntaxError in describe_schema before ClientError (#29)
eaee6a7 chore:          bump version to 0.1.3
357ad03 feat(mcp):      expose queries.md as MCP prompt templates (#12)
6493224 feat(parser):   Python Stage 2 framework detection + endpoints + resolver fixes
c6da6c6 fix(cli):       detect modern src-layout Python packages via pyproject.toml
d0abe53 feat(onboarding): one-command install for any repo via codegraph init
b12520a chore(ci):      enable workflow_dispatch for arch-check
55789fd feat(arch-check): first-class CLI subcommand + GitHub Actions gate
af77cd3 feat(commands): add 5 graph-powered slash commands for daily dev work
453a6a4 chore(loader):  unify test-file pairing + widen graph index scope
d48ee26 feat(parser):   emit Python CALLS edges + wire MCP call-graph tools
edb8cca feat(parser):   extract docstrings, params, and return types for Python
1cfc590 feat(claude):   wire codegraph CLI into this repo's Claude Code setup
154954c feat(parser):   index Python codebases via tree-sitter-python (Stage 1)
09822fa docs(roadmap):  session handoff document for continuing work across agents
```

Forty-two sessions' worth of work grouped by theme:

### Schema / MCP — fix DEFINES_IFACE constant and remove duplicate edge writes (issue #188)

- `ec10b5c fix(schema,mcp)` — Two related bugs in `schema.py` and `mcp.py` fixed together. **(1) Constant mismatch:** `schema.py:243` defined `DEFINES_IFACE = "DEFINES_INTERFACE"` — the value did not match the variable name. All Cypher strings in `loader.py` and `mcp.py` already used the literal `DEFINES_IFACE` as the Neo4j relationship type, so the constant was effectively dead and the mismatch was invisible at runtime but would have caused silent failures in any code path that consumed the constant. Fixed to `DEFINES_IFACE = "DEFINES_IFACE"`. **(2) Double-write in `reindex_file()`:** `mcp.py`'s `_EDGE_WHITELIST` included `DEFINES_CLASS`, `DEFINES_FUNC`, `DEFINES_IFACE`, and `DEFINES_ATOM`. These 4 edge types are already emitted inline by the node-creation MERGEs earlier in `reindex_file()` (lines 765, 786, 824, 880). Including them in `_EDGE_WHITELIST` caused the generic edge-writing loop to write each ownership edge a second time, producing phantom duplicate relationships in Neo4j. Fixed by removing all 4 from both the import block and `_EDGE_WHITELIST`. **(3) Regression test:** `test_reindex_file_ownership_edges_not_doubled` added to `tests/test_mcp.py` — creates all 4 ownership edge types in `result.edges`, confirms `DEFINES_INTERFACE` never appears, verifies ownership edges come from node MERGEs only, and asserts no ownership edge leaks into the generic loop. Arch-check: 5/5 policies pass. Test count: 495 → 496. Version bumped to v0.1.48 (PR #189 merged to `main`, `223685e`).

### Loader / MCP — schema-resilient delete cascade (issue #161)

- `54d2100 fix(loader)` — `delete_file_subgraph()` in `loader.py` and the inline cascade in `mcp.py`'s `reindex_file()` previously used a 10-step ordered Cypher sequence that had to be manually updated whenever a new child node type or ownership edge was added to the schema. The cascade was also fragile: the ordering was undocumented, and a missing step would leave orphaned nodes after `--since` incremental re-indexing. Replaced with a 3-step pattern that is schema-resilient by construction: **(1)** Delete all grandchildren of owned classes via `(c:Class)-->(child) WHERE NOT child:Class AND NOT child:Decorator` — catches Method, Endpoint, Column, GraphQLOperation, Atom, and any future types without code changes; **(2)** Delete direct children via the 4 ownership edges (`DEFINES_CLASS|DEFINES_FUNC|DEFINES_IFACE|DEFINES_ATOM`) — handles Function, Class, Interface, and Atom nodes; **(3)** `DETACH DELETE` the File node itself — automatically drops IMPORTS, BELONGS_TO, and any other File-level edges. The `(c:Class)-->(child)` catch-all is safe because all outgoing edges from Class to non-Class/non-Decorator targets are ownership edges; cross-file references (EXTENDS, IMPLEMENTS, INJECTS, etc.) all target Class nodes and are excluded by the `WHERE NOT child:Class` guard. Code review found and fixed one critical bug: step 2 initially used `DEFINES_INTERFACE` but the actual Neo4j relationship type (emitted at `loader.py:387` and `mcp.py:824`) is `DEFINES_IFACE` — corrected before commit. `tests/test_incremental.py` assertion updated from 10 → 3 call assertions. Loader and MCP Cypher kept byte-identical (same 3-step logic, differing only in UNWIND vs single-path parameter style). Arch-check: 5/5 policies pass. Test count: 495 (unchanged). Version bumped to v0.1.47.

### Ownership module — pipe-safe git log delimiter (issue #170)

- `d91b45e fix(ownership)` — `collect_ownership` in `ownership.py` used `|` as the separator in the `git log --pretty=format:` string (`%H|%ae|%an|%at`). Author names containing a literal `|` (e.g. `Jo|hn Doe`) caused `payload.split("|", 3)` to produce 5 parts instead of 4, crashing the subsequent `int(ts)` conversion and silently dropping the commit. Fix replaces the delimiter with ASCII Unit Separator (`\x1f`, 0x1f) in both the format string (line 40) and the split call (line 67). Updated 2 existing test mocks to use `\x1f`. Added regression test `test_collect_ownership_pipe_in_author_name` confirming that `Jo|hn Doe` parses to correct `authors`, `last_modified`, and `contributors` output. Code review: 0 actionable issues. Arch-check: 5/5 policies pass. Test count: 495 (1 new). Version bumped to v0.1.46.

### Ownership module — rooted CODEOWNERS pattern false-positive fix (issue #175)

- `9192514 fix(ownership)` — Fixed `_co_pattern_match` in `ownership.py` (lines 157-160): rooted patterns like `/docs` and `/docs/` were incorrectly matched against sibling directories such as `docs-internal/`. Root cause: the fallback glob used `pat + "*"` (producing `docs*`) instead of anchoring to children. Fix replaces this with `base + "/*"` where `base = stripped.rstrip("/")`, so `/docs` generates the glob `docs/*` which correctly matches only direct and nested children of `docs/`, not any path starting with `docs`. Added 4 parametrized regression tests in `tests/test_ownership.py` covering both `/docs` and `/docs/` variants against child paths (should match) and sibling `docs-internal/` paths (should not match). Code review: 0 actionable issues (reviewer's `fnmatch` cross-slash concern was factually wrong — Python's `fnmatch.fnmatch` matches `docs/*` against `docs/a/b/c.md`). Arch-check: 5/5 policies pass. Test count: 494 (4 new). Version bumped to v0.1.45.

### Workflow — fix-and-file replaces file-issues (PR #184)

- `ef625a0 feat(workflow)` — The `fix-and-file` workflow replaces the older `file-issues` approach. Fixes small bugs inline rather than filing separate issues for them, reducing issue noise for trivial one-liners found during implementation. No codegraph source changes — workflow tooling only.

### Ownership module — harden contract, docstring, and shallow-copy fix (issues #181, #180)

- `5d01a60 fix(ownership)` — Three hardening changes across `ownership.py`, `cli.py`, and `loader.py`. **(1) Issue #181 — docstring:** `collect_ownership()` lacked any docstring; added a 9-line docstring documenting the always-truthy return contract, all 5 keys (`authors`, `teams`, `last_modified`, `contributors`, `owned_by`), and error conditions (OSError / non-zero git exit → all-empty dict, never `None`). **(2) Issue #181 — `is not None` guards:** `cli.py:392` and `loader.py:507` both tested `if ownership:` which is always `True` for the post-#176 return value (a dict with 5 keys, never an empty `{}`). Changed to `if ownership is not None:` to correctly express the intent (sentinel vs. empty-but-valid). The `loader.py` guard is load-bearing — `ownership: dict | None = None` in the function signature makes `None` the real sentinel. **(3) Issue #180 — independent list objects on error paths:** `_EMPTY_OWNERSHIP` error-path returns used `dict(_EMPTY_OWNERSHIP)` (shallow copy), which means all callers got the *same* 5 `[]` objects. If any caller mutated a list, the sentinel would be corrupted. Changed to `{k: [] for k in _EMPTY_OWNERSHIP}` so each call creates 5 independent `[]` objects. Code-review: 0 actionable issues (reviewer confirmed `[] == []` by value so existing `test_collect_ownership_git_nonzero_exit` / `test_collect_ownership_logs_on_os_error` still pass, and the `is not None` guard in `cli.py` is intentional even though it's always `True` — it communicates intent). Arch-check: 5/5 policies pass. Test count: 490 (unchanged). Version bumped to v0.1.44. PR #182 merged (`07ac776`). Workflow fix `bbb0d38` also lands: reviewer prompt now identifies the code as written by Codex.

### Ownership module — typed empty return on error paths (issues #176, #171)

- `a1d7cb9 fix(ownership)` — `collect_ownership()` in `codegraph/codegraph/ownership.py` previously returned bare `{}` on two error paths (the `OSError`/`SubprocessError` catch at line 29 and the `returncode != 0` branch at line 37). Callers pattern-match or iterate over the result, so `{}` — while falsy — is structurally different from a successful empty-git-log return which includes all 5 keys. **(1)** Added `_EMPTY_OWNERSHIP` module-level constant with all 5 keys (`authors`, `teams`, `last_modified`, `contributors`, `owned_by`) set to `[]`. **(2)** Both error-path `return {}` statements replaced with `return dict(_EMPTY_OWNERSHIP)` (shallow copy so callers can't mutate the constant). **(3)** `tests/test_ownership.py` — 3 test assertions updated from `== {}` to `== dict(_EMPTY_OWNERSHIP)`: `test_collect_ownership_git_nonzero_exit`, `test_collect_ownership_logs_on_os_error`, `test_collect_ownership_subprocess_timeout`. 2 test docstrings updated (previously said "returns `{}`"). Import line updated to include `_EMPTY_OWNERSHIP`. No production callers (`cli.py:392`, `loader.py:507`) needed changes — both iterate or UNWIND the value, which is a no-op on an empty list. Code-review: 0 actionable issues (reviewer raised 2 non-issues explicitly accepted by plan: shared list refs via shallow copy, and `if ownership:` truthiness change — both verified safe). Arch-check: 5/5 policies pass. Test count: 490 (unchanged). Version bumped to v0.1.43 (`chore: bump version` commit). PR #177 merged (`7fc679d`). Workflow fix `a8a5a53` also lands: `close-fixed-issues` now catches `out-of-scope` and `orphaned done` states in addition to the previous `done` + `closed` states.

### Ownership module — pattern-matching and edge-case test coverage (issue #172)

- `573b86d test(ownership)` — 5 new test functions added to `codegraph/tests/test_ownership.py`, covering gaps identified in issue #172 (the existing suite lacked direct tests for `_co_pattern_match` logic, last-rule-wins semantics, the no-match-returns-empty path, subprocess timeout handling, and empty git-log output). **(1) `test_co_pattern_match_cases`** — 6 parametrized cases: bare glob match/no-match, rooted prefix match/no-match, path-pattern (`src/*.py`), double-star (`**/*.py`). **(2) `test_match_codeowners_last_rule_wins`** — two rules both matching the same path; asserts the later rule's owners win. **(3) `test_match_codeowners_no_matching_rule`** — no rule matches the path; asserts `[]` is returned. **(4) `test_collect_ownership_subprocess_timeout`** — `subprocess.run` raises `subprocess.TimeoutExpired`; asserts `{}` is returned and a `logger.warning` is emitted (via `caplog`). **(5) `test_collect_ownership_empty_git_log`** — `subprocess.run` returns exit 0 with empty `stdout`; asserts all 5 expected dict keys (`last_author`, `last_date`, `contributors`, `teams`, `codeowners`) are present with empty/zero values. Import line updated to include `_match_codeowners` and `_co_pattern_match`. Code-review: 0 issues. Arch-check: 5/5 policies pass. Test count: 480 → 490. Version bumped to v0.1.42 (`0205114`). PR #173 merged to `main` (`45b24b9`).

### Ownership module — deterministic ordering, git exit-code check, and post-review fixes (issues #166, #167)

- `22d4608 fix(ownership)` — Four issues fixed as a batch in `codegraph/codegraph/ownership.py` and `codegraph/tests/test_ownership.py`. **(1) Issue #167 — deterministic contributor ordering:** `collect_ownership()` was calling `counter.most_common(10)` which is non-deterministic on equal-count entries (CPython 3.11 insertion-ordered, but not guaranteed across runs or implementations). Replaced with `sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:10]` — primary sort by descending count, secondary alphabetical tiebreaker. New test `test_contributors_deterministic_on_tie` verifies two contributors with identical commit counts are always returned in alphabetical order. **(2) Issue #166 — git exit-code check:** `collect_ownership()` called `subprocess.run()` but never checked `proc.returncode`. A failed `git log` (e.g. non-git directory, access error) would silently continue with an empty `stdout`, parsing zero lines and returning `{}` without any indication of failure. Fixed by adding `if proc.returncode != 0:` → `logger.warning("collect_ownership: git log exited %d for %s", proc.returncode, path)` → `return {}`. New test `test_collect_ownership_git_nonzero_exit` injects `returncode=128` and asserts the warning is emitted and `{}` is returned. **(3) Post-review fix for #158 — OSError in `_parse_codeowners`:** the initial fix only caught `UnicodeDecodeError` in the `open()` call, leaving a TOCTOU window: the file could disappear or become unreadable between the `.exists()` check and the `open()`. Added `OSError` to the `except` clause (`except (UnicodeDecodeError, OSError):`). New test `test_parse_codeowners_non_utf8` verifies the combined catch. **(4) Post-review fix for #159 — log prefix consistency:** the `returncode != 0` warning was using an em-dash (`"collect_ownership - git log …"`) instead of a colon like all other warnings in the module. Fixed to `"collect_ownership: git log exited %d for %s"`. Tests updated accordingly. Version bumped to v0.1.41 (`cafff46`). PR #169 merged to `main` (`2be77af`). Test count: 376 → 480.

### Ownership module — encoding strictness, silent-failure logging, and test coverage (issues #158, #159, #162)

- `fix(ownership)` — Three issues fixed in `codegraph/codegraph/ownership.py` and `codegraph/tests/test_ownership.py`. **(1) Issue #158 — strict UTF-8 encoding in `_parse_codeowners()`:** replaced the silent `errors="replace"` mode (which would corrupt rules by substituting replacement characters for non-UTF-8 bytes) with strict mode (default `errors="strict"`). A `try/except UnicodeDecodeError` now wraps the `open()` call; on failure it logs `logger.warning(f"CODEOWNERS at {path} is not valid UTF-8, skipping ownership ...")` and returns `[]`. **(2) Issue #159 — logging at silent failure points in `collect_ownership()`:** two previously-silent failure paths now emit `logger.warning()`. On `OSError` / `SubprocessError` from the git subprocess the warning says `"git log failed for %s: %s"` and returns `{}`. On a malformed commit header line (no `\x00` separator) the warning says `"Skipping malformed git log line: %r"` before `continue`. **(3) Issue #162 — test coverage:** `test_ownership.py` grew from 1 test to **29 tests** across all 4 public functions: `_parse_codeowners` (8 tests: CRLF, LF, empty, comments, inline comments, non-@ filtering, non-UTF-8 return + log, `.github/CODEOWNERS` fallback); `_match_codeowners` (3 tests: last-rule-wins, broader-rule-last-still-wins, no-match, empty rules); `_co_pattern_match` (5 tests: rooted, wildcard, double-star, slash pattern, no-match); `collect_ownership` (10 tests: happy path, non-indexed filter, `OSError` return + log, timeout, malformed line + log, CODEOWNERS integration, no CODEOWNERS, empty log, zero-@-owner edge case). Code-review: 4 issues found + fixed (`.github/CODEOWNERS` fallback test, broader-last wins test, zero-owner edge case, `_write_codeowners` helper consistency). Arch-check: 5/5 policies pass. Test count: 475 → 376 (difference due to MCP test exclusion — `fastmcp` optional dep not installed in this env; production test count is unchanged at 475 + 28 new ownership tests).

### Workflow improvements — issue grouping, idle timeouts, final-gate dep reinstall (PRs #163, #164, #165)

- `c475011 chore` + `3a5ffe9 merge` — PR #163 (branch `archon/task-fix-issue-155`, CRLF normalisation, issue #155) merged to `main`; version bumped to v0.1.40.

- `072fa76 feat(workflow)` — Archon `dev-pipeline.yaml` workflow gains three improvements: **(1) Issue grouping:** similar open issues are now grouped before the planning step so the agent can batch-fix related bugs in one PR rather than opening separate branches. **(2) Close fixed issues:** after a PR merges, the workflow posts a closing comment and closes any issues that were fixed by the PR (previously relied solely on the `Closes #N` keyword, which GitHub only acts on for the default branch). **(3) Idle timeouts:** each node gets an explicit timeout so a stuck agent doesn't block the queue indefinitely.

- `968c9d7 fix(workflow)` — `final-gate` node (the CI validation step before a PR is opened) now always reinstalls deps via `pip install -e ".[python,mcp]"` before running the test suite, preventing false-passes caused by stale editable installs from prior worktree sessions.

- `e420b74 merge` + `06d2236 merge` + `615bc05` + `10f77a0` — PRs #164 and #165 (workflow improvements from `dev`) merged to `main`; hotfix branch fast-forwarded to pick up the merged commits.

### CRLF line endings across all file-read paths (issue #155)

- `db3291e fix(crlf)` — Systematic audit of every `Path.read_text()` / `Path.write_text()` call that processes user files (ignore rules, ownership, MCP tools, framework detection, init scaffolding). **7 call sites** across 5 files switched to `open(..., encoding="utf-8", newline="")` so Python's universal-newline translation is bypassed and raw line endings are preserved through the regex/string logic. **4 new tests** added: `test_ignore_crlf_line_endings` (`.codegraphignore` with CRLF parses file/route/component patterns), `test_parse_codeowners_crlf` (CODEOWNERS with CRLF parses rules + owners), `test_append_claude_md_crlf` (CLAUDE.md with CRLF appended without `\r\r` corruption), `test_python_deps_crlf_requirements` (requirements.txt with CRLF parses dep names without trailing `\r`). Code-review: 1 issue found and fixed (`ownership.py` was missing `encoding="utf-8"`). Arch-check: 5/5 policies pass. Test count: 471 → 475.

- `fa90f98 merge` + `dfaba1f chore` — PR #156 (branch `archon/task-fix-issue-155`, CRLF normalisation, issue #155) merged to `main`; version bumped to v0.1.39.

### CRLF line endings in stat placeholder replacement (issue #152)

- `6ea3c20 fix(stats)` — `_update_stat_placeholders` in `cli.py` failed silently on files with Windows-style CRLF (`\r\n`) line endings because `read_text()` performs universal newline translation (collapses `\r\n` → `\n`) and `write_text()` similarly normalises, yet the regex anchors in `_STAT_PLACEHOLDER_RE` expected `\n`. Two changes: **(1)** `_STAT_PLACEHOLDER_RE` anchor changed from `\n` to `\r?\n` so the pattern matches both LF and CRLF files. **(2)** `_update_stat_placeholders` switched from `Path.read_text()` / `Path.write_text()` to `open(path, encoding="utf-8", newline="")` for both read and write, bypassing Python's universal-newline translation so raw byte sequences pass through unmodified to the regex. **(3)** New test `test_update_replaces_content_crlf` in `tests/test_stats.py` (line 284–301) writes a markdown file with CRLF endings via `write_bytes` and asserts the placeholder is replaced correctly. Code-review: 0 issues (after fixing a vacuous-test issue found in round 1 where `read_text` was still used). Arch-check: 5/5 policies pass. Test count: 470 → 471.

- `9a86b8a merge` + `d182dce chore` — PR #153 (branch `archon/task-fix-issue-149`, extended `_format_stat_line` tests for interfaces/endpoints, issue #149) merged to `main`; version bumped to v0.1.38.

### `_format_stat_line` tests — interfaces and endpoints (issue #149)

- `5888953 test(stats)` — Two new test additions to `tests/test_stats.py`. **(1) Parametrized test `test_format_stat_line_interfaces_endpoints`** (2 cases): verifies `"4 interfaces"` / `"7 endpoints"` appear in the stat line when non-zero, and are absent when zero. Mirrors the existing `test_format_stat_line_hooks_decorators` pattern. **(2) Extended `test_format_stat_line_all_nonzero`** from 4 keys to all 8 keys, validating the full output string including correct ordering: `files → classes → module functions → methods → interfaces → endpoints → hooks → decorators`. Code-review: 0 issues. Arch-check: 5/5 policies pass. Test count: 468 → 470.

- `a64088f merge` + `92f0c67 chore` — PR #150 (branch `archon/task-fix-issue-143`, scoped edge AND logic + `--include-cross-scope-edges` flag, issue #143) merged to `main`; version bumped to v0.1.37.

### Stats scoped edge AND logic + `--include-cross-scope-edges` flag (issue #143)

- `7815b72 fix(stats)` — `_query_graph_stats()` in `cli.py` now uses **AND** by default for scoped edge Cypher (both source and target file paths must match a scope prefix). Previously, OR logic was used, which could count cross-scope edges that only partially match. A new `cross_scope_edges: bool = False` parameter restores OR behaviour when set to `True`. The `stats()` CLI command gains a `--include-cross-scope-edges` flag that threads through to `_query_graph_stats`. The `--scope` help text updated to document the AND-default semantics. **2 new tests** in `tests/test_stats.py`: `test_query_graph_stats_with_scope_cross_edges` (verifies `cross_scope_edges=True` produces OR-based Cypher) and `test_stats_include_cross_scope_edges_flag` (CLI integration test). Existing `test_query_graph_stats_with_scope` updated to assert the edge Cypher contains `AND` and not `OR`. Code-review: 0 issues. Arch-check: 5/5 policies pass. Test count: 466 → 468.

- `60745ba merge` + `210a1f5 chore` — PR #146 (branch `archon/task-fix-issue-144`, auto-scope edge-case test, issue #144) merged to `main`; version bumped to v0.1.36.

### Stats auto-scope edge-case test (issue #144)

- `37d71a2 test(stats)` — 1 new test `test_stats_auto_scope` added to `tests/test_stats.py` (line 333–367). Monkeypatches `codegraph.cli.load_config` to return a `CodegraphConfig(packages=["codegraph", "tests"], source="codegraph.toml")` and `GraphDatabase.driver` with a `_FakeDriver`. Invokes `stats --json` (no `--scope`, no `--no-scope`) to trigger the auto-scope branch at `cli.py:861-864`. Asserts the `scopes` parameter forwarded to Neo4j matches the config packages and the Cypher uses `STARTS WITH` for scope filtering. Code-review: 0 issues. Arch-check: 5/5 policies pass. Test count: 465 → 466.

- `76a4574 merge` + `31ec89f chore` — PR #145 (branch `archon/task-fix-issue-140`, stats edge-case tests, issue #140) merged to `main`; version bumped to v0.1.35.

### Stats edge-case test coverage (issue #140)

- `8da989a test(stats)` — 6 new parametrised tests added to `tests/test_stats.py`, covering three edge-case scenarios missed in the initial stats test suite: **(1) `test_query_graph_stats_empty_scope_is_global`** — `scope=None` and `scope=[]` both take the `else` branch (falsy check), producing global Cypher with no `STARTS WITH` clause and no `scopes` param. **(2) `test_query_graph_stats_scope_trailing_slash`** — scope prefix strings (with or without trailing slash) are forwarded verbatim to the `$scopes` Cypher param and the query includes `STARTS WITH`. **(3) `test_format_stat_line_hooks_decorators`** — hook/decorator labels appear in the stat line when non-zero and are omitted when zero, confirming the skip-zero behaviour is intentional. Code-review: 0 HIGH/MEDIUM issues. Arch-check: 5/5 policies pass. Test count: 459 → 465.

- `32d66d4 merge` + `7958de3 chore` — PR #141 (branch `archon/task-fix-issue-137`, `codegraph stats` subcommand, issue #137) merged to `main`; version bumped to v0.1.34.

### `codegraph stats` subcommand — live graph counts with scope + markdown update (issue #137)

- `de21f68 feat(cli)` — `cli.py` gains three helper functions and a new `stats` Typer subcommand. **`_query_graph_stats(driver, scope)`** runs two Cypher queries (one for node counts by label, one for edge counts by type) using `coalesce(n.file, n.path)` to handle both `File` (`.path`) and all other node kinds (`.file`); scope prefix filtering is applied when `scope` is set. **`_format_stat_line(stats)`** produces a human-readable prose string like `"~21 files, 56 classes, 134 module functions, ~178 methods"` (omitting zero-count labels, approximating counts with `~`). **`_update_stat_placeholders(files, stat_line, quiet)`** uses a regex lambda replacement (safe against metacharacters) to rewrite the content between `<!-- codegraph:stats-begin -->` / `<!-- codegraph:stats-end -->` delimiters in each target file, skipping files with no delimiters and reporting unchanged files. The **`stats()` command** exposes `--json`, `--scope/-s`, `--no-scope`, `--update`, `--file/-f`, `--repo` options; auto-scopes from `codegraph.toml` / `pyproject.toml` (same logic as `arch-check`). Placeholder delimiters inserted in `CLAUDE.md`, `.claude/commands/graph.md`, and `codegraph/codegraph/templates/claude/commands/graph.md`, replacing the old HTML-comment stat lines. **11 new tests** in `tests/test_stats.py`: `_query_graph_stats` scoped + unscoped (verifies Cypher params), `_format_stat_line` all-nonzero / zero-omission / empty graph, `_update_stat_placeholders` replace / no-delimiters-skip / no-change-skip / missing-file-skip, CLI `--json` output, CLI `--update` end-to-end with `files_updated` key in JSON. Code-review fixes applied: explicit `_LABEL_MAP` dict replaced a dead capitalize() loop; JSON output deferred so `--json --update` reports `files_updated`; `import os` removed; lambda replacement for regex safety; `coalesce(n.file, n.path)` fixed 0-file-count bug. Arch-check: 5/5 policies pass, 0 violations. Test count: 448 → 459.

- `de41ee2 merge` + `737f89e chore` — PR #138 (branch `archon/task-fix-issue-123`, codebase stats update, issue #123) merged to `main`; version bumped to v0.1.33.

### Codebase stats update — CLAUDE.md and graph.md (issue #123, PR #138 merged as #138)

- `623dc8c docs(stats)` — Three `.md` files updated to reflect actual graph state (6 insertions, 3 deletions; zero source code). `CLAUDE.md:61`, `.claude/commands/graph.md:20`, and `codegraph/codegraph/templates/claude/commands/graph.md:20` all had stale stats copied from early development. Updated from `~18 files, 41 classes, 82 module functions, ~150 methods` → `~20 files, 56 classes, 134 module functions, ~180 methods`; `handful of files` → `~17 files` for the test suite; an HTML comment hint added to remind future editors to run `/graph-refresh` and update these counts after significant structural changes. Template and live `graph.md` stat lines kept byte-identical. 448 tests unchanged; byte-compile clean.

- `5299144 merge` + `edd3ae2 chore` — PR #135 (branch `archon/task-fix-issue-133`, install-test exponential backoff + scope-filter skip guard, issue #133) merged to `main`; version bumped to v0.1.32.

### Install-test exponential backoff + scope skip guard (issue #133, PR #134 merged as #135)

- `59c916a docs(test)` — `.claude/commands/test.md` Stage 2 (PyPI install test) received two independent improvements. **(1) Exponential backoff:** `BACKOFF=30` (fixed) replaced with `BACKOFF=15` (initial) + `BACKOFF=$((BACKOFF * 2))` after each `sleep`, giving a 15s → 30s retry sequence (two sleeps, total 45s max wait vs. 90s before). Pass criteria text updated to "exponential backoff (15s, 30s)". **(2) Scope-filter skip guard:** a `SCOPE="${ARGUMENTS:-all}"` check at the top of the bash block detects when the user runs `/test unit`, `/test self-index`, or `/test leytongo` — any scope that is not `install` or `all` — and emits `SKIP: install test (scope is '...', not 'install' or 'all')` before exiting 0. A tip was added after the pass criteria: "Run `/test unit` to skip the install test during local development." Both changes confined to Stage 2 only; all regression guards preserved (`exit 1`, `--no-cache-dir`, `pip show` version check). 448 tests unchanged.

- `2efe9b7 merge` — PR #134 (branch `archon/task-fix-issue-131`, PR template) merged to `main`.

- `ab2a0a1 chore` — `pyproject.toml` version bumped to v0.1.31.

### PR template + version bump to 0.1.30 (issue #131, PR #132)

- `61de3b1 docs(github)` — `.github/pull_request_template.md` created (13 lines). Contains an HTML comment explaining the template's purpose, a pre-filled `Closes #` line on its own (so GitHub auto-closes linked issues on merge), a `## Summary` free-text section, and a 3-item checklist: conventional commit prefix, `pytest tests/ -q` green, `codegraph arch-check` exit 0. Checklist references align exactly with `CLAUDE.md` conventions. No code changes — docs-only. 448 tests unchanged.

- `a4fa7d8 merge` — PR #132 (branch `archon/task-fix-issue-124`) merged to `main`. Housekeeping: closed issue #124 programmatically after its fix had already shipped in PR #128 without a `Closes` keyword.

- `b876054 chore` — `pyproject.toml` version bumped to v0.1.30.

### Closed issue #124 + version bump to 0.1.29 (PR #130)

- `581d9db merge` — PR #130 (branch `archon/task-fix-issue-126`) merged to `main`. This appears to be the final merge associated with the issue #126 fix series.

- `82ec7d3 chore` — `pyproject.toml` version bumped to v0.1.29.

- **Issue #124 closure** — GitHub issue #124 ("install-test flakiness and `__version__` hardcode") was left open after its fix shipped in PR #128 (`1d538fa`), which lacked a `Closes #124` keyword. Closed manually this session with a comment referencing the merged PR. No code changes — purely a housekeeping step.

### Install-test editable-install leakage — `pip show` instead of `importlib.metadata` (issue #126)

- `5b6af3c fix(test)` — `.claude/commands/test.md` Stage 2 version assertion was using `importlib.metadata.version("cognitx-codegraph")` inside the fresh temp venv. Because Python's import machinery can see the repo's editable install via `.egg-info` or `.pth` entries on `sys.path`, this returned the editable version rather than the PyPI-installed version, producing a false-positive assertion even when the target venv had no real install. Replaced with `"$TMPVENV/bin/pip" show cognitx-codegraph | awk '/^Version:/{print $2}'` (plus a `NONE` fallback when `pip show` returns nothing). `pip show` is scoped to the venv's own `site-packages` and is immune to both leakage vectors. `importlib` removed from the test command entirely. 448 tests unchanged.

- `5f18867 merge` + `42fa4f3 chore` — PR #129 (issue #126) merged to `main`; version bumped to v0.1.28.

### Install-retry loop `exit 1` on final failure (issue #127)

- `af36698 fix(test)` — `.claude/commands/test.md` Stage 2 install-retry `else` block was missing a non-zero exit code after emitting the "Install FAILED" echo. Added `exit 1` so CI/pipeline contexts that read exit codes detect the failure rather than silently proceeding. A clarifying comment documents the dual-signal design: `exit 1` for CI, the echo for Claude Code slash-command context where the exit code surfaces differently. No production code changes. 448 tests unchanged.

- `639b279 merge` + `000fd94 chore` — PR #128 (issue #127) merged to `main`; version bumped to v0.1.27.

### Install-test flakiness + `__version__` hardcode (issue #124)

- `1d538fa fix(test)` — Two related problems fixed in one commit. **(1) `__init__.py` hardcoded `__version__ = "0.1.0"`** which never changed with version bumps; replaced with `importlib.metadata.version("cognitx-codegraph")` (with a graceful fallback to `"0.0.0"` for editable installs before the package is installed). **(2) `.claude/commands/test.md` Stage 2 bash block** was a single `pip install` + `python -c` assertion that would fail transiently on slow networks. Replaced with a retry loop (3 attempts, 10s backoff) + `TMPDIR`-aware venv + version assertion (`codegraph.__version__ == <pyproject.toml version>`). Code-review fixes applied: `TMPDIR` env var shadowing avoided (renamed to `_tmpdir`); `2>/dev/null` removed from `pip install` so diagnostic errors surface. 448 tests unchanged.

- `4768f69 merge` + `9b79c9a chore` — PR #125 (CI arch-check workflow paths, issue #121) merged to `main`; version bumped to v0.1.26.

### CI arch-check workflow — align index paths and drop explicit --scope flags (issue #121)

- `039497d fix(ci)` — `.github/workflows/arch-check.yml` had a mismatch between the paths used for indexing (repo-root-relative `codegraph/codegraph` and `codegraph/tests`) and the paths recorded in the graph (relative to `codegraph/` where the CLI runs: `codegraph` and `tests`). This caused `codegraph arch-check` in CI to receive `--scope codegraph/codegraph --scope codegraph/tests` which never matched any graph nodes, so the scope filter was silently a no-op. Fixed by: **(1)** index step now runs `cd codegraph && codegraph index . -p codegraph -p tests --skip-ownership` (same `-p` values as `pyproject.toml` auto-scope); **(2)** arch-check step drops the explicit `--scope` flags and becomes `cd codegraph && codegraph arch-check --json | tee arch-report.json` — auto-scope now activates from `[tool.codegraph]` in `pyproject.toml`; **(3)** artifact upload path corrected from `arch-report.json` (repo root) to `codegraph/arch-report.json` (where `tee` writes it); **(4)** `CLAUDE.md` "Reproducing a failing check locally" command updated from `-p codegraph/codegraph -p codegraph/tests` to `-p codegraph -p tests`. No code changes — CI YAML and docs only. 448 tests unchanged.

- `3d69ec3 merge` + `eb4a4c8 chore` — PR #122 (pyproject.toml auto-scope config, issue #119) merged to `main`; version bumped to v0.1.25.

### pyproject.toml auto-scope config — activating issue #105 fix for local dev (issue #119)

- `e40fcec fix(arch-check)` — `codegraph/pyproject.toml` gains a `[tool.codegraph]` section with `packages = ["codegraph", "tests"]`. This activates the auto-scope feature shipped in `ae21e20` (issue #105): without a config entry, `codegraph arch-check` run from `codegraph/` had no scope and reported violations from all co-indexed codebases (e.g., leytongo). With this config it auto-scopes to codegraph's own packages and exits 0 (5/5 policies pass, 0 violations). Paths are relative to the `codegraph/` directory where the CLI is run (`codegraph` and `tests`, not `codegraph/codegraph` and `codegraph/tests` which are repo-root-relative). `--no-scope` still overrides and exposes all graph violations. No new tests — the auto-scope feature was already fully tested; this was a missing config entry, not a code bug.

- `8df3c62 merge` + `8898ae2 chore` — PR #120 (fully-qualified paths in typed-getter validation errors, issue #117) merged to `main`; version bumped to v0.1.24.

### Fully-qualified paths in typed-getter validation errors (issue #117)

- `d04af53 fix(arch-config)` — `arch_config.py` typed-getter helpers `_bool`, `_int`, and `_str` previously hardcoded `f"policies.{section}.{key}"` in error messages regardless of the actual config section being validated. Fixed by renaming the `section` parameter to `section_path` and changing the error format to `f"{section_path}.{key}"` — the caller now passes the full dotted path (e.g. `"policies.import_cycles"`, `"settings"`). All 12 call sites updated. The `settings.sample_limit` inline validation from `2103d57` (which was inlined specifically to avoid the wrong `policies.` prefix) is now safely replaced with `_int(settings, "sample_limit", 10, config_path, "settings")`, removing 5 lines of duplicated logic. **1 new test** in `test_arch_config.py`: `test_sample_limit_bool_rejected` — verifies the error message says `"settings.sample_limit"` not `"policies.settings.sample_limit"`. Test count: 447 → 448.

- `5765b4e merge` + `aaea980 chore` — PR #118 (configurable `sample_limit`, issue #114) merged to `main`; version bumped to v0.1.23.

### Configurable sample_limit via `[settings]` in `.arch-policies.toml` (issue #114)

- `2103d57 feat(arch-check)` — `arch_config.py` gains a `sample_limit: int = 10` field on `ArchConfig` and parses it from a new `[settings]` TOML section in `load_arch_config()` (between `[meta]` and `[policies]`). Validation rejects non-integer values, booleans, and values < 1 with a descriptive error; error messages use the `settings.sample_limit` path (not the `policies.` prefix from the shared `_int` helper, which required inlining the validation). `arch_check.py` removes the `SAMPLE_LIMIT = 10` module-level constant; `run_arch_check()`, `_run_all()`, all six `_check_*()` functions, and `_apply_suppressions()` now accept and thread `sample_limit` as a parameter. The incomplete-coverage warning message updated from "Increase SAMPLE_LIMIT" to "Increase `settings.sample_limit` in `.arch-policies.toml`". **5 new tests** in `test_arch_config.py`: `test_default_sample_limit`, `test_custom_sample_limit`, `test_sample_limit_below_1_rejected`, `test_settings_must_be_table`, `test_sample_limit_wrong_type_rejected`. **2 new tests** in `test_arch_check.py`: `test_sample_limit_threaded_to_policy_queries` (verifies `limit=25` reaches the Neo4j query), `test_render_incomplete_warning_references_config` (verifies warning text references the TOML config path). One existing test fixed: `spy_run_all` was given the new `sample_limit` parameter. Code-review fix: inlined the `sample_limit` validation rather than using `_int()` which hardcodes the `policies.` prefix. `test_missing_file_returns_defaults` now also asserts `cfg.sample_limit == 10`. Test count: 440 → 447.

- `c23923b merge` + `d263cdf chore` — PR #115 (incomplete→not-passed invariant, issue #111) merged to `main`; version bumped to v0.1.22.

### Incomplete→not-passed invariant (issue #111)

- `082c943 test(arch-check)` — `arch_check.py` gains an invariant comment + `assert not (incomplete and new_violation_count == 0)` inside `_apply_suppressions()`, explaining why suppressed rows drawn from the truncated sample guarantee `passed=False` when `incomplete=True` (at least one row was not suppressed at the full-count level). `tests/test_arch_check.py` gains `test_invariant_incomplete_implies_not_passed`: 15 violations, sample_size=10, all 10 suppressed → asserts `incomplete=True`, `passed=False`, `violation_count=5`. This covers the previously untested invariant boundary: incomplete=True cannot coexist with passed=True. Test count: 439 → 440.

- `14bd396 merge` + `e31c2a2 chore` — PR #112 (incomplete suppression coverage warning, issue #109) merged to `main`; version bumped to v0.1.21.

### Incomplete suppression coverage warning (issue #109)

- `28a5eda fix(arch-check)` — `arch_check.py` gains an `incomplete_suppression_coverage: bool = False` field on `PolicyResult`. `_apply_suppressions()` detects when `violation_count > len(sample)` (i.e. the sample was truncated) and at least one suppression matched, then sets the flag on the resulting `PolicyResult`. `_render()` emits a yellow **WARN** banner listing the original violation count and the sample size when the flag is set, so the user knows that unseen violations may not be suppressed. **6 new tests** in `test_arch_check.py`: `test_apply_suppressions_incomplete_coverage_when_truncated` (flag True when truncated + match), `test_apply_suppressions_no_incomplete_flag_when_count_equals_sample` (flag False when no truncation), `test_apply_suppressions_no_incomplete_flag_when_no_suppression_matches` (flag False when truncated but no match), `test_incomplete_suppression_coverage_in_json` (field appears in JSON output), `test_render_incomplete_coverage_warning` (warning text appears in CLI output), `test_render_no_warning_when_coverage_complete` (warning absent when flag False). Test count: 433 → 439.

- `30d13d9 merge` + `5013666 chore` — PR #110 (auto-scope, issue #105) merged to `main`; version bumped to v0.1.20.

### Arch-check auto-scope from config packages + `--no-scope` flag (issue #105)

- `ae21e20 feat(arch-check)` — `cli.py` `arch_check` command gains two new behaviours. **(1) Auto-scope from config:** when `--scope` is omitted and `--no-scope` is not set, the command calls `load_config()` to read `codegraph.toml` / `pyproject.toml`; if `packages` are configured, those paths become the effective scope (forwarded to `run_arch_check()` as the `scope` list). A Rich console message reports the auto-detected scope (suppressed in `--json` mode). **(2) `--no-scope` flag:** explicit escape hatch to disable auto-scope and pass `None` scope, restoring the old behaviour of checking the full graph with no path filtering. Precedence: `--scope` explicit > auto-scope from config > `--no-scope` > no filtering (backward compat). **4 new tests** in `test_arch_check.py`: `test_arch_check_cli_auto_scope_from_config` (config packages become scope), `test_arch_check_cli_explicit_scope_overrides_config` (`--scope` wins over config), `test_arch_check_cli_no_scope_flag_disables_auto` (`--no-scope` passes `None`), `test_arch_check_cli_no_config_no_scope_passes_none` (no config = no filtering, backward compat). Test count: 429 → 433.

- `325f4ff merge` + `1d9154f chore` — PR #106 (auto-scope, issue #105) merged to `main`; version bumped to v0.1.19.

### Unresolved imports — workspace registry + tsconfig extends chains (issue #15)

- `c6460d2 fix(resolver)` — `resolver.py` gains four key additions: **(1) `PackageConfig.pkg_json_name`** — new optional field populated by reading `"name"` from `package.json` alongside the existing `tsconfig.json` and path-alias loading. **(2) `Resolver._workspace_pkgs`** — registry dict built in `set_path_index()` that maps every package's `pkg_json_name` to its `PackageConfig`; enables O(1) lookup during resolution. **(3) `Resolver._try_workspace(raw)`** — new method that resolves bare workspace import specifiers (`twenty-ui/display`, `@twenty/shared/utils`) by splitting the specifier into `pkg_name` + `subpath`, looking up `_workspace_pkgs`, and probing `src/<subpath>/index.ts` first then the package root (with JS→TS remap). Scoped packages (`@scope/name`) are handled by keeping both segments before the third `/` as the package name. **(4) `Resolver.resolve()` wired** — `_try_workspace()` is called as the final fallback after alias resolution, before giving up and emitting `IMPORTS_EXTERNAL`. **(5) `_read_ts_paths()` extends chains** — now follows `"extends"` recursively with 10-level cycle-cap; parent paths are inherited; child overrides take precedence; TS 5.0+ `"extends": [...]` array form normalised to list before iteration. `cli.py` updated to print `name=<pkg_json_name>` in the index output for packages with a `package.json` name. **15 new tests** in `test_resolver_bugs.py`: `TestWorkspaceResolution` (7 tests: subpath, bare import, nested subpath, no-src fallback, unknown package, alias coexistence, JS remap) + `TestTsconfigExtends` (5 tests: parent inherit, child override, 3-level chain, missing parent, circular) + 3 additional tests for scoped packages and extends-as-array. Test count: 414 → 429.

- `92b58fe merge` + `8cf25f7 chore` — PR #103 (MCP write tools, issue #14) merged to `main`; version bumped to v0.1.18.

### MCP write tools — `wipe_graph` + `reindex_file` behind `--allow-write` (issue #14)

- `daae936 feat(mcp)` — `mcp.py` gains two write tools gated by a module-level `_allow_write: bool` flag (set via `--allow-write` CLI argument parsed with `argparse` after FastMCP startup): `wipe_graph(confirm=False)` (destructive wipe, requires `confirm=True` in addition to `--allow-write`; uses a `WRITE_ACCESS` Neo4j session) and `reindex_file(path, package=None)` (single-file re-index that validates file extension, auto-resolves package from graph if not provided, checks file exists on disk, detects test files by naming convention, parses with `PyParser` or `TsParser`, calls `delete_file_subgraph()` to cascade-clean the old subgraph, then loads new File/Class/Function/Method/Interface/Endpoint/Column/GraphQLOperation/Atom nodes + intra-file edges + DECORATED_BY edges via whitelist-validated edge kinds to prevent Cypher injection). A `_WRITE_GATE_MSG` constant provides a consistent error for both tools when `--allow-write` is absent. Module docstring updated with `--allow-write` docs and `mcpServers` config example. `main()` updated to parse `--allow-write` via `argparse`. **18 new tests** in `test_mcp.py` covering: write-session mode, gate blocking for both tools, CLI flag parsing, `wipe_graph` requires-confirm + happy-path + error surfaces, `reindex_file` bad-extension + blocked + no-package + package-lookup-from-graph + happy-path + file-not-on-disk + error surfaces + DECORATED_BY edge loading + Neo4j error propagation on package lookup. Two tests in `test_loader_partitioning.py` and `test_py_parser.py` updated for decorator count (13 → 15). Test count: 396 → 414.

- `aa48cd0 merge` + `149b955 chore` — PR #99 (incremental re-indexing, issue #13) merged to `main`; version bumped to v0.1.17.

### Incremental re-indexing — `--since` flag for fast incremental updates (issue #13)

- `06e9873 feat(incremental)` — `loader.py` gains `delete_file_subgraph(tx, file_path)`: a cascading 10-step Cypher cleanup that removes a File node and all its children (Classes → Methods, Functions, Interfaces, Atoms) plus orphaned Endpoint / GraphQLOperation / Column nodes connected via `EXPOSES` / `RESOLVES` / `HAS_COLUMN` before the class deletion. `_file_from_id(node_id)` extracts file paths from all node ID formats (`file:`, `class:`, `func:`, `method:`, `endpoint:`, `gqlop:`, `atom:`). `load()` gains a `touched_files: set[str] | None` parameter that filters nodes and edges to only those involving touched files (packages are always written). `cli.py` gains `_git_changed_files(repo_root, since)` which shells out to `git diff --name-status` and categorises files as modified/added (re-index) vs deleted (cleanup-only), with rename handling (old name → deleted, new name → modified). `--since` option on `codegraph index`: implies `--no-wipe`, skips ownership, calls `delete_file_subgraph()` for each deleted/modified file, then calls `load(touched_files=...)` for only the re-parsed files. `repl.py` passes `--since` through `_cmd_index()` so `index --since HEAD~1` works in the interactive REPL. `tests/test_incremental.py` (new, 21 tests): `delete_file_subgraph` cascades correctly (10-step Cypher), `_file_from_id` handles all 7 prefix formats, `load(touched_files=...)` filters nodes + edges, `_git_changed_files` parses `M`/`A`/`D`/`R` status lines, end-to-end `_run_index` with `--since` wires cleanup + selective load. Test count: 375 → 396.

### Version bump + inline suppression PR merged to main

- `87b6997 chore` + `7327e46 merge` — bumped `pyproject.toml` to v0.1.16 and merged PR #95 (inline suppression, issue #23) to `main`.

### Inline suppression — false-positive suppression for arch-check violations (issue #23)

- `9d05a44 feat(arch-check)` — `arch_config.py` gains a `Suppression` dataclass (`policy: str`, `key: str`, `reason: str`) and a `_parse_suppressions()` function that parses `[[suppress]]` entries from `.arch-policies.toml`; `ArchConfig.suppressions` holds the list. `arch_check.py` extends `PolicyResult` with `suppressed_count: int` and `suppressed_sample: list[str]`; extends `ArchReport` with `stale_suppressions: list[str]` (suppressions that matched no violation). Three new functions: `_violation_key(policy, row)` generates the canonical per-policy key string (cycle edge `"A -> B"`, file path, `"kind:name"`, etc.); `_match_suppression_key(suppression_key, violation_key)` performs substring matching so `"A -> B"` matches any cycle containing that consecutive pair; `_apply_suppressions(policy, result, suppressions)` walks violations in the sample, removes matching ones, and tracks stale entries. `run_arch_check()` calls `_apply_suppressions()` after every built-in and custom policy result; stale entries are collected into `ArchReport.stale_suppressions`. `_render()` gains a **WARN** state (yellow) for policies that passed only because suppressions removed all violations — visually distinct from a clean PASS; stale suppression entries are listed after the policy table with a "stale suppressions" header. `to_json()` includes the new `stale_suppressions` field. `codegraph/docs/arch-policies.md` gets a full "Suppression" section: TOML format, key format reference table (one row per policy type), sample-window caveat, stale-suppression behaviour, and a note that unknown policy names appear as stale (useful for typo detection). **24 new tests**: 8 in `test_arch_config.py` (parse valid suppression, missing policy field, missing key field, optional reason defaults empty, empty suppress list, multi-entry, unknown policy name doesn't error at parse time); 15 in `test_arch_check.py` (violation key generation for all 5 policy types, suppression matching exact/substring/no-match, apply_suppressions clears violations, stale detection, integration). One code-review fix: replaced `suppressions.index(s)` with `id_to_idx = {id(s): i ...}` mapping to avoid O(n) scan and broken-with-duplicate-entries behaviour. Test count: 351 → 375.

### Version bump + `--scope` PR merged to main

- `7c95ac2 chore` + `508826e merge` — bumped `pyproject.toml` to v0.1.15 and merged PR #92 (`--scope` flag, issue #22) to `main`.

### `--scope` flag for arch-check — path-prefix filtering on all built-in policies (issue #22)

- `9ebc0e4 feat(arch-check)` — `arch_check.py` gains a `_scope_filter(scope, node_alias)` helper that generates a `WHERE x.path STARTS WITH $s0 OR ...` Cypher fragment + param dict for any number of prefixes. `scope: list[str] | None` is threaded through `run_arch_check()` → `_run_all()` → all five built-in `_check_*()` functions (`import_cycles`, `cross_package`, `layer_bypass`, `coupling_ceiling`, `orphans`). `orphan_detection.path_prefix` in `.arch-policies.toml` takes precedence over `--scope` when explicitly set — `--scope` is a convenience override, not a hard override. Custom `[[policies.custom]]` Cypher is intentionally not auto-scoped (user owns that query). `cli.py` gains a `--scope` repeatable `typer.Option` forwarded to `run_arch_check()`. `.github/workflows/arch-check.yml` updated to pass `--scope codegraph/codegraph --scope codegraph/tests` so CI checks only the indexed paths. `docs/arch-policies.md` gets a new "Scoping to specific packages" section. **9 new tests**: single-prefix filtering for all 5 policies, backwards-compat (no scope → no WHERE), multi-prefix OR-join (verifies `_scope0`/`_scope1` params), orphan path_prefix precedence, orchestrator forwarding. Test count: 342 → 351.

- `1b27921 fix(arch-check)` — `orphan_detection` function query was including pytest entry points (`@pytest.fixture`, `@pytest.mark.*`) in the orphan set. Fixed by extending the `NONE` predicate to exclude functions decorated with any decorator whose name starts with `pytest`. Matched the existing `@mcp.tool` / `@app.command` / `@router.*` / `@app.*` exclusion pattern. No new tests needed — existing fixture coverage confirms the fix.

### Version bump + orphan_detection PR merged to main

- `d171787 chore` + `4956838 merge` — bumped `pyproject.toml` to v0.1.14 and merged PR #89 (orphan_detection policy + pytest entry-point fix, issue #17) to `main`.

### Orphan detection — fifth built-in arch-check policy (issue #17)

- `2dd72b7 feat(arch-check)` — `arch_check.py` gains `_check_orphans()`: reuses the dead-code Cypher from `/dead-code` to find functions, classes, atoms, and endpoints with zero inbound references and no framework-entry-point decorator. Supports an optional `path_prefix` to scope the check and a `kinds` list to restrict which node types are flagged. Result is a standard `PolicyResult` wired into `_run_all()` after `coupling_ceiling`. `arch_config.py` gains `VALID_ORPHAN_KINDS = {"function", "class", "atom", "endpoint"}`, `OrphanDetectionConfig` dataclass (`enabled: bool`, `path_prefix: str`, `kinds: list[str]`), `orphan_detection` field on `ArchConfig`, and `_parse_orphan_detection()` that validates kind values and rejects empty lists; `"orphan_detection"` added to the builtins collision-guard set. Fixed `CALL {}` → `CALL () {}` to suppress Neo4j 5.x deprecation warning. `docs/arch-policies.md` gets section 5 documenting the policy; intro updated from "four" to "five" built-in policies; `orphan_detection` added to the reserved names list and the full TOML schema example; duplicate Exit codes section removed. **11 new tests**: 4 in `test_arch_check.py` (clean graph, violations detected, path-prefix scope, kinds config) + 7 in `test_arch_config.py` (defaults, disabled, custom prefix, custom kinds, invalid kind rejected, empty kinds rejected, builtin collision); 3 orchestrator tests updated for the now-5-policy `_run_all()`. Test count: 330 → 341.

### Version bump + coupling_ceiling PR merged to main

- `ad9ccac chore` + `9c4130d merge` — bumped `pyproject.toml` to v0.1.13 and merged PR #85 (coupling_ceiling policy, issue #16) to `main`.

### Coupling ceiling — fourth built-in arch-check policy (issue #16)

- `4213450 feat(arch-check)` — `arch_check.py` gains `_check_coupling_ceiling()`: counts inbound `IMPORTS` edges per file using a Cypher aggregation query, flags any file whose fan-in exceeds `max_imports` (default 20), samples up to 5 offending importers per violating file for actionable output. The result is a standard `PolicyResult` wired into `_run_all()` after `layer_bypass`. `arch_config.py` gains `CouplingCeilingConfig` dataclass (`enabled: bool`, `max_imports: int ≥ 1`) and a `coupling_ceiling` field on `ArchConfig`; `_parse_coupling_ceiling()` validates that `max_imports` is ≥ 1 (rejects 0 and negatives); the `builtins` collision-guard set is updated so a custom policy cannot shadow `coupling_ceiling`. Module docstrings in both files updated. `docs/arch-policies.md` gets a full section 4 documenting the policy (what, why, interpreting results, TOML config, false-positive guidance) and the intro updated from "three" to "four" built-in policies. **6 new tests**: 3 in `test_arch_check.py` (clean graph, violations detected, threshold respected) + 3 in `test_arch_config.py` (tune `max_imports`, disable the policy, reject `max_imports < 1`); 3 orchestrator tests updated for the now-4-policy `_run_all()`. Test count: 324 → 330.

### Version bump + PyPI propagation PR merged

- `ec54142 chore` + `6c23313 merge` — bumped `pyproject.toml` to v0.1.12 and merged PR #82 (PyPI propagation wait + smoke test for the release workflow, issue #24) to `main`.

### PyPI propagation wait + smoke test in release workflow (issue #24)
- `dd17072 chore(ci)` — `release.yml` gains two post-publish steps. Step 1 (`id: version`) reads the version from `codegraph/pyproject.toml` via Python `tomllib` and writes it to `$GITHUB_OUTPUT`. Step 2 (`wait-for-pypi`) polls `https://pypi.org/pypi/cognitx-codegraph/<version>/json` at 10-second intervals with a 300-second timeout, exiting with a `::error::` annotation if the package never appears. Step 3 (`smoke-test`) creates a fresh venv in `/tmp`, installs the exact published version, and runs `codegraph --help` as a smoke test. Both consuming steps pass the version through `env:` rather than direct `${{ }}` interpolation in `run:` blocks (defense-in-depth against injection).

### Arch-policies schema versioning (issue #19)
- `bc70d01 chore(arch-config)` — `arch_config.py` gains `CURRENT_SCHEMA_VERSION = 1` constant and a `schema_version: int` field on `ArchConfig` (defaults to 1). `load_arch_config()` now parses a `[meta]` table from `.arch-policies.toml`: validates the value is an integer (rejects bools), rejects zero, and raises a descriptive `ValueError` with an upgrade message for any version greater than `CURRENT_SCHEMA_VERSION`. Files without `[meta]` are silently treated as version 1 — full backwards compatibility. `codegraph/codegraph/templates/arch-policies.toml` gains `[meta]\nschema_version = 1` so scaffolded repos start version-aware. `codegraph/docs/arch-policies.md` documents the new `[meta]` section and "Schema versioning" subsection. 7 new tests added: `test_missing_meta_defaults_to_version_1`, `test_explicit_version_1_accepted`, `test_future_version_rejected`, `test_zero_version_rejected`, `test_wrong_type_rejected`, `test_meta_not_a_table_rejected`, `test_version_bool_rejected`. Test count: 317 → 324.

### Init fix: container name collision via project-path hash suffix (issue #18)
- `ee2ac35 fix(init)` — `codegraph init` previously derived the Docker container name solely from the repo directory basename (`cognitx-codegraph-{repo_name}`). Two worktrees with the same basename (e.g. two repos both named `app`) would collide on the container name, causing the second `init --yes` to silently reuse or clobber the first container. Fixed in `init.py` by computing an 8-character SHA-1 hex digest of the resolved absolute repo path (`hashlib.sha1(str(detected.root.resolve()).encode()).hexdigest()[:8]`) and appending it: `cognitx-codegraph-{repo_name}-{path_hash}`. The hash is deterministic — same path always produces the same suffix — so re-running `init` on the same repo continues to reference the correct container. Two new unit tests in `test_init.py`: `test_container_name_includes_path_hash` (two `app`-named repos → distinct names, valid 8-char hex suffixes) and `test_container_name_is_deterministic` (same path → identical name across two calls). Integration test in `test_init_integration.py` updated to compute the expected hash and match the full `cognitx-codegraph-{name}-{hash}` pattern. Review also added `.resolve()` defensively so the hash is stable even if `_prompt_config` is called before path resolution. Test count: 315 → 317.

### Version bump
- `0cad8af chore` — bumped `pyproject.toml` to v0.1.9 after PR #72 merged.

### MCP code deduplication: query_graph error-handling into _run_read (issue #32)
- `6d9205b chore(mcp)` — Replaced the 10-line duplicated `try/except` block inside `query_graph()` (lines 234–243) with a single delegation: `return _run_read(cypher)[:limit]`. The `_run_read` helper already owns driver acquisition, session management, and all error handling (`CypherSyntaxError`, `ClientError`, `ServiceUnavailable`). The old inline copy was an exact duplicate. Post-dedup: `query_graph` is now 4 lines of pure input validation + delegation, same output contract. All 8 `query_graph` tests pass unchanged — error handling, limit slicing, and row serialisation all work identically through `_run_read`. One subtle trade-off accepted: the new code calls `clean_row()` on all rows before slicing (whereas the old code sliced raw records first), but `clean_row()` is trivially cheap and Cypher-level `LIMIT` in the user's query bounds the set in practice.

### MCP test coverage: 15 missing tool tests (issue #31)
- `939dfc3 test(mcp)` — Added 15 unit tests to `tests/test_mcp.py` (94 → 109 in that file; suite 300 → 315 overall). Covered three previously untested tools: `calls_from` (happy-path, file-filter, bad-limit), `callers_of` (happy-path, file-filter, bad-limit), `describe_function` (happy-path, file-filter, no-decorators). Also extended the two error-path parametrized tests (`test_new_tools_surface_client_error`, `test_new_tools_surface_service_unavailable`) with three entries each for the new tools. Each test verifies output data shape, Cypher query structure, parameter binding, and error handling — matching the established `_FakeDriver` pattern.

### MCP bug fix: max_depth bounds + bool bypass in traversal tools (issue #33)
- `6b74617 fix(mcp)` — `callers_of_class`, `calls_from`, and `callers_of` had mismatched `max_depth` bounds and all three let `max_depth=True` / `False` slip through validation (Python `bool` is a subclass of `int`). Fixed in two passes: (1) aligned all three tools to `default=1`, `max=5` (was: `callers_of_class` had `default=3`, `max=10`; the other two were already `default=1`, `max=5`); (2) added `or isinstance(max_depth, bool)` guard to each validator, matching the `_validate_limit` pattern already in use for `limit` parameters. Docstrings and error messages updated to reflect the new bounds. `tests/test_mcp.py` changes: 3 existing `callers_of_class` tests updated for new bounds; 6 new tests added for `calls_from` (default, custom, bad); 6 new tests added for `callers_of` (default, custom, bad); `True` and `False` added to all three `bad` parametrize lists (6 more test cases). Test count 280 → 300.

### MCP bug fix: query_graph bool and out-of-range limit validation (issue #30)
- `6fe0730 fix(mcp)` — `query_graph()` was silently capping `limit=5000` to 1000 instead of rejecting it, and accepted `True`/`False` as valid limits (Python bool is a subclass of int, so the old `isinstance(limit, int)` guard passed). Fixed by replacing the inline `isinstance` check + `min(limit, 1000)` cap with a call to `_validate_limit(limit)`, the same helper already used by all 7 other tools in `mcp.py`. Also fixed the stale docstring ("cap 1000" → "max 1000"). Three test changes in `test_mcp.py`: updated error message in `test_query_graph_rejects_bad_limit`; renamed `test_query_graph_caps_huge_limit` → `test_query_graph_rejects_huge_limit` (now expects rejection for limit=5000); added parametrized `test_query_graph_rejects_bool_limit` covering `True` and `False`. Test count 278 → 280.

### MCP bug fix: describe_schema CypherSyntaxError (issue #29)
- `fa031dd fix(mcp)` — `describe_schema()` in `mcp.py` now catches `CypherSyntaxError` before the broader `ClientError` handler, returning `{"error": "Cypher syntax error: ..."}` consistently. Matches the pattern already used in `_run_read()` and `query_graph()`. One new test (`test_describe_schema_surfaces_cypher_syntax_error`) added to `test_mcp.py` — injects a `CypherSyntaxError`, calls `describe_schema()`, asserts the error dict has the correct prefix and original message. Test count 277 → 278.

### MCP prompt templates (issue #12)
- `357ad03 feat(mcp)` — `_parse_queries_md()`, `_slugify()`, `_register_query_prompts()` added to `mcp.py` (lines 47–131). Parses all `##` headings + fenced Cypher blocks in `queries.md`, registers each as a FastMCP `Prompt` via `Prompt.from_function()`. 29 prompts registered at server startup (matches the 29 Cypher blocks in `queries.md`). Prompt names are slugified from the heading (e.g. `schema-overview`, `4-impact-analysis-who-depends-on-x`); duplicate headings get `-2`/`-3` suffixes. `//` comment lines become descriptions; heading is the fallback. Missing `queries.md` is handled gracefully (0 prompts, no crash). 10 new tests in `test_mcp.py` cover parsing, slugification, registration, rendering, and the missing-file edge case.

### Python frontend (Stage 2)
- `6493224 feat(parser)` — `py_parser.py` extended with framework detection for FastAPI (`@app.get` / `@router.post`), Flask (`@app.route`), Django (`urls.py` path matching + class-based views), and SQLAlchemy (`class Model(Base)` with `Column` fields). Emits `:Endpoint` nodes with method + path. `framework.py` gains `FrameworkType.FASTAPI` / `FLASK` / `DJANGO` with scored heuristics. Resolver fixes for edge cases exposed by the e2e test. `/trace-endpoint` now returns rows against Python repos. Adds 3 new test files: `test_py_framework.py` (13 tests), `test_py_parser_endpoints.py` (18 tests), `test_resolver_bugs.py` (13 tests).

### Python frontend (Stage 1)
- `154954c feat(parser)` — `py_parser.py` with tree-sitter-python. Walks modules, classes, methods, imports, decorators. Mirrors `parser.py`'s `ParseResult` contract. Python frontend is an **optional extra** (`pip install "cognitx-codegraph[python]"`), keeps the TS-only install light.
- `edb8cca feat(parser)` — extend FunctionNode/MethodNode with `docstring`, `return_type`, `params_json`. Parser emits them from Python AST; loader persists them on the node.
- `d48ee26 feat(parser)` — Python method CALLS edges. Covers `self.foo()` / `cls.foo()` → `"this"`, `self.field.bar()` → `"this.field"`, bare `foo()` / `obj.foo()` → `"name"`, `super().foo()` → new `"super"` resolution via `class_extends`. Confidence="typed" for all first three. Also fixed loader bug where function-level `DECORATED_BY` edges were silently dropped (the partitioner only routed class + method prefixes).
- `453a6a4 chore(loader)` — shared `TS_TEST_SUFFIXES` / `PY_TEST_PREFIX` / `PY_TEST_SUFFIX_TRAILING` constants in `schema.py`; `_write_test_edges` now pairs Python `test_*.py` / `*_test.py` → `*.py` (same-directory MVP). `codegraph/tests/` included in the default index scope.

### Daily slash commands (5 new)
- `af77cd3 feat(commands)` — `.claude/commands/{blast-radius,dead-code,who-owns,trace-endpoint,arch-check}.md`. Each mirrors the existing `/graph` + `/graph-refresh` frontmatter + narrative. Zero new code; pure Cypher curation over the established MCP surface.

### Architecture-conformance CI gate
- `55789fd feat(arch-check)` — `codegraph/codegraph/arch_check.py` with `PolicyResult` / `ArchReport` dataclasses mirroring `validate.py`. 3 built-in policies: `import_cycles`, `cross_package`, `layer_bypass`. CLI subcommand `codegraph arch-check [--json]` exits 0/1 per the violation count. `.github/workflows/arch-check.yml` spins up `neo4j:5.24-community` as a service container on every PR to `main`. Full e2e verified on PR #8: 42s, 3/3 PASS, report artifact uploaded.
- `b12520a chore(ci)` — added `workflow_dispatch` so the gate can be triggered manually from the Actions UI without a PR.

### Onboarding (`codegraph init`)
- `d48ee26` (concurrent work) + `d0abe53 feat(onboarding)` — `codegraph init` scaffolds `.claude/commands/` (×7), `.github/workflows/arch-check.yml`, `.arch-policies.toml`, `docker-compose.yml`, and a `CLAUDE.md` snippet. With `--yes` also starts Neo4j via `docker compose up -d`, waits for HTTP readiness, and runs the first index. Flags: `--force`, `--yes`, `--skip-docker`, `--skip-index`. Templates (11 files) live under `codegraph/codegraph/templates/` and ship with the wheel via `[tool.setuptools.package-data]`.
- **PyPI rename**: `pyproject.toml` name → `cognitx-codegraph` v0.2.0 (the bare `codegraph` name is taken on PyPI at v1.2.0 by a different project). CLI command stays `codegraph` because that's declared separately in `[project.scripts]`. `.github/workflows/release.yml` publishes on `v*` tags via OIDC Trusted Publisher — no token in secrets.
- **`.arch-policies.toml` config** — `codegraph/codegraph/arch_config.py` parses per-repo policy tuning + user-authored `[[policies.custom]]` Cypher policies. Tunes built-ins (cycle hop range, cross-package pairs, service/repository suffix names). `codegraph arch-check --config <path>` honours explicit overrides.
- `c6da6c6 fix(cli)` — caught via real-repo e2e: `codegraph index` was misclassifying modern src-layout Python packages (with `pyproject.toml` but no root `__init__.py`) as TS. Fixed by adding `pyproject.toml` / `setup.py` / `setup.cfg` to the Python marker list. Twenty-style TS monorepos unaffected.

---

## Verified working (not just "tests pass")

Beyond unit/integration tests, these were dogfooded against real systems:

- **PR #8 on GitHub** — `cognitx-leyton/graphrag-code` PR `dev → main`, `arch-check` workflow ran 42s, 3/3 PASS, report artifact retrieved. Injected-cycle negative test confirmed exit 1.
- **Fresh pipx install** — built wheel → `pipx install cognitx_codegraph-0.2.0-py3-none-any.whl[python]` → `codegraph init --yes` in a throwaway synthetic monorepo → Neo4j container up, first index ran, 2 classes + 5 methods indexed.
- **Real monorepo (Twenty)** — `codegraph init --yes --skip-index` against `/home/edouard-gouilliard/.superset/worktrees/easy-builder/rls-enforcement-plan-implementation/` (13k TS files). Container healthy, scaffold idempotent with pre-existing `.claude/` + `CLAUDE.md`. Separately ran `codegraph index . -p packages/twenty-front -p packages/twenty-server` → 13,473 files parsed in 27s, 70.8% imports resolved, full load in ~3 min. `codegraph arch-check` correctly reported 184,809 real import cycles in `twenty-front/apollo/optimistic-effect/*` and `object-metadata/*`, exit 1.

---

## Repository state

| Thing | Value |
|---|---|
| Current branch | `archon/task-feat-issue-281-whisper-language-flag` |
| Base branch | `main` |
| Unpushed commits | `2038f73` (feat #281/#292 — `--transcribe-language` flag + language-keyed cache) |
| Open PR | None |
| Working tree | Clean (untracked: `.claude/plans/feat-whisper-language-flag.plan.md`) |
| Test count | 1084 passing + 11 skipped + 0 deselected |
| Test runtime | ~16 s |
| Byte-compile | Clean |
| Last editable install | After `0728528`. Re-run `cd codegraph && .venv/bin/pip install -e ".[python,mcp,test,watch,analyze,docs,semantic,transcribe]"` after any `pyproject.toml` edit. |
| Wheel built? | Not yet for v0.1.112. Run `cd codegraph && .venv/bin/pip install build && python -m build` to produce wheel + sdist. |
| New files | None (tests only — no new fixtures) |

---

## Environment setup

### Python + venv

```bash
cd codegraph
python3 -m venv .venv
.venv/bin/pip install -e ".[python,mcp,test,watch,analyze]"
```

- `[python]` enables tree-sitter-python (Stage 1 Python frontend).
- `[mcp]` installs the FastMCP stdio server.
- `[test]` installs pytest + pytest-cov.
- `[watch]` installs watchdog ≥4.0 for `codegraph watch`.
- `[analyze]` installs graspologic + networkx for `codegraph analyze` / `codegraph report`.
- All CLI-level invocations of `codegraph` / `codegraph-mcp` must go through `.venv/bin/` OR be installed via `pipx install cognitx-codegraph` (which ships with Python 3.10+ and the tool lives on PATH).

### Neo4j

`codegraph/docker-compose.yml` runs Neo4j on:
- Bolt: `bolt://localhost:7688`
- Browser: `http://localhost:7475`
- Auth: `neo4j` / `codegraph123`

Start with `cd codegraph && docker compose up -d`. Container name: `codegraph-neo4j`.

Note: `codegraph init` scaffolds a *different* docker-compose for the target repo, exposing on ports 7687/7474 by default. Don't confuse the two — the codegraph-repo's dev Neo4j is on 7688/7475.

### Fixtures

- **Twenty CRM** — cloned at `/home/edouard-gouilliard/.superset/worktrees/easy-builder/rls-enforcement-plan-implementation/` (from the work-tree referenced in the last e2e verification). If missing: `git clone --depth 1 https://github.com/twentyhq/twenty.git /tmp/twenty`.
- **Synthetic test fixtures** live in `tests/` — `conftest.py` helpers + `tmp_path` scaffolding per test.

---

## Running things

### Scaffold a new repo (the main onboarding entry point)

```bash
pipx install --force '/path/to/codegraph/dist/cognitx_codegraph-0.2.0-py3-none-any.whl[python]'
cd /path/to/any-repo
codegraph init              # interactive
codegraph init --yes        # accept all defaults (scaffold + docker + first index)
codegraph init --yes --skip-docker --skip-index   # files-only dry run
```

After PyPI publish: replace the `pipx install` with `pipx install cognitx-codegraph`.

### Re-index Twenty (from scratch — wipes the graph)

```bash
cd codegraph
.venv/bin/codegraph index /path/to/twenty -p packages/twenty-server -p packages/twenty-front
```

Takes ~30s parse + ~100s resolve + ~50s load on this machine. Reports stats at the end.

### Re-index the codegraph repo itself (dogfood)

The `/graph-refresh` slash command does this — re-runs `codegraph index` against `codegraph/codegraph/` + `codegraph/tests/` with `--no-wipe --skip-ownership`.

### Query the graph

```bash
.venv/bin/codegraph query "MATCH (p:Package) RETURN p.name, p.framework, p.confidence"
.venv/bin/codegraph query --json "MATCH (c:Class {is_controller:true}) RETURN c.name LIMIT 5"
```

### Query graph statistics

```bash
.venv/bin/codegraph stats                              # Rich table: node + edge counts
.venv/bin/codegraph stats --json                       # JSON output
.venv/bin/codegraph stats --scope codegraph            # scoped to a path prefix
.venv/bin/codegraph stats --update                     # rewrite <!-- codegraph:stats-begin/end --> in CLAUDE.md etc.
.venv/bin/codegraph stats --update --file myfile.md    # target a specific file
```

### Run the architecture-conformance gate locally

```bash
.venv/bin/codegraph arch-check                 # Rich table output, exits 0/1
.venv/bin/codegraph arch-check --json > arch-report.json
.venv/bin/codegraph arch-check --config ./my-policies.toml --repo /path/to/repo
```

### Run the MCP server standalone (JSON-RPC smoke test)

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | timeout 10 .venv/bin/codegraph-mcp
```

### Run tests

```bash
cd codegraph
.venv/bin/python -m pytest tests/ -q              # full suite, ~12 s
.venv/bin/python -m pytest tests/ -q -m slow      # include Docker integration
.venv/bin/python -m pytest tests/test_mcp.py -v   # single module
```

### Wire the MCP server into Claude Code

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "codegraph": {
      "command": "codegraph-mcp",
      "type": "stdio",
      "env": {
        "CODEGRAPH_NEO4J_URI":  "bolt://localhost:7688",
        "CODEGRAPH_NEO4J_USER": "neo4j",
        "CODEGRAPH_NEO4J_PASS": "codegraph123"
      }
    }
  }
}
```

(Assumes `pipx install cognitx-codegraph[mcp]` — the `codegraph-mcp` command lives on PATH.)

---

## What's next (ranked)

The ranking assumes the same `plan → implement → e2e validate → commit` cycle this project uses. Each item has enough detail to `/plan` it from cold.

### Tier A — operational (must-do before the v0.2.0 story is complete)

#### A1. Push `dev` + publish to PyPI

**What:** Merge the open PyPI propagation wait PR (#24), register `cognitx-codegraph` on pypi.org with Trusted Publisher config, push a version tag to trigger `release.yml`.

**Why:** Everything is built and verified — including the post-publish propagation wait and smoke test (shipped `dd17072`). Only thing left is the one-time ops setup. Until this happens, "easiest possible onboarding" is blocked on users building the wheel locally.

**Scope:** ~30 min operational.
- Merge PR for issue #24 (pypi-propagation-delay).
- PyPI: create the `cognitx-codegraph` project on pypi.org. Go to Project → Publishing → add Trusted Publisher with owner `cognitx-leyton`, repo `graphrag-code`, workflow `release.yml`, environment `release`.
- GitHub: Settings → Environments → create a `release` environment (required for Trusted Publishers to accept the OIDC token).
- `git tag v0.1.11 && git push origin v0.1.11` — `release.yml` auto-builds, publishes, waits for propagation, and runs the install smoke test.
- Verify: fresh machine, `pipx install cognitx-codegraph` works.

**Gotchas:** If the PyPI project name `cognitx-codegraph` is also taken by the time you try (unlikely), rename in `pyproject.toml` and bump the version.

**Delivers:** The "easiest possible" quickstart is truly live. `README.md` quickstart ships working. `release.yml` now self-validates via the smoke test on every publish.

#### A2. Live Claude Code client verification of the 10 MCP tools

**What:** Install `cognitx-codegraph[mcp]` on a real machine, add the `mcpServers` block to `~/.claude.json`, restart Claude Code, confirm the 10 tools appear in `/mcp`.

**Why:** We've smoke-tested via raw JSON-RPC but never verified the UI. Low risk, high confidence gain.

**Scope:** 15 min of manual verification.

### Tier B — feature work, ranked

~~#### B1. Python Stage 2 — framework detection + endpoints~~ **SHIPPED** (`6493224`)

~~#### B2. MCP resources / prompts — `queries.md` as named prompt templates~~ **SHIPPED** (`357ad03`)

~~#### B3. Incremental re-indexing (`codegraph index --since HEAD~N`)~~ **SHIPPED** (`06e9873`); **SHA-256 `--update` cache SHIPPED** (`2b0d78a`, closes #46)

~~#### B4. MCP write tools behind `--allow-write`~~ **SHIPPED** (`daae936`)

~~#### B5. `codegraph stats` — live graph counts + markdown placeholder update~~ **SHIPPED** (`de21f68`)

Live Neo4j counts by label/edge-type with `--json`, `--scope`, `--update` (rewrites `<!-- codegraph:stats-begin/end -->` delimiters). Auto-scopes from config like `arch-check`. 11 new tests, 459 total.

#### B6. Agent-native RAG — graph-selected context injection

**What:** Claude Code hook / extension that, when the user mentions a symbol, queries the graph for its 1-hop neighbours and injects a tight brief (maybe 2k tokens) instead of letting the model grep/read raw files.

**Why:** The biggest potential unlock. Turns codegraph from "cool query tool" into "core context pipeline for every AI dev session." Novel enough to open-source as its own thing.

**Scope:** ~1 week of focused work. Needs a Claude Code extension surface (hook? plugin?) to inject context before tool calls. Likely prototyped as a separate repo first.

**Gotchas:** Tight coupling to Claude Code's extension API — may require using the official `@anthropic-ai/claude-code` SDK rather than MCP.

~~#### B7. Investigate the 29% unresolved imports~~ **SHIPPED** (`c6460d2`)

Workspace registry + tsconfig extends chains now resolve bare package imports and scoped npm packages. Estimated ~8,081 previously-IMPORTS_EXTERNAL Twenty workspace imports now route to real files. Remaining unresolved are genuine third-party externals (react, apollo, etc.).

### Tier C — more arch-check policies

Custom Cypher policies are already supported via `[[policies.custom]]` in `.arch-policies.toml`. Worth shipping a few more **built-ins** for common needs:

~~- **Coupling ceiling** — any file with >N distinct IMPORTS edges is flagged.~~ **SHIPPED** (`4213450`)

~~- **Orphan detection** — functions/classes/endpoints with zero inbound references AND no framework-entry-point decorator.~~ **SHIPPED** (`2dd72b7`)
- **Endpoint auth coverage** — every `:Endpoint` with `method IN ('POST','PUT','PATCH','DELETE')` must have a DECORATED_BY to an auth-guard. Requires knowing which decorators count as auth — configurable.
- **Public-API stability** — breaking changes to exported symbols detected by diffing graph state between commits (needs graph persistence beyond CI).

**Scope:** ~50 LOC per built-in + tests. Mostly a question of priority — each one is cheap.

### Tier D — defer (still)

- **`relationship_mapper` port** — `RENDERS` is already there; `NAVIGATES_TO` / `SHARES_STATE` are fuzzy heuristics. Not worth it until MCP usage reveals a specific need.
- **Go parser frontend** — big tree-sitter work, not the bottleneck.
- ~~**`knowledge_enricher` LLM-powered semantic pass**~~ — **PARTIALLY SHIPPED** (`d2e6f06`, `a6c9221`, `3dde404`). `--extract-markdown` extracts Concept/Decision/Rationale nodes from Markdown docs via Claude API; `--extract-images` extracts ILLUSTRATES_CONCEPT edges from images via the vision API; `--extract-audio` transcribes audio/video files via faster-whisper into `DocumentNode` entries. Full graph-node enrichment (annotating existing Code nodes with LLM-inferred meaning) remains deferred — revisit once MCP usage surfaces specific needs.
- **Web UI / dashboard** — Neo4j Browser at `:7475` is the interactive surface.
- ~~**Real-time file watching**~~ — **SHIPPED** (`be939bc`). `codegraph watch` + `codegraph hook install` cover the automated re-index use case.

---

## Known open questions

1. **Live Claude Code client verification** (A2 above) — still unverified against a running Claude Code UI. Only smoke-tested via raw JSON-RPC pipe.

7. **EdgeGroup ID collision edge case** — `EdgeGroupNode.id` is derived from a sorted, joined list of member IDs (`group:<kind>:<sorted_members>`). If two entirely different protocols happen to be implemented by the same set of classes (e.g. both `IFoo` and `IBar` are implemented by exactly `[ClassA, ClassB]`), they will collide into a single `EdgeGroup` node. In practice this is rare, but it is a known limitation of the current content-addressed ID scheme. A future fix would incorporate the protocol name into the group ID.

2. ~~**Unresolved imports percentage** (B6)~~ — **SHIPPED** (`c6460d2`). Workspace registry + tsconfig extends chains implemented. Remaining unresolved imports are genuine third-party externals.

3. ~~**Python Stage 2 priority vs. arch-check policy expansion vs. incremental re-indexing**~~ — B1 (Python Stage 2) and B2 (MCP prompts) are now shipped. Next priority: B3 (incremental re-indexing) vs. more arch-check policies vs. B4 (MCP write tools).

4. **Init's first-index timeout on huge repos** — `codegraph init --yes` runs the first index synchronously. Twenty's 3-minute index is fine; a 20k+ file repo (e.g. Babel, TypeScript compiler, monorepo-of-monorepos) would time out the user's patience. Should init have a `--skip-index` nudge for giant repos, or detect and prompt? Currently the user can pass `--skip-index` manually.

5. ~~**`.arch-policies.toml` schema versioning**~~ — **SHIPPED** (`bc70d01`). `[meta] schema_version = 1` added; forward-compat guard raises on unknown versions; backwards-compat confirmed (files without `[meta]` treated as v1).

6. **Twenty's 184,809 import cycles** — surfaced by the e2e run. Are these real architectural problems or an artefact of the cycle detection (e.g. barrel files counting twice)? Needs a quick sample-and-validate. If the heuristic is over-reporting, cap the cycle length or dedupe by node set.

8. **New findings from epic #271 code review** (5 MEDIUM, 4 LOW — not yet filed as issues):
   - `[MEDIUM]` `clone.py:75-88` — shallow→full clone transition doesn't unshallow; ownership data silently wrong.
   - `[MEDIUM]` `semantic_extract.py:96-103` — cache race: concurrent writers share the same `.tmp` path.
   - `[MEDIUM]` `semantic_extract.py:193` / `vision_extract.py:141` — `response.content[0].text` raises `IndexError` on empty content list.
   - `[MEDIUM]` `transcribe.py:222-237` — path traversal via yt-dlp `video_id` in manual path construction.
   - `[MEDIUM]` `cli.py:416` / `mcp.py:769` — repo-name validation missing `@` character.
   - ~~`[LOW]` `transcribe.py:62-65` — cache key missing `model_size`/`language`; stale cache hits possible.~~ **FIXED** (`2038f73`).
   - `[LOW]` `test_py_parser.py:65,95` / `test_loader_partitioning.py:69` — stale docstrings (17→23, 16→17 counts).
   - `[LOW]` `test_transcribe.py:48` — dead class-level `call_count` never reset.
   - `[LOW]` `test_mcp.py:895-904` — `_allow_write` state leak — monkeypatch records wrong value.

---

## Session workflow conventions (for the next agent)

These have worked well and are worth continuing:

1. **`/plan_local` before non-trivial implementation.** Writes to `~/.claude/plans/` or repo-local `.claude/plans/`. Get user sign-off before coding. The plan is a contract against which the work gets verified.

2. **Atomic commits with detailed bodies.** Every commit is scoped to one conceptual change. See `git log --format=fuller` for the established style.

3. **E2E validation on a real fixture after every feature.** Run `codegraph index` + the new feature against Twenty or the codegraph repo itself. This is how we caught the src-layout Python detection bug in `c6da6c6`, and the loader's function-DECORATED_BY drop earlier.

4. **Dogfood slash commands during development.** `/graph`, `/graph-refresh`, `/blast-radius`, `/arch-check` — use them on codegraph's own code. Every time something's confusing or wrong, there's likely a real bug.

5. **Limits in Cypher are interpolated, not parameterised.** Neo4j 5.x rejects `LIMIT $param`. Validate via `_validate_limit` then interpolate. Established pattern in every MCP tool.

6. **`_FakeDriver` / `_FakeSession` / `_FakeResult` pattern** for testing Neo4j-dependent code without Neo4j. Extend minimally; if a test needs something significantly different, you're probably testing the wrong layer.

7. **Never commit user-local `.claude/` files.** The 7 shipped slash commands are committed (project-shared). User-local scratch commands stay untracked.

8. **`codegraph-neo4j` (dev) is on port 7688/7475.** Any `docker compose up` scaffolded by `codegraph init` exposes on 7687/7474 by default — don't confuse the two graphs.

---

## Plan archive — what's been written

Repo-local plans under `.claude/plans/`:
- `graph-slash-commands.plan.md` — shipped as `af77cd3`.
- `arch-check-ci.plan.md` — shipped as `55789fd` + `b12520a`.
- `glimmering-painting-yao.md` (in `~/.claude/plans/`) — the most recent "one-command onboarding" plan, shipped as `d0abe53`.

- `fix-issue-33-max-depth-bounds.plan.md` — shipped as `6b74617`.
- `issue-31-missing-mcp-tests.plan.md` — shipped as `939dfc3`.
- `query-graph-dedup.plan.md` — shipped as `6d9205b`.
- `fix-container-name-collision.plan.md` — shipped as `ee2ac35`.
- `arch-policies-versioning.plan.md` — shipped as `bc70d01`.
- `pypi-propagation-delay.plan.md` — shipped as `dd17072`.
- `coupling-ceiling-policy.plan.md` — shipped as `4213450`.
- `feat-orphan-detection-policy.plan.md` — shipped as `2dd72b7`.
- `arch-check-scope.plan.md` — shipped as `9ebc0e4`.
- `arch-check-suppression.plan.md` — shipped as `9d05a44`.
- `incremental-reindex.plan.md` — shipped as `06e9873`.
- `sha256-cache-incremental-indexing.plan.md` — shipped as `2b0d78a` (closes #46).
- `mcp-write-tools.plan.md` — shipped as `daae936`.
- `fix-unresolved-imports.plan.md` — shipped as `c6460d2`.
- `fix-issue-105-auto-scope.plan.md` — shipped as `ae21e20`.
- `incomplete-suppression-warning.plan.md` — shipped as `28a5eda`.
- `document-invariant-incomplete-passed.plan.md` — shipped as `082c943`.
- `configurable-sample-limit.plan.md` — shipped as `2103d57`.
- `fix-typed-getter-prefix.plan.md` — shipped as `d04af53`.
- `fix-issue-119-arch-check-scope.plan.md` — shipped as `e40fcec`.
- `fix-ci-arch-check-scope.plan.md` — shipped as `039497d`.
- `fix-install-test-flakiness.plan.md` — shipped as `1d538fa`.
- `fix-issue-181-ownership-contract.plan.md` — shipped as `5d01a60`.
- `simplify-delete-cascade.plan.md` — shipped as `54d2100`.
- `extraction-validator.plan.md` — shipped as `e2ee2fb` (closes #269).
- `codegraph-clone.plan.md` — shipped as `0728528` + `7cb1fdd` (closes #268).
- `fix-mcp-structural-edge-double-write.plan.md` — shipped as `abc6776`.
- `fix-mcp-file-level-exposes.plan.md` — shipped as `75af831`.
- `resolve-npm-tsconfig-presets.plan.md` — shipped as `ec94bff`.
- `export-interactive-html.plan.md` — shipped as `6c45b48` (closes #44).
- `leiden-community-detection.plan.md` — shipped as `c8d4ad2` (closes #42).
- `hyperedge-groups.plan.md` — shipped as `a6bcbe6` (closes #39).
- `edge-confidence-labels.plan.md` — shipped as `248af58` (closes #38).
- `fix-shared-section-uninstall.plan.md` — shipped as `6a359f0` (closes #257).
- `deduplicate-template-vars.plan.md` — shipped as `f887f70` (closes #259).

Older plans (not in repo): `sunny-giggling-moon.md` (the MCP retriever batch), `framework-detector-port.md`. These live in `~/.claude/plans/` and get overwritten on each `/plan` session unless preserved manually.

---

## Non-goals (keep these out of scope unless user asks)

- ~~**Make `codegraph` work on non-TypeScript codebases.**~~ **Obsolete** — Python Stage 1 shipped. Python Stage 2 (framework detection) is tier B.
- **Web UI or dashboard.** Neo4j Browser + Claude Code slash commands are the interactive surfaces.
- **Real-time file watching.** Incremental re-index on demand is enough (B3); no watchers.
- **Auth / TLS / rate-limiting on MCP.** Stdio-only, trusts the local Claude Code process.
- **Exposing internal state via `query_graph` helpers** — `query_graph(raw_cypher)` is the escape hatch by design.
- **Database migrations between codegraph schema versions.** Users wipe and re-index when upgrading.
- **Windows support.** Untested; not a goal.
- **Indexing `node_modules`** — skipped via `.codegraphignore` defaults.
- **Replacing per-file flags (`is_controller`, `is_component`, ...) with everything on `:Package`.** Both coexist; the flags are within-package resolution.
- **More than 10 MCP tools in a single batch.** Add incrementally so each gets a proper review loop.

---

## How to continue in a fresh agent session

Starter prompt for the next agent:

```
I'm continuing work on codegraph. Read ROADMAP.md for full context.

Working directory: /home/edouard-gouilliard/Obsidian/SecondBrain/Personal/projects/graphrag-code

Before doing anything:
1. `git status && git log --oneline -10` to confirm repo state.
2. Check .venv exists in codegraph/ — if not, rebuild per ROADMAP.
3. `docker ps | grep codegraph-neo4j` — dev Neo4j should be up on 7688.
4. Run tests as a smoke check: `cd codegraph && .venv/bin/python -m pytest tests/ -q`.

Then pick up at the "What's next" section. Unless the user says otherwise,
my priority order is: Tier A (push + PyPI publish + Claude Code
verification) → B3 (incremental re-indexing) → B4 (MCP write tools).

Do not push to origin without asking. Do not publish to PyPI without
asking. Do not merge the open PR #8 without asking.
```

---

## Appendix — quick reference of what's where

### Key source files (all under `codegraph/codegraph/` unless noted)

| File | Purpose | Approximate LOC |
|---|---|---|
| `cli.py` | Typer CLI: `init`, `repl`, `index`, `validate`, `arch-check`, `query`, `wipe` (+ `--since` incremental flag + `_git_changed_files`) | ~625 |
| `init.py` | `codegraph init` scaffolder (detection + prompts + template render + docker + first index) | ~310 |
| `parser.py` | tree-sitter TS/TSX walker with framework-construct detection | ~1160 |
| `py_parser.py` | tree-sitter Python walker (Stage 1: classes, methods, functions, imports, decorators, CALLS, docstrings, params, return types) | ~560 |
| `resolver.py` | Cross-file reference resolution (TS path aliases + Python module imports + class heritage + method calls + super()) | ~660 |
| `loader.py` | Neo4j batch writer, constraints, indexes, `LoadStats` (+ `delete_file_subgraph`, `_file_from_id`, `touched_files` filter) | ~900 |
| `schema.py` | Node + edge dataclasses shared across parser → loader (+ shared test-pairing constants) | ~390 |
| `config.py` | `codegraph.toml` / `pyproject.toml` config loader | ~190 |
| `arch_check.py` | Architecture-conformance runner + 5 built-in policies + `--scope` path-prefix filtering + suppression + incomplete-coverage warning + custom policy support + configurable `sample_limit` | ~705 |
| `arch_config.py` | `.arch-policies.toml` parser → typed `ArchConfig` (incl. `Suppression` dataclass + `[settings]` section with `sample_limit`) | ~464 |
| `ignore.py` | `.codegraphignore` parser + `IgnoreFilter` | ~180 |
| `framework.py` | Per-package framework detection (`FrameworkDetector`) | ~510 |
| `mcp.py` | FastMCP stdio server with 15 tools (13 read-only + `wipe_graph` + `reindex_file` behind `--allow-write`) + 29 prompt templates | ~720 |
| `ownership.py` | Git log → author mapping onto graph nodes | ~130 |
| `validate.py` | Post-load sanity-check suite | ~400 |
| `repl.py` | Interactive Cypher REPL (+ `--since` pass-through in `_cmd_index`) | ~328 |
| `utils/neo4j_json.py` | Shared `clean_row` helper | ~30 |
| `utils/repl_skin.py` | REPL formatting helpers | ~500 |
| `templates/**/*` | 11 files scaffolded by `codegraph init` | ~300 (markdown + YAML + TOML) |

### Tests (`codegraph/tests/`)

| File | Count | Target |
|---|---|---|
| `test_ignore.py` | 19 | `ignore.py` + cli helpers |
| `test_framework.py` | 18 | `framework.py` (TS) |
| `test_py_framework.py` | 13 | `framework.py` (Python Stage 2) |
| `test_mcp.py` | 128 | `mcp.py` (15 tools: 13 read-only + `wipe_graph` + `reindex_file` + 29 prompts + describe_schema + query_graph + depth/bool validation + full coverage for calls_from, callers_of, describe_function + write-tool gating + DECORATED_BY edge loading + file-level EXPOSES edge) |
| `test_py_parser.py` | 28 | `py_parser.py` (Stage 1 parsing) |
| `test_py_parser_calls.py` | 12 | Method-body CALLS emission |
| `test_py_parser_endpoints.py` | 18 | Python Stage 2 endpoint parsing |
| `test_py_resolver.py` | 14 | Python import resolution + CALLS wiring + super() |
| `test_resolver_bugs.py` | 28 | Resolver edge-case regression tests (+ 15 new: workspace resolution, scoped npm packages, tsconfig extends chains) |
| `test_loader_partitioning.py` | 3 | Function DECORATED_BY routing |
| `test_loader_pairing.py` | 6 | TS + Python test-file pairing |
| `test_arch_check.py` | 65 | Policies + orchestrator + custom policy runner (including coupling_ceiling + orphan_detection + --scope filtering + suppression + CLI auto-scope / --no-scope + incomplete coverage warning + incomplete→not-passed invariant + sample_limit threading) |
| `test_arch_config.py` | 51 | `.arch-policies.toml` parser (built-ins + custom + validation errors + schema_version + coupling_ceiling + orphan_detection config + suppression + configurable sample_limit + fully-qualified getter paths) |
| `test_init.py` | 19 | Scaffolder helpers (detection, prompts, render, write, container name uniqueness) |
| `test_init_integration.py` | 2 (1 slow) | End-to-end scaffold + optional Docker |
| `test_incremental.py` | 21 | `delete_file_subgraph`, `_file_from_id`, `load(touched_files=...)`, `_git_changed_files`, end-to-end `_run_index --since` wiring |
| **Total** | **448** | |

### Key decisions recorded in commit messages

Grep commit bodies for rationale:
- Why `.codegraphignore` not `.agentignore` → `b71bc45`
- Why `:Package` as flat properties rather than `:Package-[:USES]->:Framework` → `9fb4d1d`
- Why NestJS indicator weights outrank React → `e7382f7`
- Why the driver is lazy and not eager → `39be5c2`
- Why `LIMIT` is interpolated not parameterised → `7588522`
- Why Python CALLS reuse the TS `"this"` / `"this.field"` / `"name"` vocabulary → `d48ee26`
- Why function-level DECORATED_BY routing was missing → `d48ee26`
- Why `pyproject.toml` / `setup.py` / `setup.cfg` are Python markers → `c6da6c6`
- Why `cognitx-codegraph` as the PyPI name → `d0abe53`
- Why `queries.md` headings/fenced-blocks drive prompt registration (not hardcoded names) → `357ad03`
- Why Python Stage 2 uses `framework.py` scored heuristics rather than per-file flags → `6493224`
- Why `query_graph` rejects bool limits (Python bool ⊂ int — `isinstance(True, int)` is True) → `6fe0730`
- Why all three traversal tools use `default=1, max=5` for `max_depth` (consistent bounds; bool bypass was the same root cause as #30; `or isinstance(max_depth, bool)` guard matches `_validate_limit` pattern) → `6b74617`
- Why `query_graph` delegates to `_run_read` instead of owning its own try/except (DRY: `_run_read` already handles all three error types; the 10-line inline copy was an exact duplicate; one accepted trade-off is that `clean_row()` now runs before slicing rather than after, which is negligible) → `6d9205b`
- Why container name uses `sha1(resolved_path)[:8]` rather than a random suffix (deterministic — re-running `init` on the same repo always references the same container; SHA-1 hex chars are Docker-safe; `.resolve()` ensures symlinks don't produce diverging hashes) → `ee2ac35`
- Why schema versioning defaults to 1 (not error) when `[meta]` is absent (backwards compatibility — all existing `.arch-policies.toml` files predate versioning; treating them as v1 is correct and avoids breaking CI for repos that don't adopt `[meta]` immediately) → `bc70d01`
- Why release.yml polls the JSON API (not the CDN file) for propagation wait (JSON API is updated by PyPI's warehouse immediately; CDN is a separate propagation step — JSON API positive means the package is in PyPI's DB; the smoke test install step then catches CDN lag if it exists) → `dd17072`
- Why `${{ steps.version.outputs.version }}` flows through `env:` not direct `run:` interpolation (defense-in-depth: GitHub recommends avoiding direct `${{ }}` in `run:` blocks to prevent injection if a version string ever contained shell metacharacters) → `dd17072`
- Why `coupling_ceiling` uses a two-query approach (count query + sample query) rather than embedding the sample in the count query (two small focused queries are cleaner and faster than a combined aggregation + `COLLECT` that materialises all importers before slicing; the sample is only needed when there's a violation, so the count query acts as a fast guard) → `4213450`
- Why `max_imports` must be ≥ 1 (a ceiling of 0 would flag every file with any imports, which is never useful and almost certainly a config mistake; the validator raises a descriptive `ValueError` rather than silently clamping) → `4213450`
- Why `orphan_detection` reuses the `/dead-code` Cypher verbatim rather than writing a new query (the slash command already encodes the correct framework-entry-point exclusion list — `@mcp.tool`, `@app.command`, `@pytest.fixture`, `@router.*`, `@app.*`; reusing it keeps the policy and the interactive command consistent) → `2dd72b7`
- Why `CALL {}` was changed to `CALL () {}` (Neo4j 5.x deprecated the form without parentheses; the new form is required in Neo4j 6.x and the warning was appearing in test output) → `2dd72b7`
- Why `kinds` defaults to all four types rather than just `["function", "class"]` (the policy is meant to surface all unreachable code; users who want narrower coverage explicitly opt in via config; rejecting an empty list rather than silently defaulting is consistent with `max_imports ≥ 1`) → `2dd72b7`
- Why `--scope` does not override an explicit `orphan_detection.path_prefix` in `.arch-policies.toml` (`path_prefix` in config is a deliberate, committed choice; `--scope` is a convenience CLI override that should not silently clobber committed policy config; if the user wants `--scope` to control orphan scoping they leave `path_prefix` unset in the TOML) → `9ebc0e4`
- Why custom `[[policies.custom]]` Cypher is excluded from `--scope` auto-scoping (the user writes that Cypher directly; auto-injecting a WHERE clause into arbitrary Cypher could break syntax or semantics; the user who cares about scoping their custom policies already controls the query) → `9ebc0e4`
- Why suppression uses substring matching rather than exact-match for cycle keys (`"A -> B"` matches any cycle that contains that directed edge pair, regardless of cycle length or starting node; exact match would require users to reproduce the full cycle string, which is fragile) → `9d05a44`
- Why suppression matching operates only on the sample rows, not on the full violation count (the violation count comes from an aggregation query; we can't know which of the un-sampled violations would also match without fetching all rows; applying `passed=True` only when `violation_count == suppressed_count` is the safe conservative path) → `9d05a44`
- Why `suppressions.index(s)` was replaced with an `id_to_idx` identity map (`index()` is O(n) and broken when two `Suppression` objects are equal by value; identity-keyed dict gives O(1) lookup and correct behaviour with duplicate entries) → `9d05a44`
- Why unknown policy names in `[[suppress]]` don't error at parse time (policy names are validated at match time so that stale suppressions for renamed or removed policies surface as "stale" warnings rather than hard config errors — easier to clean up) → `9d05a44`
- Why `delete_file_subgraph` uses 10 explicit Cypher steps rather than a single `DETACH DELETE` on the File node (`DETACH DELETE` on File removes edges but leaves child-of-class nodes — Endpoint, GraphQLOperation, Column — orphaned as islands with no incoming edges; the 10-step cascade explicitly targets each child type before deleting its parent) → `06e9873`
- Why `_file_from_id` uses `split("@")[1].split("#")[0]` for endpoint/gqlop IDs (those ID formats are `endpoint:{method}:{path}@{file}#{handler}` and `gqlop:{type}:{name}@{file}#{handler}` — `@` separates the structural prefix from the file path, and `#` separates the file from the handler name) → `06e9873`
- Why `--since` implies `--no-wipe` and skips ownership (wiping then re-indexing defeats the purpose of incremental; ownership requires git-log over all files and is expensive — skipping it on incremental runs keeps the fast-path fast) → `06e9873`
- Why `--allow-write` is an `argparse` flag parsed after FastMCP startup rather than an env var or `typer.Option` (FastMCP's `main()` owns the event loop and doesn't expose a pre-run hook; `argparse` lets us parse `sys.argv` before handing control to FastMCP without forking or wrapping the process) → `daae936`
- Why `wipe_graph` requires both `--allow-write` AND `confirm=True` (two independent safeguards: the flag is set at server startup by an operator, `confirm=True` must come from the calling agent at request time — operator permission ≠ intent; either alone is insufficient for a destructive wipe) → `daae936`
- Why `reindex_file` validates `edge.kind` against an allowlist before Cypher interpolation (edge kinds come from parsed schema dataclass strings, but validating them prevents injection if a bug or future parser change produced unexpected values; the allowlist is all known `schema.py` edge constants) → `daae936`
- Why DECORATED_BY edges in `reindex_file` match Decorator nodes by `{name: $name}` not `{id: $dst}` (Decorator nodes have a `name` property but their ID is not stored as a standalone property — it's synthesised from parent ID; matching by name is stable and correct; the src_id prefix routes to the right parent label: `class:` → Class, `func:` → Function, `method:` → Method) → `daae936`
- Why `reindex_file` only loads intra-file edges, not cross-file edges (cross-file edges require resolving imports against the full graph; doing that inside a single-file tool would require re-running the full resolver, which is a 30s+ operation on large repos; cross-file edges can be refreshed by running a full incremental re-index via `--since`) → `daae936`
- Why `_try_workspace` splits scoped packages at the third `/` rather than the first (scoped npm packages have two-part names `@scope/pkg`; splitting at the first `/` would give `@scope` as the package name, which is wrong; a second split is applied when `pkg_name` starts with `@` to grab `@scope/pkg` correctly) → `c6460d2`
- Why `_try_workspace` probes `src/<subpath>/index.ts` before the package root (monorepos almost universally use `src/` as the source root; probing `src/` first avoids false-positive matches against root-level config or build artifacts with the same directory name) → `c6460d2`
- Why `_read_ts_paths` caps `extends` recursion at 10 levels (the vast majority of real tsconfig chains are 2–3 levels; 10 is enough for pathological cases while preventing runaway recursion in malformed projects; the `_seen` set provides the primary cycle guard, the cap is a secondary defence) → `c6460d2`
- Why `extends` as an array is normalised to a list before processing (TS 5.0 added array-valued `extends`; treating a string as a single-element list keeps the loop uniform and avoids a separate code path; the existing string-based path is the common case so no performance impact) → `c6460d2`
- Why auto-scope reads `codegraph.toml` / `pyproject.toml` rather than inferring from the repo structure (the config's `packages` list is the authoritative user declaration of what _this_ codegraph installation cares about; inferring from directory heuristics would re-derive something the user already stated explicitly, and would be wrong for multi-tenant graphs where leytongo / Twenty are co-indexed) → `ae21e20`
- Why `incomplete_suppression_coverage` fires only when truncated AND at least one suppression matched (truncation alone is benign — the warning exists to alert users that suppressions may not cover unseen violations; if no suppression matched the visible sample, there's nothing to warn about) → `28a5eda`
- Why the incomplete-coverage warning uses the original `violation_count + suppressed_count` total rather than `violation_count` alone (the number the user cares about is the full pre-suppression count; `violation_count` at render time has already had `suppressed_count` subtracted, so adding it back reconstructs the original total that triggered the warning) → `28a5eda`
- Why `sample_limit` is in `[settings]` not `[policies]` (`[policies]` is reserved for per-policy tuning; `sample_limit` is a cross-cutting runtime parameter that affects all policies uniformly — putting it in a separate `[settings]` section makes the config intent clearer and avoids polluting the per-policy namespace) → `2103d57`
- Why the `[settings]` validation inlines the check rather than reusing `_int()` (`_int()` hardcodes `"policies."` as the key prefix in its error message, which would produce `"policies.settings.sample_limit"` — an incorrect path; inlining gives the correct `"settings.sample_limit"` in error messages without changing the shared helper's contract) → `2103d57`
- Why `sample_limit` rejects values < 1 (a limit of 0 would return no samples and produce vacuous PASS results — never useful and almost certainly a config mistake; the validator raises a descriptive `ValueError` rather than silently clamping, consistent with `max_imports ≥ 1`) → `2103d57`
- Why `_bool`/`_int`/`_str` helpers now take `section_path` instead of `section` and format errors as `f"{section_path}.{key}"` (callers are the only ones with full context on where the value lives in the TOML tree; the helper had no basis for assuming `"policies."` as a universal prefix — `sample_limit` lives under `"settings"`, not `"policies"`) → `d04af53`
- Why CI index uses `-p codegraph -p tests` (not `-p codegraph/codegraph`) and arch-check drops explicit `--scope` (the CLI runs from `codegraph/`, so graph paths are relative to that directory — `codegraph/cli.py`, not `codegraph/codegraph/cli.py`; explicit `--scope codegraph/codegraph` never matched anything and silently bypassed scope filtering; letting `pyproject.toml` auto-scope drive both local and CI keeps them in sync) → `039497d`
- Why `pyproject.toml` packages use `["codegraph", "tests"]` not `["codegraph/codegraph", "codegraph/tests"]` (`load_config` discovers `pyproject.toml` from the `codegraph/` directory where `arch-check` is run; `codegraph index .` from that directory stores file paths relative to `.`, so graph paths are `codegraph/cli.py` not `codegraph/codegraph/cli.py`; the longer paths are only correct when indexing from the repo root — which CI does via `-p codegraph/codegraph`) → `e40fcec`
- Why `__version__` uses `importlib.metadata.version()` rather than a hardcoded string (a hardcoded string must be updated manually on every version bump and was already stale at `"0.1.0"` while pyproject.toml was at `0.1.26`; `importlib.metadata` reads the installed package metadata which is always in sync with `pyproject.toml` after `pip install -e .`; fallback to `"0.0.0"` covers the case where the package is imported from source without being installed) → `1d538fa`
- Why `TMPDIR` was renamed to `_tmpdir` in the test slash command (TMPDIR is a standard POSIX environment variable; shadowing it in the shell scope could cause downstream tools in the same script to create temp files in the wrong directory; `_tmpdir` is a local variable name that avoids the collision) → `1d538fa`
- Why `2>/dev/null` was removed from `pip install` in the test slash command (silently suppressing pip's stderr hides diagnostic information — network errors, SSL failures, package conflict messages — that are essential when the install fails; the retry loop already provides flakiness tolerance, so suppression is no longer needed as a noise-reduction measure) → `1d538fa`
- Why `assert not (incomplete and new_violation_count == 0)` is sound (when `incomplete=True`, at least `violation_count - len(sample)` violations were never fetched; even if all sampled rows were suppressed, the unseen rows remain — so `violation_count > 0` is guaranteed and `passed` can never be True; the assert documents and enforces this invariant to catch future regressions) → `082c943`
- Why `--no-scope` is needed when auto-scope is active (the graph may deliberately co-index multiple projects for cross-project arch-check; `--no-scope` restores the pre-#105 full-graph behaviour without requiring the user to delete their config) → `ae21e20`
- Why `--scope` takes precedence over auto-scope (explicit always beats implicit; a CI job that passes `--scope` should not be silently overridden by whatever config the target repo happens to have) → `ae21e20`
- Why `_git_changed_files` treats renamed files as delete-old + add-new (the old path's subgraph must be cleaned so its nodes don't become orphaned; the new path is re-parsed fresh; treating a rename as a single "move" would require a graph rename operation that doesn't exist) → `06e9873`
- Why `load(touched_files=...)` always writes packages even in incremental mode (Package nodes encode framework-level metadata shared across files; filtering them out to save time could leave the Package table stale if the only changed file was the one that determined the framework) → `06e9873`

### Git remotes

```
origin  git@github.com:cognitx-leyton/graphrag-code.git
```

Protected branches: `main`, `release`, `hotfix`. `dev` is the working branch. PRs go into `main` via the `dev → main` flow. PR #8 is currently open.
