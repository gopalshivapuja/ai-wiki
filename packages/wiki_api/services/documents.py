"""PDF and pasted-text ingest."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session
from wiki_core.utils import slugify

from wiki_api.services.content import log_action, upsert_source
from wiki_api.services.fetch import clamp

logger = logging.getLogger(__name__)

MAX_PDF_PAGES = 500


def extract_pdf_text(path: Path, max_pages: int = MAX_PDF_PAGES) -> tuple[str, str]:
    """Return (title, text). Title comes from PDF metadata, falling back to the filename."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ValueError("pypdf is not installed") from exc

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise ValueError("This PDF is password protected") from exc

    title = ""
    try:
        title = (reader.metadata.title or "").strip() if reader.metadata else ""
    except Exception:
        title = ""
    title = title or path.stem.replace("_", " ").replace("-", " ").strip()

    chunks = []
    for i, page in enumerate(reader.pages):
        if i >= max_pages:
            chunks.append(f"\n\n*(stopped after {max_pages} pages)*")
            break
        try:
            chunks.append(page.extract_text() or "")
        except Exception as exc:
            logger.warning("Failed to extract page %d of %s: %s", i, path.name, exc)

    text = "\n\n".join(c.strip() for c in chunks if c and c.strip())
    if not text.strip():
        raise ValueError(
            "No text could be extracted — this looks like a scanned PDF. "
            "It would need OCR, which this wiki does not do."
        )
    return title, text


def ingest_pdf(
    db: Session, path: Path, title: str | None = None, filename: str | None = None
) -> dict:
    """Ingest an uploaded PDF.

    `filename` is the name the user uploaded; `path` is a server-side temp file whose name
    must never appear in the stored note.
    """
    extracted_title, text = extract_pdf_text(path)
    display_name = filename or path.name
    title = (title or extracted_title).strip() or Path(display_name).stem
    slug = slugify(title) or slugify(Path(display_name).stem) or "pdf-document"
    content = clamp(f"# {title}\n\n**Source:** uploaded PDF ({display_name})\n\n---\n\n{text}")
    source, created = upsert_source(
        db, slug, title, content, "pdf", extra={"filename": display_name}
    )
    if created:
        log_action(db, "ingest", f"PDF: {title}")
    return {"slug": source.slug, "title": source.title, "type": "pdf", "created": created}


def ingest_paste(db: Session, title: str, text: str, source_type: str = "note") -> dict:
    title = (title or "").strip()
    if not title:
        raise ValueError("Title is required")
    if not (text or "").strip():
        raise ValueError("Text is required")
    slug = slugify(title)
    if not slug:
        raise ValueError("Title must contain at least one letter or number")
    content = clamp(f"# {title}\n\n{text.strip()}")
    source, created = upsert_source(db, slug, title, content, source_type)
    if created:
        log_action(db, "ingest", f"Pasted: {title}")
    return {"slug": source.slug, "title": source.title, "type": source_type, "created": created}
