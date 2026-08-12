"""Turn a captured source into connected notes.

Summarising a source produces one literature note. That is step one of the Zettelkasten and
it is where this app used to stop — leaving notes with no backlinks, links that resolved to
nothing, and no Map of Content pointing at them.

Distillation does the rest: it pulls out the atomic ideas, **converges them with notes that
already exist** so the same concept met in two sources becomes one note, writes justified
links in both directions, and files everything under a Map of Content so nothing is born an
orphan.

The rule that keeps the graph honest: a link is only written after its destination exists.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session
from wiki_core.llm import call_llm, call_llm_json

from wiki_api.database import Document
from wiki_api.services.content import (
    LinkIndex,
    build_link_index,
    create_note,
    get_doc,
    log_action,
    note_slug,
    update_note,
    upsert_literature_note,
)

logger = logging.getLogger(__name__)

# How much of a source the model reads. Long transcripts are the norm, and the ladder now
# prefers million-token models, but the useful signal is front-loaded.
SOURCE_CHARS = 24_000

# Ceiling on new notes per source. Without it, 62 lecture transcripts become 600 thin stubs
# instead of a connected graph — the concepts that matter recur, and recurrence is what
# earns a note.
MAX_NEW_ZETTELS = 6

UNREVIEWED = "unreviewed"


@dataclass
class Concept:
    name: str
    summary: str = ""
    why: str = ""
    aliases: list[str] = field(default_factory=list)


@dataclass
class DistillResult:
    literature_slug: str | None = None
    created: list[str] = field(default_factory=list)
    linked: list[str] = field(default_factory=list)
    moc: str | None = None
    skipped: str | None = None

    def as_dict(self) -> dict:
        return {
            "literature": self.literature_slug,
            "created": self.created,
            "linked_existing": self.linked,
            "moc": self.moc,
            "skipped": self.skipped,
        }


# --- concept extraction -------------------------------------------------------

_EXTRACT_SYSTEM = (
    "You extract the reusable ideas from study material for a Zettelkasten. "
    "Your entire reply is a single JSON object. Do not explain your reasoning, do not "
    "restate the task, do not use a code fence. Begin your reply with the character '{'."
)

_EXTRACT_PROMPT = """Read this source and identify the atomic concepts it teaches.

An atomic concept is one idea that would still make sense in its own note, months later,
away from this source — "Cross-Entropy Loss", "Backpropagation", "Tool Use". It is NOT a
section heading, a lesson number, or a whole topic like "machine learning".

Return at most {limit} concepts, most central first. For each give:
  name     - the canonical name, as it would title a note
  aliases  - other names or abbreviations used for it (e.g. ["MHA"]), [] if none
  summary  - two sentences explaining the idea itself, not what the source says about it
  why      - a short clause finishing "...is relevant because", for the link back

SOURCE: {title}

{body}

Reply with JSON only:
{{"concepts": [{{"name": "...", "aliases": [], "summary": "...", "why": "..."}}]}}"""


def _concepts_from(data: dict, limit: int) -> list[Concept]:
    """Validate the model's concept list, discarding anything that is not a real concept."""
    out: list[Concept] = []
    for item in (data.get("concepts") or [])[:limit]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        # Guard against the model returning a sentence or a heading as a "concept".
        if not name or len(name) > 80 or not note_slug(name):
            continue
        aliases = [str(a).strip() for a in (item.get("aliases") or []) if str(a).strip()]
        out.append(
            Concept(
                name=name,
                summary=str(item.get("summary") or "").strip(),
                why=str(item.get("why") or "").strip(),
                aliases=aliases[:5],
            )
        )
    return out


def extract_concepts(source: Document, limit: int = 8) -> list[Concept]:
    data = call_llm_json(
        _EXTRACT_PROMPT.format(
            limit=limit, title=source.title, body=(source.body or "")[:SOURCE_CHARS]
        ),
        _EXTRACT_SYSTEM,
    )
    return _concepts_from(data, limit)


# --- convergence --------------------------------------------------------------


def _normalise(name: str) -> str:
    """Fold spelling differences so one idea does not fork into several notes."""
    n = name.casefold().strip()
    n = re.sub(r"\s*\([^)]*\)", "", n)  # drop parenthetical glosses
    n = re.sub(r"[^a-z0-9]+", " ", n).strip()
    # "Cross-Entropy Loss" and "cross entropy" should meet, and so should "Transformer" and
    # "Transformer Architecture" — that pair forked a second note in the real run.
    for suffix in (
        " function",
        " algorithm",
        " method",
        " technique",
        " loss",
        " layer",
        " layers",
        " architecture",
        " architectures",
        " model",
        " models",
        " network",
        " networks",
        " mechanism",
        " mechanisms",
    ):
        if n.endswith(suffix) and len(n) > len(suffix) + 3:
            n = n[: -len(suffix)].strip()
            break
    return n


def find_existing(db: Session, index: LinkIndex, concept: Concept) -> str | None:
    """The slug of a note already covering this concept, if there is one."""
    for candidate in [concept.name, *concept.aliases]:
        slug = index.resolve(candidate)
        if slug:
            return slug

    # Nothing matched exactly: compare normalised titles and stored aliases.
    target = _normalise(concept.name)
    if not target:
        return None
    for slug, title in index.title_of.items():
        if _normalise(title) == target:
            return slug
    for slug, aliases in index.aliases_of.items():
        if any(_normalise(a) == target for a in aliases):
            return slug
    return None


# --- writing ------------------------------------------------------------------


def _zettel_body(concept: Concept, source: Document) -> str:
    return f"""# {concept.name}

{concept.summary}

## Where this came from

- [[{source.slug}|{source.title}]] — the source this was distilled from.
"""


def _add_to_moc(db: Session, moc_slug: str, moc_title: str, entries: list[tuple[str, str]]) -> str:
    """Append links to a Map of Content, creating it if absent. Never duplicates a link."""
    moc = get_doc(db, moc_slug)
    if moc is None:
        moc = create_note(
            db,
            title=moc_title,
            body=f"# {moc_title}\n\nA map of what this collection covers.\n\n## Notes\n\n",
            subtype="moc",
            tags=["moc"],
            slug=moc_slug,
        )
        _link_from_index(db, moc)

    body = moc.body or ""
    additions = [f"- [[{slug}]] — {why}" for slug, why in entries if f"[[{slug}]]" not in body]
    if not additions:
        return moc.slug
    update_note(db, moc, body=body.rstrip() + "\n" + "\n".join(additions) + "\n")
    return moc.slug


def _link_from_index(db: Session, moc: Document) -> None:
    """Add a new Map of Content to the index, so it is not itself an orphan."""
    index = get_doc(db, "index")
    if index is None or f"[[{moc.slug}]]" in (index.body or ""):
        return
    body = (index.body or "").rstrip()
    heading = "\n\n## 🗺️ Maps of Content (MOC Hubs)"
    entry = f"- [[{moc.slug}]] — {moc.title}."
    if heading.strip() in body:
        # Slot it under the existing hub section rather than at the end.
        lines = body.split("\n")
        at = next(i for i, ln in enumerate(lines) if ln.strip() == heading.strip())
        end = at + 1
        while end < len(lines) and (lines[end].startswith("- ") or not lines[end].strip()):
            if not lines[end].strip() and end > at + 1:
                break
            end += 1
        lines.insert(end, entry)
        body = "\n".join(lines)
    else:
        body = f"{body}{heading}\n\n{entry}\n"
    update_note(db, index, body=body)


def distill(
    db: Session,
    source: Document,
    moc_slug: str | None = None,
    moc_title: str | None = None,
    max_new: int = MAX_NEW_ZETTELS,
) -> DistillResult:
    """Summarise a source, then connect it to the rest of the wiki."""
    result = DistillResult()
    if source.doc_class != "source":
        result.skipped = "not a captured source"
        return result

    index = build_link_index(db)

    try:
        concepts = extract_concepts(source)
    except Exception as exc:
        # A source already captured is worth more than a failed distillation; record and move on.
        logger.warning("Concept extraction failed for %s: %s", source.slug, exc)
        concepts = []

    created: list[tuple[str, str]] = []
    linked: list[tuple[str, str]] = []

    for concept in concepts:
        existing = find_existing(db, index, concept)
        why = concept.why or f"a concept covered by {source.title}"
        if existing:
            linked.append((existing, why))
            continue
        if len(created) >= max_new:
            continue
        slug = note_slug(concept.name)
        if not slug or get_doc(db, slug):
            continue
        try:
            note = create_note(
                db,
                title=concept.name,
                body=_zettel_body(concept, source),
                subtype="zettel",
                tags=["zettel", UNREVIEWED],
                slug=slug,
            )
        except ValueError:
            continue
        if concept.aliases:
            note.extra = {**(note.extra or {}), "aliases": concept.aliases}
            db.commit()
        created.append((note.slug, why))
        index = build_link_index(db)  # so the next concept can converge on this one

    # The literature note is written last, referencing only destinations that now exist —
    # which is what stops the dangling links this pipeline used to produce.
    all_links = created + linked
    result.literature_slug = _write_literature_note(db, source, all_links).slug
    result.created = [s for s, _ in created]
    result.linked = [s for s, _ in linked]

    if moc_slug and moc_title:
        entries = [(result.literature_slug, f"notes from {source.title}"), *created]
        result.moc = _add_to_moc(db, moc_slug, moc_title, entries)

    log_action(
        db,
        "distill",
        f"{source.slug}: {len(created)} new notes, {len(linked)} linked to existing",
    )
    return result


_SUMMARY_SYSTEM = "You write literature notes for a personal knowledge base. Markdown only."

_SUMMARY_PROMPT = """Write a literature note for this source: what it covers and what is worth
remembering. Two or three short paragraphs, then 3-6 bullet takeaways. Do not invent detail
that is not in the source. Do not add a heading — one is supplied.

SOURCE: {title}

{body}"""


def _write_literature_note(db: Session, source: Document, links: list[tuple[str, str]]) -> Document:
    try:
        summary = call_llm(
            _SUMMARY_PROMPT.format(title=source.title, body=(source.body or "")[:SOURCE_CHARS]),
            _SUMMARY_SYSTEM,
        )
    except Exception as exc:
        logger.warning("Summary failed for %s: %s", source.slug, exc)
        summary = "*The summary could not be generated. The captured source is linked below.*"

    header = f"# {source.title}\n\n**Source:** [[{source.slug}|{source.title}]]"
    if source.url:
        header += f" · [original]({source.url})"

    concepts = ""
    if links:
        concepts = "\n\n## Concepts\n\n" + "\n".join(f"- [[{slug}]] — {why}" for slug, why in links)

    return upsert_literature_note(
        db,
        source,
        title=f"{source.title}",
        body=f"{header}\n\n{summary}\n{concepts}\n",
        tags=["literature", UNREVIEWED],
    )
