# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project scope

`ai-wiki` is a private, single-user knowledge base: FastAPI + React + PostgreSQL, deployed as one
container on Railway. It is an independent repo (`github.com/gopalshivapuja/ai-wiki`) and is **not**
part of the file-based vault at `/Users/gopal/Wiki` — do not apply that vault's conventions here.

Run commands live in [README.md](./README.md). The API documents itself at `/docs`; do not maintain a
hand-written endpoint list anywhere, it will drift.

## The data model

**One table, `documents`, holds everything.** A row is either a note (`doc_class="note"` — anything
you or the AI wrote) or a captured source (`doc_class="source"` — web page, PDF, transcript, paste).
`subtype` is the vocabulary within each: `zettel|concept|entity|moc|synthesis|literature|page|index`
for notes, `web|pdf|youtube|audio|arxiv|note` for sources.

This was two tables with two slug namespaces. That split leaked a `kind` discriminator into ~35
places, required two search implementations and two REST resources, and — the reason it had to go —
made it structurally impossible for a wikilink to resolve to a source. Consequences of the current
design, all load-bearing:

- **One slug namespace.** Ingested sources are prefixed `src-`. Do not reintroduce a second
  namespace; `summary_slug()`, `protect_curated`, `url_hash` disambiguation and a dict-shaped 404 all
  existed only to manage the old collision.
- **`derived_from_id`** links a literature note to its source. A real foreign key, not a naming
  convention. `upsert_literature_note()` uses it to update the right note instead of guessing.
- **`immutable`** marks captured material. `update_note()` raises `Immutable` → HTTP 409.
- Sources appear in search, the graph, backlinks and red-link detection exactly like notes.

`Revision` snapshots a document before every content change (`_snapshot()` in `content.py`). Nothing
else protects against a bad edit or an AI rewrite.

## Durability — treat this as a hard requirement

`GET /api/export` streams a zip of markdown-with-frontmatter; `POST /api/jobs/import` reads the same
format. That single format is backup, restore, Obsidian interop **and first-boot seeding** —
`seed_if_empty()` is an ordinary caller of `import_markdown()`, not separate boot-time magic.

If you change how documents are stored, change `to_markdown()` and `import_markdown()` together, and
keep `test_export_import_round_trip` passing. A knowledge base whose only copy is one hobby-tier
database is not something to ship.

## Architecture

- `packages/wiki_api/` — `app.py` (lifespan, SPA), `database.py` (ORM models), `routes.py`,
  `routes_jobs.py`, `auth.py`, `startup.py`, `schema_ddl.py`, `services/`, `jobs/`.
- `packages/wiki_core/` — dependency-light helpers: `utils.py` (slugify, wikilink/frontmatter
  parsing), `llm.py` (OpenRouter). No DB imports; keep it that way.
- `apps/web/` — React 18 + Vite. `hooks.ts` holds `useAsync` / `usePoll` / `useSearch`; use them
  rather than hand-rolling another fetch-plus-loading-plus-error triple (none of the hand-rolled ones
  guarded against out-of-order responses).
- `seed/` — starter content in the export format. Not read after first boot.

### Boot sequence (`app.py::lifespan`) — the order is load-bearing

`check_secrets()` → `wait_for_database()` → `init_db()` (`create_all`) → `apply_schema_ddl()` →
`seed_if_empty()` → `JobRunner.start()`.

`wait_for_database` retries with backoff because the app and database containers start together.
`check_secrets` refuses to boot a hosted deployment still using the built-in `JWT_SECRET`.

### Schema changes

**No Alembic.** New tables come from `create_all()`; anything SQLAlchemy cannot express goes in
`schema_ddl.py::PG_STATEMENTS`, which must stay additive and idempotent. It currently holds the
generated `search_tsv` column and the GIN indexes. Failures there are fatal by design — a boot that
warns and then serves broken search is worse than one that stops.

Adopt Alembic when you need a rename/drop/type change, a backfill a generated column cannot express,
more than one steady-state replica, or tables large enough that `ADD COLUMN`'s lock outlasts the
healthcheck.

### Search

PostgreSQL full-text only, in `services/search.py`. There is deliberately no second implementation:
the old BM25 fallback ranked differently and silently masked failures in the real one.

Two non-obvious constraints: `to_tsvector` must take the explicit `'english'` argument (the one-arg
form is not `IMMUTABLE` and Postgres rejects it in a generated column), and input is capped by
`left(body, 400000)` because a tsvector over 1MB aborts the `INSERT` — that breaks *ingest*, not just
search. `ts_headline` runs only over rows that survived `LIMIT`; it cannot use the index.

### Links

Never resolve wikilinks in a loop with per-link queries. Build one `LinkIndex` with
`build_link_index(db)` and call `.resolve()`. Resolution order: exact slug → uid → `slugify(target)` →
`src-`-prefixed → case-folded title.

### Background jobs

`jobs/runner.py` is a DB-backed queue drained by **one** asyncio worker. The `jobs` table is the
source of truth so a redeploy loses nothing.

- Handlers in `jobs/handlers.py` take `(params, ctx)` and **own their sessions** — open
  `session_scope()` only around database work. Passing a session in meant a transcription held a
  pooled connection for ten minutes and lost the result if it dropped.
- Handlers are plain sync functions run whole in a worker thread; a sync `Session` must stay on one
  thread.
- `reap_orphans()` assumes exactly one runner process and filters on `started_at` so a booting
  container cannot kill the outgoing one's work. **Do not run `--workers > 1`** without giving jobs an
  owner id; set `JOB_RUNNER_ENABLED=0` for any extra web-only process.
- Cancellation is cooperative: handlers stop at the next `ctx.should_stop()`.
- Upload bytes travel in `Job.payload`, not on ephemeral disk, so retry works across a redeploy.

### Serving and security

One process. `app.py` registers a `/{full_path:path}` SPA catch-all, so **any new API route must live
under `/api`** or the catch-all swallows it. The catch-all resolves paths and verifies they stay
inside `STATIC_DIR` — do not remove that check.

Every outbound fetch of a user-supplied URL goes through `services/fetch.py`: http(s) only, private
and link-local addresses blocked, response size capped. Never call `urllib.request.urlopen` on user
input directly.

**The wiki is private.** Every route requires a token. There is no public/private split by document
class — literature notes reproduce the substance of the sources they summarise, so that split
protected nothing.

Auth is one admin from the environment. `_ensure_admin()` re-syncs the password from
`ADMIN_PASSWORD` on every boot, which is why there is no signup and no in-app password change — they
would be reverted. Changing `ADMIN_EMAIL` creates a *second* admin and leaves the first usable.

## Conventions

- Ingest and mutation logic belongs in `services/`; `routes.py` stays thin — Pydantic bodies plus
  `_fail()` for status mapping (`Immutable`→409, `ValueError`/`FetchError`→400, `LLMNotConfigured`→503).
- Every ingest path goes through `content.store_source()`, so none can forget to log or to mark the
  result immutable.
- Creates, edits, deletes, ingests and imports call `log_action()`; it backs `/api/log`.
- Use `utcnow()` from `database.py`, never `datetime.utcnow()`.
- Do not hardcode OpenRouter model ids anywhere. `llm.py` validates against the live catalogue and
  falls back to a discovered free model; `GET /api/llm/models` reports what it chose.
- Frontend errors go through `extractDetail()` in `api.ts` — FastAPI's 422 `detail` is a *list*, and
  `res.statusText` is empty over HTTP/2.

## Tests

One file, `tests/test_wiki.py`, against real PostgreSQL. They are chosen by risk, not coverage: the
seed actually imports, sources are link targets, the export round-trips, `reap_orphans` spares fresh
jobs, the SPA is served, SSRF and traversal are blocked, and the crawler fetches each page once.

`test_every_env_var_is_documented` fails the build when a new `os.environ.get` is missing from
`.env.example`. Keep it that way — the docs drifted badly before it existed.
