#!/usr/bin/env python3
"""Migrate atomic zettels to slug-only filenames and fix wikilinks."""

from __future__ import annotations

import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ATOMIC = BASE / "wiki" / "atomic"
WIKI = BASE / "wiki"

REPLACEMENTS = {
    "20260810100100-scaled-dot-product-attention": "scaled-dot-product-attention",
    "20260810100200-multi-head-attention": "multi-head-attention",
    "20260810100300-react-agent-loop": "react-agent-loop",
    "20260810100400-evaluator-optimizer-pattern": "evaluator-optimizer-pattern",
    "20260810100500-lora-low-rank-adaptation": "lora-low-rank-adaptation",
}

DISPLAY = {
    "scaled-dot-product-attention": "Scaled Dot-Product Attention",
    "multi-head-attention": "Multi-Head Attention",
    "react-agent-loop": "ReAct Agent Loop",
    "evaluator-optimizer-pattern": "Evaluator-Optimizer Pattern",
    "lora-low-rank-adaptation": "LoRA Low-Rank Adaptation",
}


def main():
    # Rename atomic files
    for old_stem, new_slug in REPLACEMENTS.items():
        old_path = ATOMIC / f"{old_stem}.md"
        new_path = ATOMIC / f"{new_slug}.md"
        if old_path.exists() and not new_path.exists():
            content = old_path.read_text(encoding="utf-8")
            # Add alias if missing
            if "aliases:" not in content:
                content = content.replace(
                    "sources:",
                    f'aliases:\n  - "{old_stem}"\nsources:',
                    1,
                )
            new_path.write_text(content, encoding="utf-8")
            old_path.unlink()
            print(f"Renamed {old_stem} -> {new_slug}")

    # Fix all wiki markdown files
    for md in list(WIKI.rglob("*.md")) + list(BASE.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        original = text

        for old_stem, new_slug in REPLACEMENTS.items():
            display = DISPLAY.get(new_slug, new_slug.replace("-", " ").title())
            # Full stem links
            text = text.replace(f"[[{old_stem}]]", f"[[{new_slug}|{display}]]")
            text = text.replace(f"[[{old_stem}|", f"[[{new_slug}|")
            # Backtick-wrapped links
            text = text.replace(f"`[[{new_slug}|{display}]]`", f"[[{new_slug}|{display}]]")
            text = text.replace(f"`[[{new_slug}]]`", f"[[{new_slug}|{display}]]")

        # Strip backticks from any remaining wikilinks
        text = re.sub(r"`(\[\[[^\]]+\]\])`", r"\1", text)

        # Fix plain slug links without display titles for atomic notes
        for slug, display in DISPLAY.items():
            text = re.sub(
                rf"\[\[{re.escape(slug)}\]\](?!\|)",
                f"[[{slug}|{display}]]",
                text,
            )

        if text != original:
            md.write_text(text, encoding="utf-8")
            print(f"Updated links in {md.relative_to(BASE)}")

    # Clean ghost log entry
    log_path = WIKI / "log.md"
    if log_path.exists():
        log = log_path.read_text(encoding="utf-8")
        log = log.replace("## [2026-08-10] zettel | Created atomic zettel 'Sample Test Zettel' (UID: 20260810114501)\n", "")
        log_path.write_text(log, encoding="utf-8")


if __name__ == "__main__":
    main()
