# Railway Deployment Guide

Deploy the LLM Wiki in two services on Railway.

## Architecture

| Service | Dockerfile | Port | Purpose |
|---------|-----------|------|---------|
| `wiki-api` | `docker/Dockerfile.api` | 8000 | FastAPI backend |
| `wiki-web` | `docker/Dockerfile.web` | 80 | React frontend (nginx) |
| `postgres` | Railway plugin | 5432 | Users & sessions |

## Step 1: Create Project

1. Go to [railway.app](https://railway.app) and create a new project
2. Add **PostgreSQL** from the template marketplace

## Step 2: Deploy API

1. New Service → Deploy from GitHub repo
2. Set **Root Directory** to repo root
3. Set **Dockerfile Path** to `docker/Dockerfile.api`
4. Add environment variables:

```
JWT_SECRET=<generate-a-long-random-string>
ADMIN_EMAIL=you@yourdomain.com
ADMIN_PASSWORD=<strong-password>
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=openrouter/free
DATABASE_URL=${{Postgres.DATABASE_URL}}
REQUIRE_AUTH=true
ALLOWED_ORIGINS=https://<your-web-service>.up.railway.app
WIKI_BASE_DIR=/app
```

5. Generate a public domain for the API service

## Step 3: Deploy Web

1. New Service → same repo
2. **Dockerfile Path**: `docker/Dockerfile.web`
3. Build arg / env:

```
VITE_API_URL=https://<your-api-service>.up.railway.app
```

4. Generate a public domain for the web service
5. Update API `ALLOWED_ORIGINS` with the web domain

## Step 4: Verify

```bash
curl https://<api-domain>/health
# {"status":"ok"}

curl "https://<api-domain>/api/search?q=attention&limit=1"
```

Open the web domain → search → login → explore graph.

## CLI Remote Access

```bash
wiki login --api-url https://<api-domain>
# email + password

wiki search "transformer" --json
wiki query "What is LoRA?"
```

## Notes

- Wiki content is baked into the Docker image from `wiki/` and `sources/`
- For live content updates, mount a Railway volume at `/app/wiki` or set up git-pull on deploy
- Set `REQUIRE_AUTH=true` in production to protect write/LLM endpoints
- Read endpoints work without auth when `REQUIRE_AUTH=false`
