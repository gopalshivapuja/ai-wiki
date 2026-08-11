"""PostgreSQL full-text search over pages and raw sources.

Backed by the generated `search_tsv` columns and GIN indexes created in schema_ddl.py.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

# Curated pages outrank raw ingested text when both match.
SOURCE_WEIGHT = 0.85

# ts_headline re-parses the document and cannot use the index, so it runs in an outer query
# over only the rows that survived LIMIT, and never over more than this much text.
HEADLINE_MAX_CHARS = 20_000

_HEADLINE_OPTS = "MaxFragments=2,FragmentDelimiter= … ,MinWords=6,MaxWords=22,StartSel=«,StopSel=»"

_PAGES_ARM = """
    SELECT 'page'::text AS kind, p.slug, p.title, p.page_type AS type,
           ts_rank_cd(p.search_tsv, q.tsq) AS score
    FROM pages p, q
    WHERE p.search_tsv @@ q.tsq
"""

_SOURCES_ARM = """
    SELECT 'source'::text AS kind, s.slug, s.title, s.source_type AS type,
           ts_rank_cd(s.search_tsv, q.tsq) * :source_weight AS score
    FROM raw_sources s, q
    WHERE s.search_tsv @@ q.tsq
"""

# StartSel/StopSel use guillemets rather than HTML tags: snippets come from ingested web
# content and are rendered as text by the frontend.
_OUTER = """
WITH q AS (SELECT websearch_to_tsquery('english', :query) AS tsq),
hits AS (
{arms}
    ORDER BY score DESC, title ASC
    LIMIT :limit
)
SELECT h.kind, h.slug, h.title, h.type, h.score,
       ts_headline('english',
                   left(coalesce(CASE WHEN h.kind = 'page' THEN p.body ELSE s.body END, ''),
                        :headline_chars),
                   q.tsq, '{opts}') AS snippet
-- CROSS JOIN, not a comma: with "FROM hits h, q LEFT JOIN ..." the join binds to q alone
-- and h is not in scope for the ON clause.
FROM hits h
CROSS JOIN q
LEFT JOIN pages p ON h.kind = 'page' AND p.slug = h.slug
LEFT JOIN raw_sources s ON h.kind = 'source' AND s.slug = h.slug
ORDER BY h.score DESC, h.title ASC
"""


def search_postgres(
    db: Session, query: str, top_k: int = 12, include_sources: bool = True
) -> list[dict]:
    if not query.strip():
        return []

    arms = _PAGES_ARM + ("\n    UNION ALL\n" + _SOURCES_ARM if include_sources else "")
    sql = text(_OUTER.format(arms=arms, opts=_HEADLINE_OPTS))

    params: dict = {
        "query": query,
        "limit": top_k,
        "headline_chars": HEADLINE_MAX_CHARS,
    }
    if include_sources:
        params["source_weight"] = SOURCE_WEIGHT

    rows = db.execute(sql, params).mappings().all()
    return [
        {
            "score": round(float(r["score"]), 4),
            "slug": r["slug"],
            "title": r["title"],
            "snippet": (r["snippet"] or "").replace("\n", " ").strip(),
            "type": r["type"],
            "kind": r["kind"],
        }
        for r in rows
    ]
