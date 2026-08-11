"""Knowledge graph from database pages."""

from __future__ import annotations

from sqlalchemy.orm import Session
from wiki_core.utils import WIKILINK_RE, parse_wikilinks

from wiki_api.database import Page, RawSource
from wiki_api.services.content import build_slug_index


def build_graph(db: Session) -> dict:
    index = build_slug_index(db)
    rows = db.query(Page.slug, Page.title, Page.page_type, Page.body).all()

    nodes = [
        {"id": slug, "slug": slug, "title": title, "type": ptype, "link_count": 0}
        for slug, title, ptype, _ in rows
    ]

    edges: list[dict] = []
    seen_edges: set[tuple[str, str]] = set()
    degree: dict[str, int] = {slug: 0 for slug, _, _, _ in rows}

    for slug, _, _, body in rows:
        for link in parse_wikilinks(body or ""):
            target = index.resolve(link.target)
            if not target or target == slug or target not in degree:
                continue
            key = (slug, target)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edges.append({"source": slug, "target": target})
            degree[slug] += 1
            degree[target] += 1

    for n in nodes:
        n["link_count"] = degree.get(n["slug"], 0)

    return {"nodes": nodes, "edges": edges}


def stats(db: Session) -> dict:
    rows = db.query(Page.page_type, Page.body).all()
    total_links = sum(len(WIKILINK_RE.findall(body or "")) for _, body in rows)
    types = [ptype for ptype, _ in rows]
    return {
        "total_pages": len(rows),
        "total_sources": db.query(RawSource).count(),
        "zettels": types.count("zettel"),
        "concepts": types.count("concept"),
        "entities": types.count("entity"),
        "literature": sum(1 for t in types if t in ("literature", "source")),
        "mocs": types.count("moc"),
        "total_wikilinks": total_links,
        "avg_links_per_page": round(total_links / len(rows), 2) if rows else 0,
    }
