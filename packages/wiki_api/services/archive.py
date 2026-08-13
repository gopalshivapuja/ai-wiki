"""Export and import the whole wiki as markdown with YAML frontmatter.

One format serves backup, restore, portability (Obsidian and friends read it directly), and
first-boot seeding. Without an export, a database on a hobby plan is the only copy of
everything you have written — which is not an acceptable place for years of notes to live.
"""

from __future__ import annotations

import io
import logging
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

from sqlalchemy.orm import Session

from wiki_api.database import SOURCE, Document
from wiki_api.services.content import import_markdown, log_action, to_markdown

logger = logging.getLogger(__name__)

MAX_IMPORT_FILES = 5_000
MAX_IMPORT_BYTES = 100_000_000

ProgressFn = Callable[[int, int, str], None]


def _archive_path(doc: Document) -> str:
    folder = "sources" if doc.doc_class == SOURCE else f"notes/{doc.subtype}"
    return f"{folder}/{doc.slug}.md"


class _DrainableBuffer(io.RawIOBase):
    """A write-only sink that can be emptied without losing its stream position.

    zipfile records every entry's offset in the central directory from ``fp.tell()``. The
    previous implementation drained with ``seek(0)`` + ``truncate(0)``, which reset ``tell()``
    to zero, so each offset after the first drain pointed at the wrong byte and the archive
    could not be extracted — "bad zipfile offset".

    It only bit above ``chunk_docs`` documents, because a smaller wiki is written in a single
    piece and never drains mid-stream. That is why the round-trip test never caught it while
    every real backup of a 600-document wiki was unreadable.
    """

    def __init__(self) -> None:
        self._parts: list[bytes] = []
        self._pos = 0

    def writable(self) -> bool:
        return True

    # Reported as non-seekable so zipfile never tries to rewind into bytes we already yielded.
    def seekable(self) -> bool:
        return False

    def write(self, b) -> int:
        data = bytes(b)
        self._parts.append(data)
        self._pos += len(data)
        return len(data)

    def tell(self) -> int:
        return self._pos

    def drain(self) -> bytes:
        data = b"".join(self._parts)
        self._parts.clear()
        return data


def export_stream(db: Session, chunk_docs: int = 50) -> Iterator[bytes]:
    """Yield a zip of the whole wiki.

    Written to a buffer that is drained as it fills, so a large wiki never has to fit in the
    container's memory at once.
    """
    buffer = _DrainableBuffer()
    zf = zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED)

    written = 0
    # yield_per streams rows instead of materialising every body at once.
    for doc in db.query(Document).order_by(Document.slug).yield_per(chunk_docs):
        zf.writestr(_archive_path(doc), to_markdown(doc))
        written += 1
        if written % chunk_docs == 0:
            chunk = buffer.drain()
            if chunk:
                yield chunk

    zf.writestr(
        "README.md",
        "# ai-wiki export\n\n"
        f"{written} documents, one markdown file each, with YAML frontmatter.\n\n"
        "`notes/` is what you wrote; `sources/` is captured material.\n"
        "Re-import this archive with POST /api/import, or open the folder in any "
        "markdown editor.\n",
    )
    zf.close()
    yield buffer.drain()
    logger.info("Exported %d documents", written)


def import_archive(db: Session, data: bytes, on_progress: ProgressFn | None = None) -> dict:
    """Import a zip produced by export_stream (or any folder of markdown with frontmatter)."""
    if len(data) > MAX_IMPORT_BYTES:
        raise ValueError(f"Archive exceeds the {MAX_IMPORT_BYTES // 1_000_000}MB limit")

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("That file is not a readable zip archive") from exc

    names = [
        n
        for n in zf.namelist()
        # Reject absolute paths and traversal before touching anything.
        if n.lower().endswith(".md")
        and not n.startswith(("/", "\\"))
        and ".." not in Path(n).parts
        and Path(n).name.lower() != "readme.md"
    ]
    if not names:
        raise ValueError("The archive contains no markdown files")
    if len(names) > MAX_IMPORT_FILES:
        raise ValueError(f"Archive holds more than {MAX_IMPORT_FILES} files")

    imported, failed, sources = 0, [], []
    import tempfile

    with tempfile.TemporaryDirectory(prefix="wiki-import-") as tmp:
        tmpdir = Path(tmp)
        for i, name in enumerate(names, start=1):
            if on_progress and i % 10 == 0:
                on_progress(i, len(names), f"Importing {name}")
            try:
                # Written to a temp file so import_markdown() is the same code path used by
                # seeding — one importer, not two.
                target = tmpdir / Path(name).name
                target.write_bytes(zf.read(name))
                hint = _subtype_hint(name)
                doc = import_markdown(db, target, subtype_hint=hint)
                if doc:
                    imported += 1
                    if doc.doc_class == SOURCE:
                        sources.append(doc.slug)
                target.unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("Import failed for %s: %s", name, exc)
                failed.append({"file": name, "error": str(exc)[:200]})

    log_action(db, "import", f"Imported {imported} documents from an archive")
    # Reported so the runner distils them, like any other capture route.
    return {"imported": imported, "failed": failed, "total": len(names), "sources": sources}


def _subtype_hint(archive_name: str) -> str | None:
    """Infer the document type from the archive layout when frontmatter omits it."""
    parts = Path(archive_name).parts
    if "sources" in parts:
        return "web"
    if "notes" in parts:
        idx = parts.index("notes")
        if idx + 1 < len(parts) - 1:
            return parts[idx + 1]
    return None


def seed_if_empty(db: Session, seed_dir: Path) -> int:
    """Import bundled starter content on first boot, when the wiki is empty.

    An ordinary caller of the import path rather than boot-time magic with its own rules.
    """
    if db.query(Document.id).first() is not None:
        return 0
    if not seed_dir.is_dir():
        logger.warning("No seed directory at %s — starting empty", seed_dir)
        return 0

    count = 0
    for md in sorted(seed_dir.rglob("*.md")):
        rel = md.relative_to(seed_dir)
        if md.name.lower() == "readme.md" or "assets" in rel.parts:
            continue
        try:
            if import_markdown(db, md, subtype_hint=_subtype_hint(str(rel))):
                count += 1
        except Exception as exc:
            logger.warning("Could not seed %s: %s", rel, exc)

    if count:
        log_action(db, "seed", f"Imported {count} starter documents")
        logger.info("Seeded %d documents from %s", count, seed_dir)
    else:
        logger.warning("Seed directory %s contained no importable markdown", seed_dir)
    return count


def default_seed_dir() -> Path:
    """Where the bundled starter content lives.

    WIKI_SEED_DIR is what the Docker image sets. The fallback only resolves in a source
    checkout: after a plain `pip install .` this module lives in site-packages, which is
    why production once seeded nothing at all, silently.
    """
    import os

    env = os.environ.get("WIKI_SEED_DIR")
    if env:
        return Path(env) / "seed"
    return Path(__file__).resolve().parents[3] / "seed"
