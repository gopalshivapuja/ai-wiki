"""API routes — all data from PostgreSQL."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from wiki_core.utils import slugify

from wiki_api.auth import get_current_user, get_optional_user
from wiki_api.database import ActivityLog, Page, RawSource, User, get_db
from wiki_api.services.content import (
    build_slug_index,
    create_zettel,
    delete_page,
    delete_source,
    get_backlinks,
    get_outgoing_links,
    get_page,
    get_source,
    list_pages,
    page_to_dict,
    source_to_dict,
    summary_slug,
    upsert_page,
)
from wiki_api.services.fetch import FetchError
from wiki_api.services.graph import build_graph, stats
from wiki_api.services.ingest import ai_query
from wiki_api.services.search import search

logger = logging.getLogger(__name__)
router = APIRouter()

PAGE_TYPES = ("zettel", "concept", "entity", "moc", "synthesis", "literature", "page", "index")


class QueryBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class ZettelBody(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str | None = Field(default=None, max_length=1_000_000)


class PageUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    body: str | None = Field(default=None, max_length=1_000_000)
    tags: list[str] | None = None
    type: str | None = None


def _fail(exc: Exception, default: str) -> HTTPException:
    """Map service errors to honest status codes.

    A blanket 500 used to turn 'source not found' into a server error and leak upstream URLs
    and internal network errors to the client.
    """
    if isinstance(exc, (ValueError, FetchError)):
        return HTTPException(400, str(exc))
    logger.exception(default)
    return HTTPException(500, default)


# --- read ---------------------------------------------------------------------


@router.get("/search")
def api_search(
    q: str = Query(...),
    limit: int = Query(12, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    # Raw sources are behind auth, so anonymous search must not surface their text either.
    return {"results": search(db, q, top_k=limit, include_sources=user is not None)}


@router.get("/pages")
def api_pages(
    type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    pages = list_pages(db)
    out = []
    for p in pages:
        tags = p.tags or []
        if type and p.page_type != type:
            continue
        if tag and tag not in tags:
            continue
        out.append({"slug": p.slug, "title": p.title, "type": p.page_type, "tags": tags})
    return {"pages": out}


@router.get("/tags")
def api_tags(db: Session = Depends(get_db)):
    counts: dict[str, int] = {}
    for (tags,) in db.query(Page.tags).all():
        for t in tags or []:
            counts[t] = counts.get(t, 0) + 1
    return {
        "tags": [{"tag": t, "count": c} for t, c in sorted(counts.items(), key=lambda x: -x[1])]
    }


@router.get("/pages/{slug}")
def api_page(slug: str, db: Session = Depends(get_db)):
    p = get_page(db, slug)
    if not p:
        # A source with this slug may exist — tell the client where to look instead of 404ing blind.
        if get_source(db, slug):
            raise HTTPException(
                404, detail={"message": "No page with that slug", "source_slug": slug}
            )
        raise HTTPException(404, "Page not found")
    d = page_to_dict(p)
    d["backlinks"] = get_backlinks(db, slug)
    d["links"] = get_outgoing_links(db, p)
    d["summary_of"] = p.source_refs or []
    return d


@router.get("/sources")
def api_sources(
    collection: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(RawSource).order_by(RawSource.created_at.desc())
    if collection:
        q = q.filter(RawSource.collection == collection)
    sources = q.all()
    index = build_slug_index(db)
    return {
        "sources": [
            {
                "slug": s.slug,
                "title": s.title,
                "type": s.source_type,
                "url": s.url,
                "collection": s.collection,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                # Lets the UI show "Summarize" or "View note" per source.
                "summary_slug": index.resolve(summary_slug(s.slug)),
            }
            for s in sources
        ]
    }


@router.get("/sources/{slug}")
def api_source(slug: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    s = get_source(db, slug)
    if not s:
        raise HTTPException(404, "Source not found")
    d = source_to_dict(s)
    index = build_slug_index(db)
    d["summary_slug"] = index.resolve(summary_slug(s.slug))
    return d


@router.get("/graph")
def api_graph(db: Session = Depends(get_db)):
    return build_graph(db)


@router.get("/stats")
def api_stats(db: Session = Depends(get_db)):
    return stats(db)


@router.get("/resolve")
def api_resolve(target: str = Query(...), db: Session = Depends(get_db)):
    resolved = build_slug_index(db).resolve(target)
    return {"target": target, "slug": resolved, "exists": resolved is not None}


@router.get("/log")
def api_log(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
):
    entries = db.query(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(limit).all()
    return {
        "entries": [
            {
                "action": e.action,
                "summary": e.summary,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ]
    }


# --- write --------------------------------------------------------------------


@router.post("/zettels", status_code=201)
def api_zettel(
    body: ZettelBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    try:
        p = create_zettel(db, body.title, body.body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"slug": p.slug, "title": p.title}


@router.put("/pages/{slug}")
def api_update_page(
    slug: str,
    body: PageUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    p = get_page(db, slug)
    if not p:
        raise HTTPException(404, "Page not found")
    if body.type and body.type not in PAGE_TYPES:
        raise HTTPException(400, f"Unknown page type '{body.type}'")

    updated = upsert_page(
        db,
        slug=slug,
        title=(body.title or p.title).strip(),
        body=p.body if body.body is None else body.body,
        page_type=body.type or p.page_type,
        uid=p.uid,
        tags=p.tags if body.tags is None else [t.strip() for t in body.tags if t.strip()],
    )
    return page_to_dict(updated)


@router.delete("/pages/{slug}", status_code=204)
def api_delete_page(
    slug: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    if not delete_page(db, slug):
        raise HTTPException(404, "Page not found")


@router.delete("/sources/{slug}", status_code=204)
def api_delete_source(
    slug: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    if not delete_source(db, slug):
        raise HTTPException(404, "Source not found")


@router.post("/pages/{slug}/rename")
def api_rename_page(
    slug: str,
    body: ZettelBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Rename a page's title, keeping its slug so existing wikilinks keep resolving."""
    p = get_page(db, slug)
    if not p:
        raise HTTPException(404, "Page not found")
    if not slugify(body.title):
        raise HTTPException(400, "Title must contain at least one letter or number")
    p.title = body.title.strip()
    db.commit()
    db.refresh(p)
    return page_to_dict(p)


# --- LLM ----------------------------------------------------------------------


@router.get("/llm/models")
def api_models():
    from wiki_core.llm import model_status

    return model_status()


@router.post("/llm/query")
def api_query(
    body: QueryBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    try:
        return ai_query(db, body.question)
    except Exception as exc:
        raise _fail(exc, "The model could not be reached") from exc
