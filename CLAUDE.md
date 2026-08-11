# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project scope

`ai-wiki` is a standalone web app (FastAPI + React + PostgreSQL) implementing an LLM Wiki /
Zettelkasten knowledge base. It is an independent repo (`github.com/gopalshivapuja/ai-wiki`) and is
**not** part of the file-based personal vault at `/Users/gopal/Wiki` — do not apply that vault's
`CLAUDE.md` conventions here, and do not re-nest this repo inside it.

`AGENTS.md` defines the content schema (zettel taxonomy, frontmatter, wikilink conventions) and the
HTTP API surface. There is no CLI.

## Commands

The frontend must be built before the backend can serve the SPA.

```bash
# Full stack (Postgres + app on :8000)
cp .env.example .env
docker compose up --build

# Local backend against SQLite
pip install -e ".[dev]"
DATABASE_URL=sqlite:///./wiki.db JWT_SECRET=dev uvicorn wiki_api.app:app --reload

# Frontend dev server (proxies /api and /health to :8000)
cd apps/web && npm install && npm run dev     # :5173
cd apps/web && npm run build                  # backend serves apps/web/dist automatically

# Tests — run BOTH; they cover different code paths
DATABASE_URL=sqlite:////tmp/wiki_test.db JWT_SECRET=test pytest tests/ -v
DATABASE_URL=postgresql://user@localhost:5432/wiki_test JWT_SECRET=test pytest tests/ -v
DATABASE_URL=sqlite:////tmp/wiki_test.db JWT_SECRET=test pytest tests/test_wiki.py::test_search -v

ruff check . && ruff format packages tests
```

## Architecture

**PostgreSQL is the single source of truth.** The markdown under `wiki/` and `sources/` is seed data
only: `seed_if_empty()` imports it once, when the database is empty. Editing those files has no
effect on a seeded database, and content created in the app never writes back to disk.

`WIKI_SEED_DIR` must point at the directory containing `wiki/` and `sources/`. The Dockerfile sets it
to `/app`. Without it the seeder resolves relative to its own module path, which lands in
site-packages after a non-editable `pip install .` — that silently seeded nothing in production, and
editable installs hide it, so **the Docker smoke test in CI is what guards this**.

Layout:
- `packages/wiki_api/` — FastAPI app, routes, auth, models, `services/`, `jobs/`.
- `packages/wiki_core/` — dependency-light helpers: `utils.py` (slugify, wikilink and frontmatter
  parsing), `llm.py` (OpenRouter). No DB imports; keep it that way.
- `apps/web/` — React 18 + Vite SPA.

### Data model

Five tables (`database.py`): `Page`, `RawSource`, `User`, `ActivityLog`, `Job`.

`Page` and `RawSource` are **separate slug namespaces that can legitimately collide** — the same
material can be both a captured source and a curated note. Consequences to respect:
- Search returns a `kind` discriminator (`"page"` / `"source"`); the frontend routes to `/wiki/:slug`
  or `/source/:slug` accordingly. Do not drop it.
- AI summaries go to `summary_slug(source_slug)`, never the source's own slug.
- Automated writers pass `upsert_page(..., protect_curated=True)`, which refuses to overwrite a
  hand-written page of a different type.
- `upsert_source` never mutates an existing row and returns `(source, created)`. A different URL that
  slugifies identically gets a hash suffix.

### Schema changes

**No Alembic.** New tables come from `Base.metadata.create_all()`; new columns and indexes on
existing tables go in `schema_ddl.py::PG_STATEMENTS`, which runs additive, idempotent DDL at every
boot and no-ops on SQLite. Boot order in `lifespan` is load-bearing: `init_db()` → `apply_schema_ddl()`
→ `seed_if_empty()`.

Adopt Alembic when you need a column rename/type change/drop, a data backfill a generated column
cannot express, more than one replica (two containers would race the DDL), or the tables grow large
enough that `ADD COLUMN`'s brief `ACCESS EXCLUSIVE` lock outlasts the healthcheck.

### Search

`services/search.py` is a dispatcher: PostgreSQL FTS when the dialect is `postgresql`, the pure-Python
BM25 in `search_bm25.py` otherwise (and as a fallback if FTS raises, e.g. before the columns exist).
Both must return the identical dict shape — CI's SQLite run only exercises the fallback.

The Postgres path uses generated `search_tsv` columns and GIN indexes. Two non-obvious constraints:
`to_tsvector` must take the explicit `'english'` argument (the one-arg form is not `IMMUTABLE` and is
rejected in a generated column), and the input is capped by `left(body, 400000)` because a tsvector
over 1MB aborts the `INSERT` — that would break ingest, not just search.

### Links and graph

Never resolve wikilinks in a loop with `resolve_slug` — it re-queries per call. Build a `SlugIndex`
once with `build_slug_index(db)` and use `.resolve()`. Resolution order is slug → uid → `slugify(target)`.

### Background jobs

Long ingests cannot run in a request (the Railway proxy times out). `jobs/runner.py` is a DB-backed
queue drained by asyncio workers started in `lifespan`; the `jobs` table is the source of truth so a
redeploy cannot lose work. Handlers in `jobs/handlers.py` are **plain sync functions** run whole in a
worker thread via `anyio.to_thread.run_sync` with a dedicated `CapacityLimiter` — a sync SQLAlchemy
session must stay on one thread, and the separate limiter keeps jobs from starving request threads.

- Background code must use `session_scope()`, never the request-scoped `get_db` session.
- Cancellation is cooperative: handlers stop at the next `ctx.check_stop()`/`should_stop()` checkpoint.
- Jobs left `running` by a crash are marked failed at boot (`reap_orphans`), not retried automatically.

### Serving and security

One process. `app.py` registers a `/{full_path:path}` SPA catch-all, so **any new API route must live
under `/api`** or the catch-all swallows it. The catch-all resolves paths and verifies they stay
inside `STATIC_DIR`; do not remove that check.

All outbound fetches of user-supplied URLs go through `services/fetch.py`, which enforces an
http(s)-only scheme allowlist, blocks private/loopback/link-local addresses, and caps response size.
Never call `urllib.request.urlopen` on user input directly.

Auth split: reads are public; writes, ingest, LLM calls and raw source text require
`Depends(get_current_user)`. Anonymous search passes `include_sources=False` so it cannot leak source
material that `/api/sources` gates.

## Conventions

- Ingest and page-mutating logic belongs in `services/`; `routes.py` stays thin — Pydantic bodies plus
  status mapping. Map `ValueError`/`FetchError` to 4xx; do not let internal errors reach the client.
- Every mutation calls `log_action(db, action, summary)`, which backs `/api/log`.
- Use `utcnow()` from `database.py`, not the deprecated `datetime.utcnow()`.
- Do not hardcode OpenRouter model ids anywhere. `llm.py` validates against the live catalogue and
  falls back to a discovered free model; `GET /api/llm/models` reports the resolution.
