"""Database models. PostgreSQL is the single source of truth."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)

DEFAULT_DATABASE_URL = "postgresql://wiki:wiki@localhost:5432/wiki"
DEFAULT_JWT_SECRET = "dev-secret-change-in-production"
DEFAULT_ADMIN_PASSWORD = "changeme"

DATABASE_URL = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# PostgreSQL only. A second dialect meant a second search implementation with different
# ranking, which silently masked failures in the real one.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=int(os.environ.get("DB_POOL_SIZE", "5")),
    max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "5")),
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def utcnow() -> datetime:
    """Timezone-aware UTC now. Use instead of the deprecated datetime.utcnow()."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


# What a document is. `note` is anything you write or the AI writes for you; `source` is
# captured material that is never edited after capture.
NOTE = "note"
SOURCE = "source"

# Subtypes of a note. Only `literature` carries behaviour (it marks machine-written pages);
# the rest are organisational vocabulary.
NOTE_SUBTYPES = (
    "zettel",
    "concept",
    "entity",
    "moc",
    "synthesis",
    "literature",
    "page",
    "index",
)
SOURCE_SUBTYPES = ("web", "pdf", "youtube", "audio", "arxiv", "note")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Document(Base):
    """A note or a captured source.

    One table, one slug namespace. Splitting these apart meant a `kind` discriminator in
    ~35 places, two search implementations, two REST resources — and, worse, wikilinks could
    never resolve to a source, so "this note came from that source" was not a link.
    """

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, index=True, nullable=False)
    uid = Column(String, nullable=True, index=True)
    title = Column(String, nullable=False)

    doc_class = Column(String, nullable=False, default=NOTE, index=True)
    subtype = Column(String, nullable=False, default="page", index=True)

    body = Column(Text, nullable=False, default="")
    # JSONB so tag filtering is a GIN-indexed containment query instead of a Python scan.
    tags = Column(JSONB, default=list)

    # Sources only.
    url = Column(String, nullable=True)
    collection = Column(String, nullable=True, index=True)
    extra = Column(JSONB, default=dict)

    # A literature note points at the source it summarises. Replaces both the `source_refs`
    # JSON array and the `summary-<slug>` naming convention.
    derived_from_id = Column(
        Integer, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Captured material is not editable. The invariant survives the table merge as a column.
    immutable = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    @property
    def is_source(self) -> bool:
        return self.doc_class == SOURCE


class Revision(Base):
    """A prior version of a document's body, written before every content-changing update.

    Without this, a bad paste, a stray select-all-delete, or an AI rewrite is unrecoverable.
    """

    __tablename__ = "revisions"

    id = Column(Integer, primary_key=True)
    document_id = Column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True)
    action = Column(String, nullable=False)
    summary = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)


class Job(Base):
    """A background job. The `jobs` table is the queue — see wiki_api/jobs/runner.py."""

    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    kind = Column(String, nullable=False, index=True)
    # queued | running | cancelling | done | failed | cancelled
    status = Column(String, nullable=False, default="queued", index=True)
    params = Column(JSON, default=dict)
    # Uploaded bytes live here, not on the container's ephemeral disk, so a redeploy between
    # enqueue and execution does not lose the file and retry can work.
    payload = Column(Text, nullable=True)
    progress_current = Column(Integer, default=0)
    progress_total = Column(Integer, nullable=True)
    progress_message = Column(String, default="")
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


def get_db() -> Iterator[Session]:
    """Request-scoped session, closed when the response is returned.

    Never capture this in a background task — use session_scope() there.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Task-owned session with commit/rollback/close, for background jobs."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_admin()


def _ensure_admin() -> None:
    """Create the admin on first boot and keep the password in sync with ADMIN_PASSWORD.

    The environment is the credential store: there is deliberately no signup and no in-app
    password change, because this function would revert it on the next deploy.

    Note that changing ADMIN_EMAIL creates a *second* admin and leaves the first one usable —
    delete the old row by hand if you rotate the address.
    """
    from wiki_api.auth_utils import get_admin_email, hash_password, verify_password

    email = get_admin_email()
    password = os.environ.get("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            db.add(User(email=email, hashed_password=hash_password(password)))
            db.commit()
            logger.info("Created admin user %s", email)
        elif not verify_password(password, user.hashed_password):
            user.hashed_password = hash_password(password)
            db.commit()
            logger.info("Updated admin password for %s from ADMIN_PASSWORD", email)
    finally:
        db.close()
