"""API routes — all data from PostgreSQL."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from wiki_api.auth import get_current_user, get_optional_user
from wiki_api.database import ActivityLog, Page, RawSource, User, get_db
from wiki_api.services.content import (
    create_zettel,
    get_backlinks,
    get_page,
    list_pages,
    log_action,
    page_to_dict,
)
from wiki_api.services.graph import build_graph, stats
from wiki_api.services.ingest import ai_query, ai_summarize, ingest_arxiv, ingest_web, ingest_youtube
from wiki_api.services.search import search

router = APIRouter()


class QueryBody(BaseModel):
    question: str


class ZettelBody(BaseModel):
    title: str


class IngestWebBody(BaseModel):
    url: str


class IngestYoutubeBody(BaseModel):
    url: str


class IngestArxivBody(BaseModel):
    id_or_url: str


class SummarizeBody(BaseModel):
    source_slug: str


@router.get("/search")
def api_search(q: str = Query(...), limit: int = Query(12), db: Session = Depends(get_db)):
    return {"results": search(db, q, top_k=limit)}


@router.get("/pages")
def api_pages(db: Session = Depends(get_db)):
    pages = list_pages(db)
    return {
        "pages": [
            {"slug": p.slug, "title": p.title, "type": p.page_type, "tags": p.tags or []}
            for p in pages
        ]
    }


@router.get("/pages/{slug}")
def api_page(slug: str, db: Session = Depends(get_db)):
    p = get_page(db, slug)
    if not p:
        raise HTTPException(404, "Page not found")
    d = page_to_dict(p)
    d["backlinks"] = get_backlinks(db, slug)
    return d


@router.get("/sources")
def api_sources(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    sources = db.query(RawSource).order_by(RawSource.created_at.desc()).all()
    return {
        "sources": [
            {"slug": s.slug, "title": s.title, "type": s.source_type, "url": s.url}
            for s in sources
        ]
    }


@router.get("/graph")
def api_graph(db: Session = Depends(get_db)):
    return build_graph(db)


@router.get("/stats")
def api_stats(db: Session = Depends(get_db)):
    return stats(db)


@router.get("/log")
def api_log(db: Session = Depends(get_db), user: User = Depends(get_current_user), limit: int = 50):
    entries = db.query(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(limit).all()
    return {
        "entries": [
            {"action": e.action, "summary": e.summary, "created_at": e.created_at.isoformat()}
            for e in entries
        ]
    }


@router.post("/llm/query")
def api_query(body: QueryBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return {"answer": ai_query(db, body.question)}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/llm/summarize")
def api_summarize(body: SummarizeBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return ai_summarize(db, body.source_slug)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/zettels")
def api_zettel(body: ZettelBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        p = create_zettel(db, body.title)
        return {"slug": p.slug, "title": p.title}
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/ingest/web")
def api_ingest_web(body: IngestWebBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return ingest_web(db, body.url)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/ingest/youtube")
def api_ingest_youtube(body: IngestYoutubeBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return ingest_youtube(db, body.url)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/ingest/arxiv")
def api_ingest_arxiv(body: IngestArxivBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        return ingest_arxiv(db, body.id_or_url)
    except Exception as e:
        raise HTTPException(500, str(e))
