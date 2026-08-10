"""Slug utilities."""

from __future__ import annotations

import re


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text.strip("-")[:80]


def atomic_slug_from_stem(stem: str) -> str:
    """Extract human slug from atomic filename (uid-slug or slug-only)."""
    if re.match(r"^\d{14}-", stem):
        return stem.split("-", 1)[1]
    return stem
