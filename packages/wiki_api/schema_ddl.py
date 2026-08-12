"""Idempotent, additive-only DDL applied at every boot.

There is no migration tool by design. New *tables* come from `Base.metadata.create_all()`;
things SQLAlchemy cannot express — chiefly the generated `tsvector` column — live here.

Rules for anything added below:

* It MUST be safe to run on every boot (`IF NOT EXISTS` or equivalent).
* It MUST be additive. Never drop, rename, or rewrite user data here.

Adopt Alembic when you need a column rename/type change/drop, a data backfill a generated
column cannot express, more than one steady-state replica, or tables large enough that the
brief ACCESS EXCLUSIVE lock from `ADD COLUMN` outlasts the Railway healthcheck.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

# A tsvector cannot exceed 1MB. An hour-long transcript would otherwise abort the INSERT
# itself, breaking ingest rather than just search.
TSV_MAX_CHARS = 400_000

# to_tsvector MUST take the explicit 'english' argument: the one-argument form reads
# default_text_search_config, is only STABLE, and Postgres rejects it in a generated column.
_TSV_EXPR = f"""
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', left(coalesce(body, ''), {TSV_MAX_CHARS})), 'B')
"""

PG_STATEMENTS: list[str] = [
    # Full-text search. A generated STORED column rather than a trigger: the database keeps
    # it consistent, ADD COLUMN backfills every existing row atomically, and there is no
    # backfill script to forget.
    (
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS search_tsv tsvector "
        f"GENERATED ALWAYS AS ({_TSV_EXPR}) STORED"
    ),
    # Not CONCURRENTLY: that cannot run inside a transaction block, and at this scale the
    # momentary lock during boot is irrelevant.
    "CREATE INDEX IF NOT EXISTS ix_documents_search_tsv ON documents USING GIN (search_tsv)",
    # Tag filtering and the tag cloud, without scanning every body.
    "CREATE INDEX IF NOT EXISTS ix_documents_tags ON documents USING GIN (tags jsonb_path_ops)",
    "CREATE INDEX IF NOT EXISTS ix_jobs_status_created ON jobs (status, created_at)",
]


def apply_schema_ddl() -> None:
    """Run the additive DDL. Raises if a statement fails.

    Failures are fatal on purpose: a missing tsvector column means search is broken, and a
    boot that logs a warning and serves a subtly broken app is worse than one that stops.
    """
    from wiki_api.database import engine

    for stmt in PG_STATEMENTS:
        # One transaction per statement so a later failure cannot roll back earlier ones.
        with engine.begin() as conn:
            conn.execute(text(stmt))
    logger.info("schema_ddl: applied %d/%d statements", len(PG_STATEMENTS), len(PG_STATEMENTS))
