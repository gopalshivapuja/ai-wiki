# AGENTS.md — Schema & Guidelines for LLM Wiki + Zettelkasten

Welcome to the **AI Knowledge Base System** built on the **LLM Wiki Pattern** with **Zettelkasten Architecture** and **OpenRouter LLM Integration**.
This document defines the schema, conventions, and operational workflows for any AI Agent reading, updating, or maintaining this repository.

---

## 1. Core Architecture & Zettel Taxonomy

The knowledge base consists of four distinct layers based on the Zettelkasten methodology:

1. **Raw Sources (`sources/`) [Fleeting Notes]**: Immutable source documents.
   - `sources/youtube/` — Transcripts and metadata from YouTube videos.
   - `sources/web/` — Markdown conversions of web articles, blogs, and documentation.
   - `sources/pdfs/` — Extracted text and structure from research papers and PDF/arXiv documents.
   - `sources/documents/` — Raw text, notes, and local files provided by the user.
   - `sources/assets/` — Image attachments and local diagrams.
   *Rule: Never edit or delete files in `sources/`. They are the immutable ground truth.*

2. **Literature Notes (`wiki/sources/`)**: LLM-generated source summaries capturing core claims, citations, and takeaways from a raw source.

3. **Atomic Permanent Notes / Zettels (`wiki/atomic/`)**: Modular, self-contained single-concept notes assigned unique timestamp UIDs.
   - Focus on **one single idea** per note (< 250 lines).
   - Self-contained and understandable without prior context.

4. **Hub Notes & Maps of Content (`wiki/syntheses/`) [MOCs]**: Structural overview pages and comparative roadmaps that group atomic Zettels into themes.
   - `wiki/index.md` — Central catalog of all wiki pages organized by category.
   - `wiki/log.md` — Chronological log of ingestion, query, search, and maintenance passes.
   - `wiki/concepts/` — Topic overviews linking related atomic notes.
   - `wiki/entities/` — Companies, models, frameworks, benchmarks (e.g. OpenAI, PyTorch, LLaMA).

---

## 2. Formatting & Link Conventions

### Markdown, Wikilinks & Link Justification
- Use standard Obsidian-style **wikilinks**: [[note-title]] or [[note-title|Display Title]].
- **Link Rationale**: Always include explicit contextual justification when adding a wikilink:
  *Example:* `[[cross-encoder-reranking]] — applied after vector search to improve precision.`
- Every atomic note MUST be linked from at least one Map of Content (MOC) in `wiki/syntheses/` or `wiki/index.md`.

### Frontmatter & Dataview Schema
Every page in `wiki/` MUST begin with YAML frontmatter supporting Obsidian Dataview:

```yaml
---
uid: "20260810114500"
title: "Atomic Concept Title"
type: zettel | literature | moc | concept | entity | synthesis | source
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [atom, attention, deep-learning]
sources:
  - "sources/pdfs/paper-slug.md"
---
```

---

## 3. OpenRouter API & LLM Integration

Configured through the environment (see `.env.example`):
- `OPENROUTER_API_KEY` — private API key, git-ignored.
- `OPENROUTER_MODEL` / `OPENROUTER_FALLBACK_MODELS` — **optional**. Leave blank and the app
  selects a working free model from OpenRouter's live catalogue at
  `https://openrouter.ai/api/v1/models`. Do not hardcode model ids in documentation: they go
  stale, and a configured id that OpenRouter no longer serves is skipped with a warning.
  `GET /api/llm/models` reports what is configured, what is valid, and what will be used.
- `STT_PROVIDER` + `OPENAI_API_KEY` / `DEEPGRAM_API_KEY` — speech-to-text for videos with no
  captions.

---

## 4. Operations — HTTP API

There is **no CLI**. This is a web-only application; every operation is an HTTP endpoint, and
the React frontend is the interface. Authenticate with
`POST /api/auth/login` and send `Authorization: Bearer <token>`.

**Read (public):**
- `GET /api/search?q=&limit=` — ranked hits; each carries `kind: "page" | "source"`.
  Anonymous callers get pages only; raw source text requires auth.
- `GET /api/pages`, `GET /api/pages/{slug}` (includes `backlinks` and resolved `links`),
  `GET /api/tags`, `GET /api/graph`, `GET /api/stats`, `GET /api/resolve?target=`

**Write (authenticated):**
- `POST /api/zettels`, `PUT /api/pages/{slug}`, `DELETE /api/pages/{slug}`,
  `POST /api/pages/{slug}/rename`
- `GET /api/sources`, `GET /api/sources/{slug}`, `DELETE /api/sources/{slug}`
- `POST /api/llm/query` — RAG answer with citations
- `GET /api/log`

**Ingest (authenticated, asynchronous).** Each returns a job; poll `GET /api/jobs/{id}`:
- `POST /api/jobs/web` · `/arxiv` · `/youtube` · `/transcribe` · `/crawl` · `/paste` ·
  `/summarize` · `/pdf` (multipart upload)
- `GET /api/jobs`, `POST /api/jobs/{id}/cancel`, `POST /api/jobs/{id}/retry`

### Content rules for automated writers
- Sources are immutable. `upsert_source` never mutates an existing row; a different URL that
  slugifies the same gets a hash-suffixed slug.
- AI summaries are written to `summary-{source_slug}`, never to the source's own slug, and
  `upsert_page(..., protect_curated=True)` refuses to overwrite a hand-written note.

### Template Library (`templates/`)
Reference for the shape of each note type — the app does not read these at runtime.
- `templates/template-zettel.md`
- `templates/template-literature-note.md`
- `templates/template-moc.md`
