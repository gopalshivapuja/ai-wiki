"""BM25 search over database pages."""

from __future__ import annotations

import math
import re

from sqlalchemy.orm import Session

from wiki_api.database import Page, RawSource


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in re.findall(r"\w+", text) if len(t) > 2]


def search(db: Session, query: str, top_k: int = 12) -> list[dict]:
    query_terms = _tokenize(query)
    if not query_terms:
        return []

    docs: list[tuple[str, str, str, str]] = []
    for p in db.query(Page).all():
        docs.append((p.slug, p.title, p.body, p.page_type))
    for s in db.query(RawSource).all():
        docs.append((s.slug, s.title, s.body, "source"))

    doc_tokens = {i: _tokenize(f"{t} {b}") for i, (_, t, b, _) in enumerate(docs)}
    doc_freqs: dict[str, int] = {}
    for tokens in doc_tokens.values():
        for token in set(tokens):
            doc_freqs[token] = doc_freqs.get(token, 0) + 1

    n = len(docs)
    scores: list[tuple[float, int]] = []

    for i, (_, title, body, _) in enumerate(docs):
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
            scores.append((score, i))

    scores.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, i in scores[:top_k]:
        slug, title, body, ptype = docs[i]
        snippet = ""
        for q in query_terms:
            idx = body.lower().find(q)
            if idx != -1:
                snippet = body[max(0, idx - 60) : idx + 120].replace("\n", " ").strip()
                break
        results.append(
            {"score": score, "slug": slug, "title": title, "snippet": snippet, "type": ptype}
        )
    return results
