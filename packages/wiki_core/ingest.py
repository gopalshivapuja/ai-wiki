"""Source ingestion pipelines."""

from __future__ import annotations

import datetime
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from wiki_core.config import SOURCES_DIR, WIKI_DIR, ensure_directories
from wiki_core.log import append_log
from wiki_core.slug import slugify


def ingest_arxiv(id_or_url: str) -> str:
    ensure_directories()
    m = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?)", id_or_url)
    arxiv_id = m.group(1) if m else id_or_url.strip()
    api_url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
    req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        xml = resp.read().decode("utf-8")

    title = f"arXiv Paper {arxiv_id}"
    if "<entry>" in xml:
        entry = xml.split("<entry>")[1]
        tm = re.search(r"<title>(.*?)</title>", entry, re.DOTALL)
        if tm:
            title = tm.group(1).strip().replace("\n", " ")
    summary_m = re.search(r"<summary>(.*?)</summary>", xml, re.DOTALL)
    summary = summary_m.group(1).strip().replace("\n", " ") if summary_m else ""
    authors = re.findall(r"<name>(.*?)</name>", xml)
    authors_str = ", ".join(authors[:5]) if authors else "Unknown"

    slug = slugify(title) or f"arxiv-{arxiv_id}"
    filename = f"{slug}.md"
    target = SOURCES_DIR / "pdfs" / filename
    today = datetime.date.today().isoformat()
    target.write_text(
        f"""---
title: "{title}"
type: pdf_source
arxiv_id: "{arxiv_id}"
url: "https://arxiv.org/abs/{arxiv_id}"
authors: "{authors_str}"
ingested: {today}
---

# {title}

**arXiv:** [{arxiv_id}](https://arxiv.org/abs/{arxiv_id})
**Authors:** {authors_str}

## Abstract

{summary}
""",
        encoding="utf-8",
    )
    lit = WIKI_DIR / "sources" / filename
    uid = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    lit.write_text(
        f"""---
uid: "{uid}"
title: "Source Summary: {title}"
type: literature
created: {today}
updated: {today}
tags: [source-summary, arxiv]
sources:
  - "sources/pdfs/{filename}"
---

# Source Summary: {title}

**Source:** [[{slug}|{title}]]
**Authors:** {authors_str}

## Abstract

{summary}
""",
        encoding="utf-8",
    )
    append_log("ingest", f"arXiv: '{title}' ({arxiv_id})")
    return str(target)


def _extract_youtube_id(url_or_id: str) -> str:
    if len(url_or_id) == 11 and re.match(r"^[a-zA-Z0-9_-]{11}$", url_or_id):
        return url_or_id
    for p in (
        r"(?:v=|\/)([a-zA-Z0-9_-]{11})(?:[&?\/]|$)",
        r"youtu\.be\/([a-zA-Z0-9_-]{11})",
        r"youtube\.com\/embed\/([a-zA-Z0-9_-]{11})",
    ):
        m = re.search(p, url_or_id)
        if m:
            return m.group(1)
    return url_or_id


def ingest_youtube(url_or_id: str) -> str:
    ensure_directories()
    video_id = _extract_youtube_id(url_or_id)
    meta_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
    try:
        req = urllib.request.Request(meta_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp:
            meta = json.loads(resp.read().decode("utf-8"))
    except Exception:
        meta = {"title": f"YouTube {video_id}", "author_name": "Unknown"}

    title = meta.get("title", video_id)
    channel = meta.get("author_name", "Unknown")
    transcript = ""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        entries = YouTubeTranscriptApi.get_transcript(video_id)
        transcript = "\n\n".join(e["text"] for e in entries)
    except Exception as e:
        transcript = f"*(Transcript unavailable: {e})*"

    slug = slugify(title) or f"youtube-{video_id}"
    target = SOURCES_DIR / "youtube" / f"{slug}.md"
    today = datetime.date.today().isoformat()
    target.write_text(
        f"""---
title: "{title}"
type: youtube_source
video_id: "{video_id}"
url: "https://www.youtube.com/watch?v={video_id}"
channel: "{channel}"
ingested: {today}
---

# {title}

**Channel:** {channel}

## Transcript

{transcript}
""",
        encoding="utf-8",
    )
    append_log("ingest", f"YouTube: '{title}'")
    return str(target)


def ingest_web(url: str) -> str:
    ensure_directories()
    headers = {"User-Agent": "Mozilla/5.0 (compatible; LLMWiki/1.0)"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        html = resp.read().decode("utf-8", errors="ignore")

    title = url
    tm = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if tm:
        title = re.sub(r"\s+", " ", tm.group(1).strip())

    try:
        import html2text

        h = html2text.HTML2Text()
        h.ignore_images = True
        h.body_width = 0
        body = h.handle(html)
    except ImportError:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        body = soup.get_text(separator="\n\n")

    slug = slugify(title) or "web-article"
    target = SOURCES_DIR / "web" / f"{slug}.md"
    today = datetime.date.today().isoformat()
    target.write_text(
        f"""---
title: "{title}"
type: web_source
url: "{url}"
ingested: {today}
---

# {title}

**URL:** [{url}]({url})

---

{body}
""",
        encoding="utf-8",
    )
    append_log("ingest", f"Web: '{title}'")
    return str(target)


def ingest_pdf(pdf_path: str) -> str:
    ensure_directories()
    path = Path(pdf_path).resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    title = path.stem.replace("_", " ").replace("-", " ").title()
    pages_text: list[str] = []
    try:
        import pypdf

        reader = pypdf.PdfReader(str(path))
        for idx, page in enumerate(reader.pages, 1):
            pages_text.append(f"### Page {idx}\n\n{page.extract_text() or ''}")
    except ImportError:
        pages_text.append("*(Install pypdf to extract text)*")

    slug = slugify(path.stem)
    target = SOURCES_DIR / "pdfs" / f"{slug}.md"
    today = datetime.date.today().isoformat()
    target.write_text(
        f"""---
title: "{title}"
type: pdf_source
original_file: "{path.name}"
ingested: {today}
---

# {title}

## Extracted Text

{chr(10).join(pages_text)}
""",
        encoding="utf-8",
    )
    append_log("ingest", f"PDF: '{title}'")
    return str(target)
