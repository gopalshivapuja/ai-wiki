"""Seed database from bundled markdown files (first run only)."""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from wiki_api.database import Page
from wiki_api.services.content import import_markdown_file, log_action, upsert_source

BASE = Path(os.environ.get("WIKI_SEED_DIR", Path(__file__).resolve().parents[3]))


def _json_safe(obj):
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj


def seed_if_empty(db: Session) -> int:
    if db.query(Page).count() > 0:
        return 0

    count = 0
    wiki = BASE / "wiki"
    sources = BASE / "sources"

    type_map = {
        "atomic": "zettel",
        "concepts": "concept",
        "entities": "entity",
        "sources": "literature",
        "syntheses": None,
    }

    if wiki.exists():
        for sub, ptype in type_map.items():
            d = wiki / sub
            if not d.exists():
                continue
            for md in d.glob("*.md"):
                actual_type = ptype
                if sub == "syntheses":
                    actual_type = "moc" if md.stem.startswith("moc-") else "synthesis"
                import_markdown_file(db, str(md), page_type=actual_type)
                count += 1

        index = wiki / "index.md"
        if index.exists():
            import_markdown_file(db, str(index), page_type="index")

    if sources.exists():
        for md in sources.rglob("*.md"):
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
                extra=_json_safe({k: v for k, v in fm.items() if k not in ("title", "type", "url")}),
            )

    if count:
        log_action(db, "seed", f"Imported {count} wiki pages from seed data")
    return count
