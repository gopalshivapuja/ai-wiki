#!/usr/bin/env python3
"""One-off strict auditor that produced the evidence in docs/00-audit-findings.md.

This is a *planning artifact*, not product code. It exists so the numbers quoted in
the audit document can be reproduced and re-checked as the wiki changes:

    python3 docs/evidence/audit_snapshot.py

It deliberately duplicates a little logic instead of importing tools/wiki.py, because
its whole job is to be an independent second opinion on the shipped linter.

Phase 1 of docs/04-implementation-roadmap.md replaces this with a real rule-based
linter (`wiki lint --strict`) that has rule IDs, tests, and a non-zero exit code.
Delete this file once that lands.
"""
from __future__ import annotations

import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent
WIKI = BASE / "wiki"
SOURCES = BASE / "sources"

WIKILINK = re.compile(r"\[\[([^\]\|]+)(?:\|([^\]]*))?\]\]")
INLINE_CODE = re.compile(r"`[^`\n]*`")
FENCE = re.compile(r"```.*?```", re.DOTALL)
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)

REQUIRED_FRONTMATTER = ["title", "type", "created", "updated", "tags"]
VALID_TYPES = {"zettel", "literature", "moc", "concept", "entity", "synthesis", "source"}

findings: dict[str, list[str]] = {}


def add(kind: str, message: str) -> None:
    findings.setdefault(kind, []).append(message)


def spans(regex: re.Pattern[str], text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in regex.finditer(text)]


def inside(pos: int, ranges: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in ranges)


def main() -> int:
    md_files = sorted(WIKI.rglob("*.md"))
    stems = {f.stem for f in md_files}

    # Atomic notes are also reachable by their slug with the UID prefix removed.
    slug_alias: dict[str, str] = {}
    for f in md_files:
        if f.parent.name == "atomic" and re.match(r"^\d{14}-", f.stem):
            slug_alias[f.stem.split("-", 1)[1]] = f.stem

    root_docs = {f.stem for f in BASE.glob("*.md")} | {f.name for f in BASE.glob("*.md")}

    link_records: list[tuple[Path, str, bool, bool]] = []
    for f in md_files:
        text = f.read_text(encoding="utf-8")
        code_spans = spans(INLINE_CODE, text)
        fence_spans = spans(FENCE, text)
        rel = f.relative_to(BASE)

        for m in WIKILINK.finditer(text):
            target = m.group(1).strip()
            in_code = inside(m.start(), code_spans)
            in_fence = inside(m.start(), fence_spans)
            link_records.append((f, target, in_code, in_fence))

            if in_code:
                add("wikilink-in-inline-code", f"{rel}: [[{target}]]")
            if in_fence:
                add("wikilink-in-code-fence", f"{rel}: [[{target}]]")

            resolved = (
                target in stems
                or target in slug_alias
                or target in root_docs
                or target.replace(".md", "") in root_docs
            )
            if not resolved:
                add("unresolvable-target", f"{rel}: [[{target}]]")

    for f in md_files:
        if re.match(r"^\d{14}-", f.stem):
            add("uid-prefixed-filename", str(f.relative_to(BASE)))

    for f in md_files:
        rel = f.relative_to(BASE)
        text = f.read_text(encoding="utf-8")
        m = FRONTMATTER.match(text)
        if not m:
            add("missing-frontmatter", str(rel))
            continue
        keys = dict(re.findall(r"^([A-Za-z_]+):\s*(.*)$", m.group(1), re.MULTILINE))
        for required in REQUIRED_FRONTMATTER:
            if required not in keys:
                add("frontmatter-missing-key", f"{rel}: missing '{required}'")
        if "uid" not in keys:
            add("frontmatter-missing-uid", str(rel))
        declared_type = keys.get("type", "").strip().strip('"')
        if declared_type and declared_type not in VALID_TYPES:
            add("frontmatter-bad-type", f"{rel}: type={declared_type}")

    # Inbound-link count that ignores links which do not render (code spans / fences).
    inbound = {f.stem: 0 for f in md_files}
    for source_file, target, in_code, in_fence in link_records:
        target_stem = target if target in stems else slug_alias.get(target)
        if not target_stem or target_stem not in inbound:
            continue
        if target_stem == source_file.stem or in_code or in_fence:
            continue
        inbound[target_stem] += 1

    for f in md_files:
        if f.stem in ("index", "log"):
            continue
        if inbound.get(f.stem, 0) == 0:
            add("orphan-no-rendering-inbound-link", str(f.relative_to(BASE)))

    literature_stems = {p.stem for p in (WIKI / "sources").glob("*.md")}
    for raw in sorted(SOURCES.rglob("*.md")):
        if raw.stem not in literature_stems:
            add("source-without-literature-note", str(raw.relative_to(BASE)))
        else:
            add(
                "stem-collision-source-vs-literature",
                f"{raw.relative_to(BASE)} <-> wiki/sources/{raw.stem}.md",
            )

    total = 0
    for kind in sorted(findings):
        items = findings[kind]
        total += len(items)
        print(f"\n## {kind} ({len(items)})")
        for item in items:
            print(f"  - {item}")

    print(f"\n=== TOTAL FINDINGS: {total} ===")
    print(f"=== wiki pages scanned: {len(md_files)}, wikilinks found: {len(link_records)} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
