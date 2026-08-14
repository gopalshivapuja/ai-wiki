# Bulk ingest

How to load a lot of material at once — a YouTube channel, a documentation site — and what the
wiki does with it afterwards.

Install the CLI and point it at your wiki:

```bash
pip install -e .                 # add '[stt]' if you need local transcription
export WIKI_URL=https://your-app.up.railway.app
export WIKI_TOKEN=...            # from POST /api/auth/login
wiki status
```

---

## Websites

Runs entirely on the server. One job per documentation section:

```bash
wiki crawl https://docs.anthropic.com/en/docs/build-with-claude \
  --collection claude-docs --max-pages 200 --wait
```

The crawler stays on the starting domain and below the starting path, respects a depth limit,
pauses between requests, and stops at `--max-pages` (ceiling 250). Every page is stored as a
source and distilled into notes. Re-running skips pages already captured, so an interrupted
crawl is cheap to resume.

For a large site, one crawl per section beats one enormous crawl: the collection tag keeps them
grouped, and a failure costs you one section rather than everything.

## YouTube

**This cannot run on the server.** YouTube refuses caption requests from cloud IP ranges, and
both routes the app knows — the timedtext endpoint and yt-dlp's player negotiation — are
refused from Railway. The channel ingest job fails there for every video. Capture runs on your
machine instead:

```bash
wiki channel https://www.youtube.com/@SomeChannel/videos \
  --collection my-course --moc moc-my-course --whisper --wait
```

What it does:

1. Lists the channel (metadata only, no downloads).
2. Fetches published captions for each video.
3. **Falls back to local transcription** when captions are refused — audio is served freely
   from the media CDN even while captions are blocked, so it downloads the audio and runs
   Whisper on it. Needs `pip install -e '.[stt]'`. On Apple silicon this runs at roughly 10×
   realtime, and the output is generally better than YouTube's auto-captions.
4. Imports everything the wiki does not already have, and distillation links it in.

Progress is saved after every video in `~/.ai-wiki/capture-state.json`, so an interrupted run
resumes rather than starting over. Failures are recorded per video and skipped, never fatal to
the batch.

Useful flags: `--list-only` to see what would be captured, `--limit N` for the newest N,
`--pace` to slow down if YouTube starts rate-limiting (it will, if you hammer it).

A transcript produced by Whisper says so in its own text, because a machine transcript deserves
slightly less trust than a published caption.

### If captions start failing everywhere

You are rate-limited, not blocked forever. It clears in hours. `--pace 30` and a smaller
`--limit` avoid it; a different network clears it immediately. Authentication does **not** help
— the limit is by address, and browser cookies made no difference when tested.

---

## What happens after material lands

Every ingest path ends at the same place, so it does not matter which one you used:

1. The source is stored **immutably** — captured material is never edited.
2. A **literature note** is written: what the source argues, not a table of contents.
3. **Concepts are extracted** and converged against what exists already, by name and by
   meaning, so a concept met in a second source links to the note that covers it rather than
   forking a near-duplicate.
   A source longer than `SOURCE_CHARS` (24,000) is read in successive windows rather than
   truncated, and its new-note budget scales with its length. This matters more than it
   sounds: a 10-minute clip is ~10,000 characters and fits whole, but an 80-minute lecture
   runs to 70,000–90,000, and reading only the first window discards the second half of it
   silently. Concepts named in more than one window are folded into one, keeping the other
   name as an alias.
4. **Links are written in both directions**, each with a stated reason.
5. Everything is filed under a **map of content** if you passed `--moc`.
6. Every document is **embedded**, so it is findable by meaning immediately.

Notes written this way are tagged `unreviewed` until you approve them at `/review`.

## Afterwards

```bash
wiki status                  # counts, queue depth, dangling links
wiki embed --duplicates      # backfill vectors, and report near-duplicate notes
wiki backup ./backups        # download an export and verify it opens
```

`wiki status` exits non-zero if anything dangles, so it works in a script.

`--duplicates` reports pairs that look like the same note written twice. **Read them before
merging anything**: similarity is not sameness. "Many-to-One Mapping" and "One-to-Many Mapping"
score 0.933 against each other and are opposites.

`wiki backup` reads every member of the archive before saving it. An export that only *lists*
its contents can be corrupt and still look fine — that is how an unreadable backup once shipped.

## Scale

The queue runs one job at a time, so a large import takes hours. That is deliberate: each
distillation makes at least two model calls — more for a long source, one per window — and
running them concurrently exhausted the database connection pool once and took the site down
with it.

Long lectures cost proportionally more. Eighteen 80-minute lectures are ~70 model calls rather
than ~36, so queue them in batches and let each drain before the next.

Queue a large batch and leave it. Nothing is lost to a redeploy — the queue is a database
table — and `wiki status` tells you the real depth, not just the newest page.
