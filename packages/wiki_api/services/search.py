"""Search entry point. Dispatches on the database dialect.

Callers only ever use search(); which backend answered is an implementation detail.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from wiki_api.services.search_bm25 import search_bm25
from wiki_api.services.search_pg import search_postgres

logger = logging.getLogger(__name__)


def search(db: Session, query: str, top_k: int = 12, include_sources: bool = True) -> list[dict]:
    """Return ranked hits: {score, slug, title, snippet, type, kind}.

    `kind` is "page" or "source" and decides where the frontend links — pages and sources
    are separate namespaces whose slugs can legitimately collide.
    """
    if db.get_bind().dialect.name == "postgresql":
        try:
            return search_postgres(db, query, top_k, include_sources)
        except Exception:
            # Most likely a database that predates the tsvector columns. Degrade to a working
            # search rather than a 500; schema_ddl.py will have added them by the next boot.
            logger.warning("Postgres FTS failed, falling back to BM25", exc_info=True)
            db.rollback()
    return search_bm25(db, query, top_k, include_sources)
