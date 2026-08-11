# Deploy to Railway

One service. One database. No sync.

## Steps

### 1. Merge PR and connect GitHub

Connect your `ai-wiki` repo to Railway.

### 2. Add PostgreSQL

In your Railway project: **+ New** → **Database** → **PostgreSQL**

### 3. Deploy the app

**+ New** → **GitHub Repo** → select `ai-wiki`

Railway auto-detects `Dockerfile` and `railway.toml`.

### 4. Set environment variables

On the **app service** → **Variables**:

```env
DATABASE_URL=${{Postgres.DATABASE_URL}}
JWT_SECRET=<run: openssl rand -hex 32>
ADMIN_EMAIL=you@yourdomain.com
ADMIN_PASSWORD=<strong-password>
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
OPENROUTER_FALLBACK_MODELS=nvidia/nemotron-3-super-120b-a12b:free,qwen/qwen3-next-80b-a3b-instruct:free,meta-llama/llama-3.3-70b-instruct:free,openrouter/free
```

### 5. Generate domain

**Networking** → **Generate Domain** → open the URL.

### 6. Verify

```bash
curl https://YOUR-APP.up.railway.app/health
# {"status":"ok","version":"0.2.0"}
```

Open the URL → search → login → Add sources → Ask AI.

## First run

On first startup the app seeds PostgreSQL from bundled `wiki/` and `sources/` markdown (one-time import). After that, all content lives in the database.

## Local Docker test (before Railway)

```bash
cp .env.example .env
docker compose up --build
```

Open http://localhost:8000
