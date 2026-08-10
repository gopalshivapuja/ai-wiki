# The Plan: From Markdown Folder to Deployed Zettelkasten Wiki

This directory is a complete plan — audit, requirements, architecture, roadmap, and deployment design —
for turning the current markdown collection into a robust, deployed, searchable knowledge base built on
the LLM Wiki pattern with Zettelkasten structure.

**Nothing has been built yet.** That is deliberate: you asked to plan functional and non-functional
requirements first. The only code added is one throwaway audit script whose job is to prove the findings
are real (`evidence/audit_snapshot.py`), and which gets deleted in phase P1 when the real linter
replaces it.

---

## Read in this order

| # | Document | What it answers | Length |
| --- | --- | --- | --- |
| 00 | [Audit findings](00-audit-findings.md) | What is broken today, with reproducible evidence | 37 findings |
| 01 | [Functional requirements](01-functional-requirements.md) | What the system must do, with testable acceptance criteria | ~130 requirements |
| 02 | [Non-functional requirements](02-non-functional-requirements.md) | How fast, safe, cheap, and accessible it must be | ~60 targets |
| 03 | [Architecture](03-architecture.md) | How it will be built, and what was rejected | design + wireframes |
| 04 | [Implementation roadmap](04-implementation-roadmap.md) | The phases, their dependencies, and their exit criteria | 10 phases |
| 05 | [CI/CD and Railway deployment](05-cicd-and-railway-deployment.md) | How it ships and stays up | pipeline + config |
| 06 | [Open decisions](06-open-decisions.md) | The 12 choices that need your opinion | decisions + defaults |
| 07 | [Concepts explained](07-concepts-explained.md) | The jargon above, in plain English | learning companion |
| 08 | [Cursor workflow tips](08-cursor-workflow-tips.md) | How to drive this build with Cursor | practical guide |

In a hurry? Read **00** (what is broken), then **06** (what I need from you), then **04** (what happens
in what order).

---

## Executive summary

### What is wrong today

The wiki *looks* healthy because the tool grading it is lenient. `python3 tools/wiki.py lint` reports
**0 issues**; an independent strict audit reports **66**.

Your two instincts were exactly right, and both are worse than they appear:

1. **"Links are not working."** 27 wikilinks are wrapped in backticks, which renders them as literal
   text rather than links, and another 12 sit inside Mermaid code fences where they can never resolve.
   The result: **4 of your 5 atomic zettels have zero working inbound links**, so the Zettelkasten is
   disconnected by punctuation. Worse, `tools/wiki.py` and all three templates *generate* the bug, so
   every new note starts with dead links.
2. **"Many names are long numbers."** All 5 atomic notes are named `20260810100100-…`, and that
   timestamp leaks into every link and every future URL.

Underneath those, three structural problems:

- **The linter always exits 0**, even when it finds errors — so it can never gate CI, and conventions
  drift silently. 16 of 21 pages already violate the frontmatter schema in your own `AGENTS.md`.
- **Silent data loss is possible.** Two sources with similarly punctuated titles produce the same
  filename and overwrite each other with no warning. Non-Latin titles produce a hidden dotfile.
- **YouTube ingestion is broken** against the installed library and fails silently, writing its own
  error message into the source file as if it were the transcript.

### What we propose to build

A single-container application, deployed on Railway behind a login, where **markdown in git remains the
only source of truth** and everything else is derived and rebuildable:

- **A Google-style search window** — one centred field, instant results as you type, keyboard-driven,
  backed by a real inverted index (SQLite FTS5 with BM25) instead of re-scanning every file per query.
- **A genuine knowledge graph** — computed backlinks with the rationale text from each link, local and
  global graph views, broken links visibly marked, orphan and hub detection. The bookkeeping the wiki
  pattern says humans abandon becomes automatic.
- **A CLI that is a pleasure to use** — installed as `wiki`, real subcommands and flags, `--json`
  everywhere, meaningful exit codes, and `wiki lint --strict` as the quality gate.
- **Content tested like code** — a pull request that adds a dead link goes red in CI.
- **Readable names** — `scaled-dot-product-attention.md`, with the UID preserved in frontmatter and
  aliases so no existing link ever breaks.
- **Deployment that cannot silently break** — health-check-gated releases, automatic rollback,
  post-deploy smoke tests, and no managed database, targeting under $5/month.

### The order of work

**P0 + P1 fixes everything you complained about** in one small, reviewable pull request: readable
filenames, working links, and a linter that stops both from coming back. No infrastructure required.

**P2 → P3 → P5 → P6 → P7** then delivers the deployed, private, searchable, graph-linked web wiki. P4
(ingest and LLM hardening), P8 (browser editing), and P9 (nightly agent audits) can follow or run in
parallel.

### What is deliberately not being built

Real-time collaboration, mobile apps, public sign-up, self-hosted models, and any design where a
database — rather than your markdown — becomes the master copy of your knowledge. Your notes should
outlive this application, and after every phase the wiki still opens in Obsidian as a plain vault.

---

## Reproducing the audit

```bash
python3 tools/wiki.py lint                 # the shipped linter → "0 issues found", exit 0
python3 docs/evidence/audit_snapshot.py    # independent strict audit → 66 findings
```

The gap between those two numbers is the reason this plan starts with a linter and not a web app.
