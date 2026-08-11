"""Guarded outbound HTTP.

Every fetch of a user-supplied URL goes through here. Plain urllib.urlopen honours file://
and ftp://, follows redirects to anywhere, and resp.read() has no size limit — so an
unguarded ingest could read local files or cloud metadata and store them where the public
search endpoint would serve them back.
"""

from __future__ import annotations

import html as html_module
import ipaddress
import logging
import re
import socket
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; LLMWiki/0.3; +https://github.com/gopalshivapuja/ai-wiki)"

MAX_HTML_BYTES = 2_000_000
MAX_PDF_BYTES = 25_000_000
MAX_AUDIO_BYTES = 100_000_000
MAX_STORED_CHARS = 400_000  # keeps bodies under the tsvector limit; see schema_ddl.py

DEFAULT_TIMEOUT = 20


class FetchError(ValueError):
    """A URL was rejected or could not be fetched. Safe to show to the user."""


def _check_host(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchError(f"Only http and https URLs are allowed (got '{parsed.scheme or url}')")
    host = parsed.hostname
    if not host:
        raise FetchError("URL has no host")

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise FetchError(f"Could not resolve host '{host}': {exc}") from exc

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local  # 169.254.x.x — cloud instance metadata
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise FetchError(f"Refusing to fetch a private or internal address ({ip})")


def _open(url: str, timeout: int):
    _check_host(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} fetching {url}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"Could not fetch {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise FetchError(f"Timed out fetching {url}") from exc


def fetch_text(
    url: str,
    *,
    max_bytes: int = MAX_HTML_BYTES,
    timeout: int = DEFAULT_TIMEOUT,
    expect_html: bool = False,
) -> tuple[str, str]:
    """Fetch a URL as text. Returns (content_type, body). Reads at most max_bytes."""
    with _open(url, timeout) as resp:
        content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if expect_html and content_type and not content_type.startswith("text/html"):
            raise FetchError(f"Expected HTML, got '{content_type}'")
        raw = resp.read(max_bytes + 1)
    if len(raw) > max_bytes:
        logger.warning("Truncated %s at %d bytes", url, max_bytes)
        raw = raw[:max_bytes]
    charset = "utf-8"
    m = re.search(rb'charset=["\']?([\w-]+)', raw[:2000], re.IGNORECASE)
    if m:
        charset = m.group(1).decode("ascii", errors="ignore") or "utf-8"
    try:
        return content_type, raw.decode(charset, errors="ignore")
    except LookupError:
        return content_type, raw.decode("utf-8", errors="ignore")


def download_to_file(
    url: str, dest: Path, *, max_bytes: int, timeout: int = 60, chunk: int = 65536
) -> Path:
    """Stream a URL to disk without ever holding it all in memory."""
    total = 0
    with _open(url, timeout) as resp, dest.open("wb") as fh:
        while True:
            block = resp.read(chunk)
            if not block:
                break
            total += len(block)
            if total > max_bytes:
                fh.close()
                dest.unlink(missing_ok=True)
                raise FetchError(f"File exceeds the {max_bytes // 1_000_000}MB limit")
            fh.write(block)
    return dest


def clamp(text: str, limit: int = MAX_STORED_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n*(truncated at {limit:,} characters)*"


def html_to_markdown(html: str, *, main_content: bool = True) -> str:
    """Convert HTML to markdown, dropping page chrome when possible."""
    if main_content:
        html = extract_main_content(html)
    try:
        import html2text
    except ImportError:  # pragma: no cover - html2text is a hard dependency
        return re.sub(r"<[^>]+>", "", html)
    conv = html2text.HTML2Text()
    conv.ignore_images = True
    conv.body_width = 0
    conv.ignore_emphasis = False
    return conv.handle(html)


def extract_main_content(html: str) -> str:
    """Strip nav/header/footer/script chrome and prefer <main>/<article> when present.

    Matters most for docs sites, where the sidebar tree would otherwise dominate every page.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:  # pragma: no cover
        return html

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    for selector in ("main", "article", "[role=main]", "#content", ".content", ".markdown-body"):
        node = soup.select_one(selector)
        if node and len(node.get_text(strip=True)) > 200:
            return str(node)
    body = soup.body
    return str(body) if body else str(soup)


def _clean_title(raw: str) -> str:
    # Entities must be decoded before slugify sees them, or "&#8212;" becomes the literal
    # token "8212" in the slug.
    text = html_module.unescape(re.sub(r"<[^>]+>", "", raw))
    text = re.sub(r"\s+", " ", text).strip()
    # Drop the boilerplate site suffix docs sites append to every single page.
    text = re.split(r"\s+[\u2014\u2013|\u00b7]\s+", text)[0].strip() or text
    return text[:200]


def page_title(html: str, fallback: str) -> str:
    for pattern in (r"<title[^>]*>(.*?)</title>", r"<h1[^>]*>(.*?)</h1>"):
        m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if m:
            title = _clean_title(m.group(1))
            if title:
                return title
    return fallback
