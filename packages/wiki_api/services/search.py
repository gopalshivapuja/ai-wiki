"""PostgreSQL full-text search over documents.

Backed by the generated `search_tsv` column and GIN index created in schema_ddl.py. There is
deliberately no second implementation: a fallback engine masked failures in this one and
ranked differently, so passing tests against it proved nothing about production.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

# Notes outrank raw captured text when both match.
SOURCE_WEIGHT = 0.85

# ts_headline re-parses the document and cannot use the index, so it runs only over the rows
# that survived LIMIT, and never over more than this much text.
HEADLINE_MAX_CHARS = 20_000

# Guillemets, not <b>: snippets come from ingested web content and are rendered as text.
_HEADLINE_OPTS = "MaxFragments=2,FragmentDelimiter= … ,MinWords=6,MaxWords=22,StartSel=«,StopSel=»"

_SQL = text(
    f"""
WITH q AS (
    SELECT CASE WHEN :match_all
        -- Search box: every term must match, so results are precise.
        THEN websearch_to_tsquery('english', :query)
        -- Retrieval for RAG: any term may match, ranked by how many and how close.
        -- A natural question ("why does multi-head attention help?") shares only a couple
        -- of words with the right note, so requiring all of them retrieves nothing at all.
        -- to_tsquery of NULL is NULL and simply matches no rows, so an all-stopword
        -- question degrades quietly instead of raising.
        ELSE to_tsquery(
            'english',
            (SELECT string_agg(lexeme, ' | ') FROM unnest(to_tsvector('english', :query)))
        )
    END AS tsq
),
hits AS (
    SELECT d.id, d.slug, d.title, d.doc_class, d.subtype,
           ts_rank_cd(d.search_tsv, q.tsq)
             * CASE WHEN d.doc_class = 'source' THEN :source_weight ELSE 1 END AS score
    FROM documents d, q
    WHERE d.search_tsv @@ q.tsq
      AND (:include_sources OR d.doc_class <> 'source')
    ORDER BY score DESC, d.title ASC
    LIMIT :limit
)
SELECT h.slug, h.title, h.doc_class, h.subtype, h.score,
       ts_headline('english', left(coalesce(d.body, ''), :headline_chars), q.tsq,
                   '{_HEADLINE_OPTS}') AS snippet
FROM hits h
CROSS JOIN q
JOIN documents d ON d.id = h.id
ORDER BY h.score DESC, h.title ASC
"""
)


def search(
    db: Session,
    query: str,
    top_k: int = 12,
    include_sources: bool = True,
    match_all: bool = True,
) -> list[dict]:
    """Ranked hits: {score, slug, title, snippet, type, doc_class}.

    `match_all=False` loosens the query to "any term", which is what retrieval for the AI
    needs — a question is not a search phrase.
    """
    if not query.strip():
        return []

    rows = (
        db.execute(
            _SQL,
            {
                "query": query,
                "limit": top_k,
                "headline_chars": HEADLINE_MAX_CHARS,
                "source_weight": SOURCE_WEIGHT,
                "include_sources": include_sources,
                "match_all": match_all,
            },
        )
        .mappings()
        .all()
    )

    return [
        {
            "score": round(float(r["score"]), 4),
            "slug": r["slug"],
            "title": r["title"],
            "snippet": (r["snippet"] or "").replace("\n", " ").strip(),
            "type": r["subtype"],
            "doc_class": r["doc_class"],
        }
        for r in rows
    ]
