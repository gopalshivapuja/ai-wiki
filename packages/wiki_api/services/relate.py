"""Find notes that are about the same thing, without anyone having linked them.

Brute-force cosine over every stored vector. At a few thousand notes that is under a
millisecond in pure Python, so there is deliberately no pgvector: an extension and a migration
would buy nothing measurable and cost a dependency. Revisit past ~50k documents.

The threshold matters more than the maths. In a wiki that is entirely about one subject,
everything resembles everything — attention resembles convolution resembles gradient descent,
because all three are "a thing in a neural network". A low cut-off produces a long list of
technically-similar notes that tell you nothing. MIN_SIMILARITY is set where the neighbours
stop being merely on-topic and start being genuinely about the same idea.
"""

from __future__ import annotations

import math

from sqlalchemy.orm import Session

from wiki_api.database import NOTE, SOURCE, Document
from wiki_api.services.embed import from_bytes

# Above this, two notes are about the same idea rather than the same field.
MIN_SIMILARITY = 0.72
# Above this they are very likely the same note written twice — a merge candidate, not a link.
DUPLICATE_SIMILARITY = 0.92


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def _vectors(db: Session, include_sources: bool) -> list[tuple[str, str, str, list[float]]]:
    q = db.query(
        Document.slug, Document.title, Document.subtype, Document.doc_class, Document.embedding
    ).filter(Document.embedding.isnot(None))
    if not include_sources:
        q = q.filter(Document.doc_class != SOURCE)
    out = []
    for slug, title, subtype, _doc_class, blob in q.all():
        vec = from_bytes(blob)
        if vec:
            out.append((slug, title, subtype, vec))
    return out


def similar_to_vector(
    db: Session,
    vector: list[float],
    k: int = 8,
    threshold: float = MIN_SIMILARITY,
    exclude: set[str] | None = None,
    include_sources: bool = False,
) -> list[dict]:
    skip = exclude or set()
    scored = [
        {"slug": slug, "title": title, "type": subtype, "score": round(cosine(vector, vec), 4)}
        for slug, title, subtype, vec in _vectors(db, include_sources)
        if slug not in skip
    ]
    scored = [s for s in scored if s["score"] >= threshold]
    scored.sort(key=lambda s: -s["score"])
    return scored[:k]


def similar(
    db: Session,
    slug: str,
    k: int = 8,
    threshold: float = MIN_SIMILARITY,
    include_sources: bool = False,
) -> list[dict]:
    """The notes nearest this one in meaning. Empty when it has no embedding yet."""
    doc = db.query(Document).filter(Document.slug == slug).first()
    vector = from_bytes(doc.embedding) if doc else None
    if not vector:
        return []
    return similar_to_vector(
        db, vector, k=k, threshold=threshold, exclude={slug}, include_sources=include_sources
    )


def duplicate_pairs(db: Session, threshold: float = DUPLICATE_SIMILARITY) -> list[dict]:
    """Notes that look like the same idea written twice.

    Reported, never merged automatically: "Forward Diffusion Process" and "Forward Process in
    Diffusion Models" are one note, but "Positional Encoding" and "Rotary Positional Encoding"
    score nearly as high and are genuinely two. That judgement stays with a person.
    """
    notes = [v for v in _vectors(db, include_sources=False) if v[2] not in ("index", "moc")]
    pairs = []
    for i, (slug_a, title_a, _ta, vec_a) in enumerate(notes):
        for slug_b, title_b, _tb, vec_b in notes[i + 1 :]:
            score = cosine(vec_a, vec_b)
            if score >= threshold:
                pairs.append(
                    {
                        "a": slug_a,
                        "a_title": title_a,
                        "b": slug_b,
                        "b_title": title_b,
                        "score": round(score, 4),
                    }
                )
    pairs.sort(key=lambda p: -p["score"])
    return pairs


def embed_missing(db: Session, batch: int = 64, force: bool = False) -> dict:
    """Embed documents that have no vector yet. Safe to call repeatedly."""
    from wiki_api.database import utcnow
    from wiki_api.services.embed import MODEL_NAME, available, embed_texts

    if not available():
        return {"embedded": 0, "skipped": "no embedding model available"}

    q = db.query(Document)
    if not force:
        q = q.filter(Document.embedding.is_(None))
    pending = q.all()

    done = 0
    for start in range(0, len(pending), batch):
        chunk = pending[start : start + batch]
        vectors = embed_texts([f"{d.title}\n\n{d.title}\n\n{d.body or ''}" for d in chunk])
        if vectors is None:
            break
        for doc, blob in zip(chunk, vectors, strict=False):
            doc.embedding = blob
            doc.embedding_model = MODEL_NAME
            doc.embedded_at = utcnow()
        db.commit()
        done += len(chunk)
    return {"embedded": done, "total": len(pending)}


def note_count_with_embeddings(db: Session) -> int:
    return (
        db.query(Document)
        .filter(Document.embedding.isnot(None), Document.doc_class == NOTE)
        .count()
    )
