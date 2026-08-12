"""Ingest pipelines. Every path ends at content.store_source()."""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
from pathlib import Path

from sqlalchemy.orm import Session
from wiki_core.llm import call_llm

from wiki_api.database import Document
from wiki_api.services.content import (
    get_doc,
    store_source,
    upsert_literature_note,
)
from wiki_api.services.fetch import (
    FetchError,
    clamp,
    fetch_text,
    html_to_markdown,
    page_title,
)

logger = logging.getLogger(__name__)

# Caps on what reaches the model. Without them, five long documents make a prompt the
# provider rejects outright.
RAG_CHARS_PER_DOC = 4_000
SUMMARIZE_CHARS = 8_000
MAX_PDF_PAGES = 500


# --- web ----------------------------------------------------------------------


def store_web_page(
    db: Session, url: str, html: str, collection: str | None = None
) -> tuple[Document, bool]:
    """Store already-fetched HTML.

    Separate from ingest_web so the crawler can pass the HTML it just read. Previously the
    crawler fetched each page for its links and then ingest_web fetched the same URL again —
    50 requests for a 25-page crawl.
    """
    title = page_title(html, url)
    body = clamp(f"# {title}\n\n**Source:** [{url}]({url})\n\n---\n\n{html_to_markdown(html)}")
    return store_source(
        db,
        title=title,
        body=body,
        subtype="web",
        url=url,
        collection=collection,
        slug_hint=url,
        log_label=f"Web: {title}",
    )


def ingest_web(db: Session, url: str, collection: str | None = None) -> dict:
    _, html = fetch_text(url)
    doc, created = store_web_page(db, url, html, collection)
    return _result(doc, created)


# --- arXiv --------------------------------------------------------------------


def ingest_arxiv(db: Session, id_or_url: str) -> dict:
    m = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?)", id_or_url)
    arxiv_id = m.group(1) if m else id_or_url.strip()
    if not re.fullmatch(r"[\w.\-/]+", arxiv_id):
        raise FetchError(f"Not a valid arXiv id: {id_or_url}")

    api = f"https://export.arxiv.org/api/query?id_list={urllib.parse.quote(arxiv_id)}"
    _, xml = fetch_text(api, timeout=20)

    title = f"arXiv {arxiv_id}"
    if "<entry>" in xml:
        tm = re.search(r"<title>(.*?)</title>", xml.split("<entry>")[1], re.DOTALL)
        if tm:
            title = re.sub(r"\s+", " ", tm.group(1)).strip()
    sm = re.search(r"<summary>(.*?)</summary>", xml, re.DOTALL)
    abstract = re.sub(r"\s+", " ", sm.group(1)).strip() if sm else ""
    authors = ", ".join(re.findall(r"<name>(.*?)</name>", xml)[:8])

    url = f"https://arxiv.org/abs/{arxiv_id}"
    body = (
        f"# {title}\n\n**arXiv:** [{arxiv_id}]({url})\n**Authors:** {authors}\n\n"
        f"## Abstract\n\n{abstract}"
    )
    doc, created = store_source(
        db,
        title=title,
        body=body,
        subtype="arxiv",
        url=url,
        extra={"arxiv_id": arxiv_id, "authors": authors},
        slug_hint=arxiv_id,
        log_label=f"arXiv: {title}",
    )

    if created:
        # Links to the source, not to itself — the note used to cite its own slug.
        upsert_literature_note(
            db,
            doc,
            title=f"Source summary: {title}",
            body=(
                f"# Source summary: {title}\n\n**Source:** [[{doc.slug}|{title}]]\n\n"
                f"**Authors:** {authors}\n\n## Abstract\n\n{abstract}\n"
            ),
            tags=["source-summary", "arxiv"],
        )
    return _result(doc, created)


# --- YouTube ------------------------------------------------------------------


def extract_video_id(url_or_id: str) -> str:
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", url_or_id.strip()):
        return url_or_id.strip()
    for pattern in (
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
        r"(?:v=|/embed/|/shorts/|/live/)([a-zA-Z0-9_-]{11})",
    ):
        m = re.search(pattern, url_or_id)
        if m:
            return m.group(1)
    raise FetchError(f"Could not find a YouTube video id in: {url_or_id}")


def list_channel_videos(url: str, limit: int | None = None) -> list[dict]:
    """List a channel or playlist without downloading anything.

    Metadata only — each video is then ingested through the normal captions path, so one
    failure does not take the batch with it.
    """
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "socket_timeout": 30,
    }
    if limit:
        opts["playlistend"] = limit

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    entries = info.get("entries") or []
    out = []
    for e in entries:
        vid = e.get("id")
        if not vid or len(vid) != 11:
            continue
        out.append(
            {
                "id": vid,
                "title": e.get("title") or vid,
                "duration": e.get("duration"),
            }
        )
    return out


def fetch_youtube_metadata(vid: str) -> dict:
    meta_url = (
        f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json"
    )
    try:
        _, body = fetch_text(meta_url, timeout=15)
        return json.loads(body)
    except Exception as exc:
        logger.warning("YouTube metadata lookup failed for %s: %s", vid, exc)
        return {}


class CaptionsBlocked(FetchError):
    """YouTube refused the request. Not the same as a video having no captions."""


# Phrases YouTube uses when it is refusing a datacenter IP rather than reporting an absence.
_BLOCKED_SIGNS = (
    "ipblocked",
    "requestblocked",
    "too many requests",
    "sign in to confirm",
    "not a bot",
    "blocked",
    "429",
)


def fetch_youtube_transcript(vid: str) -> str | None:
    """Fetch captions. Returns None only when the video genuinely has none.

    Raises CaptionsBlocked when YouTube refuses us — which is what happens from a cloud
    host. Reporting that as "no captions" sent people toward speech-to-text, which costs
    money and is blocked from the same address.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        logger.warning("youtube-transcript-api is not installed")
        return None
    try:
        fetched = YouTubeTranscriptApi().fetch(vid)
        snippets = getattr(fetched, "snippets", fetched)
        parts = [(s.text if hasattr(s, "text") else s.get("text", "")) for s in snippets]
        return "\n".join(p for p in parts if p).strip() or None
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        if any(sign in detail.lower() for sign in _BLOCKED_SIGNS):
            logger.warning("YouTube refused captions for %s: %s", vid, detail[:200])
            raise CaptionsBlocked(
                "YouTube is refusing caption requests from this server — cloud IP ranges are "
                "commonly blocked. Fetch the captions from a home connection and import them, "
                "rather than paying for speech-to-text that will be refused too."
            ) from exc
        logger.info("No captions for %s: %s", vid, detail[:200])
        return None


def ingest_youtube(db: Session, url_or_id: str) -> dict:
    vid = extract_video_id(url_or_id)
    meta = fetch_youtube_metadata(vid)
    title = meta.get("title") or f"YouTube {vid}"
    channel = meta.get("author_name") or "Unknown"

    transcript = fetch_youtube_transcript(vid)
    if transcript is None:
        raise FetchError(
            f"'{title}' has no captions. Use 'Transcribe audio' to run speech-to-text on it."
        )

    url = f"https://www.youtube.com/watch?v={vid}"
    body = clamp(
        f"# {title}\n\n**Channel:** {channel}\n**Video:** [{url}]({url})\n\n"
        f"## Transcript\n\n{transcript}"
    )
    doc, created = store_source(
        db,
        title=title,
        body=body,
        subtype="youtube",
        url=url,
        extra={"channel": channel, "video_id": vid, "transcript_source": "captions"},
        slug_hint=vid,
        log_label=f"YouTube: {title}",
    )
    return _result(doc, created)


# --- files and text -----------------------------------------------------------


def extract_pdf_text(path: Path, max_pages: int = MAX_PDF_PAGES) -> tuple[str, str]:
    """Return (title, text). Title comes from PDF metadata, falling back to the filename."""
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise ValueError("This PDF is password protected") from exc

    try:
        title = (reader.metadata.title or "").strip() if reader.metadata else ""
    except Exception:
        title = ""
    title = title or path.stem.replace("_", " ").replace("-", " ").strip()

    chunks = []
    for i, page in enumerate(reader.pages):
        if i >= max_pages:
            chunks.append(f"\n\n*(stopped after {max_pages} pages)*")
            break
        try:
            chunks.append(page.extract_text() or "")
        except Exception as exc:
            logger.warning("Failed to extract page %d of %s: %s", i, path.name, exc)

    text = "\n\n".join(c.strip() for c in chunks if c and c.strip())
    if not text.strip():
        raise ValueError(
            "No text could be extracted — this looks like a scanned PDF, which would need "
            "OCR. This wiki does not do OCR."
        )
    return title, text


def ingest_pdf(
    db: Session, path: Path, title: str | None = None, filename: str | None = None
) -> dict:
    extracted_title, text = extract_pdf_text(path)
    display_name = filename or path.name
    title = (title or extracted_title).strip() or Path(display_name).stem
    body = clamp(f"# {title}\n\n**Source:** uploaded PDF ({display_name})\n\n---\n\n{text}")
    doc, created = store_source(
        db,
        title=title,
        body=body,
        subtype="pdf",
        extra={"filename": display_name},
        slug_hint=Path(display_name).stem,
        log_label=f"PDF: {title}",
    )
    return _result(doc, created)


def ingest_paste(db: Session, title: str, text: str) -> dict:
    title = (title or "").strip()
    if not title:
        raise ValueError("Title is required")
    if not (text or "").strip():
        raise ValueError("Text is required")
    doc, created = store_source(
        db,
        title=title,
        body=clamp(f"# {title}\n\n{text.strip()}"),
        subtype="note",
        log_label=f"Pasted: {title}",
    )
    return _result(doc, created)


def _result(doc: Document, created: bool) -> dict:
    return {"slug": doc.slug, "title": doc.title, "type": doc.subtype, "created": created}


# --- AI -----------------------------------------------------------------------


def ai_summarize(db: Session, source_slug: str) -> dict:
    src = get_doc(db, source_slug)
    if not src:
        raise ValueError(f"Nothing found at '{source_slug}'")

    summary = call_llm(
        f"SOURCE: {src.title}\n\n{(src.body or '')[:SUMMARIZE_CHARS]}\n\n"
        "Write a Literature Note in markdown with: a two-sentence summary, 3-6 key takeaways "
        "as bullets, and a '## Concepts' section listing the atomic concepts worth their own "
        "note as [[wikilink]] items.",
        "You are an expert knowledge base summarizer. Output markdown only.",
    )
    header = f"# Source summary: {src.title}\n\n**Source:** [[{src.slug}|{src.title}]]\n\n"
    if src.url:
        header += f"**Original:** [{src.url}]({src.url})\n\n"

    note = upsert_literature_note(
        db,
        src,
        title=f"Source summary: {src.title}",
        body=f"{header}{summary}\n",
        tags=["source-summary", "ai-generated"],
    )
    return {"slug": note.slug, "title": note.title, "source_slug": src.slug}


SYSTEM_PROMPT = "You answer strictly from the provided wiki context. Use wikilinks for citations."

NO_CONTEXT = "Nothing in the wiki matches that question yet. Add a source first."


def retrieve(db: Session, question: str) -> tuple[str, list[dict]]:
    """Find the documents that should answer a question. Returns (prompt, citations).

    Retrieval takes a fraction of a second, so callers can show the citations immediately
    and let the much slower generation fill in underneath.
    """
    from wiki_api.services.search import search

    # match_all=False: a question shares only a word or two with the note that answers it.
    results = search(db, question, top_k=5, match_all=False)
    if not results:
        return "", []

    slugs = [r["slug"] for r in results]
    docs = {d.slug: d for d in db.query(Document).filter(Document.slug.in_(slugs)).all()}

    context_parts, citations = [], []
    for slug in slugs:
        doc = docs.get(slug)
        if not doc:
            continue
        context_parts.append(
            f"--- {doc.slug} ({doc.title}) ---\n{(doc.body or '')[:RAG_CHARS_PER_DOC]}\n---"
        )
        citations.append({"slug": doc.slug, "title": doc.title, "doc_class": doc.doc_class})

    prompt = (
        f"QUESTION: {question}\n\nWIKI CONTEXT:\n" + "\n\n".join(context_parts) + "\n\n"
        "Answer using only the context above. Cite with [[slug|Title]] wikilinks, using the "
        "exact slug shown in each context header. If the context does not answer the "
        "question, say so plainly."
    )
    return prompt, citations


def ai_query(db: Session, question: str) -> dict:
    prompt, citations = retrieve(db, question)
    if not prompt:
        return {"answer": NO_CONTEXT, "citations": []}
    return {"answer": call_llm(prompt, SYSTEM_PROMPT), "citations": citations}
