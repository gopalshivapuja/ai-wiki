"""Job handlers.

Plain synchronous functions, each run whole in a worker thread. They open a database session
only around actual database work — never for the duration of a network call.
"""

from __future__ import annotations

import base64
import logging
import tempfile
from pathlib import Path

from wiki_api.database import session_scope
from wiki_api.jobs.runner import JobContext, JobHandler
from wiki_api.services import archive, crawl, ingest, transcribe

logger = logging.getLogger(__name__)


def _summarize(slug: str, ctx: JobContext, enabled: bool) -> list[dict]:
    """Write a literature note for a freshly ingested source.

    Failures are recorded rather than raised: the source is already stored, and losing the
    ingest because the model was rate-limited would be the wrong trade.
    """
    if not enabled:
        return []
    ctx.progress(1, 2, "Summarizing with AI")
    try:
        with session_scope() as db:
            return [ingest.ai_summarize(db, slug)]
    except Exception as exc:
        logger.warning("Auto-summarize failed for %s: %s", slug, exc)
        return [{"slug": slug, "error": str(exc)}]


def _ingest_job(fn, params: dict, ctx: JobContext, *args) -> dict:
    ctx.progress(0, 2, "Fetching")
    with session_scope() as db:
        result = fn(db, *args)
    ctx.progress(1, 2, "Stored")
    result["summaries"] = _summarize(result["slug"], ctx, params.get("summarize", True))
    ctx.progress(2, 2, "Done")
    return result


def handle_web(params: dict, ctx: JobContext) -> dict:
    return _ingest_job(ingest.ingest_web, params, ctx, params["url"])


def handle_arxiv(params: dict, ctx: JobContext) -> dict:
    ctx.progress(0, 1, "Fetching arXiv metadata")
    with session_scope() as db:
        result = ingest.ingest_arxiv(db, params["id_or_url"])
    ctx.progress(1, 1, "Stored")
    return result


def handle_youtube(params: dict, ctx: JobContext) -> dict:
    return _ingest_job(ingest.ingest_youtube, params, ctx, params["url"])


def handle_paste(params: dict, ctx: JobContext) -> dict:
    return _ingest_job(ingest.ingest_paste, params, ctx, params["title"], params["text"])


def handle_transcribe(params: dict, ctx: JobContext) -> dict:
    """Download and transcribe with no session open, then store.

    The model call can take ten minutes; holding a pooled connection across it risks losing
    the transcript after the provider has already been paid.
    """
    transcript, meta = transcribe.fetch_transcript(params["url"], on_progress=ctx.progress)
    ctx.progress(3, 4, "Storing transcript")
    with session_scope() as db:
        result = transcribe.store_transcript(db, meta, transcript)
    result["summaries"] = _summarize(result["slug"], ctx, params.get("summarize", True))
    return result


def handle_crawl(params: dict, ctx: JobContext) -> dict:
    with session_scope() as db:
        result = crawl.crawl_site(
            db,
            params["url"],
            collection=params.get("collection"),
            max_pages=params.get("max_pages", crawl.DEFAULT_MAX_PAGES),
            max_depth=params.get("max_depth", crawl.DEFAULT_MAX_DEPTH),
            on_progress=ctx.progress,
            should_stop=ctx.should_stop,
        )
    # Summarizing a whole crawl is one model call per page, so it stays opt-in.
    if params.get("summarize"):
        notes = []
        for i, slug in enumerate(result["created"], start=1):
            if ctx.should_stop():
                break
            ctx.progress(i, len(result["created"]), f"Summarizing {slug}")
            notes.extend(_summarize(slug, ctx, True))
        result["summaries"] = notes
    return result


def handle_pdf(params: dict, ctx: JobContext) -> dict:
    """Extract an uploaded PDF.

    The bytes travel in the job row, so a redeploy between upload and execution cannot lose
    the file and retry works.
    """
    payload = params.pop("_payload", None)
    if not payload:
        raise ValueError(
            f"The uploaded file for '{params.get('filename', 'this PDF')}' is missing. "
            "Please upload it again."
        )
    ctx.progress(0, 2, "Extracting text")
    with tempfile.TemporaryDirectory(prefix="wiki-pdf-") as tmp:
        path = Path(tmp) / (params.get("filename") or "upload.pdf")
        path.write_bytes(base64.b64decode(payload))
        with session_scope() as db:
            result = ingest.ingest_pdf(db, path, params.get("title"), params.get("filename"))
    ctx.progress(1, 2, "Stored")
    result["summaries"] = _summarize(result["slug"], ctx, params.get("summarize", True))
    return result


def handle_summarize(params: dict, ctx: JobContext) -> dict:
    ctx.progress(0, 1, "Asking the model")
    with session_scope() as db:
        result = ingest.ai_summarize(db, params["source_slug"])
    ctx.progress(1, 1, "Wrote literature note")
    return result


def handle_import(params: dict, ctx: JobContext) -> dict:
    payload = params.pop("_payload", None)
    if not payload:
        raise ValueError("The uploaded archive is missing. Please upload it again.")
    ctx.progress(0, 1, "Reading archive")
    with session_scope() as db:
        return archive.import_archive(db, base64.b64decode(payload), on_progress=ctx.progress)


HANDLERS: dict[str, JobHandler] = {
    "web": handle_web,
    "arxiv": handle_arxiv,
    "youtube": handle_youtube,
    "transcribe": handle_transcribe,
    "crawl": handle_crawl,
    "pdf": handle_pdf,
    "paste": handle_paste,
    "summarize": handle_summarize,
    "import": handle_import,
}
