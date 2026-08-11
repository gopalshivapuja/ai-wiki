"""Bounded same-section crawl, for product docs and multi-page articles."""

from __future__ import annotations

import logging
import re
import time
from collections import deque
from collections.abc import Callable
from urllib.parse import urldefrag, urljoin, urlparse

from sqlalchemy.orm import Session
from wiki_core.utils import slugify

from wiki_api.services.content import log_action
from wiki_api.services.fetch import MAX_HTML_BYTES, FetchError, fetch_text
from wiki_api.services.ingest import ingest_web

logger = logging.getLogger(__name__)

DEFAULT_MAX_PAGES = 25
# Server-side ceiling regardless of what the client asks for.
HARD_MAX_PAGES = 50
DEFAULT_MAX_DEPTH = 2
POLITENESS_DELAY = 0.5

_SKIP_EXTENSIONS = re.compile(
    r"\.(png|jpe?g|gif|svg|webp|ico|css|js|zip|tar|gz|pdf|mp4|mp3|woff2?|ttf)(\?|$)",
    re.IGNORECASE,
)

ProgressFn = Callable[[int, int, str], None]
StopFn = Callable[[], bool]


def _normalize(url: str) -> str:
    """Drop the fragment, keeping the path intact.

    The trailing slash is load-bearing: urljoin resolves "next.html" against
    ".../tutorial/" as ".../tutorial/next.html", but against ".../tutorial" as
    ".../next.html" — which 404s across an entire docs site.
    """
    return urldefrag(url)[0]


def _dedupe_key(url: str) -> str:
    """Canonical form for the visited set, so /a and /a/ are not crawled twice."""
    return _normalize(url).rstrip("/")


def _scope_prefix(path: str) -> str:
    """The directory the start URL sits in."""
    if path.endswith("/"):
        return path.rstrip("/")
    return path.rsplit("/", 1)[0]


def in_scope(start: str, candidate: str) -> bool:
    """Same host, and at or below the start URL's directory."""
    s, c = urlparse(start), urlparse(candidate)
    if c.scheme not in ("http", "https") or c.netloc != s.netloc:
        return False
    if _SKIP_EXTENSIONS.search(c.path):
        return False
    # /guide/intro pulls in /guide/setup but not /blog/post. A start URL at the site root
    # crawls the whole host, bounded by max_pages.
    prefix = _scope_prefix(s.path)
    return c.path.startswith(prefix) if prefix else True


def extract_links(html: str, base_url: str) -> list[str]:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        hrefs = [a.get("href") for a in soup.find_all("a", href=True)]
    except ImportError:  # pragma: no cover
        hrefs = re.findall(r'<a[^>]+href=["\']([^"\']+)["\']', html, re.IGNORECASE)

    out, seen = [], set()
    for href in hrefs:
        if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
            continue
        full = _normalize(urljoin(base_url, href))
        if full not in seen:
            seen.add(full)
            out.append(full)
    return out


def crawl_site(
    db: Session,
    start_url: str,
    *,
    collection: str | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    on_progress: ProgressFn | None = None,
    should_stop: StopFn | None = None,
) -> dict:
    """Crawl a docs section. One RawSource per page, all sharing a collection name.

    Page bodies are stored and dropped one at a time — nothing accumulates in memory.
    """
    max_pages = max(1, min(int(max_pages), HARD_MAX_PAGES))
    max_depth = max(0, min(int(max_depth), 5))
    start = _normalize(start_url)
    collection = collection or slugify(urlparse(start).netloc + urlparse(start).path) or "crawl"

    queue: deque[tuple[str, int]] = deque([(start, 0)])
    visited: set[str] = {_dedupe_key(start)}
    created: list[str] = []
    failed: list[dict] = []

    while queue and len(created) < max_pages:
        if should_stop and should_stop():
            logger.info("Crawl of %s cancelled after %d pages", start, len(created))
            break

        url, depth = queue.popleft()
        if on_progress:
            on_progress(len(created), max_pages, f"Fetching {url}")

        try:
            _, html = fetch_text(url, max_bytes=MAX_HTML_BYTES, expect_html=True)
        except FetchError as exc:
            failed.append({"url": url, "error": str(exc)})
            continue

        try:
            result = ingest_web(db, url, collection=collection)
            created.append(result["slug"])
        except Exception as exc:
            failed.append({"url": url, "error": str(exc)})

        if depth < max_depth:
            for link in extract_links(html, url):
                key = _dedupe_key(link)
                if key not in visited and in_scope(start, link):
                    visited.add(key)
                    queue.append((link, depth + 1))

        del html
        time.sleep(POLITENESS_DELAY)

    log_action(db, "crawl", f"Crawled {len(created)} pages from {start} into '{collection}'")
    return {
        "collection": collection,
        "start_url": start,
        "created": created,
        "pages": len(created),
        "failed": failed,
        "reached_limit": len(created) >= max_pages and bool(queue),
    }
