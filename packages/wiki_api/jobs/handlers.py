"""Job handlers.

Plain synchronous functions, each run whole in a worker thread. They open a database session
only around actual database work — never for the duration of a network call.

Handlers **capture**; they do not distil. Any source a handler stores is reported back in
`result["sources"]`, and the runner queues distillation for it. That is the single choke
point: previously each handler decided for itself whether to summarise, so arXiv never did,
crawl and paste defaulted to off, and import never did — meaning whether your wiki grew a
graph depended on which button you pressed.
"""

from __future__ import annotations

import base64
import logging
import tempfile
from pathlib import Path

from wiki_api.database import session_scope
from wiki_api.jobs.runner import JobContext, JobHandler
from wiki_api.services import archive, crawl, distill, ingest, transcribe

logger = logging.getLogger(__name__)


def _captured(result: dict, *slugs: str) -> dict:
    """Mark the sources a handler created so the runner can distil them."""
    result["sources"] = [s for s in slugs if s]
    return result


def handle_web(params: dict, ctx: JobContext) -> dict:
    ctx.progress(0, 1, "Fetching page")
    with session_scope() as db:
        result = ingest.ingest_web(db, params["url"])
    ctx.progress(1, 1, "Stored")
    return _captured(result, result["slug"])


def handle_arxiv(params: dict, ctx: JobContext) -> dict:
    ctx.progress(0, 1, "Fetching arXiv metadata")
    with session_scope() as db:
        result = ingest.ingest_arxiv(db, params["id_or_url"])
    ctx.progress(1, 1, "Stored")
    return _captured(result, result["slug"])


def handle_youtube(params: dict, ctx: JobContext) -> dict:
    ctx.progress(0, 1, "Fetching captions")
    with session_scope() as db:
        result = ingest.ingest_youtube(db, params["url"])
    ctx.progress(1, 1, "Stored")
    return _captured(result, result["slug"])


def handle_paste(params: dict, ctx: JobContext) -> dict:
    ctx.progress(0, 1, "Storing text")
    with session_scope() as db:
        result = ingest.ingest_paste(db, params["title"], params["text"])
    ctx.progress(1, 1, "Stored")
    return _captured(result, result["slug"])


def handle_transcribe(params: dict, ctx: JobContext) -> dict:
    """Download and transcribe with no session open, then store.

    The model call can take ten minutes; holding a pooled connection across it risks losing
    the transcript after the provider has already been paid.
    """
    transcript, meta = transcribe.fetch_transcript(params["url"], on_progress=ctx.progress)
    ctx.progress(3, 4, "Storing transcript")
    with session_scope() as db:
        result = transcribe.store_transcript(db, meta, transcript)
    return _captured(result, result["slug"])


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
    return _captured(result, *result.get("created", []))


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
    return _captured(result, result["slug"])


def handle_youtube_channel(params: dict, ctx: JobContext) -> dict:
    """Expand a channel or playlist into one ingest job per video."""
    from wiki_api.jobs.runner import enqueue

    ctx.progress(0, 1, "Listing videos")
    videos = ingest.list_channel_videos(params["url"], limit=params.get("limit"))
    if not videos:
        raise ValueError("No videos found at that URL")

    queued = 0
    with session_scope() as db:
        for i, v in enumerate(videos, start=1):
            ctx.progress(i, len(videos), f"Queueing {v['title'][:60]}")
            enqueue(
                db,
                "youtube",
                {
                    "url": f"https://www.youtube.com/watch?v={v['id']}",
                    "moc": params.get("moc"),
                    "moc_title": params.get("moc_title"),
                    "distill": params.get("distill", True),
                },
            )
            queued += 1
    return {"videos": len(videos), "queued": queued, "titles": [v["title"] for v in videos[:5]]}


def handle_distill(params: dict, ctx: JobContext) -> dict:
    """Connect a captured source to the rest of the wiki."""
    from wiki_api.services.content import get_doc

    ctx.progress(0, 2, "Reading the source")
    with session_scope() as db:
        source = get_doc(db, params["source_slug"])
        if source is None:
            raise ValueError(f"Nothing found at '{params['source_slug']}'")
        ctx.progress(1, 2, "Extracting concepts and linking")
        result = distill.distill(
            db,
            source,
            moc_slug=params.get("moc"),
            moc_title=params.get("moc_title"),
            max_new=params.get("max_new")
            if params.get("max_new") is not None
            else distill.MAX_NEW_ZETTELS,
        )
    ctx.progress(2, 2, "Linked")
    return result.as_dict()


def handle_summarize(params: dict, ctx: JobContext) -> dict:
    """Re-run distillation for one source, on demand."""
    return handle_distill({"source_slug": params["source_slug"], **params}, ctx)


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
    "youtube-channel": handle_youtube_channel,
    "transcribe": handle_transcribe,
    "crawl": handle_crawl,
    "pdf": handle_pdf,
    "paste": handle_paste,
    "distill": handle_distill,
    "summarize": handle_summarize,
    "import": handle_import,
}
