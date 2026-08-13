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
class Relation:
    """A stated connection to another concept. The reason is required — an unjustified link
    is noise, and this pipeline's whole failure mode was links nobody could explain."""

    name: str
    reason: str


@dataclass
class Concept:
    name: str
    summary: str = ""
    why: str = ""
    confuse: str = ""
    aliases: list[str] = field(default_factory=list)
    relates_to: list[Relation] = field(default_factory=list)


@dataclass
class DistillResult:
    literature_slug: str | None = None
    created: list[str] = field(default_factory=list)
    linked: list[str] = field(default_factory=list)
    moc: str | None = None
    cross_links: int = 0
    skipped: str | None = None

    def as_dict(self) -> dict:
        return {
            "literature": self.literature_slug,
            "created": self.created,
            "linked_existing": self.linked,
            "moc": self.moc,
            "cross_links": self.cross_links,
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

Exclude the logistics around the material: course platforms, cohorts, office hours, teaching
assistants, enrolment, badges, fees, scheduling. Those describe how the material is delivered,
not what it teaches. If a source is purely administrative, return an empty list.

Name each concept in its plainest, most canonical form — "Vanishing Gradient", not "The
Vanishing Gradient Problem in RNNs" — and singular rather than plural, so the same idea met
in two lectures lands on one note.

Return at most {limit} concepts, most central first. For each give:
  name     - the canonical name, as it would title a note
  aliases  - other names or abbreviations used for it (e.g. ["MHA"]), [] if none
  summary  - THREE OR FOUR sentences that make the note stand on its own months from now:
             what it is, the problem it solves or the failure it prevents, and one concrete
             detail (a mechanism, a formula in words, or a worked example). Explain the idea
             itself, never "the source says". Do not open by restating the name as a
             definition — say something.
  confuse  - one clause naming what this is commonly confused with, or "" if nothing
  why      - a short clause finishing "...is relevant because", for the link back
  relates_to - the OTHER concept names from this same list that this one genuinely connects
             to, each with the reason. Only real relationships: "X is what makes Y possible",
             "X is the failure Y fixes", "X and Y are alternatives for the same job". If a
             pair merely appears in the same lecture, leave it out.

SOURCE: {title}

{body}

Reply with JSON only:
{{"concepts": [{{"name": "...", "aliases": [], "summary": "...", "confuse": "...",
  "why": "...", "relates_to": [{{"name": "...", "reason": "..."}}]}}]}}"""


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
        relations = []
        for rel in item.get("relates_to") or []:
            if not isinstance(rel, dict):
                continue
            target, reason = (
                str(rel.get("name") or "").strip(),
                str(rel.get("reason") or "").strip(),
            )
            # A relation without a reason is exactly the kind of link that made the old graph
            # look connected while telling the reader nothing.
            if target and reason:
                relations.append(Relation(name=target, reason=reason))
        out.append(
            Concept(
                name=name,
                summary=str(item.get("summary") or "").strip(),
                why=str(item.get("why") or "").strip(),
                confuse=str(item.get("confuse") or "").strip(),
                aliases=aliases[:5],
                relates_to=relations[:6],
            )
        )
    return out


def extract_concepts(source: Document, limit: int = 8) -> list[Concept]:
    return extract_concepts_from(source.title, source.body or "", limit)


def extract_concepts_from(title: str, body: str, limit: int = 8) -> list[Concept]:
    """The model call, taking plain strings so it can run with no database session open."""
    data = call_llm_json(
        _EXTRACT_PROMPT.format(limit=limit, title=title, body=(body or "")[:SOURCE_CHARS]),
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
        " problem",
    ):
        if n.endswith(suffix) and len(n) > len(suffix) + 3:
            n = n[: -len(suffix)].strip()
            break
    return _singular(n)


def _singular(n: str) -> str:
    """Fold a trailing plural on the last word.

    "Vanishing Gradient", "Vanishing Gradients" and "Vanishing Gradient Problem" arrived from
    three different lectures and became three notes.

    Only a consonant followed by "s" is treated as a plural, which keeps "loss" and "bias"
    whole. That under-folds words like "values", and deliberately so: leaving two notes
    unmerged is a nuisance, while merging two genuinely different ideas loses writing.
    """
    head, _, last = n.rpartition(" ")
    if len(last) > 3 and last.endswith("s") and last[-2] not in "aeious":
        last = last[:-1]
    return f"{head} {last}".strip() if head else last


# A concept must look this much like an existing note before it links instead of creating one.
# Higher than relate.MIN_SIMILARITY: linking is a suggestion, but declining to write a note is
# a decision, and getting it wrong loses the idea entirely.
CONVERGE_SIMILARITY = 0.86


def find_existing(db: Session, index: LinkIndex, concept: Concept) -> str | None:
    """The slug of a note already covering this concept, if there is one."""
    for candidate in [concept.name, *concept.aliases]:
        slug = index.resolve(candidate)
        if slug:
            return slug

    # Nothing matched exactly: compare normalised titles and stored aliases.
    target = _normalise(concept.name)
    if target:
        for slug, title in index.title_of.items():
            if _normalise(title) == target:
                return slug
        for slug, aliases in index.aliases_of.items():
            if any(_normalise(a) == target for a in aliases):
                return slug

    return _find_semantically(db, concept)


def _find_semantically(db: Session, concept: Concept) -> str | None:
    """Last resort: does an existing note already mean this?

    String matching cannot see that "Forward Diffusion Process" and "Forward Process in
    Diffusion Models" are one idea — that pair really did become two notes. Comparing meaning
    catches the reorderings and paraphrases that normalisation never will.
    """
    from wiki_api.services.embed import embed_one
    from wiki_api.services.relate import similar_to_vector

    vector_bytes = embed_one(f"{concept.name}\n\n{concept.name}\n\n{concept.summary}")
    if not vector_bytes:
        return None
    from wiki_api.services.embed import from_bytes

    hits = similar_to_vector(
        db, from_bytes(vector_bytes), k=1, threshold=CONVERGE_SIMILARITY, include_sources=False
    )
    if hits:
        logger.info(
            "Converged %r onto %s by meaning (%.3f)",
            concept.name,
            hits[0]["slug"],
            hits[0]["score"],
        )
        return hits[0]["slug"]
    return None


# --- writing ------------------------------------------------------------------


def _zettel_body(
    concept: Concept,
    source: Document,
    related: list[tuple[str, str]] | None = None,
) -> str:
    """One note.

    The `## Related` section is the point. Notes used to carry exactly two links — their
    source and the literature note about it — so 98% of the graph's edges joined an idea to
    its paperwork rather than to another idea. Ideas have to point at each other or the
    Zettelkasten is a filing cabinet.
    """
    parts = [f"# {concept.name}", "", concept.summary]
    if concept.confuse:
        parts += ["", f"**Not to be confused with:** {concept.confuse}"]
    if related:
        parts += ["", "## Related", ""]
        parts += [f"- [[{slug}]] — {reason}" for slug, reason in related]
    parts += [
        "",
        "## Where this came from",
        "",
        f"- [[{source.slug}|{source.title}]] — the source this was distilled from.",
        "",
    ]
    return "\n".join(parts)


def _append_related(db: Session, slug: str, entries: list[tuple[str, str]]) -> None:
    """Add links to an existing note, creating the Related section if it has none.

    Used to make a link reciprocal: if A says it builds on B, B should say so too, or the
    connection only exists when you happen to be reading A.
    """
    doc = get_doc(db, slug)
    if doc is None or doc.immutable:
        return
    body = doc.body or ""
    fresh = [(t, why) for t, why in entries if f"[[{t}]]" not in body and t != slug]
    if not fresh:
        return

    lines = [f"- [[{t}]] — {why}" for t, why in fresh]
    if "## Related" in body:
        head, _, tail = body.partition("## Related")
        rest = tail.split("\n", 1)[1] if "\n" in tail else ""
        body = f"{head}## Related\n\n" + "\n".join(lines) + "\n" + rest.lstrip("\n")
    elif "## Where this came from" in body:
        head, _, tail = body.partition("## Where this came from")
        body = (
            f"{head.rstrip()}\n\n## Related\n\n"
            + "\n".join(lines)
            + "\n\n## Where this came from"
            + tail
        )
    else:
        body = body.rstrip() + "\n\n## Related\n\n" + "\n".join(lines) + "\n"
    update_note(db, doc, body=body)


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
    concepts: list[Concept] | None = None,
    summary: str | None = None,
) -> DistillResult:
    """Summarise a source, then connect it to the rest of the wiki.

    Pass `concepts` and `summary` to skip the model calls. Callers holding a pooled connection
    must do exactly that: a distillation makes two model calls of a minute or more each, and
    running them inside an open session pinned a connection for the duration. Queue a few
    dozen of those and the pool is gone — which took the whole site down, not just the jobs.
    """
    result = DistillResult()
    if source.doc_class != "source":
        result.skipped = "not a captured source"
        return result

    index = build_link_index(db)

    if concepts is None:
        try:
            concepts = extract_concepts(source)
        except Exception as exc:
            # A captured source is worth more than a failed distillation; record and move on.
            logger.warning("Concept extraction failed for %s: %s", source.slug, exc)
            concepts = []

    created: list[tuple[str, str]] = []
    linked: list[tuple[str, str]] = []
    # Where each extracted concept ended up, so relates_to can be turned into real slugs once
    # every note in this batch exists.
    placed: dict[str, str] = {}

    for concept in concepts:
        existing = find_existing(db, index, concept)
        why = concept.why or f"a concept covered by {source.title}"
        if existing:
            linked.append((existing, why))
            placed[concept.name] = existing
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
                body=_zettel_body(concept, source, related=_neighbours(db, concept)),
                subtype="zettel",
                tags=["zettel", UNREVIEWED],
                slug=slug,
            )
        except ValueError:
            continue
        if concept.aliases:
            note.extra = {**(note.extra or {}), "aliases": concept.aliases}
        note.embedding = _embed_concept(concept)
        db.commit()
        created.append((note.slug, why))
        placed[concept.name] = note.slug
        index = build_link_index(db)  # so the next concept can converge on this one

    # Only now that every note in this batch exists can the model's stated relationships be
    # written as links — the rule that keeps the graph free of dangling targets.
    result.cross_links = _write_cross_links(db, concepts, placed)

    # The literature note is written last, referencing only destinations that now exist —
    # which is what stops the dangling links this pipeline used to produce.
    all_links = created + linked
    result.literature_slug = _write_literature_note(db, source, all_links, summary=summary).slug
    result.created = [s for s, _ in created]
    result.linked = [s for s, _ in linked]

    if moc_slug and moc_title:
        entries = [(result.literature_slug, f"notes from {source.title}"), *created]
        result.moc = _add_to_moc(db, moc_slug, moc_title, entries)

    log_action(
        db,
        "distill",
        f"{source.slug}: {len(created)} new notes, {len(linked)} linked to existing, "
        f"{result.cross_links} idea-to-idea links",
    )
    return result


def _embed_concept(concept: Concept) -> bytes | None:
    from wiki_api.services.embed import embed_document

    return embed_document(concept.name, concept.summary)


def _neighbours(db: Session, concept: Concept, k: int = 3) -> list[tuple[str, str]]:
    """Existing notes this concept is near in meaning.

    Suggestions, not assertions: the reason given is honest about being a resemblance rather
    than claiming a relationship the model never stated.
    """
    from wiki_api.services.embed import from_bytes
    from wiki_api.services.relate import MIN_SIMILARITY, similar_to_vector

    blob = _embed_concept(concept)
    if not blob:
        return []
    hits = similar_to_vector(
        db, from_bytes(blob), k=k, threshold=MIN_SIMILARITY, include_sources=False
    )
    return [(h["slug"], f"closely related — {h['title']}") for h in hits]


def _write_cross_links(db: Session, concepts: list[Concept], placed: dict[str, str]) -> int:
    """Turn the model's stated relationships into reciprocal links between notes.

    This is the fix for a graph in which only 1.7% of edges joined one idea to another. Each
    link is written in both directions, because a relationship that is only visible from one
    side is half a relationship.
    """
    by_name = {name.casefold(): slug for name, slug in placed.items()}
    written = 0
    for concept in concepts:
        source_slug = placed.get(concept.name)
        if not source_slug:
            continue
        for rel in concept.relates_to:
            target = by_name.get(rel.name.casefold())
            if not target or target == source_slug:
                continue
            _append_related(db, source_slug, [(target, rel.reason)])
            _append_related(db, target, [(source_slug, rel.reason)])
            written += 1
    return written


_SUMMARY_SYSTEM = "You write literature notes for a personal knowledge base. Markdown only."

_SUMMARY_PROMPT = """Write a literature note for this source — what it argues, not a table of
contents.

Two or three short paragraphs covering: the claim or question the source is built around, the
line of reasoning it uses to get there, and what it takes for granted without arguing. Then
3-6 bullets of what is worth remembering months from now — specific enough to be useful, so
"attention is O(n^2) in sequence length, which is why context windows are expensive" rather
than "discusses attention".

If the source is a lecture, say what it actually teaches, not that it is a lecture. Do not
invent detail that is not in the source, and do not add a heading — one is supplied.

SOURCE: {title}

{body}"""


def summarise_source(title: str, body: str) -> str:
    """The literature-note model call, taking plain strings so it needs no session."""
    try:
        return call_llm(
            _SUMMARY_PROMPT.format(title=title, body=(body or "")[:SOURCE_CHARS]), _SUMMARY_SYSTEM
        )
    except Exception as exc:
        logger.warning("Summary failed for %s: %s", title, exc)
        return "*The summary could not be generated. The captured source is linked below.*"


def _write_literature_note(
    db: Session,
    source: Document,
    links: list[tuple[str, str]],
    summary: str | None = None,
) -> Document:
    if summary is None:
        summary = summarise_source(source.title, source.body or "")

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
