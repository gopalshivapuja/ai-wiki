"""YAML frontmatter parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml


@dataclass
class PageMeta:
    slug: str
    path: str
    title: str = ""
    uid: str = ""
    type: str = "zettel"
    created: str = ""
    updated: str = ""
    tags: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    raw_frontmatter: dict[str, Any] = field(default_factory=dict)


FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    body = text[m.end() :]
    return fm, body


def extract_title(text: str, fallback: str = "") -> str:
    fm, body = parse_frontmatter(text)
    if fm.get("title"):
        return str(fm["title"])
    m = re.search(r"^#\s+(.*)$", body, re.MULTILINE)
    return m.group(1).strip() if m else fallback
