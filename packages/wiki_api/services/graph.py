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


MAX_NEIGHBOURHOOD = 60


def build_neighbourhood(db: Session, slug: str, hops: int = 1) -> dict:
    """The graph immediately around one document.

    A whole-wiki graph is unreadable past a few dozen notes — 400 notes and 1,100 edges draw a
    hairball that answers no question. The question a reader actually has is "what surrounds
    this idea?", which is this.

    Edges are followed in both directions: a note you link to and a note that links to you are
    equally its neighbours.
    """
    full = build_graph(db, include_sources=True)
    by_slug = {n["slug"]: n for n in full["nodes"]}
    if slug not in by_slug:
        return {"nodes": [], "edges": [], "center": slug, "hops": hops, "truncated": False}

    adjacent: dict[str, set[str]] = {}
    for e in full["edges"]:
        adjacent.setdefault(e["source"], set()).add(e["target"])
        adjacent.setdefault(e["target"], set()).add(e["source"])

    keep = {slug}
    frontier = {slug}
    for _ in range(max(1, min(hops, 3))):
        nxt: set[str] = set()
        for node in frontier:
            nxt |= adjacent.get(node, set()) - keep
        if not nxt:
            break
        keep |= nxt
        frontier = nxt

    # A hub can pull in hundreds at two hops, which recreates the hairball at smaller scale.
    # Keep the centre, then the best-connected, so what survives is the meaningful skeleton.
    truncated = len(keep) > MAX_NEIGHBOURHOOD
    if truncated:
        ranked = sorted(keep - {slug}, key=lambda s: -by_slug[s]["link_count"])
        keep = {slug, *ranked[: MAX_NEIGHBOURHOOD - 1]}

    return {
        "nodes": [by_slug[s] for s in keep],
        "edges": [e for e in full["edges"] if e["source"] in keep and e["target"] in keep],
        "center": slug,
        "hops": hops,
        "truncated": truncated,
    }


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
