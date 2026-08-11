"""Knowledge graph from database pages."""

from __future__ import annotations

from sqlalchemy.orm import Session

from wiki_api.database import Page
from wiki_api.services.content import resolve_slug
from wiki_core.utils import parse_wikilinks


def build_graph(db: Session) -> dict:
    pages = db.query(Page).all()
    slug_set = {p.slug for p in pages}
    nodes = []
    edges = []
    inbound: dict[str, int] = {p.slug: 0 for p in pages}

    for p in pages:
        nodes.append(
            {
                "id": p.slug,
                "slug": p.slug,
                "title": p.title,
                "type": p.page_type,
                "link_count": 0,
            }
        )

    for p in pages:
        for link in parse_wikilinks(p.body):
            target = resolve_slug(db, link.target)
            if target and target in slug_set and target != p.slug:
                edges.append({"source": p.slug, "target": target})
                inbound[target] = inbound.get(target, 0) + 1

    out_count: dict[str, int] = {}
    for e in edges:
        out_count[e["source"]] = out_count.get(e["source"], 0) + 1

    for n in nodes:
        n["link_count"] = inbound.get(n["slug"], 0) + out_count.get(n["slug"], 0)

    return {"nodes": nodes, "edges": edges}


def stats(db: Session) -> dict:
    pages = db.query(Page).all()
    from wiki_core.utils import WIKILINK_RE

    total_links = sum(len(WIKILINK_RE.findall(p.body)) for p in pages)
    return {
        "total_pages": len(pages),
        "zettels": sum(1 for p in pages if p.page_type == "zettel"),
        "concepts": sum(1 for p in pages if p.page_type == "concept"),
        "entities": sum(1 for p in pages if p.page_type == "entity"),
        "literature": sum(1 for p in pages if p.page_type in ("literature", "source")),
        "mocs": sum(1 for p in pages if p.page_type == "moc"),
        "total_wikilinks": total_links,
        "avg_links_per_page": round(total_links / len(pages), 2) if pages else 0,
    }
