"""Pure-Python BM25 search. Used on SQLite (tests, local dev) and as the Postgres fallback.

This loads and tokenizes the whole corpus on every call. That is fine for a few hundred
pages; Postgres deployments use the indexed implementation in search_pg.py instead.
"""

from __future__ import annotations

import math
import re

from sqlalchemy.orm import Session

from wiki_api.database import Page, RawSource

# Sources rank slightly below curated pages when both match, mirroring search_pg.py.
SOURCE_WEIGHT = 0.85


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in re.findall(r"\w+", text) if len(t) > 2]


def search_bm25(
    db: Session, query: str, top_k: int = 12, include_sources: bool = True
) -> list[dict]:
    query_terms = _tokenize(query)
    if not query_terms:
        return []

    # (slug, title, body, type, kind)
    docs: list[tuple[str, str, str, str, str]] = [
        (p.slug, p.title, p.body or "", p.page_type, "page") for p in db.query(Page).all()
    ]
    if include_sources:
        docs += [
            (s.slug, s.title, s.body or "", s.source_type, "source")
            for s in db.query(RawSource).all()
        ]
    if not docs:
        return []

    doc_tokens = {i: _tokenize(f"{t} {b}") for i, (_, t, b, _, _) in enumerate(docs)}
    doc_freqs: dict[str, int] = {}
    for tokens in doc_tokens.values():
        for token in set(tokens):
            doc_freqs[token] = doc_freqs.get(token, 0) + 1

    n = len(docs)
    scores: list[tuple[float, int]] = []

    for i, (_, _, _, _, kind) in enumerate(docs):
        tokens = doc_tokens[i]
        if not tokens:
            continue
        score = 0.0
        doc_len = len(tokens)
        for q in query_terms:
            tf = tokens.count(q)
            if tf > 0:
                df = doc_freqs.get(q, 1)
                idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
                norm_tf = (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * (doc_len / 300.0)))
                score += idf * norm_tf
        if score > 0:
            if kind == "source":
                score *= SOURCE_WEIGHT
            scores.append((score, i))

    scores.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, i in scores[:top_k]:
        slug, title, body, ptype, kind = docs[i]
        snippet = ""
        lowered = body.lower()
        for q in query_terms:
            idx = lowered.find(q)
            if idx != -1:
                snippet = body[max(0, idx - 60) : idx + 120].replace("\n", " ").strip()
                break
        results.append(
            {
                "score": round(score, 4),
                "slug": slug,
                "title": title,
                "snippet": snippet,
                "type": ptype,
                "kind": kind,
            }
        )
    return results
