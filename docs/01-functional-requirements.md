# 01 — Functional Requirements

**Status:** for review · **Depends on:** `docs/00-audit-findings.md`

Every requirement has an ID, a priority, an acceptance criterion you can actually run, and a
traceability link back to the audit finding that motivated it. IDs are stable: the roadmap, tests,
and commit messages reference them.

**Priority (MoSCoW):** `M` must have (v1 is not shippable without it) · `S` should have (v1 target,
descopable under pressure) · `C` could have (v1.1) · `W` won't have (explicitly out of scope, recorded
so it does not creep back in).

**Traceability:** `F-nn` refers to findings in `docs/00-audit-findings.md`.

---

## A. Content model and naming (`FR-CON`)

| ID | Pri | Requirement | Acceptance criterion | Traces |
| --- | --- | --- | --- | --- |
| FR-CON-01 | M | Note filenames are human-readable slugs. No timestamp prefixes in filenames. | No file under `wiki/` matches `^\d{8,14}-`. Enforced by lint rule W010. | F-06 |
| FR-CON-02 | M | Every note carries an immutable `uid` in frontmatter, assigned at creation and never changed, even when the title or slug changes. | Every `wiki/**/*.md` has a unique `uid`; renaming a note in a test leaves `uid` untouched. | F-06, F-12 |
| FR-CON-03 | M | Renames never break inbound links. A note may declare `aliases: []`; the old slug and the bare UID are auto-added on rename. | Test: rename a note via `wiki rename`, then every pre-existing `[[old-slug]]` still resolves; `wiki lint` reports 0 broken links. | F-06 |
| FR-CON-04 | M | Frontmatter is validated against a published schema (`uid`, `title`, `type`, `created`, `updated`, `tags`, `sources`, optional `aliases`, `status`). `type` is a closed enum. | `wiki lint --strict` fails on a note with a missing key or an unknown `type`. | F-12 |
| FR-CON-05 | M | Slug generation is collision-safe: an existing slug produces a suffixed slug (`-2`) or an explicit error, never a silent overwrite. | Test: ingest two sources titled `Attention Is All You Need!` and `Attention, is all you need?` — two files exist, both with content. | F-07 |
| FR-CON-06 | M | Slug generation never yields an empty string. Non-Latin titles are transliterated or fall back to `<type>-<uid>`. | Test: a source titled `机器学习` produces a non-empty, non-dotfile filename. | F-08 |
| FR-CON-07 | S | Raw sources and their literature notes are unambiguously distinguishable by name or link syntax. | `[[x]]` never resolves to two candidate pages; ambiguity is a lint error (W012). | F-09 |
| FR-CON-08 | M | Wikilinks are never emitted inside inline code spans or fenced code blocks by any generator (CLI, templates, LLM prompts). | Grep of all templates and generator strings finds zero `` `[[ `` sequences; lint rule W001 fails the build if one appears. | F-01, F-02 |
| FR-CON-09 | S | Each wikilink carries a rationale (`[[target]] — why this link exists`). The rationale is stored as the graph edge label. | `wiki lint` warns (W020) on a link with no rationale; `wiki graph --json` includes `rationale` per edge. | F-13 |
| FR-CON-10 | S | Diagrams are generated from real link data, not hand-maintained. Mermaid blocks contain no wikilinks. | Lint rule W002 fails on a wikilink inside a fence; MOC diagrams are produced by `wiki graph --mermaid`. | F-03 |
| FR-CON-11 | M | `wiki/index.md` and `wiki/log.md` conform to the same frontmatter schema as every other page. | `wiki lint --strict` passes on both files. | F-12 |
| FR-CON-12 | S | The activity log is machine-readable (structured records) while remaining human-readable markdown. | `wiki log --json` returns parsed entries with `date`, `action`, `summary`, `refs`. | F-36 |
| FR-CON-13 | M | `sources/` remains immutable. No command writes to or deletes from an existing file in `sources/`. | Test: every command is run against a fixture repo; `sources/` file hashes are unchanged except for newly added files. | — |
| FR-CON-14 | C | A note may declare `status: draft \| review \| stable` so the web UI can visually flag unreviewed AI output. | Web page renders a "draft" badge when `status: draft`. | F-24 |

---

## B. Quality gates and linting (`FR-LINT`)

| ID | Pri | Requirement | Acceptance criterion | Traces |
| --- | --- | --- | --- | --- |
| FR-LINT-01 | M | Lint exits non-zero when errors are present, so it can gate CI. `--strict` promotes warnings to errors. | `wiki lint` on a fixture with a broken link exits 1. | F-10 |
| FR-LINT-02 | M | Every rule has a stable ID, a severity, a one-line explanation, and a documented fix. | `wiki lint --explain W001` prints the rationale and the fix. | F-11 |
| FR-LINT-03 | M | Lint supports `--json` output for CI annotations and the web UI health page. | Output validates against the published findings JSON schema. | F-11 |
| FR-LINT-04 | S | Findings can be suppressed deliberately, per line or per file, with a required reason. | A `<!-- wiki-lint-disable W020: intentional -->` comment suppresses exactly that finding; suppressions without a reason are themselves an error. | F-11 |
| FR-LINT-05 | M | Lint is linear in corpus size: the graph is built once, then queried. | Benchmark: 2,000 synthetic notes lint in under 5 seconds (see NFR-PERF-04). | F-14 |
| FR-LINT-06 | M | Rules cover, at minimum: unrendered wikilinks (W001/W002), broken targets (W003), ambiguous targets (W012), orphan atomic notes (W004), missing/invalid frontmatter (W005–W007), UID-prefixed filenames (W010), unindexed sources (W008), bloated zettels over 250 lines (W009), missing link rationale (W020), duplicate UIDs (W011). | Each rule has at least one passing and one failing unit-test fixture. | F-01…F-14 |
| FR-LINT-07 | S | `wiki fix` auto-repairs the mechanically safe subset (unwrap backticked links, add missing `uid`, normalise `updated`) and prints a diff before writing. | Test: `wiki fix --dry-run` on the current repo lists the 27 backtick unwraps without modifying files. | F-01, F-12 |
| FR-LINT-08 | S | An AI audit (`wiki ai-lint`) reports contradictions, stale claims, and conceptual gaps — advisory only, never gating CI. | Nightly workflow produces a report artifact; a failure or empty LLM response does not fail the pipeline. | F-22 |

---

## C. CLI (`FR-CLI`)

The CLI is the primary authoring interface and must stay pleasant to use from a terminal.

| ID | Pri | Requirement | Acceptance criterion | Traces |
| --- | --- | --- | --- | --- |
| FR-CLI-01 | M | Installed as a real command: `pip install -e .` provides `wiki`. | `wiki --version` works from any directory. | F-28 |
| FR-CLI-02 | M | Built on a real CLI framework with `--help` per subcommand, typed options, and clear errors. | `wiki search --help` documents `--top-k`, `--json`, `--type`. | F-27 |
| FR-CLI-03 | M | Exit codes are meaningful: `0` success, `1` findings/failure, `2` usage error, `3` external service failure. | Test matrix asserts each code. | F-10 |
| FR-CLI-04 | M | Every read command supports `--json` for scripting and agent use. | `wiki search "attention" --json \| jq '.results[0].slug'` works. | F-11 |
| FR-CLI-05 | M | Read-only commands have no side effects (no directory creation, no log writes). | Test: `git status --porcelain` is empty after `wiki lint`, `wiki search`, `wiki stats`, `wiki graph`. | F-37 |
| FR-CLI-06 | M | Command surface (see table below) covers the full authoring loop: create, ingest, link, search, ask, audit, publish. | Every command in the table has an integration test. | — |
| FR-CLI-07 | S | Global flags: `--repo <path>` (operate on a wiki elsewhere), `--quiet`, `--verbose`, `--no-color`. | `wiki --repo /tmp/other lint` works from an unrelated cwd. | F-26 |
| FR-CLI-08 | S | Shell completion for bash/zsh/fish. | `wiki --install-completion` succeeds. | F-27 |
| FR-CLI-09 | S | Mutating commands support `--dry-run`, and destructive ones require confirmation or `--yes`. | `wiki rename --dry-run` prints planned edits only. | F-18 |
| FR-CLI-10 | C | An MCP server wrapper exposes the same operations as tools, so Cursor/Claude can drive the wiki natively. | MCP server lists `search`, `read`, `create`, `link`, `lint` tools. | — |

### Target command surface

Existing commands are preserved as aliases so muscle memory and `AGENTS.md` keep working.

| Command | Purpose | New? |
| --- | --- | --- |
| `wiki new <type> "Title"` | Create a zettel/concept/entity/moc/synthesis from a template | replaces `new-zettel` |
| `wiki ingest <url\|path>` | Auto-detect source kind (arXiv, YouTube, web, PDF, local doc) and ingest | unifies 4 commands |
| `wiki ingest-arxiv\|-youtube\|-web\|-pdf` | Explicit per-kind ingest, kept as aliases | existing |
| `wiki search "<query>"` | Hybrid lexical + semantic search with snippets | improved |
| `wiki ask "<question>"` | Grounded RAG answer with citations, optional `--save-as` to file it back into the wiki | replaces `query` |
| `wiki summarize <source>` | LLM literature note for a raw source | renames `ai-summarize` |
| `wiki lint [--strict] [--json] [--fix]` | Quality gate | improved |
| `wiki ai-lint` | Advisory LLM graph audit | existing |
| `wiki graph [--focus s] [--depth n] [--json\|--mermaid]` | Emit the knowledge graph | **new** |
| `wiki backlinks <slug>` | List inbound links with rationales | **new** |
| `wiki open <slug>` | Print/open a note by slug, alias, or UID | **new** |
| `wiki rename <old> <new>` | Rename a note, rewrite all inbound links, record alias | **new** |
| `wiki link <a> <b> --why "..."` | Add a bidirectional link with rationale to both notes | **new** |
| `wiki orphans` | Notes with no inbound links | **new** |
| `wiki index --rebuild` | Regenerate `wiki/index.md` from frontmatter | **new** |
| `wiki reindex` | Rebuild the search index | **new** |
| `wiki stats` | Graph metrics: counts, density, hubs, orphans | improved |
| `wiki auto-link` | Suggest missing links | improved |
| `wiki log <action> <summary>` | Append a log entry | existing |
| `wiki serve [--port] [--reload]` | Run the web app locally | **new** |
| `wiki doctor` | Check env, deps, API key validity, index freshness | **new** |
| `wiki export --format obsidian\|json\|zip` | Export the vault | C |

---

## D. Ingestion (`FR-ING`)

| ID | Pri | Requirement | Acceptance criterion | Traces |
| --- | --- | --- | --- | --- |
| FR-ING-01 | M | Supported sources: arXiv, YouTube (with transcript), web article, local PDF, local text/markdown. | One integration test per kind against recorded fixtures (no live network in CI). | — |
| FR-ING-02 | M | Ingest failures fail loudly: a missing transcript or unparseable PDF produces a non-zero exit and **no** partial file containing an error message as content. | Test: simulate transcript failure — command exits 3, no file written. | F-15 |
| FR-ING-03 | M | The YouTube path targets the installed library API and is version-pinned. | Integration test passes against the pinned `youtube-transcript-api` major version. | F-15 |
| FR-ING-04 | M | Every ingest produces both the raw source file and a literature-note stub, consistently across all source kinds. | Test: after each ingest kind, `wiki lint` reports no unindexed source. | F-16 |
| FR-ING-05 | M | Ingest is idempotent and content-addressed: re-ingesting the same source detects the existing copy and requires `--force`, reporting a content diff. | Test: ingest twice — second run exits 0 with "already ingested, unchanged". | F-18 |
| FR-ING-06 | S | Structured metadata (authors, publication date, canonical URL, arXiv ID, channel, duration, retrieval timestamp, content hash) is captured in frontmatter. | Ingested arXiv fixture has all fields populated and HTML entities decoded. | F-17 |
| FR-ING-07 | M | XML/HTML is parsed with real parsers over HTTPS; entities are decoded. | Test: a fixture titled `Attention & Beyond` is stored with a literal `&`. | F-17 |
| FR-ING-08 | M | URL fetching enforces an allowlist-by-scheme, blocks private/link-local/loopback address ranges, limits redirects, caps response size, and sets timeouts. | Test: ingesting `http://169.254.169.254/` and `http://127.0.0.1:5432` is refused. | F-19 |
| FR-ING-09 | S | Batch ingest from a list file, with per-item success/failure summary and continue-on-error. | `wiki ingest --from-file urls.txt` reports `7 ok, 1 failed`. | — |
| FR-ING-10 | C | Image assets referenced by a source are downloaded to `sources/assets/` and rewritten to local paths. | Ingested article with images has local relative paths. | — |
| FR-ING-11 | S | After ingest, the tool proposes (does not silently apply) wiki updates: which MOCs, concepts, and entities should change. | `wiki ingest <url> --propose` prints a change plan. | — |

---

## E. Search (`FR-SRCH`)

This is the "Google search window" you asked for. Search quality is the make-or-break feature.

| ID | Pri | Requirement | Acceptance criterion | Traces |
| --- | --- | --- | --- | --- |
| FR-SRCH-01 | M | One retrieval implementation, shared by CLI, web, and the RAG pipeline. | `grep -c "idf"` across the codebase finds the scoring maths in exactly one module. | F-30 |
| FR-SRCH-02 | M | Lexical search uses a real inverted index (SQLite FTS5, BM25 ranking) built from the markdown files. | `wiki reindex` builds an index; `wiki search` uses it; deleting the index and re-running rebuilds transparently. | F-31 |
| FR-SRCH-03 | M | Results include title, type, breadcrumb path, score, and a highlighted snippet showing the matched terms in context. | JSON result objects contain all six fields. | — |
| FR-SRCH-04 | M | Search covers `wiki/` and `sources/` with a filter, so you can search compiled knowledge, raw sources, or both. | `wiki search "x" --scope wiki\|sources\|all` behaves accordingly. | F-30 |
| FR-SRCH-05 | S | Filters: `--type`, `--tag`, `--since`, `--source`. Web UI exposes the same as chips. | Filtered search returns a strict subset. | — |
| FR-SRCH-06 | S | Semantic search via embeddings, fused with BM25 using Reciprocal Rank Fusion. Degrades gracefully to lexical-only when no embedding provider is configured. | With embeddings disabled, search still returns results and logs a notice. | F-23 |
| FR-SRCH-07 | S | Chunk-level indexing (heading-scoped chunks) so long sources are retrievable by section, and RAG context is built from chunks, not whole files. | `wiki ask` citations reference a heading anchor, not just a file. | F-23 |
| FR-SRCH-08 | M | Typo tolerance and prefix matching so search-as-you-type is useful from the third keystroke. | `attentoin` returns the attention pages; `atten` returns results. | — |
| FR-SRCH-09 | S | The index updates incrementally on file change (mtime + content hash), and a stale index is detected and reported. | `wiki doctor` reports index freshness; editing one note reindexes only that note. | — |
| FR-SRCH-10 | C | Query logging (local only) to power "recent searches" and to measure which queries return nothing. | Web UI shows recent searches; `wiki stats --queries` lists zero-result queries. | — |

---

## F. Knowledge graph (`FR-GRAPH`)

| ID | Pri | Requirement | Acceptance criterion | Traces |
| --- | --- | --- | --- | --- |
| FR-GRAPH-01 | M | A graph is derived from wikilinks: typed nodes (zettel, concept, entity, moc, source, synthesis) and directed edges carrying the link rationale. | `wiki graph --json` emits `{nodes:[{slug,type,title}], edges:[{from,to,rationale}]}`. | F-13 |
| FR-GRAPH-02 | M | Backlinks are computed, never hand-maintained, and shown on every page. | Opening a note in the web UI lists every page linking to it with the rationale text. | F-14 |
| FR-GRAPH-03 | M | Link resolution handles slug, alias, UID, and case-insensitive title, and reports ambiguity rather than guessing. | Unit tests for each resolution path plus the ambiguous case. | F-05, F-09 |
| FR-GRAPH-04 | M | Unresolved links are visibly marked in the UI (broken-link styling) rather than silently rendered as text. | A note with `[[does-not-exist]]` renders a distinct broken-link style. | F-01 |
| FR-GRAPH-05 | S | Clicking a broken link offers "create this note", pre-filled with the referring context. | Interaction creates a stub with correct frontmatter and a backlink. | — |
| FR-GRAPH-06 | M | Interactive graph views: local graph (focus node, adjustable depth) and global graph, both filterable by type and tag. | `/graph` renders; `/graph?focus=<slug>&depth=2` centres on that node. | — |
| FR-GRAPH-07 | S | Graph metrics: degree centrality (hubs), orphans, weakly-connected components, and "concepts mentioned but never given a page". | `wiki stats` reports all four. | F-14 |
| FR-GRAPH-08 | C | Link suggestions ranked by embedding similarity, presented as a review queue rather than applied automatically. | Suggestion list is reviewable and individually acceptable. | — |
| FR-GRAPH-09 | S | Nodes carry enough metadata for visual encoding: type → colour, inbound-link count → size, recency → opacity. | Graph JSON includes `degree` and `updated`. | — |

---

## G. Web interface (`FR-WEB`)

| ID | Pri | Requirement | Acceptance criterion | Traces |
| --- | --- | --- | --- | --- |
| FR-WEB-01 | M | Landing page is a centred, Google-style search field with the corpus size beneath it and nothing else competing for attention. | Visual review against the wireframe in `docs/03-architecture.md` §7. | — |
| FR-WEB-02 | M | Search-as-you-type: debounced incremental results, no full page reload, keyboard-first (`/` focuses, `↑`/`↓` navigate, `Enter` opens, `Esc` clears). | Manual + automated browser test of each key binding. | — |
| FR-WEB-03 | M | Note pages render markdown correctly: headings, tables, code blocks with syntax highlighting, LaTeX maths (the atomic notes contain `$$…$$`), Mermaid diagrams, and **working wikilinks as real anchors**. | `/wiki/scaled-dot-product-attention` renders the attention equation and clickable links. | F-01, F-03 |
| FR-WEB-04 | M | Every page shows: frontmatter metadata, tags, source provenance, outbound links, backlinks with rationales, and a local graph mini-map. | Page contains all six regions. | F-13 |
| FR-WEB-05 | M | Navigation: breadcrumbs, browse-by-type, browse-by-tag, recently updated, and the MOC hubs as the primary entry points. | Every page reachable within three clicks from the landing page. | — |
| FR-WEB-06 | S | Full-page search results view with filter chips, result counts, and pagination. | `/search?q=attention&type=zettel` works as a shareable URL. | — |
| FR-WEB-07 | M | Ask view: natural-language question, streamed grounded answer, inline citations that link to the cited notes. | Citations are clickable and land on the right note. | F-23 |
| FR-WEB-08 | S | "File this answer into the wiki" action turns a good answer into a new note with provenance recorded. | Action creates a note whose frontmatter records the question and cited sources. | — |
| FR-WEB-09 | S | Health/admin page surfacing `wiki lint --json`: broken links, orphans, unindexed sources, schema violations, index freshness. | Page reflects the same findings as the CLI. | F-11 |
| FR-WEB-10 | S | Create and edit notes in the browser, with a markdown editor, live preview, wikilink autocomplete, and a commit message. | Edit → save → change appears in git history. | — |
| FR-WEB-11 | S | Trigger ingestion from the browser with progress feedback for long-running jobs. | Submitting a URL shows queued → running → done, and the new source appears. | F-19 |
| FR-WEB-12 | M | Responsive and usable on mobile: search, read, and follow links all work at 375px width. | Manual test at 375/768/1440px. | — |
| FR-WEB-13 | S | Dark mode, respecting `prefers-color-scheme` with a manual override. | Toggle persists across reloads. | — |
| FR-WEB-14 | M | Rendered markdown is sanitised: no script execution from note content. | Test: a note containing `<script>` and `<img onerror=…>` renders inert. | F-24 |
| FR-WEB-15 | M | Note lookup by slug is path-traversal safe. | Test: `/wiki/../../etc/passwd` and encoded variants return 404, never file contents. | — |
| FR-WEB-16 | C | Command palette (`Cmd/Ctrl+K`) for jump-to-note, recent, and actions. | Palette opens and navigates. | — |
| FR-WEB-17 | C | Read-only public share links for individual notes. | A share URL renders one note without a session. | — |

---

## H. Authentication and authorisation (`FR-AUTH`)

| ID | Pri | Requirement | Acceptance criterion | Traces |
| --- | --- | --- | --- | --- |
| FR-AUTH-01 | M | The deployed web app is private by default: every route except `/healthz`, `/login`, and static assets requires an authenticated session. | Test: unauthenticated request to `/`, `/wiki/*`, `/api/*` returns 401/redirect. | — |
| FR-AUTH-02 | M | Single-owner login with a username and a password verified against an Argon2id (or bcrypt) hash supplied via environment variable. No plaintext password anywhere in the repo, image, or logs. | Repo grep finds no password; image inspection finds only the hash. | — |
| FR-AUTH-03 | M | Sessions are signed, `HttpOnly`, `Secure`, `SameSite=Lax` cookies with a configurable idle and absolute expiry, and a working logout that invalidates server-side. | Cookie flags asserted in tests; logout then reusing the cookie fails. | — |
| FR-AUTH-04 | M | Login is rate-limited with exponential backoff and temporary lockout; failures are logged without revealing whether the username exists. | Test: 10 rapid failures trigger lockout; error text is identical for bad user and bad password. | — |
| FR-AUTH-05 | M | CSRF protection on every state-changing request. | Test: POST without a valid token is rejected. | — |
| FR-AUTH-06 | S | `wiki auth hash-password` generates the hash to paste into Railway variables, so you never invent your own hashing. | Command outputs a valid Argon2id hash. | — |
| FR-AUTH-07 | C | Optional OAuth (GitHub) sign-in with an allowlist of permitted accounts. | Non-allowlisted account is refused. | — |
| FR-AUTH-08 | C | Multi-user with roles (`owner`, `editor`, `reader`) once more than one person needs access. | Reader cannot POST edits. | — |
| FR-AUTH-09 | S | CLI authentication for talking to a remote deployment: a scoped API token in `~/.config/wiki/credentials`, never in the repo. | `wiki --remote https://… search "x"` works with a token, fails without. | — |
| FR-AUTH-10 | W | Public sign-up, email verification, password reset flows. Out of scope: this is a personal wiki with one owner. | — | — |

---

## I. LLM and agent operations (`FR-LLM`)

| ID | Pri | Requirement | Acceptance criterion | Traces |
| --- | --- | --- | --- | --- |
| FR-LLM-01 | M | Model configuration is data, not code: primary and fallback models come from config/env, with no hardcoded list in the source. | Changing `OPENROUTER_MODEL` alters behaviour with no code edit; `grep` finds no model list in the source. | F-20, F-21 |
| FR-LLM-02 | M | Configured model slugs are validated against the live OpenRouter catalogue by `wiki doctor`, which reports unknown slugs. | `wiki doctor` flags a bogus slug. | F-20 |
| FR-LLM-03 | M | One documented default, referenced by both code and `.env.example`. | Code default and `.env.example` are asserted equal by a test. | F-21 |
| FR-LLM-04 | M | Retries with exponential backoff and jitter, `Retry-After` honoured on 429, per-request and total timeouts, and a fail-fast cap so a query cannot hang for minutes. | Test with a mocked 429 then 200 succeeds; test with all-failing models returns within the configured budget. | F-22 |
| FR-LLM-05 | S | Token usage and estimated cost are recorded per call and summarised by `wiki stats --llm`. | Report shows calls, tokens, and cost by model. | F-22 |
| FR-LLM-06 | M | RAG context respects an explicit token budget, assembled from ranked chunks with per-chunk provenance, never a blind character truncation. | Unit test: an oversized corpus produces a prompt within budget that still includes the top-ranked chunk. | F-23 |
| FR-LLM-07 | M | Answers cite the notes they used, and citations are verified to resolve to real pages before being shown. | Test: an answer citing a non-existent note is flagged, not rendered as a link. | F-01 |
| FR-LLM-08 | M | Retrieved source text is delimited and framed as untrusted data; the system prompt states that instructions inside sources must not be followed. | Test: a fixture source containing "ignore previous instructions" does not change the output format. | F-24 |
| FR-LLM-09 | S | AI-authored pages are marked (`generated_by`, `status: draft`) so human-reviewed and machine-drafted content are distinguishable. | Generated literature notes carry both fields. | F-24 |
| FR-LLM-10 | S | LLM calls are mockable, and no test requires a live API key or network. | Full test suite passes with no `OPENROUTER_API_KEY` set. | F-25 |
| FR-LLM-11 | S | Every LLM operation degrades gracefully without a key: the command explains what is unavailable and exits 3, while all non-LLM features keep working. | Test: with no key, `wiki ask` exits 3 with a helpful message; `wiki search` exits 0. | — |

---

## J. Operations, CI/CD, and deployment (`FR-OPS`)

| ID | Pri | Requirement | Acceptance criterion | Traces |
| --- | --- | --- | --- | --- |
| FR-OPS-01 | M | One-command local setup and one-command local run, documented in the README. | A fresh clone reaches a working local app with two commands. | F-35 |
| FR-OPS-02 | M | CI on every push and PR: lint, format check, type check, tests with coverage, and `wiki lint --strict` over the actual wiki content. | A PR introducing a backticked wikilink fails CI. | F-10, F-25 |
| FR-OPS-03 | M | Deterministic builds: pinned dependencies via a lockfile, and a container image that builds identically from a clean checkout. | Two consecutive builds produce the same dependency set. | F-28 |
| FR-OPS-04 | M | Containerised app that respects the platform-injected `PORT`, runs as a non-root user, and starts without a shell script. | `docker run -e PORT=9000` serves on 9000. | — |
| FR-OPS-05 | M | Automated deploy to Railway on merge to `main`, with a health check gate and automatic rollback on failure. | A deliberately broken deploy does not replace the healthy release. | — |
| FR-OPS-06 | M | `/healthz` (liveness) and `/readyz` (readiness: index present, wiki readable) endpoints, unauthenticated and cheap. | Both return JSON quickly with no auth. | — |
| FR-OPS-07 | M | All secrets come from environment variables; none are committed, printed, or logged. Secret-scanning runs in CI. | CI secret scan passes; logs of a failed LLM call contain no key material. | — |
| FR-OPS-08 | S | Structured JSON logs with levels and a request ID, plus a smoke test that runs against the deployed URL after each release. | Post-deploy job asserts login page, search API, and one note render. | F-33 |
| FR-OPS-09 | S | Content is backed up: git remains the source of truth, and any container-side writes are committed back to git rather than living only on a volume. | Test: an edit made in the deployed app appears as a git commit. | — |
| FR-OPS-10 | S | Scheduled nightly job runs `wiki lint` and `wiki ai-lint` and opens an issue or PR with findings and suggested next sources. | Nightly run produces a report artifact. | F-08 |
| FR-OPS-11 | S | Preview environments for pull requests so UI changes are reviewable before merge. | Opening a PR yields a URL. | — |
| FR-OPS-12 | M | README documents architecture, setup, the full command surface, deployment, and the schema; a LICENSE file exists. | Both present and accurate. | F-35 |
| FR-OPS-13 | S | `AGENTS.md` is kept in sync with the real command surface as part of the same PR that changes it. | CI check compares documented commands against the CLI's registered commands. | F-27 |

---

## K. Explicitly out of scope for v1 (`W`)

Recorded so these do not quietly expand the build:

- Real-time multi-user collaborative editing (CRDTs, presence).
- Mobile native apps.
- Public sign-up and self-service account management (FR-AUTH-10).
- Fine-tuning or self-hosting models; OpenRouter remains the inference boundary.
- Automatic acceptance of AI-proposed wiki edits without human review — deliberate, per the
  Karpathy pattern's insistence that you stay the curator.
- Migrating content out of markdown into a database as the master copy.

---

## L. Traceability check

Every S1 and S2 finding maps to at least one `M` requirement:

| Finding | Covered by |
| --- | --- |
| F-01, F-02 (backticked links) | FR-CON-08, FR-LINT-06, FR-LINT-07, FR-WEB-03 |
| F-03 (mermaid links) | FR-CON-10, FR-GRAPH-01 |
| F-04 (orphans) | FR-LINT-06, FR-GRAPH-02, FR-GRAPH-07 |
| F-05, F-09 (link ambiguity) | FR-CON-07, FR-GRAPH-03 |
| F-06 (UID filenames) | FR-CON-01, FR-CON-02, FR-CON-03 |
| F-07, F-08 (slug bugs) | FR-CON-05, FR-CON-06 |
| F-10, F-11 (lint cannot gate) | FR-LINT-01, FR-LINT-02, FR-LINT-03, FR-OPS-02 |
| F-12 (frontmatter) | FR-CON-04, FR-CON-11, FR-LINT-06 |
| F-13 (rationales) | FR-CON-09, FR-GRAPH-01 |
| F-14, F-31 (quadratic) | FR-LINT-05, FR-SRCH-02 |
| F-15, F-16 (ingest) | FR-ING-02, FR-ING-03, FR-ING-04 |
| F-17, F-18 (parsing, idempotency) | FR-ING-05, FR-ING-07 |
| F-19 (SSRF) | FR-ING-08 |
| F-20…F-22 (LLM config, retries) | FR-LLM-01…FR-LLM-04 |
| F-23 (context truncation) | FR-LLM-06, FR-SRCH-07 |
| F-24 (prompt injection) | FR-LLM-08, FR-WEB-14 |
| F-25…F-37 (hygiene) | FR-CLI-01…FR-CLI-05, FR-SRCH-01, FR-OPS-02, FR-OPS-12 |

Next: `docs/02-non-functional-requirements.md`.
