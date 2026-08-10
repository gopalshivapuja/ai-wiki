"""RAG query over wiki."""

from __future__ import annotations

import math
import re
from pathlib import Path

from wiki_core.config import WIKI_DIR, ensure_directories
from wiki_core.llm import call_openrouter
from wiki_core.log import append_log


def _bm25_top_docs(question: str, top_k: int = 5) -> list[Path]:
    query_terms = [t.lower() for t in re.findall(r"\w+", question) if len(t) > 2]
    files = list(WIKI_DIR.rglob("*.md"))
    doc_freqs: dict[str, int] = {}
    doc_tokens: dict[Path, list[str]] = {}

    for f in files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        tokens = [t.lower() for t in re.findall(r"\w+", text)]
        doc_tokens[f] = tokens
        for token in set(tokens):
            doc_freqs[token] = doc_freqs.get(token, 0) + 1

    n = len(files)
    scores: list[tuple[float, Path]] = []
    for f in files:
        tokens = doc_tokens[f]
        if not tokens:
            continue
        score = 0.0
        doc_len = len(tokens)
        for q_term in query_terms:
            tf = tokens.count(q_term)
            if tf > 0:
                df = doc_freqs.get(q_term, 1)
                idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
                norm_tf = (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * (doc_len / 300.0)))
                score += idf * norm_tf
        if score > 0:
            scores.append((score, f))
    scores.sort(key=lambda x: x[0], reverse=True)
    top = [f for _, f in scores[:top_k]]
    return top or files[:3]


def query_wiki(question: str, verbose: bool = True) -> str:
    ensure_directories()
    top_docs = _bm25_top_docs(question)
    from wiki_core.config import BASE_DIR

    context_blocks = []
    for f in top_docs:
        rel = f.relative_to(BASE_DIR)
        context_blocks.append(
            f"--- FILE: {rel} (slug: {f.stem}) ---\n{f.read_text(encoding='utf-8')}\n--- END ---"
        )
    context_str = "\n\n".join(context_blocks)
    system_prompt = (
        "You are an expert AI Knowledge Base Assistant maintaining an LLM Wiki with Zettelkasten architecture.\n"
        "Answer using ONLY the provided context. Cite sources with wikilinks [[slug|Title]].\n"
        "Use clear markdown formatting."
    )
    user_prompt = f"QUESTION: {question}\n\nCONTEXT:\n{context_str}\n\nANSWER:"
    answer = call_openrouter(user_prompt, system_prompt, verbose=verbose)
    append_log("query", f"LLM RAG Query: '{question}'")
    return answer


def ai_summarize_source(source_path: str) -> str:
    from pathlib import Path

    from wiki_core.config import WIKI_DIR, ensure_directories
    from wiki_core.log import append_log
    from wiki_core.slug import slugify

    ensure_directories()
    path = Path(source_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Source not found: {path}")

    text = path.read_text(encoding="utf-8", errors="ignore")
    system_prompt = (
        "You are an expert LLM Knowledge Base Summarizer.\n"
        "Generate a structured Literature Note with:\n"
        "1. Executive Summary & Core Claims\n"
        "2. Key Takeaways (numbered)\n"
        "3. Proposed Atomic Zettels\n"
        "4. Suggested Wikilinks [[slug|Title]]"
    )
    summary = call_openrouter(
        f"SOURCE: {path.name}\n\n{text[:8000]}\n\nLITERATURE NOTE:",
        system_prompt,
    )
    today = __import__("datetime").date.today().isoformat()
    slug = slugify(path.stem)
    uid = __import__("datetime").datetime.now().strftime("%Y%m%d%H%M%S")
    target = WIKI_DIR / "sources" / f"{slug}.md"
    content = f"""---
uid: "{uid}"
title: "Source Summary: {path.stem}"
type: literature
created: {today}
updated: {today}
tags: [source-summary, ai-generated]
sources:
  - "sources/{path.parent.name}/{path.name}"
---

# Source Summary: {path.stem}

**Original Source:** `{path.name}`
**Ingested:** {today}

---

{summary}
"""
    target.write_text(content, encoding="utf-8")
    append_log("ai-summarize", f"Generated literature note for '{path.name}'")
    return str(target)


def ai_lint_wiki(verbose: bool = True) -> str:
    from wiki_core.config import ATOMIC_DIR, INDEX_FILE, ensure_directories

    ensure_directories()
    index_text = INDEX_FILE.read_text(encoding="utf-8") if INDEX_FILE.exists() else ""
    atomic = [f.stem for f in ATOMIC_DIR.glob("*.md")] if ATOMIC_DIR.exists() else []
    system_prompt = (
        "You are a Knowledge Base Graph Auditor. Identify gaps, MOC recommendations, and ingestion suggestions."
    )
    report = call_openrouter(
        f"INDEX:\n{index_text}\n\nATOMIC ZETTELS:\n{atomic}\n\nAUDIT:",
        system_prompt,
        verbose=verbose,
    )
    append_log("ai-lint", "Executed LLM graph audit")
    return report
