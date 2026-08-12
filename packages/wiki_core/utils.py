"""Slug and wikilink utilities."""

from __future__ import annotations

import re
from dataclasses import dataclass

WIKILINK_RE = re.compile(r"\[\[([^\]\|]+)(?:\|([^\]]+))?\]\]")

# Fenced blocks and inline code. Their contents are shown verbatim, so any [[...]] inside is
# illustration — a mermaid node label, a code sample — not a link. Counting them inflated the
# graph and the backlink panel with edges that render as inert text.
_CODE_RE = re.compile(r"```.*?```|~~~.*?~~~|`[^`\n]*`", re.DOTALL)


def slugify(text: str) -> str:
    text = text.lower()
    # Separators become word breaks. Deleting them outright turned "vanishing/exploding"
    # into "vanishingexploding".
    text = re.sub(r"[/\\&+,:]", " ", text)
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text.strip("-")[:80]


@dataclass
class Wikilink:
    target: str
    display: str | None = None


def strip_code(text: str) -> str:
    """Blank out code spans and fences, preserving offsets is not needed here."""
    return _CODE_RE.sub(" ", text)


def parse_wikilinks(text: str) -> list[Wikilink]:
    """Wikilinks in prose. Links inside code blocks are deliberately ignored."""
    return [
        Wikilink(target=t.strip(), display=d.strip() if d else None)
        for t, d in WIKILINK_RE.findall(strip_code(text))
    ]


def count_wikilinks(text: str) -> int:
    return len(WIKILINK_RE.findall(strip_code(text)))


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
