"""Wikilink parsing and resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass

from wiki_core.slug import atomic_slug_from_stem, slugify

WIKILINK_RE = re.compile(r"\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]")


@dataclass
class Wikilink:
    target: str
    display: str | None = None

    @property
    def display_or_target(self) -> str:
        return self.display or self.target


def parse_wikilinks(text: str) -> list[Wikilink]:
    links = []
    for target, display in WIKILINK_RE.findall(text):
        links.append(Wikilink(target=target.strip(), display=display.strip() if display else None))
    return links


def build_page_index(wiki_pages: dict[str, "Path"]) -> dict[str, str]:
    """Map all resolvable link targets to canonical slug."""
    from pathlib import Path  # noqa: F811

    index: dict[str, str] = {}
    for stem, path in wiki_pages.items():
        canonical = atomic_slug_from_stem(stem)
        index[stem] = canonical
        index[canonical] = canonical
        index[slugify(stem)] = canonical
        index[stem.lower()] = canonical
        index[canonical.lower()] = canonical
        # UID-only alias for legacy links
        if re.match(r"^\d{14}-", stem):
            index[stem] = canonical
    return index


def resolve_link(target: str, index: dict[str, str]) -> str | None:
    t = target.strip()
    t_slug = slugify(t)
    for key in (t, t_slug, t.lower(), t_slug.lower()):
        if key in index:
            return index[key]
    return None
