"""API routes. Everything lives under /api or the SPA catch-all swallows it."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from wiki_core.llm import LLMNotConfigured

from wiki_api.auth import get_current_user, require_admin
from wiki_api.database import (
    NOTE,
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
    log_action,
    outgoing_links,
    restore_revision,
    revisions,
    row_to_dict,
    tag_counts,
    to_dict,
    update_note,
)
from wiki_api.services.distill import UNREVIEWED
from wiki_api.services.fetch import FetchError
from wiki_api.services.graph import build_graph, build_neighbourhood, orphans, stats
from wiki_api.services.ingest import ai_query
from wiki_api.services.relate import duplicate_pairs, embed_missing, similar
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
    """The whole graph. Kept for export and analysis; the UI draws neighbourhoods instead."""
    return build_graph(db, include_sources=include_sources)


@router.get("/graph/{slug}")
def api_neighbourhood(
    slug: str,
    hops: int = Query(1, ge=1, le=3),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """What surrounds one document — the question a whole-wiki graph cannot answer."""
    if get_doc(db, slug) is None:
        raise HTTPException(404, f"Nothing found at '{slug}'")
    return build_neighbourhood(db, slug, hops=hops)


@router.get("/random")
def api_random(
    type: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """One random note, for rediscovery.

    Notes only: a captured source is raw material, not something worth being handed at random.
    Chosen in the database so a 400-note wiki does not ship every slug to the browser.
    """
    q = db.query(Document).filter(Document.doc_class == NOTE, Document.subtype != "index")
    if type:
        q = q.filter(Document.subtype == type)
    doc = q.order_by(func.random()).first()
    if doc is None:
        raise HTTPException(404, "There are no notes yet")
    body = doc.body or ""
    # Skip the H1 and any frontmatter-ish preamble to find a sentence worth previewing.
    preview = next(
        (
            line.strip()
            for line in body.splitlines()
            if line.strip() and not line.startswith(("#", "-", "*", ">", "|"))
        ),
        "",
    )
    return {**to_dict(doc, include_body=False), "preview": preview[:280]}


@router.get("/llms.txt", response_class=PlainTextResponse)
def api_llms_txt(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """A map of this wiki for a language model, in the llms.txt convention.

    An agent arriving at a JSON API has no idea what the wiki holds or where to start. This
    says what is here, names the maps of content as entry points, and gives the traversal
    order that actually works: search, read, follow links.

    Authenticated like everything else — the wiki is private, and describing its contents is
    still describing its contents.
    """
    s = stats(db)
    mocs = list_docs(db, doc_class=NOTE, subtype="moc", limit=50)
    collections = sorted(
        {r.collection for r in list_docs(db, doc_class="source", limit=2000) if r.collection}
    )

    lines = [
        "# ai-wiki",
        "",
        "> A private single-user Zettelkasten. Every document is either a note (something "
        "written or distilled) or a source (captured material: a web page, PDF, or video "
        "transcript). Notes are joined by [[wikilinks]]; a link is only written once its "
        "destination exists, so a resolved link always points at a real document.",
        "",
        f"{s['total_notes']} notes, {s['total_sources']} sources, {s['total_wikilinks']} links "
        f"({s['avg_links_per_note']} per note).",
        "",
        "## Start here",
        "",
        "Maps of content are the entry points. Each one organises a subject and links to the "
        "notes under it.",
        "",
    ]
    lines += [f"- [{m.title}](/api/documents/{m.slug}): {m.slug}" for m in mocs] or ["- (none yet)"]
    lines += [
        "",
        "## Note types",
        "",
        f"- zettel ({s['zettels']}): one atomic idea, the unit worth citing",
        f"- literature ({s['literature']}): what one source said, linked to that source",
        f"- concept ({s['concepts']}), entity ({s['entities']}): longer-lived reference notes",
        f"- moc ({s['mocs']}): a map of content",
        "",
        "Notes tagged `unreviewed` were written by a model and not yet checked by a human. "
        "Weigh them accordingly.",
        "",
    ]
    if collections:
        lines += ["## Source collections", "", *[f"- {c}" for c in collections], ""]
    lines += [
        "## How to traverse",
        "",
        "1. `GET /api/search?q=...` — full-text search over notes and sources.",
        "2. `GET /api/documents/{slug}` — the markdown body, plus `links` (outgoing, each "
        "flagged with whether it resolves) and `backlinks` (what points here).",
        "3. `GET /api/graph/{slug}?hops=1` — the neighbourhood around a document.",
        "4. `GET /api/documents?type=moc` — list the maps of content.",
        "5. `POST /api/llm/query` — ask a question and get an answer with citations.",
        "",
        "Every route needs `Authorization: Bearer <token>`. Prefer reading a map of content "
        "before searching: it gives the vocabulary this wiki actually uses.",
        "",
    ]
    return "\n".join(lines)


@router.get("/related/{slug}")
def api_related(
    slug: str,
    k: int = Query(8, ge=1, le=20),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Notes near this one in meaning, whether or not anything links them.

    Empty until embeddings exist — the wiki works without them, it is just less associative.
    """
    _require(db, slug)
    return {"related": similar(db, slug, k=k)}


@router.post("/maintenance/embed")
def api_embed(
    force: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Backfill embeddings. Idempotent, so it is safe to re-run after adding notes."""
    return embed_missing(db, force=force)


@router.get("/maintenance/duplicates")
def api_duplicates(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Notes that look like the same idea written twice. Reported, never merged for you."""
    return {"pairs": duplicate_pairs(db)}


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
    body: NoteCreate, db: Session = Depends(get_db), user: User = Depends(require_admin)
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
    user: User = Depends(require_admin),
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
    user: User = Depends(require_admin),
):
    doc = _require(db, slug)
    try:
        return _detail(db, restore_revision(db, doc, revision_id))
    except Exception as exc:
        raise _fail(exc, "Could not restore that revision") from exc


@router.delete("/documents/{slug}", status_code=204)
def api_delete(slug: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    if not delete_doc(db, slug):
        raise HTTPException(404, f"Nothing found at '{slug}'")


class ApproveBody(BaseModel):
    slugs: list[str] = Field(default_factory=list, max_length=500)


@router.get("/review")
def api_review_queue(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Notes written by the pipeline and not yet confirmed by a human."""
    rows = (
        db.query(Document)
        .filter(Document.tags.contains([UNREVIEWED]))
        .order_by(Document.created_at.desc())
        .limit(limit)
        .all()
    )
    out = []
    for d in rows:
        src = db.get(Document, d.derived_from_id) if d.derived_from_id else None
        item = to_dict(d)
        item["preview"] = (d.body or "")[:400]
        item["source"] = {"slug": src.slug, "title": src.title} if src else None
        out.append(item)
    total = db.query(Document).filter(Document.tags.contains([UNREVIEWED])).count()
    return {"documents": out, "total": total}


@router.post("/review/approve")
def api_review_approve(
    body: ApproveBody, db: Session = Depends(get_db), user: User = Depends(require_admin)
):
    """Drop the unreviewed tag. With no slugs given, approves everything pending."""
    q = db.query(Document).filter(Document.tags.contains([UNREVIEWED]))
    if body.slugs:
        q = q.filter(Document.slug.in_(body.slugs))
    approved = 0
    for doc in q.all():
        doc.tags = [t for t in (doc.tags or []) if t != UNREVIEWED]
        approved += 1
    db.commit()
    if approved:
        log_action(db, "review", f"Approved {approved} note(s)")
    return {"approved": approved}


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
