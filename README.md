# ai-wiki

A private knowledge base. Capture sources, turn them into linked atomic notes, and ask AI
questions answered only from what you have collected.

Everything lives in PostgreSQL, and everything can be exported back out as plain markdown.

## What it does

**Search** — a Google-style box on the home page and in the nav, backed by PostgreSQL
full-text search: ranked, with highlighted snippets, phrase queries and `-exclusions`.

**Notes** — create, edit and delete markdown notes in the browser, with live preview and
`[[` autocomplete. Backlinks, outgoing links, red links for notes you have referenced but
not written, tags, and revision history. Each note draws its own **Connections** map: the
notes one or two hops away, in both directions. There is deliberately no whole-wiki graph —
past a few dozen notes that is a hairball that answers no question.

**Add a source** — web pages, whole documentation sections (bounded crawl), YouTube
captions, speech-to-text for videos without captions, arXiv papers, PDF uploads, and pasted
text. Long imports run as background jobs with progress and cancel.

**Bulk ingest** — a `wiki` CLI for loading a channel or a documentation site in one command,
with resumable capture and local transcription for videos YouTube will not serve captions for.
See **[docs/INGEST.md](docs/INGEST.md)**.

**Ask AI** — retrieval over your own notes, with citations that link back, and one-click
"save this answer as a note".

**Backup** — download the whole wiki as a zip of markdown files, and import it again. Notes
and sources share one link namespace, so a source is a first-class link target, not a
footnote.

**Readable by an LLM** — `GET /api/llms.txt` describes the wiki in the llms.txt convention:
what it holds, its maps of content as entry points, and how to traverse it. For agents, an
MCP server exposes the same thing as tools (see below).

Sources are captured immutably; notes are yours to edit. An AI summary is written to its own
document and can never overwrite something you wrote.

## Run it

```bash
cp .env.example .env          # set JWT_SECRET; add OPENROUTER_API_KEY for the AI features
docker compose up --build
```

Open **http://localhost:8000** and log in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`.

### Without Docker

Needs PostgreSQL (`docker compose up db` will do).

```bash
pip install -e ".[dev]"
cd apps/web && npm install && npm run build && cd ../..

DATABASE_URL=postgresql://wiki:wiki@localhost:5432/wiki JWT_SECRET=dev \
  uvicorn wiki_api.app:app --reload

# Frontend with hot reload, in another terminal (proxies the API to :8000)
cd apps/web && npm run dev     # http://localhost:5173
```

## Tests

```bash
DATABASE_URL=postgresql://wiki:wiki@localhost:5432/wiki_test JWT_SECRET=test pytest tests/ -v
ruff check . && cd apps/web && npm run build
```

## Deploy

[DEPLOY.md](./DEPLOY.md) covers Railway, including what it costs (roughly $6–11/month).

## Tech stack

React + Vite served by FastAPI, SQLAlchemy on PostgreSQL, an in-process background job
queue, OpenRouter for text and OpenAI Whisper or Deepgram for transcription.

Architecture and conventions are in [CLAUDE.md](./CLAUDE.md). The API documents itself at
`/docs` while the app is running.

## Using the wiki from Claude

`packages/wiki_mcp` is a read-only MCP server that lets Claude Code or Claude Desktop search
the wiki, read notes and follow links. It runs on your machine and talks to the deployed app,
so there is no second copy of your data.

```bash
pip install -e '.[mcp]'

claude mcp add ai-wiki \
  --env WIKI_URL=https://your-app.up.railway.app \
  --env WIKI_TOKEN=your-token \
  -- python -m wiki_mcp.server
```

**[Full setup, the six tools, worked examples and troubleshooting → `docs/MCP.md`](docs/MCP.md)**

For non-MCP consumers, `GET /api/llms.txt` describes the wiki in the llms.txt convention.

## Bulk ingest

```bash
pip install -e .            # add '[stt]' for local transcription
export WIKI_URL=... WIKI_TOKEN=...

wiki status                                          # counts, queue depth, dangling links
wiki crawl https://docs.example.com --max-pages 200  # a documentation section
wiki channel https://youtube.com/@x/videos --whisper # a channel, captured locally
wiki backup ./backups                                # export, verified readable
```

**[Full guide → docs/INGEST.md](docs/INGEST.md)** — including why YouTube capture has to run on
your machine rather than on the server.

## A fresh database starts empty

There is no bundled starter content. Restore from an export (`POST /api/jobs/import`) or add a
source; the tests seed themselves from `tests/fixtures/seed`.
