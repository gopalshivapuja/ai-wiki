"""Page and content operations."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session
from wiki_core.utils import parse_frontmatter, parse_wikilinks, slugify

from wiki_api.database import ActivityLog, Page, RawSource, utcnow

# Page types that hold user-authored content and must never be silently overwritten by an
# automated writer (ingest, AI summarize, crawl).
CURATED_TYPES = {"zettel", "concept", "entity", "moc", "synthesis", "index", "page"}


def log_action(db: Session, action: str, summary: str) -> None:
    db.add(ActivityLog(action=action, summary=summary[:500]))
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
    return d


def source_to_dict(s: RawSource, include_body: bool = True) -> dict:
    d = {
        "slug": s.slug,
        "title": s.title,
        "type": s.source_type,
        "url": s.url,
        "collection": s.collection,
        "extra": s.extra or {},
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }
    if include_body:
        d["body"] = s.body
    return d


def get_page(db: Session, slug: str) -> Page | None:
    return db.query(Page).filter(Page.slug == slug).first()


def get_source(db: Session, slug: str) -> RawSource | None:
    return db.query(RawSource).filter(RawSource.slug == slug).first()


# --- link resolution ----------------------------------------------------------


@dataclass(frozen=True)
class SlugIndex:
    """In-memory slug/uid map, built with one query.

    Resolving links used to cost up to three SELECTs *per wikilink*, for every link of every
    page — roughly 12,000 queries to render the graph of a 500-page wiki.
    """

    by_slug: dict[str, str]
    by_uid: dict[str, str]

    def resolve(self, target: str) -> str | None:
        t = target.strip()
        if t in self.by_slug:
            return t
        if t in self.by_uid:
            return self.by_uid[t]
        return self.by_slug.get(slugify(t))


def build_slug_index(db: Session) -> SlugIndex:
    rows = db.query(Page.slug, Page.uid).all()
    return SlugIndex(
        by_slug={slug: slug for slug, _ in rows},
        by_uid={uid: slug for slug, uid in rows if uid},
    )


def resolve_slug(db: Session, target: str) -> str | None:
    """Resolve one link target. In a loop, build a SlugIndex once instead."""
    return build_slug_index(db).resolve(target)


def get_backlinks(db: Session, slug: str) -> list[dict]:
    index = build_slug_index(db)
    rows = db.query(Page.slug, Page.title, Page.page_type, Page.body).all()
    results = []
    for other_slug, title, page_type, body in rows:
        if other_slug == slug:
            continue
        for link in parse_wikilinks(body or ""):
            if index.resolve(link.target) == slug:
                results.append({"slug": other_slug, "title": title, "type": page_type})
                break
    return results


def get_outgoing_links(db: Session, page: Page) -> list[dict]:
    """Links leaving this page, flagged with whether the target exists (red links)."""
    index = build_slug_index(db)
    seen: set[str] = set()
    out = []
    for link in parse_wikilinks(page.body or ""):
        resolved = index.resolve(link.target)
        key = resolved or link.target
        if key in seen or resolved == page.slug:
            continue
        seen.add(key)
        out.append(
            {
                "target": link.target,
                "slug": resolved,
                "display": link.display or link.target,
                "exists": resolved is not None,
            }
        )
    return out


def list_pages(db: Session) -> list[Page]:
    return db.query(Page).order_by(Page.title).all()


# --- writes -------------------------------------------------------------------


def upsert_page(
    db: Session,
    slug: str,
    title: str,
    body: str,
    page_type: str = "page",
    uid: str | None = None,
    tags: list | None = None,
    source_refs: list | None = None,
    protect_curated: bool = False,
) -> Page:
    """Create or update a page.

    Automated writers pass protect_curated=True so they can never clobber a hand-written
    note that happens to share a slug.
    """
    p = get_page(db, slug)
    if p:
        if protect_curated and p.page_type in CURATED_TYPES and p.page_type != page_type:
            raise ValueError(f"Refusing to overwrite curated page '{slug}' (type '{p.page_type}')")
        p.title = title
        p.body = body
        p.page_type = page_type
        if uid:
            p.uid = uid
        if tags is not None:
            p.tags = tags
        if source_refs is not None:
            p.source_refs = source_refs
        p.updated_at = utcnow()
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


def delete_page(db: Session, slug: str) -> bool:
    p = get_page(db, slug)
    if not p:
        return False
    db.delete(p)
    db.commit()
    log_action(db, "delete", f"Deleted page '{slug}'")
    return True


def new_uid() -> str:
    return utcnow().strftime("%Y%m%d%H%M%S")


def create_zettel(db: Session, title: str, body: str | None = None) -> Page:
    slug = slugify(title)
    if not slug:
        # slugify() strips everything non-ASCII, so e.g. a CJK-only title yields "" — which
        # previously created a page at an unreachable URL.
        raise ValueError("Title must contain at least one letter or number")
    if get_page(db, slug):
        raise ValueError(f"Page already exists: {slug}")
    uid = new_uid()
    if body is None:
        body = f"""# {title}

## Context & Core Principle

*State the single atomic concept clearly.*

## Related Knowledge & Links

-
"""
    p = upsert_page(db, slug, title, body, page_type="zettel", uid=uid, tags=["zettel", "atomic"])
    log_action(db, "zettel", f"Created '{title}' ({slug})")
    return p


def import_markdown_file(db: Session, path: str, page_type: str | None = None) -> Page | None:
    fp = Path(path)
    if not fp.is_file():
        return None
    text = fp.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)

    stem = fp.stem
    # Atomic notes are named "<14-digit uid>-<slug>.md"; keep only the slug part.
    if re.match(r"^\d{14}-", stem):
        stem = stem.split("-", 1)[1]
    slug = slugify(stem)
    if not slug:
        return None

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
    collection: str | None = None,
) -> tuple[RawSource, bool]:
    """Store an immutable raw source. Returns (source, created).

    Sources are never mutated once stored. Two different URLs that slugify to the same title
    get distinct slugs via a short URL hash — previously the second one was silently dropped
    while the API still reported success.
    """
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8] if url else None

    existing = get_source(db, slug)
    if existing:
        if url_hash and existing.url_hash and existing.url_hash != url_hash:
            slug = f"{slug}-{url_hash}"
            existing = get_source(db, slug)
        if existing:
            return existing, False

    s = RawSource(
        slug=slug,
        title=title,
        body=body,
        source_type=source_type,
        url=url,
        url_hash=url_hash,
        extra=extra or {},
        collection=collection,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s, True


def delete_source(db: Session, slug: str) -> bool:
    s = get_source(db, slug)
    if not s:
        return False
    db.delete(s)
    db.commit()
    log_action(db, "delete", f"Deleted source '{slug}'")
    return True


def summary_slug(source_slug: str) -> str:
    """Slug for the literature note generated from a source.

    Namespaced so an AI summary can never land on top of the curated note about the same
    material — which is exactly what used to happen for the bundled seed data.
    """
    return f"summary-{source_slug}"[:80]
