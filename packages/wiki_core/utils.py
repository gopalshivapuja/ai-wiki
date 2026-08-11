"""Slug and wikilink utilities."""

from __future__ import annotations

import re
from dataclasses import dataclass

WIKILINK_RE = re.compile(r"\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]")


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text.strip("-")[:80]


@dataclass
class Wikilink:
    target: str
    display: str | None = None


def parse_wikilinks(text: str) -> list[Wikilink]:
    return [
        Wikilink(target=t.strip(), display=d.strip() if d else None)
        for t, d in WIKILINK_RE.findall(text)
    ]


def parse_frontmatter(text: str) -> tuple[dict, str]:
    import yaml

    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return fm, text[m.end() :]
