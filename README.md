# LLM Wiki + Zettelkasten Platform

Personal AI knowledge base based on [Andrej Karpathy's LLM Wiki pattern](llm-wiki.md), with Zettelkasten architecture, web UI, CLI, and OpenRouter LLM integration.

## Quick Start

### 1. Install

```bash
pip install -e ".[api,dev]"
pip install -r requirements.txt
cd apps/web && npm install && cd ../..
```

### 2. Configure

```bash
cp .env.example .env
# Add OPENROUTER_API_KEY for AI features
```

### 3. Run locally

**API** (terminal 1):
```bash
uvicorn wiki_api.app:app --reload --port 8000
```

**Web** (terminal 2):
```bash
cd apps/web && npm run dev
```

Open http://localhost:5173 — Google-style search over your wiki.

**CLI**:
```bash
wiki search "attention"
wiki read transformer-architecture
wiki query "What is LoRA?"
wiki stats
wiki lint
```

### 4. Docker

```bash
docker compose -f docker-compose.yml up --build
```

- Web: http://localhost:3000
- API: http://localhost:8000
- Health: http://localhost:8000/health

## Default Login

- Email: `admin@example.com`
- Password: `changeme` (set `ADMIN_PASSWORD` in `.env`)

Read-only browsing works without login. AI features (Ask, ingest, new zettel) require login.

## CLI Remote Mode

```bash
wiki login --api-url http://localhost:8000
wiki search "transformer" --json
```

## Project Structure

```
wiki/           # Knowledge base (Zettelkasten layers)
sources/        # Immutable raw sources
packages/
  wiki_core/    # Shared library (search, graph, ingest, RAG)
  wiki_api/     # FastAPI backend
  wiki_cli/     # Typer CLI
apps/web/       # React + Vite frontend
docker/         # Dockerfiles
```

## Railway Deployment

1. Create a Railway project
2. Add **PostgreSQL** plugin
3. Deploy API service from `docker/Dockerfile.api`
4. Deploy Web service from `docker/Dockerfile.web`
5. Set environment variables:

```
JWT_SECRET=<random-secret>
ADMIN_EMAIL=you@example.com
ADMIN_PASSWORD=<strong-password>
OPENROUTER_API_KEY=sk-or-v1-...
DATABASE_URL=<from Railway Postgres>
ALLOWED_ORIGINS=https://your-web.up.railway.app
REQUIRE_AUTH=true
```

## Schema

See [AGENTS.md](AGENTS.md) for Zettelkasten conventions and agent workflows.
