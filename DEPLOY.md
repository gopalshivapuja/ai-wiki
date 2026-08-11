# Deploy to Railway

One service, one database.

## Steps

### 1. Add PostgreSQL

In your Railway project: **+ New** → **Database** → **PostgreSQL**.

### 2. Deploy the app

**+ New** → **GitHub Repo** → select `ai-wiki`. Railway detects the `Dockerfile` and
`railway.toml` automatically.

### 3. Set environment variables

On the **app service** → **Variables**:

```env
DATABASE_URL=${{Postgres.DATABASE_URL}}
JWT_SECRET=<openssl rand -hex 32>
ADMIN_EMAIL=you@yourdomain.com
ADMIN_PASSWORD=<a strong password>
OPENROUTER_API_KEY=sk-or-v1-...
```

Leave `OPENROUTER_MODEL` unset and the app picks a working free model from OpenRouter's live
catalogue. Model ids go stale often, so pinning one is usually worse than letting it choose.
Check `GET /api/llm/models` to see what it resolved to.

For transcription of videos without captions, also set `STT_PROVIDER=openai` and
`OPENAI_API_KEY` (or `STT_PROVIDER=deepgram` and `DEEPGRAM_API_KEY`).

Changing `ADMIN_PASSWORD` later and redeploying **does** update the password — the app
re-hashes it at boot when it no longer matches.

### 4. Turn OFF app sleeping

Settings → disable **Serverless** / app sleeping for the app service.

Sleeping is triggered by a lack of *inbound HTTP*, but a running crawl or transcription only
makes *outbound* calls. Left on, the natural failure is: you start a 5-minute crawl, close
the tab, the container sleeps, and the job dies. (Interrupted jobs are marked failed on the
next boot with a Retry button, so nothing is silently lost — but it is avoidable.)

### 5. Generate a domain

**Networking** → **Generate Domain**, then open the URL.

### 6. Verify

```bash
curl https://YOUR-APP.up.railway.app/health
# {"status":"ok","version":"0.3.0"}

curl https://YOUR-APP.up.railway.app/api/stats
# total_pages must be > 0 — if it is 0, the seed data did not load; check the deploy logs
# for "Seed data not found under ...".
```

## What it costs

Railway bills **measured per-minute usage, not allocated limits**: RAM $10/GB/month, vCPU
$20/vCPU/month, volume $0.15/GB/month, egress $0.05/GB. The Hobby plan is $5/month
*including* $5 of usage, so you pay `max($5, actual usage)`. PostgreSQL is billed as an
ordinary service at the same rates, not as a priced add-on.

| | App | Postgres | Volume + egress | **Total** |
|---|---|---|---|---|
| Low | 0.30 GB / 0.02 vCPU | 0.20 GB / 0.01 vCPU | 1 GB | **~$6/mo** |
| Typical | 0.45 GB / 0.03 vCPU | 0.50 GB / 0.02 vCPU | 3 GB | **~$11/mo** |
| High | 0.60 GB / 0.08 vCPU | 1.0 GB / 0.05 vCPU | 5 GB | **~$20/mo** |

**RAM is about 85% of the bill.** The image already runs `uvicorn --workers 1` and a small
connection pool to keep it near the low end. Hobby's 5 GB volume cap fits this workload;
going past it forces the Pro plan at $20/month. CPU and egress are noise at a few hundred
requests per day.

**OpenRouter** — `:free` models genuinely cost $0/token but allow only 20 requests/minute
and **50 requests/day**. A one-time **$10 credit purchase raises that permanently to 1,000
requests/day**, which is the single highest-leverage thing you can spend money on here. If
you would rather pay per token, Gemini Flash-class models run about $0.003 per RAG query —
roughly $0.50–2.40/month at 20 questions a day.

**Transcription** is the only genuinely metered add-on: about $0.36 per hour of audio.
Ten hours a month is ~$3.60. Self-hosting Whisper instead would need 1–2 GB of resident RAM
and would roughly double the Railway bill, which is why this uses an external API.

**Realistic all-in: $6–14/month.**

## First run

On first boot the app imports the bundled `wiki/` and `sources/` markdown into PostgreSQL,
once. After that the database is the only source of truth and those files are ignored.

## Local test before deploying

```bash
cp .env.example .env
docker compose up --build
```
