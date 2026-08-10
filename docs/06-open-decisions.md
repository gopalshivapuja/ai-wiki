# 06 — Open Decisions

**Status:** awaiting your input · **Depends on:** all preceding documents

Twelve decisions where a reasonable person could choose differently. Each has a recommendation and a
default, so if you say nothing, work can proceed sensibly — but these are the places where five minutes
of your opinion saves a lot of rework.

Each becomes an ADR in `docs/adr/` once settled (NFR-MNT-06).

---

## D1 · Filenames: readable slugs, or keep the timestamp UIDs?

**Recommendation:** slug filenames, UID in frontmatter, `aliases` for backward compatibility
(`docs/03-architecture.md` §3).

Slugs give you readable links, readable URLs, and links you can type from memory. The UID survives in
frontmatter, so you keep chronological identity and stable external references — you just stop looking
at 14 digits every time you glance at a filename.

**Cost of choosing this:** a one-time migration touching 5 files and 12 links.
**Cost of not choosing it:** every future link, URL, and conversation carries the digits.

**Default if you don't answer:** slugs. You called the long numbers out first, so I am reading that as
a preference already.

---

## D2 · One repository, or split app code from wiki content?

| Option | Pros | Cons |
| --- | --- | --- |
| **Single repo (recommended for v1)** | One clone, one CI pipeline, content versioned alongside the schema that governs it; the image ships with content baked in | Every note you commit triggers an image rebuild and redeploy |
| Two repos: `wiki-app` + `wiki-content` | Content commits do not rebuild the app; multiple wikis can share one app; cleaner separation | Two clones, cross-repo CI, the container must fetch content at boot, and you need a token for a private content repo |

**Recommendation:** single repo for v1. The redeploy-per-note cost is real but small, and it keeps
`AGENTS.md`, the linter, and the content in one reviewable place — which is the whole point of the
"content is tested like code" gate.

**The signal to split:** when you are adding notes several times a day and the rebuild latency starts
to feel like friction. The split is straightforward later; the app already reads content from a
configurable directory.

**Default:** single repo.

---

## D3 · Login: password, or GitHub OAuth?

| Option | Pros | Cons |
| --- | --- | --- |
| **Owner password + Argon2id (recommended)** | No third-party dependency, no database, works offline, trivial to test | You manage a password; adding readers means sharing it |
| GitHub OAuth with an allowlist | No password to manage, per-person identity, easy to add readers | Extra dependency, more moving parts, harder to test, requires an app registration |

**Recommendation:** password for v1 behind an `AuthBackend` interface, so OAuth is an additive change
rather than a rewrite (`docs/03-architecture.md` §9).

**The signal to switch:** the second person who needs their own account.

**Default:** password.

---

## D4 · Web stack: server-rendered HTMX, or a React SPA?

**Recommendation:** FastAPI + Jinja2 + HTMX + Alpine, with Tailwind built in CI.

For a read-mostly document site, server rendering is faster to first paint, needs no Node in the
runtime image, works with JavaScript disabled, and lets the web app import `wikikit` directly instead
of talking to itself over HTTP. Search-as-you-type — the one genuinely interactive feature — is a single
`hx-get` on the input.

**Choose React instead if** you want to grow this into a heavily interactive app (drag-and-drop graph
editing, collaborative editing, offline-first). Say so now, because it changes the whole front end.

**Default:** HTMX.

---

## D5 · Search: SQLite FTS5, or a dedicated search service?

**Recommendation:** SQLite FTS5 with BM25, optionally fused with embeddings.

At 2,000 notes this is not a close call: FTS5 gives ranking and snippet highlighting for free, adds
zero infrastructure, and the index is a single disposable file. Meilisearch is a lovely product and
would be a second service, a second bill, and a second failure domain to solve a problem you do not
have yet.

**The signal to revisit:** 50,000+ notes, or a need for faceted search and typo tolerance beyond what
FTS5 plus a little normalisation gives you.

**Default:** SQLite FTS5.

---

## D6 · Semantic search in v1, or lexical only?

**Recommendation:** build the fusion seam in P3, ship lexical-only, enable embeddings when you notice
searches failing because you remembered the *idea* rather than the *words*.

Embeddings genuinely help conceptual recall ("that thing about splitting attention across subspaces")
but they add an embedding provider, a re-embedding step on every edit, and a cost line. The seam costs
nothing to build now; the feature can be switched on with one environment variable.

**Sub-decision if you enable it:** OpenRouter-hosted embeddings (no local dependency, per-call cost) or
a local sentence-transformer (free, but adds ~100 MB of PyTorch to the image, which is a real
consideration on a scale-to-zero container).

**Default:** lexical in v1, seam ready, embeddings off.

---

## D7 · Can the web app write, or is authoring CLI-only?

**Recommendation:** read-only web in v1 (P5–P7), git write-back in P8.

This is the decision with the worst failure mode if you get it wrong: a web app that saves to the
container filesystem on Railway **loses your writing on the next redeploy**
(`docs/05-cicd-and-railway-deployment.md` §6). Read-only v1 removes that risk entirely and matches the
Karpathy workflow — you author with an agent and a terminal, and read in a browser.

**The signal to prioritise P8:** you keep wanting to fix a typo from your phone. Which, realistically,
you will.

**Default:** read-only v1.

---

## D8 · Should any part of the wiki be publicly readable?

Options: fully private (recommended default) · per-note public share links (FR-WEB-17) · a public
static export of selected notes built by CI.

**Recommendation:** fully private for v1. Ingested third-party content is quotation for personal
research; republishing it changes the licensing conversation (NFR-DAT-04). If you later want a public
face, the clean answer is a *separate* static export of notes you explicitly mark
`visibility: public`, not authentication holes in the private app.

**Default:** fully private.

---

## D9 · Domain scope: AI knowledge base, or general-purpose?

The existing content is entirely AI/ML, and `AGENTS.md` is written around that. The Karpathy pattern
explicitly supports personal, research, book, and business wikis.

**Why it matters:** it determines whether the taxonomy stays `concepts / entities / atomic / syntheses`
or generalises, whether ingest needs non-technical sources (podcasts, email, meeting notes), and whether
one vault or several.

**Recommendation:** keep v1 focused on AI/ML — the concrete taxonomy is a feature, not a limitation —
but make the content directory and taxonomy configurable so a second vault is a config change rather
than a fork.

**Default:** AI/ML focus, configurable taxonomy.

---

## D10 · Deploy trigger: GitHub Actions, or Railway's GitHub integration?

**Recommendation:** GitHub Actions as the gatekeeper.

Railway's native integration deploys on push, which is simpler but bypasses your quality gate — a
commit with 27 broken links would sail into production. Actions runs CI first and only then calls
`railway up`, which is the entire point of having `wiki lint --strict`.

**Default:** GitHub Actions with a `RAILWAY_TOKEN` secret.

---

## D11 · Scale to zero, or always on?

**Recommendation:** scale to zero (`deploy.sleepApplication true`).

It is the main cost lever, and a ~5-second cold start on the first search after an idle period is a
fair trade for a personal wiki. Flip it off if that first search of the day feels annoying enough to be
worth a few dollars a month.

**Default:** scale to zero.

---

## D12 · How much should the LLM write unsupervised?

Options: propose-only with human promotion (recommended) · auto-write literature notes but never touch
existing pages · full autonomy on ingest.

**Recommendation:** propose-only, with AI output marked `status: draft` and `generated_by`. Two reasons:
it is our prompt-injection containment strategy (F-24), and the Karpathy pattern is explicit that you
remain the curator while the LLM does the bookkeeping. Automation belongs in the *maintenance* work —
backlinks, index regeneration, health reports — not in deciding what your wiki believes.

**Default:** propose-only.

---

## Decision summary

| ID | Question | Recommended default |
| --- | --- | --- |
| D1 | Filenames | Readable slugs, UID in frontmatter, aliases for compatibility |
| D2 | Repo layout | Single repo for v1 |
| D3 | Login | Owner password (Argon2id), OAuth-ready interface |
| D4 | Web stack | FastAPI + Jinja + HTMX + Tailwind |
| D5 | Search engine | SQLite FTS5 + BM25 |
| D6 | Semantic search | Seam now, embeddings off in v1 |
| D7 | Web writes | Read-only v1, git write-back in P8 |
| D8 | Public access | Fully private |
| D9 | Scope | AI/ML focus, configurable taxonomy |
| D10 | Deploy trigger | GitHub Actions gating `railway up` |
| D11 | Idle behaviour | Scale to zero |
| D12 | LLM autonomy | Propose-only, human promotion |

---

## What I need from you to start building

Strictly speaking, nothing — the defaults above are coherent and safe. But three answers would change
what gets built, so they are worth your attention first:

1. **D4 (web stack)** — switching later is expensive. HTMX unless you want a heavily interactive app.
2. **D7 (web writes)** — determines whether P8 is a nice-to-have or the reason you use this at all.
3. **Where to start** — the recommendation is `P0 + P1`: it fixes the dead links and the long-number
   filenames in one small, reviewable pull request, with a linter that stops them coming back. That
   gives you a visibly better wiki before any infrastructure exists.
