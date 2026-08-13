"""An MCP server that lets a language model read the wiki.

Runs on your machine over stdio and talks to the deployed wiki over HTTP, so nothing about the
hosted app changes and no second copy of the data exists:

    WIKI_URL=https://…up.railway.app WIKI_TOKEN=… python -m wiki_mcp.server

The tools mirror how the wiki is meant to be traversed: start from a map of content, search
when you know the words, read a note, then follow its links. `read_note` returns outgoing
links and backlinks alongside the body precisely so the next hop needs no guessing.

Deliberately read-only. An agent that can rewrite notes unsupervised is a different and much
larger decision than one that can read them.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from mcp.server.mcpserver import MCPServer

TIMEOUT = 60

server = MCPServer(
    name="ai-wiki",
    instructions=(
        "A private Zettelkasten of notes and captured sources. Call wiki_overview first if "
        "you do not know what it contains; prefer reading a map of content before searching, "
        "since it gives you the vocabulary this wiki actually uses. Notes tagged 'unreviewed' "
        "were written by a model and not checked by a human — weigh them accordingly."
    ),
)


class WikiError(RuntimeError):
    """Something the model should read and correct, not a crash."""


def _base() -> str:
    return os.environ.get("WIKI_URL", "http://localhost:8000").rstrip("/")


def _token() -> str:
    token = os.environ.get("WIKI_TOKEN", "")
    if not token:
        raise WikiError("WIKI_TOKEN is not set; the wiki is private and every route needs it.")
    return token


def _request(path: str, params: dict | None = None, body: dict | None = None) -> Any:
    url = f"{_base()}/api{path}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    headers = {"Authorization": f"Bearer {_token()}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            raw = response.read().decode()
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise WikiError("The wiki rejected the token (401). Check WIKI_TOKEN.") from exc
        if exc.code == 404:
            raise WikiError(f"Nothing found at '{path}'.") from exc
        raise WikiError(f"{path} failed: HTTP {exc.code}: {exc.read().decode()[:300]}") from exc
    except urllib.error.URLError as exc:
        raise WikiError(f"Could not reach the wiki at {_base()}: {exc.reason}") from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


@server.tool()
def wiki_overview() -> str:
    """What this wiki contains, its maps of content, and how to traverse it.

    Call this first when you do not yet know what is in the wiki.
    """
    return _request("/llms.txt")


@server.tool()
def search_wiki(query: str, limit: int = 10, include_sources: bool = True) -> list[dict]:
    """Full-text search across notes and captured sources.

    Returns slug, title and a matching snippet. Pass a slug to read_note for the full text.

    Args:
        query: Words to search for.
        limit: Maximum results, 1-50.
        include_sources: Include captured sources as well as notes.
    """
    got = _request(
        "/search",
        {
            "q": query,
            "limit": max(1, min(limit, 50)),
            "include_sources": str(bool(include_sources)).lower(),
        },
    )
    return [
        {
            "slug": r.get("slug"),
            "title": r.get("title"),
            "type": r.get("type"),
            "doc_class": r.get("doc_class"),
            "snippet": r.get("snippet"),
        }
        for r in (got or {}).get("results", [])
    ]


@server.tool()
def read_note(slug: str) -> dict:
    """Read one document in full.

    Returns the markdown body, the links it makes (resolving ones only), and the documents
    that link to it — enough to choose the next hop without another search.

    Args:
        slug: The document's slug, as returned by search_wiki or list_maps.
    """
    doc = _request(f"/documents/{urllib.parse.quote(slug)}")
    return {
        "slug": doc.get("slug"),
        "title": doc.get("title"),
        "type": doc.get("type"),
        "doc_class": doc.get("doc_class"),
        "url": doc.get("url"),
        "tags": doc.get("tags"),
        "unreviewed": "unreviewed" in (doc.get("tags") or []),
        "body": doc.get("body"),
        "links": [
            {"slug": link.get("slug"), "title": link.get("display")}
            for link in doc.get("links") or []
            if link.get("exists") and not link.get("is_self")
        ],
        "backlinks": [
            {"slug": b.get("slug"), "title": b.get("title")} for b in doc.get("backlinks") or []
        ],
    }


@server.tool()
def list_maps() -> list[dict]:
    """List the maps of content — the curated entry points into the wiki.

    Read one of these before searching; it gives you the vocabulary the wiki uses.
    """
    got = _request("/documents", {"doc_class": "note", "type": "moc"})
    return [
        {"slug": d.get("slug"), "title": d.get("title")} for d in (got or {}).get("documents", [])
    ]


@server.tool()
def related_notes(slug: str, hops: int = 1) -> dict:
    """The documents surrounding one document, following links in both directions.

    Args:
        slug: The document at the centre.
        hops: 1 for immediate neighbours, 2 for the wider cluster. Capped at 3.
    """
    got = _request(f"/graph/{urllib.parse.quote(slug)}", {"hops": max(1, min(hops, 3))})
    centre = got.get("center")
    return {
        "center": centre,
        "truncated": got.get("truncated"),
        "nodes": [
            {"slug": n.get("slug"), "title": n.get("title"), "type": n.get("type")}
            for n in got.get("nodes", [])
            if n.get("slug") != centre
        ],
    }


@server.tool()
def ask_wiki(question: str) -> dict:
    """Ask a question and get an answer synthesised from the wiki, with citations.

    Use this for a quick answer. Use search_wiki and read_note when you need the sources
    themselves, or want to reason over them yourself.
    """
    return _request("/llm/query", body={"question": question})


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
