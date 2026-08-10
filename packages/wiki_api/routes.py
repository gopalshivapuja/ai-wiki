"""Wiki API routes."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from wiki_api.auth import get_current_user, get_optional_user
from wiki_api.database import User
from wiki_core.config import BASE_DIR, load_dotenv
from wiki_core.frontmatter import extract_title, parse_frontmatter
from wiki_core.graph import build_graph, get_backlinks, get_page_by_slug
from wiki_core.ingest import ingest_arxiv, ingest_web, ingest_youtube
from wiki_core.lint import auto_link_suggestions, graph_stats, lint_wiki
from wiki_core.log import append_log
from wiki_core.rag import ai_lint_wiki, ai_summarize_source, query_wiki
from wiki_core.search import search
from wiki_core.zettel import new_zettel

load_dotenv()
router = APIRouter()

REQUIRE_AUTH = os.environ.get("REQUIRE_AUTH", "false").lower() == "true"


def _auth_dep(user: User | None = Depends(get_optional_user)):
    if REQUIRE_AUTH and user is None:
        raise HTTPException(status_code=401, detail="Authentication required")


def _write_auth(user: User = Depends(get_current_user)):
    return user


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
    source_path: str


class LogBody(BaseModel):
    action: str
    summary: str


@router.get("/search")
def api_search(q: str = Query(...), limit: int = 10, _: None = Depends(_auth_dep)):
    results = search(q, top_k=limit)
    return {
        "results": [
            {
                "score": r.score,
                "slug": r.slug,
                "title": r.title,
                "path": r.path,
                "snippet": r.snippet,
                "type": r.page_type,
            }
            for r in results
        ]
    }


@router.get("/pages")
def list_pages(_: None = Depends(_auth_dep)):
    graph = build_graph()
    return {
        "pages": [
            {"slug": n.slug, "title": n.title, "type": n.type, "path": n.path, "link_count": n.link_count}
            for n in graph.nodes
        ]
    }


@router.get("/pages/{slug}")
def get_page(slug: str, _: None = Depends(_auth_dep)):
    path = get_page_by_slug(slug)
    if not path:
        raise HTTPException(status_code=404, detail="Page not found")
    text = path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    return {
        "slug": slug,
        "title": extract_title(text, slug),
        "content": text,
        "body": body,
        "frontmatter": fm,
        "path": str(path.relative_to(BASE_DIR)),
        "backlinks": get_backlinks(slug),
    }


@router.get("/graph")
def api_graph(_: None = Depends(_auth_dep)):
    g = build_graph()
    return {
        "nodes": [n.__dict__ for n in g.nodes],
        "edges": [e.__dict__ for e in g.edges],
    }


@router.get("/stats")
def api_stats(_: None = Depends(_auth_dep)):
    return graph_stats()


@router.get("/lint")
def api_lint(_: None = Depends(_auth_dep)):
    issues = lint_wiki()
    return {
        "issues": [{"kind": i.kind, "message": i.message, "path": i.path} for i in issues],
        "count": len(issues),
    }


@router.get("/auto-link")
def api_auto_link(_: None = Depends(_auth_dep)):
    return {"suggestions": [{"path": p, "term": t, "slug": s} for p, t, s in auto_link_suggestions()]}


@router.post("/llm/query")
def api_query(body: QueryBody, user: User = Depends(get_current_user)):
    try:
        answer = query_wiki(body.question, verbose=False)
        return {"answer": answer}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/llm/summarize")
def api_summarize(body: SummarizeBody, user: User = Depends(get_current_user)):
    path = str((BASE_DIR / body.source_path).resolve())
    try:
        out = ai_summarize_source(path)
        return {"path": out}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/llm/audit")
def api_audit(user: User = Depends(get_current_user)):
    try:
        report = ai_lint_wiki(verbose=False)
        return {"report": report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/zettels")
def api_new_zettel(body: ZettelBody, user: User = Depends(get_current_user)):
    try:
        slug = new_zettel(body.title)
        return {"slug": slug}
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/ingest/web")
def api_ingest_web(body: IngestWebBody, user: User = Depends(get_current_user)):
    try:
        return {"path": ingest_web(body.url)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest/youtube")
def api_ingest_youtube(body: IngestYoutubeBody, user: User = Depends(get_current_user)):
    try:
        return {"path": ingest_youtube(body.url)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest/arxiv")
def api_ingest_arxiv(body: IngestArxivBody, user: User = Depends(get_current_user)):
    try:
        return {"path": ingest_arxiv(body.id_or_url)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/log")
def api_log(body: LogBody, user: User = Depends(get_current_user)):
    line = append_log(body.action, body.summary)
    return {"line": line}
