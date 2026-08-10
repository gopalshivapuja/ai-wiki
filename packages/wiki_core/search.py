"""BM25-style lexical search."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from wiki_core.config import BASE_DIR, SOURCES_DIR, WIKI_DIR
from wiki_core.frontmatter import extract_title
from wiki_core.graph import canonical_slug


@dataclass
class SearchResult:
    score: float
    slug: str
    title: str
    path: str
    snippet: str
    page_type: str = ""


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in re.findall(r"\w+", text) if len(t) > 2]


def search(query: str, top_k: int = 10, include_sources: bool = True) -> list[SearchResult]:
    query_terms = _tokenize(query)
    if not query_terms:
        return []

    files: list[Path] = list(WIKI_DIR.rglob("*.md"))
    if include_sources:
        files += list(SOURCES_DIR.rglob("*.md"))

    doc_freqs: dict[str, int] = {}
    doc_tokens: dict[Path, list[str]] = {}
    doc_titles: dict[Path, str] = {}

    for f in files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        tokens = _tokenize(text)
        doc_tokens[f] = tokens
        doc_titles[f] = extract_title(text, f.stem)
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
    results: list[SearchResult] = []

    for score, f in scores[:top_k]:
        text = f.read_text(encoding="utf-8", errors="ignore")
        snippet = ""
        for q_term in query_terms:
            idx = text.lower().find(q_term)
            if idx != -1:
                start = max(0, idx - 60)
                end = min(len(text), idx + 120)
                snippet = text[start:end].replace("\n", " ").strip()
                break
        rel = f.relative_to(BASE_DIR)
        slug = canonical_slug(f) if "wiki" in str(rel) else f.stem
        page_type = "source" if "sources/" in str(rel) and "/wiki/" not in str(rel) else "wiki"
        if "wiki/atomic" in str(rel):
            page_type = "zettel"
        elif "wiki/concepts" in str(rel):
            page_type = "concept"
        elif "wiki/entities" in str(rel):
            page_type = "entity"
        elif "wiki/sources" in str(rel):
            page_type = "literature"
        elif "wiki/syntheses" in str(rel):
            page_type = "moc" if f.stem.startswith("moc-") else "synthesis"
        results.append(
            SearchResult(
                score=score,
                slug=slug,
                title=doc_titles[f],
                path=str(rel),
                snippet=snippet,
                page_type=page_type,
            )
        )
    return results
