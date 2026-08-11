"""Seed database from bundled markdown files (first run only)."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from wiki_api.database import Page, RawSource
from wiki_api.services.content import import_markdown_file, log_action, upsert_source

logger = logging.getLogger(__name__)


def _default_base() -> Path:
    """Where the bundled wiki/ and sources/ markdown lives.

    WIKI_SEED_DIR wins and is what the Docker image sets. The parents[3] fallback only
    resolves correctly for an editable/in-repo install: after a plain `pip install .` the
    module lives in site-packages and that path points at the Python installation, not the
    repo — which is why production previously seeded nothing at all, silently.
    """
    env = os.environ.get("WIKI_SEED_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3]


BASE = _default_base()


def _json_safe(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj


def seed_if_empty(db: Session) -> int:
    """Import bundled markdown when the database has no content yet.

    Gated on pages *and* sources both being empty, so a database that somehow has pages but
    no sources (or the reverse) still gets completed.
    """
    if db.query(Page).count() > 0 and db.query(RawSource).count() > 0:
        return 0

    base = _default_base()
    wiki = base / "wiki"
    sources = base / "sources"

    if not wiki.is_dir() and not sources.is_dir():
        logger.error(
            "Seed data not found under %s (wiki/ and sources/ are both missing). "
            "The wiki will start empty. Set WIKI_SEED_DIR to the directory containing them.",
            base,
        )
        return 0

    count = 0

    type_map = {
        "atomic": "zettel",
        "concepts": "concept",
        "entities": "entity",
        "sources": "literature",
        "syntheses": None,
    }

    if wiki.is_dir():
        for sub, ptype in type_map.items():
            d = wiki / sub
            if not d.is_dir():
                continue
            for md in sorted(d.glob("*.md")):
                actual_type = ptype
                if sub == "syntheses":
                    actual_type = "moc" if md.stem.startswith("moc-") else "synthesis"
                if import_markdown_file(db, str(md), page_type=actual_type):
                    count += 1

        index = wiki / "index.md"
        if index.is_file() and import_markdown_file(db, str(index), page_type="index"):
            count += 1

    source_count = 0
    if sources.is_dir():
        for md in sorted(sources.rglob("*.md")):
            if md.parent.name == "assets":
                continue
            text = md.read_text(encoding="utf-8")
            from wiki_core.utils import parse_frontmatter

            fm, body = parse_frontmatter(text)
            title = fm.get("title", md.stem)
            upsert_source(
                db,
                slug=md.stem,
                title=str(title),
                body=body.strip(),
                source_type=str(fm.get("type", md.parent.name)),
                url=fm.get("url"),
                extra=_json_safe(
                    {k: v for k, v in fm.items() if k not in ("title", "type", "url")}
                ),
            )
            source_count += 1

    total = count + source_count
    if total:
        log_action(db, "seed", f"Imported {count} wiki pages and {source_count} sources")
        logger.info("Seeded %d pages and %d sources from %s", count, source_count, base)
    else:
        logger.warning("Seed directory %s contained no markdown files", base)
    return total
