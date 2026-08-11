"""Page and content operations."""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy.orm import Session

from wiki_api.database import ActivityLog, Page, RawSource
from wiki_core.utils import parse_frontmatter, parse_wikilinks, slugify


def log_action(db: Session, action: str, summary: str) -> None:
    db.add(ActivityLog(action=action, summary=summary))
    db.commit()


def page_to_dict(p: Page, include_body: bool = True) -> dict:
    d = {
        "slug": p.slug,
        "uid": p.uid,
        "title": p.title,
        "type": p.page_type,
        "tags": p.tags or [],
        "source_refs": p.source_refs or [],
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }
    if include_body:
        d["body"] = p.body
        d["content"] = f"---\ntitle: {p.title}\ntype: {p.page_type}\n---\n\n{p.body}"
    return d


def get_page(db: Session, slug: str) -> Page | None:
    return db.query(Page).filter(Page.slug == slug).first()


def resolve_slug(db: Session, target: str) -> str | None:
    t = target.strip()
    p = db.query(Page).filter(Page.slug == t).first()
    if p:
        return p.slug
    p = db.query(Page).filter(Page.uid == t).first()
    if p:
        return p.slug
    p = db.query(Page).filter(Page.slug == slugify(t)).first()
    return p.slug if p else None


def get_backlinks(db: Session, slug: str) -> list[dict]:
    results = []
    for p in db.query(Page).all():
        if p.slug == slug:
            continue
        for link in parse_wikilinks(p.body):
            resolved = resolve_slug(db, link.target)
            if resolved == slug:
                results.append({"slug": p.slug, "title": p.title, "type": p.page_type})
                break
    return results


def list_pages(db: Session) -> list[Page]:
    return db.query(Page).order_by(Page.title).all()


def upsert_page(
    db: Session,
    slug: str,
    title: str,
    body: str,
    page_type: str = "page",
    uid: str | None = None,
    tags: list | None = None,
    source_refs: list | None = None,
) -> Page:
    p = get_page(db, slug)
    if p:
        p.title = title
        p.body = body
        p.page_type = page_type
        if uid:
            p.uid = uid
        if tags is not None:
            p.tags = tags
        if source_refs is not None:
            p.source_refs = source_refs
        p.updated_at = datetime.utcnow()
    else:
        p = Page(
            slug=slug,
            uid=uid,
            title=title,
            body=body,
            page_type=page_type,
            tags=tags or [],
            source_refs=source_refs or [],
        )
        db.add(p)
    db.commit()
    db.refresh(p)
    return p


def create_zettel(db: Session, title: str) -> Page:
    uid = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    slug = slugify(title)
    if get_page(db, slug):
        raise ValueError(f"Page already exists: {slug}")
    body = f"""# {title}

**UID:** `{uid}`

## Context & Core Principle

*State the single atomic concept clearly.*

## Related Knowledge & Links

- [[moc-llm-architectures|LLM Architectures MOC]]
"""
    p = upsert_page(db, slug, title, body, page_type="zettel", uid=uid, tags=["zettel", "atomic"])
    log_action(db, "zettel", f"Created '{title}' ({slug})")
    return p


def import_markdown_file(db: Session, path: str, page_type: str | None = None) -> Page | None:
    from pathlib import Path

    fp = Path(path)
    if not fp.exists():
        return None
    text = fp.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    slug = slugify(fp.stem) if fp.parent.name == "atomic" and re.match(r"^\d{14}-", fp.stem) else fp.stem
    if re.match(r"^\d{14}-", fp.stem):
        slug = fp.stem.split("-", 1)[1]
    title = fm.get("title") or fp.stem.replace("-", " ").title()
    m = re.search(r"^#\s+(.*)$", body, re.MULTILINE)
    if m:
        title = m.group(1).strip()
    ptype = page_type or fm.get("type", "page")
    return upsert_page(
        db,
        slug=slug,
        title=str(title),
        body=body.strip(),
        page_type=str(ptype),
        uid=fm.get("uid"),
        tags=fm.get("tags", []),
        source_refs=fm.get("sources", []),
    )


def upsert_source(
    db: Session,
    slug: str,
    title: str,
    body: str,
    source_type: str,
    url: str | None = None,
    extra: dict | None = None,
) -> RawSource:
    s = db.query(RawSource).filter(RawSource.slug == slug).first()
    if s:
        return s  # immutable
    s = RawSource(slug=slug, title=title, body=body, source_type=source_type, url=url, extra=extra or {})
    db.add(s)
    db.commit()
    db.refresh(s)
    return s
