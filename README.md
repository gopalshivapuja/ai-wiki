# LLM Wiki

A personal knowledge base: capture sources, turn them into linked atomic notes, and ask AI
questions answered only from what you have collected. Everything lives in **PostgreSQL** —
no files to sync, no CLI.

## What it does

**Search** — a Google-style box on the home page and in the nav. On PostgreSQL it uses real
full-text search (ranked, with highlighted snippets, phrase queries and `-exclusions`).

**Notes** — create, edit and delete markdown notes in the browser, with live preview and
`[[` autocomplete for linking. Backlinks, outgoing links, red links for notes that do not
exist yet, tags, and an interactive knowledge graph.

**Add a source** — web pages, whole documentation sections (bounded crawl), YouTube
captions, audio transcription for videos without captions, arXiv papers, PDF uploads, and
pasted text. Long imports run as background jobs with progress and cancel.

**Ask AI** — retrieval over your own notes, with citations that link back to the source, and
a one-click "save this answer as a note".

Sources are immutable; notes are yours to edit. An AI summary is written to its own page and
can never overwrite something you wrote.

## Run it locally

```bash
cp .env.example .env          # optional: add OPENROUTER_API_KEY for the AI features
docker compose up --build
```

Open **http://localhost:8000** and log in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`
(`admin@example.com` / `changeme` by default — change these before deploying).

### Without Docker

```bash
pip install -e ".[dev]"
cd apps/web && npm install && npm run build && cd ../..

# Backend (SQLite is fine for development)
DATABASE_URL=sqlite:///./wiki.db JWT_SECRET=dev uvicorn wiki_api.app:app --reload

# Frontend with hot reload, in another terminal
cd apps/web && npm run dev     # http://localhost:5173, proxies the API to :8000
```

## Tests

```bash
DATABASE_URL=sqlite:////tmp/wiki_test.db JWT_SECRET=test pytest tests/ -v
ruff check .

# Against PostgreSQL, which additionally covers full-text search and the job queue
DATABASE_URL=postgresql://user@localhost:5432/wiki_test JWT_SECRET=test pytest tests/ -v
```

## Deploy

See [DEPLOY.md](./DEPLOY.md) for Railway, including **what it costs** (roughly $6–14/month
all-in).

## Tech stack

- **Frontend** — React + Vite, served by FastAPI
- **Backend** — FastAPI + SQLAlchemy, with an in-process background job queue
- **Database** — PostgreSQL (SQLite supported for development and tests)
- **AI** — OpenRouter for text, OpenAI Whisper or Deepgram for transcription

Conventions and the note schema are in [AGENTS.md](./AGENTS.md); architecture notes for
contributors are in [CLAUDE.md](./CLAUDE.md).
