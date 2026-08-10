"""Wiki linting and auto-link."""

from __future__ import annotations

import re
from dataclasses import dataclass

from wiki_core.config import ATOMIC_DIR, BASE_DIR, INDEX_FILE, SOURCES_DIR, WIKI_DIR, ensure_directories
from wiki_core.graph import build_link_index, canonical_slug, discover_wiki_pages
from wiki_core.slug import slugify
from wiki_core.wikilinks import WIKILINK_RE, parse_wikilinks, resolve_link


@dataclass
class LintIssue:
    kind: str
    message: str
    path: str = ""


def lint_wiki() -> list[LintIssue]:
    ensure_directories()
    issues: list[LintIssue] = []
    pages = discover_wiki_pages()
    link_index = build_link_index(pages)

    for filepath in WIKI_DIR.rglob("*.md"):
        rel_path = str(filepath.relative_to(BASE_DIR))
        text = filepath.read_text(encoding="utf-8")
        for link in parse_wikilinks(text):
            if not resolve_link(link.target, link_index):
                issues.append(
                    LintIssue("broken_wikilink", f"[[{link.target}]] target not found", rel_path)
                )

    if ATOMIC_DIR.exists():
        for zettel in ATOMIC_DIR.glob("*.md"):
            rel = str(zettel.relative_to(BASE_DIR))
            content = zettel.read_text(encoding="utf-8")
            if "uid:" not in content:
                issues.append(LintIssue("missing_uid", "Missing uid in frontmatter", rel))
            if len(content.splitlines()) > 250:
                issues.append(LintIssue("bloated_zettel", f">{250} lines", rel))
            slug = canonical_slug(zettel)
            other_text = ""
            for other in WIKI_DIR.rglob("*.md"):
                if other != zettel:
                    other_text += other.read_text(encoding="utf-8")
            if slug not in other_text and zettel.stem not in other_text:
                issues.append(LintIssue("unlinked_zettel", "Not linked from any page", rel))

    sources_wiki_stems = {s.stem for s in (WIKI_DIR / "sources").glob("*.md")}
    for raw in SOURCES_DIR.rglob("*.md"):
        if raw.parent.name == "assets":
            continue
        if raw.stem not in sources_wiki_stems:
            issues.append(
                LintIssue("unindexed_source", "No literature summary in wiki/sources/", str(raw.relative_to(BASE_DIR)))
            )

    if INDEX_FILE.exists():
        index_text = INDEX_FILE.read_text(encoding="utf-8")
        for filepath in WIKI_DIR.rglob("*.md"):
            if filepath.parent == ATOMIC_DIR or filepath.stem in ("index", "log"):
                continue
            if filepath.stem not in index_text and canonical_slug(filepath) not in index_text:
                issues.append(LintIssue("orphan_page", "Not referenced in wiki/index.md", str(filepath.relative_to(BASE_DIR))))

    return issues


def auto_link_suggestions() -> list[tuple[str, str, str]]:
    ensure_directories()
    titles_map: dict[str, str] = {}
    for f in WIKI_DIR.rglob("*.md"):
        if f.stem in ("index", "log"):
            continue
        text = f.read_text(encoding="utf-8")
        t_match = re.search(r"^#\s+(.*)$", text, re.MULTILINE)
        title = t_match.group(1).strip() if t_match else canonical_slug(f)
        slug = canonical_slug(f)
        titles_map[title.lower()] = slug
        titles_map[slug.lower()] = slug
        titles_map[f.stem.lower()] = slug

    suggestions: list[tuple[str, str, str]] = []
    for f in WIKI_DIR.rglob("*.md"):
        rel = str(f.relative_to(BASE_DIR))
        text = f.read_text(encoding="utf-8")
        existing = {l.target.lower() for l in parse_wikilinks(text)}
        for term, target_slug in titles_map.items():
            if len(term) < 4 or target_slug == canonical_slug(f) or target_slug in existing:
                continue
            if re.search(r"\b" + re.escape(term) + r"\b", text, re.IGNORECASE):
                if f"[[{target_slug}" not in text:
                    suggestions.append((rel, term, target_slug))
    return suggestions


def graph_stats() -> dict:
    ensure_directories()
    wikilink_pattern = WIKILINK_RE
    all_wiki = list(WIKI_DIR.rglob("*.md"))
    total_links = sum(len(wikilink_pattern.findall(f.read_text(encoding="utf-8"))) for f in all_wiki)
    return {
        "atomic_zettels": len(list(ATOMIC_DIR.glob("*.md"))) if ATOMIC_DIR.exists() else 0,
        "concept_pages": len(list((WIKI_DIR / "concepts").glob("*.md"))),
        "entity_pages": len(list((WIKI_DIR / "entities").glob("*.md"))),
        "literature_summaries": len(list((WIKI_DIR / "sources").glob("*.md"))),
        "mocs": len([f for f in (WIKI_DIR / "syntheses").glob("*.md") if f.name.startswith("moc-")]),
        "raw_sources": len(list(SOURCES_DIR.rglob("*.md"))),
        "total_wikilinks": total_links,
        "avg_links_per_note": round(total_links / len(all_wiki), 2) if all_wiki else 0,
    }
