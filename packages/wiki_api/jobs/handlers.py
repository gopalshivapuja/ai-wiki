"""Job handlers.

Plain synchronous functions — the runner executes each one whole inside a worker thread.
They take a task-owned Session and report progress through JobContext.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from wiki_api.jobs.runner import JobContext, JobHandler
from wiki_api.services import crawl as crawl_service
from wiki_api.services import documents, ingest, transcribe

logger = logging.getLogger(__name__)


def _maybe_autosummarize(
    db: Session, ctx: JobContext, slugs: list[str], enabled: bool
) -> list[dict]:
    """Generate literature notes for freshly ingested sources.

    Failures are collected rather than raised: the source is already stored, and losing the
    ingest because the LLM was rate-limited would be the wrong trade.
    """
    if not enabled or not slugs:
        return []
    notes = []
    for i, slug in enumerate(slugs, start=1):
        if ctx.should_stop():
            break
        ctx.progress(i, len(slugs), f"Summarizing {slug}")
        try:
            notes.append(ingest.ai_summarize(db, slug))
        except Exception as exc:
            logger.warning("Auto-summarize failed for %s: %s", slug, exc)
            notes.append({"slug": slug, "error": str(exc)})
    return notes


def handle_web(db: Session, params: dict, ctx: JobContext) -> dict:
    ctx.progress(0, 1, "Fetching page")
    result = ingest.ingest_web(db, params["url"])
    ctx.progress(1, 1, "Stored")
    result["summaries"] = _maybe_autosummarize(
        db, ctx, [result["slug"]], params.get("summarize", True)
    )
    return result


def handle_arxiv(db: Session, params: dict, ctx: JobContext) -> dict:
    ctx.progress(0, 1, "Fetching arXiv metadata")
    result = ingest.ingest_arxiv(db, params["id_or_url"])
    ctx.progress(1, 1, "Stored")
    return result


def handle_youtube(db: Session, params: dict, ctx: JobContext) -> dict:
    ctx.progress(0, 1, "Fetching captions")
    result = ingest.ingest_youtube(db, params["url"])
    ctx.progress(1, 1, "Stored")
    result["summaries"] = _maybe_autosummarize(
        db, ctx, [result["slug"]], params.get("summarize", True)
    )
    return result


def handle_transcribe(db: Session, params: dict, ctx: JobContext) -> dict:
    result = transcribe.ingest_audio(
        db, params["url"], on_progress=lambda c, t, m: (ctx.check_stop(), ctx.progress(c, t, m))[1]
    )
    result["summaries"] = _maybe_autosummarize(
        db, ctx, [result["slug"]], params.get("summarize", True)
    )
    return result


def handle_crawl(db: Session, params: dict, ctx: JobContext) -> dict:
    result = crawl_service.crawl_site(
        db,
        params["url"],
        collection=params.get("collection"),
        max_pages=params.get("max_pages", crawl_service.DEFAULT_MAX_PAGES),
        max_depth=params.get("max_depth", crawl_service.DEFAULT_MAX_DEPTH),
        on_progress=ctx.progress,
        should_stop=ctx.should_stop,
    )
    # Summarizing an entire crawl would be dozens of LLM calls, so it is opt-in here.
    if params.get("summarize"):
        result["summaries"] = _maybe_autosummarize(db, ctx, result["created"], True)
    return result


def handle_pdf(db: Session, params: dict, ctx: JobContext) -> dict:
    path = Path(params["upload_path"])
    if not path.is_file():
        # The upload is staged on the container's ephemeral disk while only its path lives in
        # the job row, so a job still queued when the container is replaced loses its file.
        raise ValueError(
            f"The uploaded file for '{params.get('filename', 'this PDF')}' is no longer "
            "available — the server restarted before the job ran. Please upload it again."
        )
    try:
        ctx.progress(0, 1, "Extracting text")
        result = documents.ingest_pdf(db, path, params.get("title"), params.get("filename"))
        ctx.progress(1, 1, "Stored")
    finally:
        path.unlink(missing_ok=True)
    result["summaries"] = _maybe_autosummarize(
        db, ctx, [result["slug"]], params.get("summarize", True)
    )
    return result


def handle_paste(db: Session, params: dict, ctx: JobContext) -> dict:
    ctx.progress(0, 1, "Storing text")
    result = documents.ingest_paste(db, params["title"], params["text"])
    ctx.progress(1, 1, "Stored")
    result["summaries"] = _maybe_autosummarize(
        db, ctx, [result["slug"]], params.get("summarize", False)
    )
    return result


def handle_summarize(db: Session, params: dict, ctx: JobContext) -> dict:
    ctx.progress(0, 1, "Asking the model")
    result = ingest.ai_summarize(db, params["source_slug"])
    ctx.progress(1, 1, "Wrote literature note")
    return result


HANDLERS: dict[str, JobHandler] = {
    "web": handle_web,
    "arxiv": handle_arxiv,
    "youtube": handle_youtube,
    "transcribe": handle_transcribe,
    "crawl": handle_crawl,
    "pdf": handle_pdf,
    "paste": handle_paste,
    "summarize": handle_summarize,
}
