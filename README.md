# LLM Wiki

Web-only personal knowledge base (Karpathy LLM Wiki + Zettelkasten). All content lives in **PostgreSQL** — no files, no sync, no CLI.

## Features

- Google-style search across your knowledge base
- Markdown reader with wikilinks and backlinks
- Interactive knowledge graph
- Ask AI (RAG with Nemotron via OpenRouter)
- Ingest web articles, arXiv papers, YouTube transcripts
- Create atomic zettels and AI literature summaries

## Run locally with Docker

```bash
cp .env.example .env   # add OPENROUTER_API_KEY
docker compose up --build
```

Open **http://localhost:8000**

Login: `admin@example.com` / `changeme`

## Deploy to Railway

1. Create project at [railway.app](https://railway.app)
2. Add **PostgreSQL** plugin
3. Deploy from GitHub — uses `Dockerfile` at repo root
4. Set environment variables (see `DEPLOY.md`)
5. Generate a public domain

That's it — one service, one database, no sync.

## Default credentials

Change `ADMIN_PASSWORD` in production!

- Email: `admin@example.com`
- Password: `changeme`

## Tech stack

- **Frontend**: React + Vite (served by FastAPI)
- **Backend**: FastAPI + SQLAlchemy
- **Database**: PostgreSQL
- **LLM**: OpenRouter (Nemotron 3 Ultra + fallbacks)
