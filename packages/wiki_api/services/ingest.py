"""Ingest pipelines — write directly to PostgreSQL."""

from __future__ import annotations

import datetime
import json
import re
import urllib.request

from sqlalchemy.orm import Session

from wiki_api.services.content import log_action, upsert_page, upsert_source
from wiki_core.llm import call_llm
from wiki_core.utils import slugify


def ingest_web(db: Session, url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; LLMWiki/2.0)"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="ignore")

    title = url
    m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        title = re.sub(r"\s+", " ", m.group(1).strip())

    try:
        import html2text

        body = html2text.HTML2Text()
        body.ignore_images = True
        body.body_width = 0
        md = body.handle(html)
    except ImportError:
        md = re.sub(r"<[^>]+>", "", html)

    slug = slugify(title) or "web-article"
    content = f"# {title}\n\n**URL:** [{url}]({url})\n\n---\n\n{md}"
    upsert_source(db, slug, title, content, "web", url=url)
    log_action(db, "ingest", f"Web: {title}")
    return {"slug": slug, "title": title, "type": "web"}


def ingest_arxiv(db: Session, id_or_url: str) -> dict:
    m = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?)", id_or_url)
    arxiv_id = m.group(1) if m else id_or_url.strip()
    api = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
    req = urllib.request.Request(api, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        xml = resp.read().decode("utf-8")

    title = f"arXiv {arxiv_id}"
    if "<entry>" in xml:
        tm = re.search(r"<title>(.*?)</title>", xml.split("<entry>")[1], re.DOTALL)
        if tm:
            title = tm.group(1).strip().replace("\n", " ")
    sm = re.search(r"<summary>(.*?)</summary>", xml, re.DOTALL)
    summary = sm.group(1).strip().replace("\n", " ") if sm else ""
    authors = ", ".join(re.findall(r"<name>(.*?)</name>", xml)[:5])

    slug = slugify(title) or f"arxiv-{arxiv_id}"
    url = f"https://arxiv.org/abs/{arxiv_id}"
    content = f"# {title}\n\n**arXiv:** [{arxiv_id}]({url})\n**Authors:** {authors}\n\n## Abstract\n\n{summary}"
    upsert_source(db, slug, title, content, "arxiv", url=url, extra={"arxiv_id": arxiv_id, "authors": authors})

    uid = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    lit_body = f"# Source Summary: {title}\n\n**Source:** [[{slug}|{title}]]\n\n## Abstract\n\n{summary}"
    upsert_page(db, slug, f"Source Summary: {title}", lit_body, "literature", uid=uid, tags=["source-summary", "arxiv"])
    log_action(db, "ingest", f"arXiv: {title}")
    return {"slug": slug, "title": title, "type": "arxiv"}


def ingest_youtube(db: Session, url_or_id: str) -> dict:
    vid = url_or_id
    if len(url_or_id) != 11:
        for p in (r"(?:v=|\/)([a-zA-Z0-9_-]{11})", r"youtu\.be\/([a-zA-Z0-9_-]{11})"):
            m = re.search(p, url_or_id)
            if m:
                vid = m.group(1)
                break

    meta_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json"
    try:
        with urllib.request.urlopen(urllib.request.Request(meta_url, headers={"User-Agent": "Mozilla/5.0"})) as r:
            meta = json.loads(r.read().decode())
    except Exception:
        meta = {"title": vid, "author_name": "Unknown"}

    title = meta.get("title", vid)
    channel = meta.get("author_name", "Unknown")
    transcript = ""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        entries = YouTubeTranscriptApi.get_transcript(vid)
        transcript = "\n\n".join(e["text"] for e in entries)
    except Exception as e:
        transcript = f"*(Transcript unavailable: {e})*"

    slug = slugify(title) or f"youtube-{vid}"
    url = f"https://www.youtube.com/watch?v={vid}"
    content = f"# {title}\n\n**Channel:** {channel}\n\n## Transcript\n\n{transcript}"
    upsert_source(db, slug, title, content, "youtube", url=url, extra={"channel": channel, "video_id": vid})
    log_action(db, "ingest", f"YouTube: {title}")
    return {"slug": slug, "title": title, "type": "youtube"}


def ai_summarize(db: Session, source_slug: str) -> dict:
    from wiki_api.database import RawSource

    src = db.query(RawSource).filter(RawSource.slug == source_slug).first()
    if not src:
        raise ValueError(f"Source not found: {source_slug}")

    summary = call_llm(
        f"SOURCE: {src.title}\n\n{src.body[:8000]}\n\nGenerate a Literature Note with summary, takeaways, and [[wikilink]] suggestions.",
        "You are an expert knowledge base summarizer. Output markdown.",
    )
    uid = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
    body = f"# Source Summary: {src.title}\n\n**Source:** [[{src.slug}|{src.title}]]\n\n{summary}"
    upsert_page(db, src.slug, f"Source Summary: {src.title}", body, "literature", uid=uid, tags=["ai-generated"])
    log_action(db, "ai-summarize", f"Summarized {src.slug}")
    return {"slug": src.slug, "title": src.title}


def ai_query(db: Session, question: str) -> str:
    from wiki_api.database import Page
    from wiki_api.services.search import search

    results = search(db, question, top_k=5)
    context_parts = []
    for r in results:
        p = db.query(Page).filter(Page.slug == r["slug"]).first()
        if p:
            context_parts.append(f"--- {p.slug} ---\n{p.body}\n---")
    context = "\n\n".join(context_parts) or "No context found."
    answer = call_llm(
        f"QUESTION: {question}\n\nWIKI CONTEXT:\n{context}\n\nAnswer with [[slug|Title]] citations.",
        "Answer using only the provided wiki context. Use wikilinks for citations.",
    )
    log_action(db, "query", question[:100])
    return answer
