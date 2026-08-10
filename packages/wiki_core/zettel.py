"""Zettel creation and page utilities."""

from __future__ import annotations

import datetime

from wiki_core.config import ATOMIC_DIR, ensure_directories
from wiki_core.log import append_log
from wiki_core.slug import slugify


def new_zettel(title: str) -> str:
    ensure_directories()
    now = datetime.datetime.now()
    uid = now.strftime("%Y%m%d%H%M%S")
    slug = slugify(title)
    filename = f"{slug}.md"
    target_path = ATOMIC_DIR / filename
    if target_path.exists():
        raise FileExistsError(f"Zettel already exists: {target_path}")

    today = now.strftime("%Y-%m-%d")
    content = f"""---
uid: "{uid}"
title: "{title}"
type: zettel
created: {today}
updated: {today}
tags: [zettel, atomic]
sources: []
aliases:
  - "{uid}-{slug}"
---

# {title}

**UID:** `{uid}`
**Created:** {today}

## Context & Core Principle

*State the single atomic concept or idea clearly in self-contained detail.*

## Related Knowledge & Links

- [[moc-llm-architectures|LLM Architectures MOC]] — Map of Content grouping architectural concepts.
"""
    target_path.write_text(content, encoding="utf-8")
    append_log("zettel", f"Created atomic zettel '{title}' (UID: {uid}, slug: {slug})")
    return slug
