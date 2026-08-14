"""Document reads, writes, and link resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session, object_session
from wiki_core.utils import parse_frontmatter, parse_wikilinks, slugify

from wiki_api.database import NOTE, SOURCE, ActivityLog, Document, Revision, utcnow

# Ingested sources are slugged under this prefix so they share one namespace with notes
# without colliding. Replaces the old two-table split and its disambiguation machinery.
SOURCE_PREFIX = "src-"
SOURCE_SUBTYPE_SET = ("web", "pdf", "youtube", "audio", "arxiv", "note")

MAX_SLUG_LEN = 80


def log_action(db: Session, action: str, summary: str) -> None:
    db.add(ActivityLog(action=action, summary=summary[:500]))
    db.commit()


def new_uid() -> str:
    return utcnow().strftime("%Y%m%d%H%M%S")


def note_slug(title: str) -> str:
    return slugify(title)[:MAX_SLUG_LEN]


def source_slug(title: str, fallback: str = "") -> str:
    base = slugify(title) or slugify(fallback) or "untitled"
    return f"{SOURCE_PREFIX}{base}"[:MAX_SLUG_LEN]


# --- serialisation ------------------------------------------------------------


def to_dict(d: Document, include_body: bool = True) -> dict:
    out = {
        "slug": d.slug,
        "uid": d.uid,
        "title": d.title,
        "doc_class": d.doc_class,
        "type": d.subtype,
        "tags": d.tags or [],
        "url": d.url,
        "collection": d.collection,
        "immutable": bool(d.immutable),
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }
    if include_body:
        out["body"] = d.body
    return out


def row_to_dict(r) -> dict:
    """Serialise a projected row from list_docs (no body loaded)."""
    return {
        "slug": r.slug,
        "uid": r.uid,
        "title": r.title,
        "doc_class": r.doc_class,
        "type": r.subtype,
        "tags": r.tags or [],
        "url": r.url,
        "collection": r.collection,
        "immutable": bool(r.immutable),
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


# --- reads --------------------------------------------------------------------


def get_doc(db: Session, slug: str) -> Document | None:
    return db.query(Document).filter(Document.slug == slug).first()


def list_docs(
    db: Session,
    doc_class: str | None = None,
    subtype: str | None = None,
    tag: str | None = None,
    collection: str | None = None,
    limit: int | None = None,
    offset: int = 0,
):
    """List documents without loading bodies.

    Only the columns callers render are selected — listing used to be `SELECT *`, shipping
    every body across the wire just to filter on a tag.
    """
    q = db.query(
        Document.id,
        Document.slug,
        Document.uid,
        Document.title,
        Document.doc_class,
        Document.subtype,
        Document.tags,
        Document.url,
        Document.collection,
        Document.immutable,
        Document.created_at,
        Document.updated_at,
    )
    if doc_class:
        q = q.filter(Document.doc_class == doc_class)
    if subtype:
        q = q.filter(Document.subtype == subtype)
    if collection:
        q = q.filter(Document.collection == collection)
    if tag:
        # GIN-indexed containment, not a Python scan over every row.
        q = q.filter(Document.tags.contains([tag]))

    q = q.order_by(Document.title)
    if offset:
        q = q.offset(offset)
    if limit:
        q = q.limit(limit)
    return q.all()


def tag_counts(db: Session) -> list[dict]:
    counts: dict[str, int] = {}
    for (tags,) in db.query(Document.tags).all():
        for t in tags or []:
            counts[t] = counts.get(t, 0) + 1
    return [
        {"tag": t, "count": c} for t, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


# --- links --------------------------------------------------------------------


@dataclass(frozen=True)
class LinkIndex:
    """In-memory slug/uid/title map, built with one query.

    Resolving a link used to cost up to three SELECTs *per wikilink*, for every link of every
    document — thousands of queries to render one graph.
    """

    by_slug: dict[str, str]
    by_uid: dict[str, str]
    by_title: dict[str, str]
    title_of: dict[str, str]
    # slug -> alternative names for the same idea, so "MHA" reaches "Multi-Head Attention".
    aliases_of: dict[str, list[str]]
    by_alias: dict[str, str]

    def resolve(self, target: str) -> str | None:
        t = target.strip()
        if t in self.by_slug:
            return t
        if t in self.by_uid:
            return self.by_uid[t]
        slugged = slugify(t)
        if slugged in self.by_slug:
            return slugged
        # Sources live under a prefix; let [[Some Article]] find src-some-article.
        prefixed = f"{SOURCE_PREFIX}{slugged}"
        if prefixed in self.by_slug:
            return prefixed
        by_title = self.by_title.get(t.casefold())
        if by_title:
            return by_title
        return self.by_alias.get(t.casefold())


def build_link_index(db: Session) -> LinkIndex:
    rows = db.query(Document.slug, Document.uid, Document.title, Document.extra).all()
    aliases_of = {
        slug: [str(a) for a in (extra or {}).get("aliases", []) if str(a).strip()]
        for slug, _, _, extra in rows
    }
    aliases_of = {slug: names for slug, names in aliases_of.items() if names}
    return LinkIndex(
        by_slug={slug: slug for slug, _, _, _ in rows},
        by_uid={uid: slug for slug, uid, _, _ in rows if uid},
        by_title={title.casefold(): slug for slug, _, title, _ in rows if title},
        title_of={slug: title for slug, _, title, _ in rows},
        aliases_of=aliases_of,
        by_alias={alias.casefold(): slug for slug, names in aliases_of.items() for alias in names},
    )


def outgoing_links(doc: Document, index: LinkIndex) -> list[dict]:
    """Links leaving this document, flagged with whether the target exists (red links).

    Keyed on the raw target, not the resolved slug: the frontend looks entries up by the
    text written inside [[...]], so two spellings of the same destination must both appear.
    Deduping by slug dropped the second one, and the renderer then fell back to treating the
    raw text as a slug — a guaranteed 404. Self-links are reported too, so they can render
    as plain text rather than a link to nowhere.
    """
    seen: set[str] = set()
    out = []
    for link in parse_wikilinks(doc.body or ""):
        target = link.target.strip()
        if target in seen:
            continue
        seen.add(target)
        resolved = index.resolve(target)
        out.append(
            {
                "target": target,
                "slug": resolved,
                # Fall back to the destination's real title rather than the raw slug, so a
                # sidebar of links reads as prose instead of URL fragments.
                "display": link.display or index.title_of.get(resolved or "", target),
                "exists": resolved is not None,
                "is_self": resolved is not None and resolved == doc.slug,
            }
        )
    return out


def backlinks(db: Session, slug: str, index: LinkIndex) -> list[dict]:
    rows = db.query(
        Document.slug, Document.title, Document.subtype, Document.doc_class, Document.body
    ).all()
    results = []
    for other, title, subtype, doc_class, body in rows:
        if other == slug:
            continue
        for link in parse_wikilinks(body or ""):
            if index.resolve(link.target) == slug:
                results.append(
                    {"slug": other, "title": title, "type": subtype, "doc_class": doc_class}
                )
                break
    return results


# --- writes -------------------------------------------------------------------


class Immutable(ValueError):
    """Attempted to edit captured source material."""


def _snapshot(db: Session, doc: Document) -> None:
    db.add(Revision(document_id=doc.id, title=doc.title, body=doc.body or ""))


def _starter_body(title: str) -> str:
    return f"""# {title}

## Context & core principle

*State the single atomic concept clearly.*

## Related

-
"""


def create_note(
    db: Session,
    title: str,
    body: str | None = None,
    subtype: str = "zettel",
    tags: list[str] | None = None,
    derived_from_id: int | None = None,
    slug: str | None = None,
) -> Document:
    title = (title or "").strip()
    slug = slug or note_slug(title)
    if not slug:
        # slugify() strips non-ASCII, so a CJK-only title yields "" and an unreachable URL.
        raise ValueError("Title must contain at least one letter or number")
    if get_doc(db, slug):
        raise ValueError(f"A document already exists at '{slug}'")

    doc = Document(
        slug=slug,
        uid=new_uid(),
        title=title or slug,
        doc_class=NOTE,
        subtype=subtype,
        body=_starter_body(title) if body is None else body,
        tags=tags or [],
        derived_from_id=derived_from_id,
        immutable=False,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    log_action(db, "create", f"Created note '{title}' ({slug})")
    return doc


def update_note(
    db: Session,
    doc: Document,
    title: str | None = None,
    body: str | None = None,
    tags: list[str] | None = None,
    subtype: str | None = None,
) -> Document:
    if doc.immutable:
        raise Immutable(
            f"'{doc.slug}' is captured source material and cannot be edited. "
            "Write a note about it instead."
        )

    if (body is not None and body != doc.body) or (title is not None and title != doc.title):
        _snapshot(db, doc)

    if title is not None:
        doc.title = title.strip() or doc.title
    if body is not None:
        doc.body = body
    if tags is not None:
        doc.tags = tags
    if subtype is not None:
        doc.subtype = subtype
    doc.updated_at = utcnow()
    db.commit()
    db.refresh(doc)
    log_action(db, "edit", f"Edited '{doc.slug}'")
    return doc


def revisions(db: Session, doc: Document, limit: int = 20) -> list[Revision]:
    return (
        db.query(Revision)
        .filter(Revision.document_id == doc.id)
        .order_by(Revision.created_at.desc(), Revision.id.desc())
        .limit(limit)
        .all()
    )


def restore_revision(db: Session, doc: Document, revision_id: int) -> Document:
    rev = (
        db.query(Revision)
        .filter(Revision.id == revision_id, Revision.document_id == doc.id)
        .first()
    )
    if not rev:
        raise ValueError("That revision does not belong to this document")
    return update_note(db, doc, title=rev.title, body=rev.body)


def delete_doc(db: Session, slug: str) -> bool:
    doc = get_doc(db, slug)
    if not doc:
        return False
    # A literature note whose source is deleted keeps its text and loses the link.
    db.query(Document).filter(Document.derived_from_id == doc.id).update({"derived_from_id": None})
    db.query(Revision).filter(Revision.document_id == doc.id).delete()
    db.delete(doc)
    db.commit()
    log_action(db, "delete", f"Deleted '{slug}'")
    return True


def store_source(
    db: Session,
    *,
    title: str,
    body: str,
    subtype: str,
    url: str | None = None,
    extra: dict | None = None,
    collection: str | None = None,
    slug_hint: str = "",
    log_label: str | None = None,
) -> tuple[Document, bool]:
    """Store captured material. Returns (document, created).

    The single place a source becomes a row — every ingest path goes through here, so none
    can forget to log it or to mark it immutable.
    """
    slug = source_slug(title, slug_hint)
    existing = get_doc(db, slug)
    if existing:
        # Same slug, different URL: keep both rather than silently discarding the new one.
        if url and existing.url and existing.url != url:
            suffix = slugify(url.rsplit("/", 1)[-1])[:20] or new_uid()[-6:]
            slug = f"{slug}-{suffix}"[:MAX_SLUG_LEN]
            existing = get_doc(db, slug)
        if existing:
            return existing, False

    doc = Document(
        slug=slug,
        uid=new_uid(),
        title=title or slug,
        doc_class=SOURCE,
        subtype=subtype,
        body=body,
        url=url,
        extra=extra or {},
        collection=collection,
        immutable=True,
        tags=[],
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    log_action(db, "ingest", log_label or f"{subtype}: {title}")
    return doc, True


def upsert_literature_note(
    db: Session, source: Document, title: str, body: str, tags: list[str]
) -> Document:
    """Create or replace the literature note derived from a source.

    Linked by foreign key rather than by a slug naming convention, so it can never land on
    top of something you wrote — and the previous version is snapshotted first.
    """
    existing = (
        db.query(Document)
        .filter(Document.derived_from_id == source.id, Document.subtype == "literature")
        .first()
    )
    if existing is None:
        # Imported or seeded notes have no derived_from_id, which is how a second summary
        # got created for a source that already had one. Adopt the existing note instead.
        stem = source.slug.removeprefix(SOURCE_PREFIX)
        for candidate in (f"summary-{stem}"[:MAX_SLUG_LEN], stem):
            found = get_doc(db, candidate)
            if found and found.doc_class == NOTE:
                found.derived_from_id = source.id
                found.subtype = "literature"
                db.commit()
                existing = found
                break
    if existing:
        _snapshot(db, existing)
        existing.title = title
        existing.body = body
        existing.tags = tags
        existing.updated_at = utcnow()
        db.commit()
        db.refresh(existing)
        return existing

    # Derived from the source's slug, not the note's title — the title already begins with
    # "Source summary:", which produced slugs like `summary-source-summary-pep-20`.
    stem = source.slug.removeprefix(SOURCE_PREFIX)
    base = f"summary-{stem}"[:MAX_SLUG_LEN]
    slug, n = base, 2
    while get_doc(db, slug):
        slug = f"{base}-{n}"[:MAX_SLUG_LEN]
        n += 1
    return create_note(
        db,
        title=title,
        body=body,
        subtype="literature",
        tags=tags,
        derived_from_id=source.id,
        slug=slug,
    )


def import_markdown(db: Session, path: Path, subtype_hint: str | None = None) -> Document | None:
    """Import one markdown file with YAML frontmatter.

    Used by both first-boot seeding and POST /api/import, so restoring a backup and shipping
    starter content are the same code path.
    """
    if not path.is_file():
        return None
    fm, body = parse_frontmatter(path.read_text(encoding="utf-8"))

    stem = path.stem
    if re.match(r"^\d{14}-", stem):  # legacy "<uid>-<slug>.md"
        stem = stem.split("-", 1)[1]

    subtype = str(fm.get("type") or subtype_hint or "page")
    declared = fm.get("class")
    doc_class = str(declared) if declared else (SOURCE if subtype in SOURCE_SUBTYPE_SET else NOTE)

    title = str(fm.get("title") or stem.replace("-", " ").title())
    m = re.search(r"^#\s+(.*)$", body, re.MULTILINE)
    if m:
        title = m.group(1).strip()

    slug = (
        source_slug(title, stem) if doc_class == SOURCE else (note_slug(stem) or note_slug(title))
    )
    if not slug:
        return None

    source_ref = fm.get("source")
    derived_from_id = None
    if source_ref:
        src = get_doc(db, str(source_ref))
        derived_from_id = src.id if src else None

    doc = get_doc(db, slug)
    if doc:
        if (doc.body or "") != body.strip():
            _snapshot(db, doc)
        if derived_from_id:
            doc.derived_from_id = derived_from_id
        doc.title = title
        doc.body = body.strip()
        doc.subtype = subtype
        doc.tags = fm.get("tags") or []
        # Re-apply the frontmatter's own fields too. Updating only title/body/subtype made the
        # round trip lossy for documents that already existed: to_markdown() writes class, url
        # and aliases, and re-importing dropped them silently. It also left no way to correct a
        # transcript stored as a note — the class it was first given was permanent.
        doc.doc_class = doc_class
        doc.immutable = doc_class == SOURCE
        if fm.get("url"):
            doc.url = fm["url"]
        if fm.get("aliases"):
            doc.extra = {**(doc.extra or {}), "aliases": fm["aliases"]}
        # to_markdown() has always emitted `collection` and import dropped it, so every
        # imported source landed with collection NULL — which silently reduced
        # POST /api/jobs/crosslink {"collection": ...} to matching nothing.
        if fm.get("collection"):
            doc.collection = str(fm["collection"])
        doc.updated_at = utcnow()
    else:
        doc = Document(
            slug=slug,
            uid=str(fm.get("uid") or new_uid()),
            title=title,
            doc_class=doc_class,
            subtype=subtype,
            body=body.strip(),
            tags=fm.get("tags") or [],
            url=fm.get("url"),
            immutable=doc_class == SOURCE,
            derived_from_id=derived_from_id,
            collection=str(fm["collection"]) if fm.get("collection") else None,
            extra={"aliases": fm["aliases"]} if fm.get("aliases") else {},
        )
        db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def to_markdown(doc: Document) -> str:
    """Serialise a document back to markdown with YAML frontmatter (inverse of import)."""
    import yaml

    meta = {
        "uid": doc.uid,
        "title": doc.title,
        "class": doc.doc_class,
        "type": doc.subtype,
        "created": doc.created_at.date().isoformat() if doc.created_at else None,
        "updated": doc.updated_at.date().isoformat() if doc.updated_at else None,
    }
    if doc.tags:
        meta["tags"] = list(doc.tags)
    if doc.url:
        meta["url"] = doc.url
    if doc.collection:
        meta["collection"] = doc.collection
    if doc.derived_from_id:
        session = object_session(doc)
        src = session.get(Document, doc.derived_from_id) if session else None
        if src:
            meta["source"] = src.slug
    aliases = (doc.extra or {}).get("aliases")
    if aliases:
        meta["aliases"] = list(aliases)
    meta = {k: v for k, v in meta.items() if v is not None}
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{front}\n---\n\n{doc.body or ''}\n"
