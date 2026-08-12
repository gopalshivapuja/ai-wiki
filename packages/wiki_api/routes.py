"""API routes. Everything lives under /api or the SPA catch-all swallows it."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from wiki_core.llm import LLMNotConfigured

from wiki_api.auth import get_current_user
from wiki_api.database import (
    NOTE_SUBTYPES,
    ActivityLog,
    Document,
    User,
    get_db,
    utcnow,
)
from wiki_api.services import archive
from wiki_api.services.content import (
    Immutable,
    backlinks,
    build_link_index,
    create_note,
    delete_doc,
    get_doc,
    list_docs,
    outgoing_links,
    restore_revision,
    revisions,
    row_to_dict,
    tag_counts,
    to_dict,
    update_note,
)
from wiki_api.services.fetch import FetchError
from wiki_api.services.graph import build_graph, orphans, stats
from wiki_api.services.ingest import ai_query
from wiki_api.services.search import search

logger = logging.getLogger(__name__)
router = APIRouter()


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str | None = Field(default=None, max_length=1_000_000)
    type: str = Field(default="zettel")
    tags: list[str] = Field(default_factory=list)


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    body: str | None = Field(default=None, max_length=1_000_000)
    tags: list[str] | None = None
    type: str | None = None


class QuestionBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


def _fail(exc: Exception, fallback: str) -> HTTPException:
    """Map service errors to honest status codes.

    A blanket 500 turned "not found" into a server error and leaked internal network detail
    to the client.
    """
    if isinstance(exc, Immutable):
        return HTTPException(409, str(exc))
    if isinstance(exc, (ValueError, FetchError)):
        return HTTPException(400, str(exc))
    if isinstance(exc, LLMNotConfigured):
        return HTTPException(503, str(exc))
    logger.exception(fallback)
    return HTTPException(500, fallback)


def _require(db: Session, slug: str) -> Document:
    doc = get_doc(db, slug)
    if not doc:
        raise HTTPException(404, f"Nothing found at '{slug}'")
    return doc


def _detail(db: Session, doc: Document) -> dict:
    """The full document representation. Used by GET and PUT so their shapes match."""
    index = build_link_index(db)
    out = to_dict(doc)
    out["backlinks"] = backlinks(db, doc.slug, index)
    out["links"] = outgoing_links(doc, index)

    src = db.get(Document, doc.derived_from_id) if doc.derived_from_id else None
    out["derived_from"] = {"slug": src.slug, "title": src.title} if src else None

    note = (
        db.query(Document.slug, Document.title).filter(Document.derived_from_id == doc.id).first()
    )
    out["summary"] = {"slug": note.slug, "title": note.title} if note else None
    out["revision_count"] = len(revisions(db, doc, limit=100))
    return out


# --- read ---------------------------------------------------------------------


@router.get("/search")
def api_search(
    q: str = Query(...),
    limit: int = Query(12, ge=1, le=50),
    include_sources: bool = Query(True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {"results": search(db, q, top_k=limit, include_sources=include_sources)}


@router.get("/documents")
def api_documents(
    doc_class: str | None = Query(default=None, pattern="^(note|source)$"),
    type: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    collection: str | None = Query(default=None),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = list_docs(
        db,
        doc_class=doc_class,
        subtype=type,
        tag=tag,
        collection=collection,
        limit=limit,
        offset=offset,
    )
    return {"documents": [row_to_dict(r) for r in rows]}


@router.get("/documents/{slug}")
def api_document(slug: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _detail(db, _require(db, slug))


@router.get("/documents/{slug}/revisions")
def api_revisions(slug: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    doc = _require(db, slug)
    return {
        "revisions": [
            {
                "id": r.id,
                "title": r.title,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "preview": (r.body or "")[:200],
            }
            for r in revisions(db, doc)
        ]
    }


@router.get("/tags")
def api_tags(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"tags": tag_counts(db)}


@router.get("/graph")
def api_graph(
    include_sources: bool = Query(True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return build_graph(db, include_sources=include_sources)


@router.get("/orphans")
def api_orphans(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Notes nothing links to, and links pointing at notes that do not exist yet."""
    return orphans(db)


@router.get("/stats")
def api_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return stats(db)


@router.get("/log")
def api_log(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
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


@router.post("/documents", status_code=201)
def api_create(
    body: NoteCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    if body.type not in NOTE_SUBTYPES:
        raise HTTPException(400, f"Unknown note type '{body.type}'")
    try:
        doc = create_note(db, body.title, body.body, subtype=body.type, tags=body.tags)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return to_dict(doc)


@router.put("/documents/{slug}")
def api_update(
    slug: str,
    body: NoteUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    doc = _require(db, slug)
    if body.type and body.type not in NOTE_SUBTYPES:
        raise HTTPException(400, f"Unknown note type '{body.type}'")
    try:
        updated = update_note(
            db,
            doc,
            title=body.title,
            body=body.body,
            tags=[t.strip() for t in body.tags if t.strip()] if body.tags is not None else None,
            subtype=body.type,
        )
    except Exception as exc:
        raise _fail(exc, "Could not save the note") from exc
    return _detail(db, updated)


@router.post("/documents/{slug}/restore/{revision_id}")
def api_restore(
    slug: str,
    revision_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    doc = _require(db, slug)
    try:
        return _detail(db, restore_revision(db, doc, revision_id))
    except Exception as exc:
        raise _fail(exc, "Could not restore that revision") from exc


@router.delete("/documents/{slug}", status_code=204)
def api_delete(slug: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if not delete_doc(db, slug):
        raise HTTPException(404, f"Nothing found at '{slug}'")


# --- backup -------------------------------------------------------------------


@router.get("/export")
def api_export(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Download the whole wiki as a zip of markdown files."""
    filename = f"ai-wiki-{utcnow().strftime('%Y%m%d-%H%M%S')}.zip"
    return StreamingResponse(
        archive.export_stream(db),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- LLM ----------------------------------------------------------------------


@router.get("/llm/models")
def api_models(user: User = Depends(get_current_user)):
    from wiki_core.llm import model_status

    return model_status()


@router.post("/llm/query")
def api_ask(
    body: QuestionBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    try:
        return ai_query(db, body.question)
    except Exception as exc:
        raise _fail(exc, "The model could not be reached") from exc


@router.post("/llm/query/stream")
def api_ask_stream(
    body: QuestionBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Answer as newline-delimited JSON events: citations first, then text as it generates.

    Retrieval takes ~0.3s while generation can take half a minute, so the sources appear
    immediately and the prose fills in beneath rather than the page sitting blank.
    """
    import json

    from wiki_core.llm import stream_llm

    from wiki_api.services.ingest import NO_CONTEXT, SYSTEM_PROMPT, retrieve

    prompt, citations = retrieve(db, body.question)

    def events():
        yield json.dumps({"type": "citations", "citations": citations}) + "\n"
        if not prompt:
            yield json.dumps({"type": "text", "text": NO_CONTEXT}) + "\n"
            yield json.dumps({"type": "done"}) + "\n"
            return
        try:
            for piece in stream_llm(prompt, SYSTEM_PROMPT):
                yield json.dumps({"type": "text", "text": piece}) + "\n"
            yield json.dumps({"type": "done"}) + "\n"
        except Exception as exc:
            logger.warning("Streamed answer failed: %s", exc)
            yield json.dumps({"type": "error", "message": str(exc)}) + "\n"

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        # Proxies must not buffer this or the streaming is pointless.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
