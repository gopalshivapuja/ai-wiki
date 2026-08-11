"""Idempotent, additive-only DDL applied at every boot.

This project has no migration tool by design (see CLAUDE.md). New *tables* are created by
``Base.metadata.create_all()``; new *columns and indexes on existing tables* live here.

Rules for anything added to ``PG_STATEMENTS``:

* It MUST be safe to run on every boot (``IF NOT EXISTS`` or equivalent).
* It MUST be additive. Never drop, rename, or rewrite user data here.

Adopt Alembic instead once any of these becomes true: you need a column rename/type change/drop,
you need a data backfill that a generated column cannot express, you run more than one replica
(two containers would race this at boot), or the tables grow large enough that the brief
ACCESS EXCLUSIVE lock taken by ``ADD COLUMN`` exceeds the Railway healthcheck timeout.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Cap on the text fed to to_tsvector. A tsvector cannot exceed 1MB, and a long podcast
# transcript would otherwise abort the INSERT itself — breaking ingest, not just search.
TSV_MAX_CHARS = 400_000

_TSV_EXPR = f"""
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', left(coalesce(body, ''), {TSV_MAX_CHARS})), 'B')
"""

PG_STATEMENTS: list[str] = [
    # --- crawl grouping ----------------------------------------------------
    "ALTER TABLE raw_sources ADD COLUMN IF NOT EXISTS collection varchar",
    "CREATE INDEX IF NOT EXISTS ix_raw_sources_collection ON raw_sources (collection)",
    "ALTER TABLE raw_sources ADD COLUMN IF NOT EXISTS url_hash varchar",
    # --- full-text search --------------------------------------------------
    # Generated STORED column rather than a trigger: the database guarantees consistency,
    # ADD COLUMN backfills every existing row atomically, and there is no backfill script to
    # forget. to_tsvector MUST take the explicit 'english' argument — the one-argument form
    # is only STABLE (it reads default_text_search_config) and Postgres rejects it here.
    (
        "ALTER TABLE pages ADD COLUMN IF NOT EXISTS search_tsv tsvector "
        f"GENERATED ALWAYS AS ({_TSV_EXPR}) STORED"
    ),
    # Not CONCURRENTLY: that cannot run inside a transaction block, and at this scale the
    # momentary lock during boot is irrelevant.
    "CREATE INDEX IF NOT EXISTS ix_pages_search_tsv ON pages USING GIN (search_tsv)",
    (
        "ALTER TABLE raw_sources ADD COLUMN IF NOT EXISTS search_tsv tsvector "
        f"GENERATED ALWAYS AS ({_TSV_EXPR}) STORED"
    ),
    "CREATE INDEX IF NOT EXISTS ix_raw_sources_search_tsv ON raw_sources USING GIN (search_tsv)",
    # --- job queue polling -------------------------------------------------
    "CREATE INDEX IF NOT EXISTS ix_jobs_status_created ON jobs (status, created_at)",
]


def apply_schema_ddl() -> None:
    """Run the additive DDL. No-op on any dialect other than PostgreSQL."""
    from wiki_api.database import engine

    if engine.dialect.name != "postgresql":
        logger.debug("schema_ddl: skipping, dialect is %s", engine.dialect.name)
        return

    applied = 0
    for stmt in PG_STATEMENTS:
        # One transaction per statement: a failure in a late statement must not roll back
        # the ones that already succeeded, and must not poison the connection for the rest.
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
            applied += 1
        except Exception:
            logger.exception("schema_ddl: statement failed, continuing:\n%s", stmt)
    logger.info("schema_ddl: applied %d/%d statements", applied, len(PG_STATEMENTS))
