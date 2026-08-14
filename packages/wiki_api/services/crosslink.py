"""Link ideas that came from different sources.

Distillation wires together the concepts it extracts from one source, which is why a lecture's
ideas are well connected and a lecture in module 1 shares almost no edge with module 7. On the
AI Master Class only 4 of 1,362 idea-to-idea edges joined concepts with no module in common —
the course reads as eight silos stitched together by a few hub notes.

Embeddings alone cannot fix that: they measure *similarity*, and the interesting cross-source
links are usually between things that are not alike. A GAN's discriminator is trained with
cross-entropy loss, but "Generative Adversarial Network" and "Cross-Entropy Loss" score far
apart, because one is an architecture and the other is a loss.

So embeddings propose and the model disposes. Nearest neighbours from *other* sources become
candidates; the model keeps only the pairs it can give a reason for, and that reason is written
into the link. A candidate it cannot justify is dropped rather than linked weakly — an
unjustified link is the noise this whole pipeline exists to avoid.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session
from wiki_core.llm import call_llm_json

from wiki_api.database import NOTE, Document
from wiki_api.services.content import get_doc
from wiki_api.services.relate import similar

logger = logging.getLogger(__name__)

# Wider than relate.MIN_SIMILARITY: a cross-source link does not need the two notes to be
# about the same thing, only in the same neighbourhood. The model does the discriminating.
CANDIDATE_SIMILARITY = 0.55
MAX_CANDIDATES = 8
# Only these are subject matter worth joining to other subject matter.
LINKABLE_SUBTYPES = ("zettel", "concept", "entity", "synthesis")
MAX_ACCEPTED = 4
SUMMARY_CHARS = 700

_SYSTEM = (
    "You decide which pairs of notes in a knowledge base are genuinely related. "
    "Your entire reply is a single JSON object. Begin with the character '{'."
)

_PROMPT = """Here is a note from a personal knowledge base, and some candidate notes that may
or may not be related to it.

Keep only the candidates with a REAL relationship to the subject note — one you can state in a
clause. Good reasons look like:
  "X is the loss Y is trained with"
  "X is the failure Y was designed to fix"
  "X and Y are alternatives for the same job"
  "X is a component of Y"

Reject anything whose only connection is being in the same field. "Both are neural network
concepts" is not a relationship. Being merely similar is not a relationship. If none of the
candidates qualify, return an empty list — that is a perfectly good answer and often correct.

Keep at most {max_accepted}, best first.

SUBJECT NOTE: {title}
{summary}

CANDIDATES:
{candidates}

Reply with JSON only:
{{"links": [{{"slug": "...", "reason": "a clause saying how it relates"}}]}}"""


def _digest(doc: Document) -> str:
    """The opening prose of a note, without its link lists."""
    lines = []
    for line in (doc.body or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            break  # stop at the first section: Related / Where this came from
        if stripped and not stripped.startswith(("#", "-", "*", ">", "|")):
            lines.append(stripped)
    return " ".join(lines)[:SUMMARY_CHARS]


def candidates(db: Session, doc: Document, k: int = MAX_CANDIDATES) -> list[Document]:
    """Semantic neighbours that are not already linked and did not come from the same source."""
    from wiki_core.utils import parse_wikilinks

    already = {link.target for link in parse_wikilinks(doc.body or "")}
    out: list[Document] = []
    for hit in similar(db, doc.slug, k=k * 3, threshold=CANDIDATE_SIMILARITY):
        if hit["slug"] in already or hit["slug"] == doc.slug:
            continue
        other = get_doc(db, hit["slug"])
        if other is None or other.doc_class != NOTE:
            continue
        # Ideas only. A literature note is already reachable from every concept it lists, so
        # linking one here adds an edge without connecting two ideas — which is the entire
        # point of this pass. Maps and the index are navigation, not subject matter.
        if other.subtype in ("index", "moc", "literature"):
            continue
        # Concepts from the same source are already cross-linked by distillation.
        if doc.derived_from_id and other.derived_from_id == doc.derived_from_id:
            continue
        out.append(other)
        if len(out) >= k:
            break
    return out


def propose(doc: Document, options: list[Document]) -> list[tuple[str, str]]:
    """Ask the model which candidates are genuinely related, and why. No session needed."""
    if not options:
        return []
    listing = "\n".join(f"- {o.slug}: {o.title} — {_digest(o)[:200]}" for o in options)
    data = call_llm_json(
        _PROMPT.format(
            max_accepted=MAX_ACCEPTED,
            title=doc.title,
            summary=_digest(doc),
            candidates=listing,
        ),
        _SYSTEM,
    )
    allowed = {o.slug for o in options}
    accepted: list[tuple[str, str]] = []
    for item in (data.get("links") or [])[:MAX_ACCEPTED]:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or "").strip()
        reason = str(item.get("reason") or "").strip()
        # A hallucinated slug or a missing reason is discarded rather than guessed at.
        if slug in allowed and reason:
            accepted.append((slug, reason))
    return accepted


def apply_links(db: Session, slug: str, accepted: list[tuple[str, str]]) -> int:
    """Write the accepted links in both directions."""
    from wiki_api.services.distill import _append_related

    doc = get_doc(db, slug)
    if doc is None:
        return 0
    written = 0
    for target, reason in accepted:
        if get_doc(db, target) is None:
            continue
        _append_related(db, slug, [(target, reason)])
        _append_related(db, target, [(slug, reason)])
        written += 1
    return written
