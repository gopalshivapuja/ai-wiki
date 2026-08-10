"""Knowledge graph builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from wiki_core.config import BASE_DIR, WIKI_DIR
from wiki_core.frontmatter import extract_title, parse_frontmatter
from wiki_core.slug import atomic_slug_from_stem
from wiki_core.wikilinks import WIKILINK_RE, parse_wikilinks, resolve_link


@dataclass
class GraphNode:
    id: str
    slug: str
    title: str
    type: str
    path: str
    link_count: int = 0


@dataclass
class GraphEdge:
    source: str
    target: str


@dataclass
class Graph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)


def canonical_slug(path: Path) -> str:
    return atomic_slug_from_stem(path.stem)


def discover_wiki_pages() -> dict[str, Path]:
    pages: dict[str, Path] = {}
    for p in WIKI_DIR.rglob("*.md"):
        slug = canonical_slug(p)
        pages[slug] = p
        pages[p.stem] = p
        if p.stem != slug:
            pages[p.stem] = p
    for p in BASE_DIR.glob("*.md"):
        pages[p.stem] = p
        pages[p.name] = p
    return pages


def build_link_index(pages: dict[str, Path]) -> dict[str, str]:
    from wiki_core.frontmatter import parse_frontmatter

    index: dict[str, str] = {}
    for stem, path in pages.items():
        slug = canonical_slug(path)
        for key in (stem, slug, stem.lower(), slug.lower()):
            index[key] = slug
        if path.suffix == ".md":
            try:
                fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
                for alias in fm.get("aliases", []) or []:
                    index[str(alias)] = slug
                    index[str(alias).lower()] = slug
                if fm.get("uid"):
                    index[str(fm["uid"])] = slug
            except Exception:
                pass
    return index


def build_graph() -> Graph:
    pages = discover_wiki_pages()
    link_index = build_link_index(pages)
    seen_slugs: set[str] = set()
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    for path in {p for p in pages.values()}:
        slug = canonical_slug(path)
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        text = path.read_text(encoding="utf-8")
        fm, _ = parse_frontmatter(text)
        title = extract_title(text, slug.replace("-", " ").title())
        nodes.append(
            GraphNode(
                id=slug,
                slug=slug,
                title=title,
                type=str(fm.get("type", "page")),
                path=str(path.relative_to(BASE_DIR)),
            )
        )

    slug_set = {n.slug for n in nodes}
    inbound: dict[str, int] = {s: 0 for s in slug_set}

    for path in {p for p in pages.values()}:
        source_slug = canonical_slug(path)
        text = path.read_text(encoding="utf-8")
        for link in parse_wikilinks(text):
            target_slug = resolve_link(link.target, link_index)
            if target_slug and target_slug in slug_set and target_slug != source_slug:
                edges.append(GraphEdge(source=source_slug, target=target_slug))
                inbound[target_slug] = inbound.get(target_slug, 0) + 1

    for node in nodes:
        node.link_count = inbound.get(node.slug, 0) + sum(1 for e in edges if e.source == node.slug)

    return Graph(nodes=nodes, edges=edges)


def get_backlinks(slug: str) -> list[dict]:
    graph = build_graph()
    pages = discover_wiki_pages()
    link_index = build_link_index(pages)
    results = []
    for path in {p for p in pages.values()}:
        source_slug = canonical_slug(path)
        if source_slug == slug:
            continue
        text = path.read_text(encoding="utf-8")
        for link in parse_wikilinks(text):
            target = resolve_link(link.target, link_index)
            if target == slug:
                title = extract_title(text, source_slug)
                results.append({"slug": source_slug, "title": title, "path": str(path.relative_to(BASE_DIR))})
                break
    return results


def get_page_by_slug(slug: str) -> Path | None:
    pages = discover_wiki_pages()
    link_index = build_link_index(pages)
    resolved = resolve_link(slug, link_index)
    if resolved and resolved in pages:
        return pages[resolved]
    if slug in pages:
        return pages[slug]
    return None
