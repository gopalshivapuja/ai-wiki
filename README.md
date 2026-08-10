# ai-wiki

A personal AI knowledge base built on [Andrej Karpathy's LLM Wiki pattern](llm-wiki.md) with a
Zettelkasten structure: raw sources stay immutable, an LLM agent compiles them into interlinked atomic
notes, and the wiki becomes a compounding artifact rather than something re-derived on every question.

## Current state

A markdown knowledge base plus a Python CLI:

| Path | Contents |
| --- | --- |
| `sources/` | Immutable raw sources (web, PDF, YouTube, documents, assets) |
| `wiki/` | LLM-compiled notes: `atomic/`, `concepts/`, `entities/`, `sources/`, `syntheses/` |
| `wiki/index.md` | Catalogue of every page |
| `wiki/log.md` | Chronological record of ingests, queries, and maintenance |
| `templates/` | Note templates for zettels, literature notes, and MOCs |
| `tools/wiki.py` | CLI for ingest, search, RAG query, lint, and stats |
| `AGENTS.md` | The schema that tells an AI agent how to maintain this repo |

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env          # add your OPENROUTER_API_KEY

python3 tools/wiki.py stats                       # graph metrics
python3 tools/wiki.py search "attention"          # local search
python3 tools/wiki.py ingest-arxiv 1706.03762     # add a paper
python3 tools/wiki.py ask                         # see AGENTS.md for the full command list
```

The full command surface is documented in [`AGENTS.md`](AGENTS.md).

## Where this is going

There is a complete plan in [`docs/`](docs/README.md) to turn this into a deployed, searchable,
authenticated wiki with a web interface, a knowledge-graph view, and CI/CD to Railway.

Start with [the plan index](docs/README.md), or jump to:

- [What is broken today](docs/00-audit-findings.md) — 37 findings, with reproducible evidence
- [Functional requirements](docs/01-functional-requirements.md) and
  [non-functional requirements](docs/02-non-functional-requirements.md)
- [Target architecture](docs/03-architecture.md) — including the search and graph design
- [Implementation roadmap](docs/04-implementation-roadmap.md) — phases, dependencies, exit criteria
- [Open decisions](docs/06-open-decisions.md) — the choices that need your input

Known issues being addressed, in case they bite you before the fixes land: some wikilinks are wrapped in
backticks and therefore do not render as links, atomic note filenames carry a 14-digit timestamp prefix,
`lint` always exits 0 so it cannot gate CI, and YouTube ingestion is broken against the currently
installed `youtube-transcript-api`. All are documented in
[the audit](docs/00-audit-findings.md).
