# Railway Deployment — Step-by-Step

Complete guide to get your LLM Wiki live on Railway with local CLI sync.

## Architecture on Railway

```
┌─────────────────────────────────────────────────────────┐
│                    Railway Project                       │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │  wiki-api    │  │  wiki-web    │  │  PostgreSQL  │ │
│  │  (Docker)    │  │  (Docker)    │  │  (plugin)    │ │
│  │  :8000       │  │  nginx :80   │  │              │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘ │
│         │                 │                  │          │
│         └─────────────────┴──────────────────┘          │
└─────────────────────────────────────────────────────────┘
         ▲                                    ▲
         │ git push (auto-deploy)              │ wiki login (remote CLI)
         │                                    │
    ┌────┴─────┐                         ┌────┴─────┐
    │  GitHub  │                         │  Laptop  │
    │  repo    │                         │ Obsidian │
    └──────────┘                         │ wiki CLI │
                                         └──────────┘
```

---

## Prerequisites

- GitHub repo pushed (branch merged to `main`)
- [Railway account](https://railway.app) (free tier works)
- OpenRouter API key

---

## Step 1: Merge the PR on GitHub

1. Open the PR for `cursor/full-wiki-platform-0bdb`
2. Review and merge to `main`
3. Railway will connect to this repo

---

## Step 2: Create Railway Project

1. Go to [railway.app/new](https://railway.app/new)
2. **Deploy from GitHub repo** → select `ai-wiki`
3. Name the project `llm-wiki`

---

## Step 3: Add PostgreSQL

1. In the project, click **+ New** → **Database** → **PostgreSQL**
2. Railway auto-creates `DATABASE_URL`

---

## Step 4: Deploy API Service

1. **+ New** → **GitHub Repo** → same repo (or use the auto-created service)
2. Rename service to `wiki-api`
3. **Settings** → **Build**:
   - Builder: `Dockerfile`
   - Dockerfile path: `docker/Dockerfile.api`
4. **Settings** → **Networking** → **Generate Domain** (e.g. `wiki-api-production.up.railway.app`)
5. **Variables** tab — add:

```env
OPENROUTER_API_KEY=sk-or-v1-YOUR-KEY
OPENROUTER_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
OPENROUTER_FALLBACK_MODELS=nvidia/nemotron-3-super-120b-a12b:free,qwen/qwen3-next-80b-a3b-instruct:free,meta-llama/llama-3.3-70b-instruct:free,openrouter/free
JWT_SECRET=<run: openssl rand -hex 32>
ADMIN_EMAIL=you@yourdomain.com
ADMIN_PASSWORD=<strong-password>
DATABASE_URL=${{Postgres.DATABASE_URL}}
REQUIRE_AUTH=true
ALLOWED_ORIGINS=https://PLACEHOLDER-WEB-DOMAIN.up.railway.app
WIKI_BASE_DIR=/app
```

6. Deploy and verify: `curl https://YOUR-API-DOMAIN/health` → `{"status":"ok"}`

---

## Step 5: Deploy Web Service

1. **+ New** → **GitHub Repo** → same repo
2. Rename to `wiki-web`
3. **Settings** → **Build**:
   - Dockerfile path: `docker/Dockerfile.web`
   - **Build Args**: `VITE_API_URL=https://YOUR-API-DOMAIN.up.railway.app`
4. **Networking** → **Generate Domain**
5. Go back to **wiki-api** variables → update `ALLOWED_ORIGINS` with the web domain
6. Redeploy API if needed

---

## Step 6: Verify Live App

1. Open web domain → search "attention" → click a result
2. Visit `/graph` → interactive knowledge graph
3. Login at `/login` with your `ADMIN_EMAIL` / `ADMIN_PASSWORD`
4. Try `/ask` → "What is multi-head attention?"

---

## Step 7: Connect Local CLI to Railway

On your laptop:

```bash
# Clone repo (if not already)
git clone https://github.com/gopalshivapuja/ai-wiki.git
cd ai-wiki
pip install -e ".[api]"
cp .env.example .env   # add your OPENROUTER_API_KEY

# Point CLI at Railway
wiki login --api-url https://YOUR-API-DOMAIN.up.railway.app
```

Now `wiki search`, `wiki query`, and `wiki ingest-*` can run against Railway remotely.

---

## Step 8: Local + Cloud Sync Workflow

**Best practice: Git is your sync layer.**

```bash
# 1. Work locally (Obsidian + CLI)
wiki ingest-web "https://example.com/article"
wiki ai-summarize sources/web/article-slug.md
wiki new-zettel "New Concept"
wiki lint

# 2. Commit and push
git add sources/ wiki/
git commit -m "Ingest: article about X"
git push origin main

# 3. Railway auto-redeploys with new content (~2 min)
```

### Obsidian setup

1. Open the repo folder as an Obsidian vault
2. Browse `wiki/` — wikilinks work natively
3. Use Graph view to explore connections
4. Web Clipper → saves to `sources/web/`
5. Let CLI/agent update `wiki/` pages (don't hand-edit sources)

See [SYNC.md](SYNC.md) for the full workflow.

---

## Alternative: CLI-only deploy

If you prefer terminal deploy:

```bash
curl -fsSL https://railway.com/install.sh | sh
railway login          # opens browser to sign in
cd ai-wiki
railway up -y          # deploys API from railway.toml
```

Then add the web service and Postgres via the Railway dashboard.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Build fails | Check Railway build logs; ensure Dockerfile paths are correct |
| CORS errors | Update `ALLOWED_ORIGINS` on API with exact web domain |
| Ask AI 500 | Verify `OPENROUTER_API_KEY` on API service |
| Old content on web | Push to `main`; Railway redeploys on git push |
| Login fails | Check `ADMIN_EMAIL` is a valid email (needs TLD like `.com`) |
