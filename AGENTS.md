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
- Use standard Obsidian-style **wikilinks**: `[[note-title]]` or `[[note-title|Display Title]]`.
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

The wiki connects to OpenRouter models configured in `.env`:
- `OPENROUTER_API_KEY`: Private API key (stored in `.env`, git-ignored).
- `OPENROUTER_MODEL`: Selected model (e.g. `nvidia/nemotron-4-340b-instruct`, `meta-llama/llama-3.3-70b-instruct:free`, `qwen/qwen-2.5-coder-32b-instruct:free`).

---

## 4. CLI Tooling & Workflow Integration

Use `python3 tools/wiki.py` for automated operations:

- **LLM Grounded RAG Query**: `python3 tools/wiki.py query "<question>"`
- **LLM AI Source Summarize**: `python3 tools/wiki.py ai-summarize "<PATH_TO_SOURCE>"`
- **LLM AI Graph Audit**: `python3 tools/wiki.py ai-lint`
- **New Zettel**: `python3 tools/wiki.py new-zettel "<Concept Title>"`
- **Hybrid Local Search**: `python3 tools/wiki.py search "<query>"`
- **ArXiv Paper Ingest**: `python3 tools/wiki.py ingest-arxiv "<arXiv_ID_or_URL>"`
- **YouTube Ingest**: `python3 tools/wiki.py ingest-youtube "<URL>"`
- **Web Ingest**: `python3 tools/wiki.py ingest-web "<URL>"`
- **PDF Ingest**: `python3 tools/wiki.py ingest-pdf "<PATH_TO_PDF>"`
- **Graph Statistics**: `python3 tools/wiki.py stats`
- **Auto-Link Scan**: `python3 tools/wiki.py auto-link`
- **Lint Check**: `python3 tools/wiki.py lint`
- **Log Event**: `python3 tools/wiki.py log ingest "Processed article X"`

### Template Library (`templates/`)
- `templates/template-zettel.md`
- `templates/template-literature-note.md`
- `templates/template-moc.md`
