# Local ↔ Railway ↔ Obsidian Sync Guide

Your wiki is **markdown files in git**. That is the single source of truth — the same pattern Karpathy uses with Obsidian on one side and an LLM agent on the other.

## Recommended setup (best of all worlds)

```
┌─────────────────┐     git push      ┌──────────────┐     auto-deploy    ┌─────────────┐
│  Your laptop    │ ────────────────► │   GitHub     │ ────────────────► │   Railway   │
│                 │                   │   (main)     │                    │  (web+API)  │
│  • Obsidian     │ ◄──────────────── │              │                    └─────────────┘
│  • wiki CLI     │     git pull        └──────────────┘
│  • Cursor Agent │
└─────────────────┘
```

| Tool | Role | When to use |
|------|------|-------------|
| **Obsidian** | Browse, read, graph view, web clipper | Daily reading & exploration |
| **`wiki` CLI** | Ingest, search, query, lint, new zettel | Terminal power-user workflow |
| **Web UI (Railway)** | Google-style search, share with others | Any browser, anywhere |
| **Git** | Sync layer between local and cloud | After every ingest/edit session |
| **Cursor Agent** | LLM maintains wiki per AGENTS.md | Bulk updates, cross-linking |

---

## Daily workflow

### 1. Add a source locally

```bash
# Ingest (writes to sources/ — immutable)
wiki ingest-web "https://example.com/article"
wiki ingest-arxiv "2301.00000"
wiki ingest-youtube "https://youtube.com/watch?v=..."

# Optional: AI literature note
wiki ai-summarize sources/web/article-slug.md

# Create atomic zettel
wiki new-zettel "My New Concept"

# Health check
wiki lint
wiki auto-link
```

### 2. Sync to Railway (git push)

```bash
git add sources/ wiki/
git commit -m "Ingest: article about X"
git push origin main
```

Railway auto-redeploys the API + web with your new content (if connected to GitHub).

### 3. Use Obsidian (optional)

1. Open the repo folder in Obsidian as a vault
2. Browse `wiki/` — wikilinks work natively
3. Use **Graph view** to see the Zettelkasten
4. Use **Obsidian Web Clipper** to save articles → `sources/web/`
5. **Do not edit `sources/`** after ingest (immutable rule)
6. Let the agent/CLI update `wiki/` pages

> Obsidian and the web UI read the same files. No special sync needed beyond git.

---

## CLI: local vs remote

### Local mode (default)

Works directly on files. No server needed.

```bash
wiki search "attention"
wiki query "What is LoRA?"
wiki ingest-web "https://..."
```

### Remote mode (talks to Railway API)

After deploy:

```bash
wiki login --api-url https://YOUR-API.up.railway.app
# email: admin@example.com
# password: (your ADMIN_PASSWORD)

wiki search "transformer" --json
wiki ingest-web "https://..."   # writes on Railway server
```

Use **remote** when you want ingest/query to run on Railway (e.g. from a phone or secondary machine). Use **local + git push** for the primary workflow — it's simpler and keeps git history clean.

---

## Environment files

| File | Purpose | Committed? |
|------|---------|------------|
| `.env` | Your real API keys & secrets | **No** (gitignored) |
| `.env.example` | Template for others | Yes |

Copy once: `cp .env.example .env` then add your `OPENROUTER_API_KEY`.

---

## OpenRouter model stack (configured in `.env`)

| Priority | Model | Why |
|----------|-------|-----|
| 1 (primary) | `nvidia/nemotron-3-ultra-550b-a55b:free` | Best free reasoning + 1M context |
| 2 | `nvidia/nemotron-3-super-120b-a12b:free` | Fast Nemotron fallback |
| 3 | `qwen/qwen3-next-80b-a3b-instruct:free` | Strong general chat |
| 4 | `meta-llama/llama-3.3-70b-instruct:free` | Reliable backup |
| 5 | `openrouter/free` | Auto-router last resort |

---

## Railway environment variables

Set these in the Railway dashboard for the **API** service:

```
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
OPENROUTER_FALLBACK_MODELS=nvidia/nemotron-3-super-120b-a12b:free,qwen/qwen3-next-80b-a3b-instruct:free,meta-llama/llama-3.3-70b-instruct:free,openrouter/free
JWT_SECRET=<random-64-char-string>
ADMIN_EMAIL=you@yourdomain.com
ADMIN_PASSWORD=<strong-password>
DATABASE_URL=${{Postgres.DATABASE_URL}}
REQUIRE_AUTH=true
ALLOWED_ORIGINS=https://YOUR-WEB.up.railway.app
```

For the **Web** service build arg:

```
VITE_API_URL=https://YOUR-API.up.railway.app
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Ask AI fails locally | Check `.env` has `OPENROUTER_API_KEY` |
| Web shows old content | `git push` then wait for Railway redeploy |
| Wikilinks broken in Obsidian | Use `[[slug\|Title]]` format; run `wiki lint` |
| CLI remote fails | Run `wiki login` again; check `WIKI_API_URL` in `.env` |
| Rate limited on free model | Fallback models kick in automatically; wait and retry |
