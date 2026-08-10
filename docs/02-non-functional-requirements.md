# 02 — Non-Functional Requirements

**Status:** for review · **Depends on:** `docs/01-functional-requirements.md`

Functional requirements say *what* the system does. These say *how well* — and they are where
personal projects usually die, because "it works on my laptop with 20 notes" is not the same system
as "it works on Railway with 2,000 notes and someone trying the login form 400 times".

Each NFR has a measurable target and a verification method. Anything unmeasurable is not an NFR, it
is a wish.

**Scale assumptions for v1** (state them, then design to them): 1 owner, up to 5 readers, 2,000 wiki
pages, 500 raw sources, 50 MB of markdown, under 100 searches/day, under 50 LLM calls/day. Anything
an order of magnitude beyond this is a v2 conversation, not a v1 constraint.

---

## 1. Performance (`NFR-PERF`)

| ID | Requirement | Target | Verification |
| --- | --- | --- | --- |
| NFR-PERF-01 | Search-as-you-type feels instant | p95 keystroke→results ≤ 150 ms server time at 2,000 notes; ≤ 300 ms end-to-end on a warm connection | Benchmark against a generated 2,000-note corpus, asserted in CI |
| NFR-PERF-02 | Note pages render fast | p95 ≤ 200 ms server render; first contentful paint ≤ 1.0 s on a cold cache | Lighthouse run in CI plus server timing histogram |
| NFR-PERF-03 | Graph views stay interactive | Local graph (depth 2, ≤ 150 nodes) ≤ 500 ms to interactive; global graph at 2,000 nodes remains pannable at ≥ 30 fps or degrades to a clustered view | Manual profile plus a node-count cap with automatic clustering |
| NFR-PERF-04 | Lint is linear, not quadratic | 2,000 notes lint in ≤ 5 s; complexity is O(pages + links), not O(pages²) | Timed benchmark test at 100/1,000/2,000 notes asserting sub-quadratic growth |
| NFR-PERF-05 | Full reindex is fast enough to be routine | ≤ 30 s for 2,000 notes; incremental single-note update ≤ 200 ms | Benchmark test |
| NFR-PERF-06 | Cold start is short enough for scale-to-zero | Container ready to serve ≤ 5 s from start | Post-deploy timing in the smoke-test job |
| NFR-PERF-07 | LLM answers stream | First token ≤ 3 s p95; answers stream so nothing looks frozen | Manual timing plus a streaming integration test |
| NFR-PERF-08 | Ingestion of a single source completes promptly | ≤ 30 s excluding LLM summarisation; long jobs run in the background with progress | Integration test with fixtures |
| NFR-PERF-09 | Page payload stays small | ≤ 200 KB gzipped HTML+CSS+JS for a note page, excluding optional graph and Mermaid bundles which load lazily | CI bundle-size budget check |

**Design consequences.** These numbers rule out re-reading and re-tokenising the corpus per request
(the current design, F-14/F-31) and rule in a persistent inverted index. They also mean the graph
must be served pre-computed, and heavy client libraries (Mermaid, the graph renderer, KaTeX) must be
code-split and loaded only on pages that need them.

---

## 2. Security (`NFR-SEC`)

| ID | Requirement | Target | Verification |
| --- | --- | --- | --- |
| NFR-SEC-01 | Private by default | No route except `/healthz`, `/readyz`, `/login`, and static assets serves content without a valid session | Automated route-coverage test enumerating registered routes and asserting each is protected or explicitly allowlisted |
| NFR-SEC-02 | Credentials at rest | Argon2id with tuned parameters (or bcrypt cost ≥ 12); no plaintext or reversible secret in repo, image, env dump, or logs | Unit test on the hasher; secret scanning (gitleaks) in CI; manual image inspection |
| NFR-SEC-03 | Session integrity | Signed cookies with a ≥ 32-byte secret; `HttpOnly`, `Secure`, `SameSite=Lax`; idle expiry 7 days, absolute 30 days; server-side invalidation on logout | Asserted in tests |
| NFR-SEC-04 | Brute-force resistance | ≥ 5 failures triggers exponential backoff, ≥ 10 triggers a temporary lockout; identical error text regardless of which credential was wrong | Integration test |
| NFR-SEC-05 | Transport security | HTTPS only; HSTS; HTTP redirected. Railway terminates TLS, the app must not assume plaintext is fine | Header assertion in the post-deploy smoke test |
| NFR-SEC-06 | Content rendering is inert | Note markdown is sanitised (allowlist), raw HTML restricted, and a CSP without `unsafe-inline` for scripts is enforced | XSS fixture test with `<script>`, `<img onerror>`, `javascript:` links, and a malicious Mermaid payload |
| NFR-SEC-07 | Server-side request forgery blocked | Ingest refuses non-HTTP(S) schemes, loopback, private (RFC1918), link-local (169.254/16), and unique-local ranges; caps redirects at 3, response size at 10 MB, timeout at 15 s; re-validates the IP after each redirect | Unit tests per blocked range, including a DNS-rebinding-style redirect case |
| NFR-SEC-08 | Prompt injection contained | Untrusted source text is delimited and framed as data; no tool execution is driven by source content; AI-authored pages are marked and human-reviewed before promotion out of draft | Injection fixture corpus in the test suite |
| NFR-SEC-09 | Path traversal blocked | Slug→path resolution normalises and asserts containment within the wiki root; encoded, doubled, and symlink variants rejected | Parametrised test with `../`, `%2e%2e%2f`, `....//`, and a symlink escape |
| NFR-SEC-10 | Dependency hygiene | No known high/critical CVEs in shipped dependencies; automated update PRs; lockfile committed | `pip-audit` in CI; Dependabot enabled |
| NFR-SEC-11 | Least privilege | Container runs as non-root with a read-only root filesystem except explicit writable paths; any GitHub token is scoped to a single repo with minimal permissions | Image inspection; documented token scopes |
| NFR-SEC-12 | Abuse limits | Global and per-session rate limits on search, ask, and ingest, protecting both the app and your LLM budget | Load test asserting 429s past the threshold |
| NFR-SEC-13 | Auditability | Authentication events, content mutations, and ingests are logged with actor, timestamp, and target — without logging secrets or full note bodies | Log inspection test |

---

## 3. Reliability and availability (`NFR-REL`)

| ID | Requirement | Target | Verification |
| --- | --- | --- | --- |
| NFR-REL-01 | Availability | 99% monthly for a personal deployment; no on-call, no SLA theatre | Uptime check on `/healthz` |
| NFR-REL-02 | Failed deploys never replace a healthy release | Health check gates promotion; failure triggers rollback to the previous image | Deliberate broken-deploy drill during Phase 7 |
| NFR-REL-03 | Third-party failure is contained | OpenRouter, arXiv, or YouTube being down degrades only the dependent feature; search and reading keep working | Fault-injection tests with the provider mocked as failing |
| NFR-REL-04 | No data loss from crashes | Content is markdown in git; writes are atomic (write temp, fsync, rename) and committed; a crash mid-write cannot corrupt a note | Kill-during-write test |
| NFR-REL-05 | The derived index is disposable | Deleting the search index and restarting rebuilds it automatically without human intervention | Delete-and-restart test |
| NFR-REL-06 | Recovery | Full restore from the git remote alone, documented and rehearsed | Restore drill: clone into a fresh container and serve |
| NFR-REL-07 | Idempotent operations | Re-running ingest, reindex, or migrate produces the same result and never duplicates content | Run-twice tests |
| NFR-REL-08 | Backups | Git remote is the backup; a scheduled export artifact provides a second copy independent of the platform | Nightly export job produces a downloadable archive |

---

## 4. Maintainability and code quality (`NFR-MNT`)

| ID | Requirement | Target | Verification |
| --- | --- | --- | --- |
| NFR-MNT-01 | Test coverage | ≥ 80% line coverage on the core library (parsing, linking, graph, search, slug); ≥ 60% overall; every fixed bug in this audit gets a regression test | Coverage gate in CI |
| NFR-MNT-02 | Module boundaries | Core library has no web or CLI imports; CLI and web are thin adapters over it; no module exceeds ~400 lines | Import-linter rule in CI plus review |
| NFR-MNT-03 | Static analysis clean | Ruff (lint + format) and mypy in strict mode on the core package, zero errors | CI gate |
| NFR-MNT-04 | Typed public API | All public functions annotated; no bare `except Exception` that swallows and continues (the F-15 pattern) | Ruff rules `BLE001`/`E722` enforced |
| NFR-MNT-05 | One implementation per concept | Retrieval scoring, frontmatter parsing, slug generation, and link resolution each exist exactly once | Review checklist plus a duplication scan |
| NFR-MNT-06 | Documented decisions | Each significant choice recorded as a short ADR in `docs/adr/`, including the ones rejected and why | ADR present for every item in `docs/06-open-decisions.md` |
| NFR-MNT-07 | Reproducible dev environment | Fresh clone → working tests in one command on Linux and macOS | Documented and CI-verified on both runners |
| NFR-MNT-08 | Conventional commits and readable history | Commits are scoped and imperative; one logical change per commit | Review |
| NFR-MNT-09 | Schema and docs stay honest | CI fails when the CLI's registered commands diverge from `AGENTS.md` and the README | Automated comparison test |

---

## 5. Usability and accessibility (`NFR-UX`)

| ID | Requirement | Target | Verification |
| --- | --- | --- | --- |
| NFR-UX-01 | Search is reachable instantly | `/` focuses search from any page; the landing page autofocuses it | Keyboard test |
| NFR-UX-02 | Keyboard-only operation | Search, navigate results, open notes, follow links, and toggle the graph without a mouse | Manual keyboard walkthrough |
| NFR-UX-03 | Accessibility | WCAG 2.1 AA: contrast ≥ 4.5:1, visible focus rings, semantic landmarks, labelled controls, `aria-live` on async results | axe-core scan in CI with zero critical violations |
| NFR-UX-04 | No dead ends | Empty results suggest alternatives; broken links offer creation; errors say what to do next | Review of each empty/error state |
| NFR-UX-05 | Progressive enhancement | Search and reading work with JavaScript disabled (form submit to `/search`); JS upgrades it to instant results | Test with scripting disabled |
| NFR-UX-06 | Honest latency feedback | Anything over 300 ms shows a skeleton or spinner; streamed answers render incrementally | Manual review |
| NFR-UX-07 | Mobile usable | Fully functional at 375px; tap targets ≥ 44px | Manual test at three widths |
| NFR-UX-08 | Readable typography | 60–80 character measure, sane line height, and maths that does not overflow on mobile | Visual review |
| NFR-UX-09 | The CLI is self-teaching | `wiki --help` alone is enough to discover the workflow; errors name the flag that would fix them | Fresh-user walkthrough |

---

## 6. Portability and deployability (`NFR-POR`)

| ID | Requirement | Target | Verification |
| --- | --- | --- | --- |
| NFR-POR-01 | Platform independence | No Railway-specific API in application code; the platform provides `PORT`, env vars, and a volume, nothing more | The same image runs locally via Docker and on any container host |
| NFR-POR-02 | Local dev parity | `wiki serve` gives the same behaviour as production minus TLS, with SQLite and local files | Documented and tested |
| NFR-POR-03 | Config via environment | Twelve-factor: all config from env with documented defaults and startup validation that fails fast on missing required values | Startup test with a missing required var exits non-zero with a clear message |
| NFR-POR-04 | Obsidian compatibility preserved | The wiki stays a plain Obsidian vault: wikilinks, frontmatter, Dataview queries, and graph view all keep working | Manual vault open after migration |
| NFR-POR-05 | Data escape hatch | Content is exportable as plain markdown at any time with no proprietary format | `wiki export` produces a usable vault |
| NFR-POR-06 | Python version support | 3.11 and 3.12 supported and tested | CI matrix |

---

## 7. Cost (`NFR-COST`)

| ID | Requirement | Target | Verification |
| --- | --- | --- | --- |
| NFR-COST-01 | Hosting stays cheap | ≤ $5/month on Railway for the assumed scale; a single service, no managed database in v1 | Railway usage dashboard after a month |
| NFR-COST-02 | Idle cost near zero | Scale-to-zero or a minimal always-on footprint; a wiki nobody is reading should not bill for compute | Configuration review |
| NFR-COST-03 | LLM spend is visible and bounded | Per-call token accounting, a configurable monthly cap, and free-tier models as the default | `wiki stats --llm` report plus a cap test |
| NFR-COST-04 | CI stays within free minutes | Full pipeline ≤ 5 minutes; caching for dependencies and Docker layers | Workflow timing |
| NFR-COST-05 | No surprise egress or storage growth | Ingested assets bounded per source; index size monitored | `wiki doctor` reports repo and index size |

---

## 8. Observability (`NFR-OBS`)

| ID | Requirement | Target | Verification |
| --- | --- | --- | --- |
| NFR-OBS-01 | Structured logs | JSON logs with level, timestamp, request ID, route, latency, and outcome; no secrets, no full note bodies | Log inspection test |
| NFR-OBS-02 | Health endpoints | `/healthz` (process alive) and `/readyz` (wiki readable, index present and fresh) return within 100 ms without auth | Smoke test |
| NFR-OBS-03 | Error visibility | Unhandled exceptions produce a request ID shown to the user and logged with a traceback; optional Sentry integration behind a DSN env var | Fault-injection test |
| NFR-OBS-04 | Wiki health is a first-class metric | Counts of broken links, orphans, unindexed sources, schema violations, and index age are exposed via API and the admin page | Admin page reflects `wiki lint --json` |
| NFR-OBS-05 | Deploy traceability | The running app reports its git SHA and build time at `/healthz` | Assertion in the post-deploy smoke test |

---

## 9. Data governance (`NFR-DAT`)

| ID | Requirement | Target | Verification |
| --- | --- | --- | --- |
| NFR-DAT-01 | Git is the single source of truth | No derived store is authoritative; indexes and caches are rebuildable from markdown alone | Delete-all-derived-state test |
| NFR-DAT-02 | `sources/` immutability | No code path modifies or deletes an existing file under `sources/` | Hash-comparison test across the full command surface |
| NFR-DAT-03 | Provenance | Every wiki claim traces to a source via frontmatter `sources`, and every source records its retrieval URL, timestamp, and content hash | Lint rule warns on a literature note with no `sources` |
| NFR-DAT-04 | Attribution and licensing respected | Ingested content stores the canonical URL and is treated as quotation for personal research; the deployment stays private by default | Documented in README |
| NFR-DAT-05 | Personal data | No third-party personal data is collected; no analytics that phone home; query logs stay local | Code review |
| NFR-DAT-06 | Deletion | Removing a note also removes it from indexes and reports resulting broken links rather than leaving dangling state | Delete test |

---

## 10. How the NFRs constrain the architecture

Cross-cutting consequences, stated explicitly so the architecture document can be checked against them:

1. **A persistent inverted index is mandatory** (NFR-PERF-01/04/05). Re-reading the corpus per request
   cannot meet a 150 ms p95 at 2,000 notes.
2. **The derived index must be disposable** (NFR-REL-05, NFR-DAT-01), which means it can live on
   ephemeral container storage and be rebuilt at boot — that in turn removes the need for a volume in
   v1 and helps NFR-COST-01.
3. **No managed database in v1** (NFR-COST-01). Single-owner auth needs a password hash and a signing
   secret, both of which are environment variables. Adding Postgres would be paying for a table with
   one row in it.
4. **Container writes must reach git** (NFR-REL-04, NFR-DAT-01). Ephemeral filesystems mean web edits
   have to be committed through the git remote, not merely saved to disk.
5. **Heavy client libraries load lazily** (NFR-PERF-09), so Mermaid, the graph renderer, and maths
   rendering are per-page opt-ins.
6. **Server-rendered HTML with progressive enhancement** satisfies NFR-UX-05 and NFR-PERF-02 more
   cheaply than a client-side SPA, and keeps the deploy pipeline free of a heavy front-end build.
7. **Ingest must run outside the request cycle** (NFR-PERF-08) or the platform's request timeout will
   kill long fetches mid-flight.
8. **Fail-fast config validation at boot** (NFR-POR-03) prevents the classic Railway experience of a
   green deploy that 500s on every request because one variable was never set.

Next: `docs/03-architecture.md`.
