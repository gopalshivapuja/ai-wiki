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
# {"status":"ok","version":"0.4.0"}

curl https://YOUR-APP.up.railway.app/api/stats
# total_pages must be > 0 — if it is 0, the seed data did not load; check the deploy logs
# for "Seed data not found under ...".
```

## What it costs (rates as of 2026-08)

Railway bills **measured per-minute usage, not allocated limits**: RAM $10/GB/month, vCPU
$20/vCPU/month, volume $0.15/GB/month, egress $0.05/GB. The Hobby plan is $5/month
*including* $5 of usage, so you pay `max($5, actual usage)`. PostgreSQL is billed as an
ordinary service at the same rates, not as a priced add-on.

The **app service declares no volume and does not need one** — seed data is read-only inside
the image and the only writes are short-lived files in `/tmp` (PDF uploads, downloaded
audio), which use ephemeral container disk. Only the Postgres service has a volume.

| | App (RAM/CPU) | Postgres (RAM/CPU) | PG volume + egress | **Total** |
|---|---|---|---|---|
| Low | 0.30 GB / 0.02 vCPU | 0.20 GB / 0.01 vCPU | 1 GB | **~$5.80/mo** |
| Typical | 0.45 GB / 0.03 vCPU | 0.50 GB / 0.02 vCPU | 3 GB | **~$11/mo** |
| High | 0.60 GB / 0.08 vCPU | 1.0 GB / 0.05 vCPU | 5 GB | **~$19.60/mo** |

**RAM is about 85% of the bill.** The image already runs `uvicorn --workers 1` and a small
connection pool to keep it near the low end. Hobby's 5 GB volume cap applies to the Postgres
volume; going past it forces the Pro plan at $20/month. CPU and egress are noise at a few
hundred requests per day.

**OpenRouter** — the default model is now **`google/gemini-2.5-flash-lite`, which is paid**,
because the free tier's latency was the thing that made the wiki feel broken: tens of seconds
per call turned a bulk import into a day-long job and Ask AI into a spinner. Expect roughly
$0.003 per RAG query — $0.50–2.40/month at 20 questions a day — plus cents for a bulk import.

The ladder falls back to Gemma's `:free` models, so the app still works with no credit at all;
it is just slow. `:free` models cost $0/token but allow only 20 requests/minute and **50
requests/day**, which a one-time **$10 credit purchase raises permanently to 1,000/day**.
`GET /api/llm/models` reports which model the app actually chose.

**Transcription** is the only genuinely metered add-on: about $0.36 per hour of audio.
Ten hours a month is ~$3.60. Self-hosting Whisper instead would need 1–2 GB of resident RAM
and would roughly double the Railway bill, which is why this uses an external API.

**Realistic all-in: $6–14/month.**

## First run

On first boot the app waits for the database to accept connections (retrying with backoff —
the app and database services usually start together), refuses to start if `JWT_SECRET` is
still the built-in default, then imports the bundled `wiki/` and `sources/` markdown into
PostgreSQL once. After that the database is the only source of truth and those files are
ignored.

A healthy first boot logs, in order:

```
Database reachable after N attempts     (only when it had to wait)
Created admin user <your email>
schema_ddl: applied N/N statements      (both numbers must match)
Seeded N documents from /app/seed       (N must be > 0)
Job runner started
```

## Known limitations on Railway

**YouTube audio transcription usually fails from Railway.** yt-dlp requests from datacenter
IPs are frequently met with "Sign in to confirm you're not a bot" or HTTP 403, even though
the same URL works from your laptop. YouTube ingest *via captions* is unaffected, as is
transcription of audio hosted elsewhere. There is no proxy or cookie configuration for this.

**Queued PDF jobs do not survive a redeploy.** The upload is staged in `/tmp` and only its
path is stored in the job row, so a PDF still queued when the container is replaced fails
with a missing-file error. Re-upload it. Every other job kind retries cleanly, because
already-stored sources are skipped.

## Local test before deploying

```bash
cp .env.example .env
docker compose up --build
```

## Back up your notes

The database is the only live copy. **Add source → Backup → Download everything** gives you a zip of
plain markdown that any editor can read and that this app can re-import — so a lapsed plan, a
mistaken delete, or a decision to move elsewhere never costs you your notes.

Do it after any substantial writing session. There is no automatic off-site backup; Railway's own
database backups depend on your plan.
