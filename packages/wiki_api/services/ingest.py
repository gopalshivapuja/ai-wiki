"""Ingest pipelines — write directly to PostgreSQL."""

from __future__ import annotations

import json
import logging
import re
import urllib.parse

from sqlalchemy.orm import Session
from wiki_core.llm import call_llm
from wiki_core.utils import slugify

from wiki_api.database import RawSource
from wiki_api.services.content import (
    log_action,
    new_uid,
    summary_slug,
    upsert_page,
    upsert_source,
)
from wiki_api.services.fetch import (
    FetchError,
    clamp,
    fetch_text,
    html_to_markdown,
    page_title,
)

logger = logging.getLogger(__name__)

# Cap on how much of each retrieved page is fed to the model. Without it, five long pages
# produce a prompt big enough for the provider to reject outright.
RAG_CHARS_PER_PAGE = 4_000
SUMMARIZE_CHARS = 8_000


def ingest_web(db: Session, url: str, collection: str | None = None) -> dict:
    _, html = fetch_text(url, expect_html=False)
    title = page_title(html, url)
    md = html_to_markdown(html)

    slug = slugify(title) or f"web-{abs(hash(url)) % 10**8}"
    content = clamp(f"# {title}\n\n**Source:** [{url}]({url})\n\n---\n\n{md}")
    source, created = upsert_source(db, slug, title, content, "web", url=url, collection=collection)
    if created:
        log_action(db, "ingest", f"Web: {title}")
    return {"slug": source.slug, "title": source.title, "type": "web", "created": created}


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
    summary = re.sub(r"\s+", " ", sm.group(1)).strip() if sm else ""
    authors = ", ".join(re.findall(r"<name>(.*?)</name>", xml)[:8])

    slug = slugify(title) or f"arxiv-{slugify(arxiv_id)}"
    url = f"https://arxiv.org/abs/{arxiv_id}"
    content = (
        f"# {title}\n\n**arXiv:** [{arxiv_id}]({url})\n**Authors:** {authors}\n\n"
        f"## Abstract\n\n{summary}"
    )
    source, created = upsert_source(
        db,
        slug,
        title,
        content,
        "arxiv",
        url=url,
        extra={"arxiv_id": arxiv_id, "authors": authors},
    )

    # The literature note gets its own namespaced slug so it can never overwrite a curated
    # page about the same paper.
    note_slug = summary_slug(source.slug)
    note_body = (
        f"# Source Summary: {title}\n\n**Source:** [[{note_slug}|{title}]]\n\n"
        f"**Authors:** {authors}\n\n## Abstract\n\n{summary}\n"
    )
    upsert_page(
        db,
        note_slug,
        f"Source Summary: {title}",
        note_body,
        "literature",
        uid=new_uid(),
        tags=["source-summary", "arxiv"],
        source_refs=[source.slug],
        protect_curated=True,
    )
    if created:
        log_action(db, "ingest", f"arXiv: {title}")
    return {"slug": source.slug, "title": title, "type": "arxiv", "created": created}


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


def fetch_youtube_transcript(vid: str) -> str | None:
    """Fetch captions. Returns None when the video has none.

    youtube-transcript-api 1.x removed the YouTubeTranscriptApi.get_transcript classmethod
    in favour of an instance .fetch(); the old call failed for every video and the error was
    swallowed into the stored body.
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        logger.warning("youtube-transcript-api is not installed")
        return None

    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(vid)
        snippets = getattr(fetched, "snippets", fetched)
        parts = [(s.text if hasattr(s, "text") else s.get("text", "")) for s in snippets]
        text = "\n".join(p for p in parts if p).strip()
        return text or None
    except Exception as exc:
        logger.info("No transcript for %s: %s", vid, exc)
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

    slug = slugify(title) or f"youtube-{vid}"
    url = f"https://www.youtube.com/watch?v={vid}"
    content = clamp(
        f"# {title}\n\n**Channel:** {channel}\n**Video:** [{url}]({url})\n\n"
        f"## Transcript\n\n{transcript}"
    )
    source, created = upsert_source(
        db,
        slug,
        title,
        content,
        "youtube",
        url=url,
        extra={"channel": channel, "video_id": vid, "transcript_source": "captions"},
    )
    if created:
        log_action(db, "ingest", f"YouTube: {title}")
    return {"slug": source.slug, "title": title, "type": "youtube", "created": created}


def ai_summarize(db: Session, source_slug: str) -> dict:
    src = db.query(RawSource).filter(RawSource.slug == source_slug).first()
    if not src:
        raise ValueError(f"Source not found: {source_slug}")

    summary = call_llm(
        f"SOURCE: {src.title}\n\n{(src.body or '')[:SUMMARIZE_CHARS]}\n\n"
        "Write a Literature Note in markdown with: a two-sentence summary, 3-6 key "
        "takeaways as bullets, and a '## Concepts' section listing the atomic concepts "
        "worth their own note as [[wikilink]] items.",
        "You are an expert knowledge base summarizer. Output markdown only.",
    )
    note_slug = summary_slug(src.slug)
    header = f"# Source Summary: {src.title}\n\n"
    if src.url:
        header += f"**Source:** [{src.url}]({src.url})\n\n"
    body = f"{header}{summary}\n"
    page = upsert_page(
        db,
        note_slug,
        f"Source Summary: {src.title}",
        body,
        "literature",
        uid=new_uid(),
        tags=["source-summary", "ai-generated"],
        source_refs=[src.slug],
        protect_curated=True,
    )
    log_action(db, "ai-summarize", f"Summarized {src.slug}")
    return {"slug": page.slug, "title": page.title, "source_slug": src.slug}


def ai_query(db: Session, question: str) -> dict:
    from wiki_api.database import Page
    from wiki_api.services.search import search

    results = search(db, question, top_k=5)
    context_parts = []
    citations = []
    for r in results:
        if r["kind"] == "page":
            row = db.query(Page.slug, Page.title, Page.body).filter(Page.slug == r["slug"]).first()
        else:
            row = (
                db.query(RawSource.slug, RawSource.title, RawSource.body)
                .filter(RawSource.slug == r["slug"])
                .first()
            )
        if not row:
            continue
        slug, title, body = row
        context_parts.append(f"--- {slug} ({title}) ---\n{(body or '')[:RAG_CHARS_PER_PAGE]}\n---")
        citations.append({"slug": slug, "title": title, "kind": r["kind"]})

    if not context_parts:
        return {
            "answer": "Nothing in the wiki matches that question yet. Add a source first.",
            "citations": [],
        }

    context = "\n\n".join(context_parts)
    answer = call_llm(
        f"QUESTION: {question}\n\nWIKI CONTEXT:\n{context}\n\n"
        "Answer using only the context above. Cite with [[slug|Title]] wikilinks. "
        "If the context does not answer the question, say so plainly.",
        "You answer strictly from the provided wiki context. Use wikilinks for citations.",
    )
    log_action(db, "query", question[:100])
    return {"answer": answer, "citations": citations}
