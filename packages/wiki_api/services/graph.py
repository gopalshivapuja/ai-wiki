"""Knowledge graph and statistics over documents."""

from __future__ import annotations

from sqlalchemy.orm import Session
from wiki_core.utils import count_wikilinks, parse_wikilinks

from wiki_api.database import NOTE, SOURCE, Document
from wiki_api.services.content import build_link_index


def build_graph(db: Session, include_sources: bool = True) -> dict:
    index = build_link_index(db)
    q = db.query(Document.slug, Document.title, Document.subtype, Document.doc_class, Document.body)
    if not include_sources:
        q = q.filter(Document.doc_class != SOURCE)
    rows = q.all()

    nodes = [
        {
            "id": slug,
            "slug": slug,
            "title": title,
            "type": subtype,
            "doc_class": doc_class,
            "link_count": 0,
        }
        for slug, title, subtype, doc_class, _ in rows
    ]

    known = {slug for slug, _, _, _, _ in rows}
    edges: list[dict] = []
    seen: set[tuple[str, str]] = set()
    degree: dict[str, int] = dict.fromkeys(known, 0)

    for slug, _, _, _, body in rows:
        for link in parse_wikilinks(body or ""):
            target = index.resolve(link.target)
            if not target or target == slug or target not in known:
                continue
            key = (slug, target)
            if key in seen:
                continue
            seen.add(key)
            edges.append({"source": slug, "target": target})
            degree[slug] += 1
            degree[target] += 1

    for n in nodes:
        n["link_count"] = degree.get(n["slug"], 0)

    return {"nodes": nodes, "edges": edges}


def orphans(db: Session) -> dict:
    """Notes nothing links to, and links pointing at notes that do not exist yet.

    The Zettelkasten invariant every note is supposed to satisfy — without this the graph
    quietly degrades into a folder of disconnected files.
    """
    index = build_link_index(db)
    rows = db.query(Document.slug, Document.title, Document.doc_class, Document.body).all()

    linked_to: set[str] = set()
    missing: dict[str, int] = {}
    for slug, _, _, body in rows:
        for link in parse_wikilinks(body or ""):
            target = index.resolve(link.target)
            if target and target != slug:
                linked_to.add(target)
            elif not target:
                missing[link.target.strip()] = missing.get(link.target.strip(), 0) + 1

    unlinked = [
        {"slug": slug, "title": title}
        for slug, title, doc_class, _ in rows
        if doc_class == NOTE and slug not in linked_to
    ]
    wanted = [
        {"target": t, "mentions": c}
        for t, c in sorted(missing.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return {"unlinked": unlinked, "wanted": wanted}


def stats(db: Session) -> dict:
    rows = db.query(Document.doc_class, Document.subtype, Document.body).all()
    notes = [(s, b) for c, s, b in rows if c == NOTE]
    sources = [s for c, s, _ in rows if c == SOURCE]
    total_links = sum(count_wikilinks(b or "") for _, b in notes)
    subtypes = [s for s, _ in notes]

    return {
        "total_notes": len(notes),
        "total_sources": len(sources),
        "zettels": subtypes.count("zettel"),
        "concepts": subtypes.count("concept"),
        "entities": subtypes.count("entity"),
        "literature": subtypes.count("literature"),
        "mocs": subtypes.count("moc"),
        "total_wikilinks": total_links,
        "avg_links_per_note": round(total_links / len(notes), 2) if notes else 0,
    }
