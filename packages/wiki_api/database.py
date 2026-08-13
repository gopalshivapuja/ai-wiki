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
    LargeBinary,
    String,
    Text,
    create_engine,
)
from sqlalchemy import event, inspect as sa_inspect
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


ADMIN = "admin"
READER = "reader"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    # "admin" writes; "reader" only reads. Defaulting to admin means the existing row keeps
    # its access when this column appears, which matters because create_all() adds it in
    # place with no migration.
    role = Column(String, nullable=False, default=ADMIN, server_default=ADMIN)
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

    # Position in meaning-space, so "related" can be computed instead of only hand-written.
    # Raw float32 rather than JSON: 1.5KB against roughly 9KB, and it is never queried in SQL —
    # similarity is computed in Python, which at this size is faster than a round trip.
    embedding = Column(LargeBinary, nullable=True)
    embedding_model = Column(String, nullable=True)
    embedded_at = Column(DateTime(timezone=True), nullable=True)

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
    """Create missing tables. Nothing more.

    User bootstrap deliberately does NOT live here: it queries columns that apply_schema_ddl()
    may not have added yet. Adding `users.role` and calling _ensure_admin() from here failed
    boot with "column users.role does not exist", because create_all() had left the existing
    table untouched and the DDL had not run. See ensure_users(), called after the DDL.
    """
    Base.metadata.create_all(bind=engine)


def ensure_users() -> None:
    """Sync the accounts from the environment. Must run after apply_schema_ddl()."""
    _ensure_admin()
    _ensure_demo()


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
            db.add(User(email=email, hashed_password=hash_password(password), role=ADMIN))
            db.commit()
            logger.info("Created admin user %s", email)
        else:
            if not verify_password(password, user.hashed_password):
                user.hashed_password = hash_password(password)
                logger.info("Updated admin password for %s from ADMIN_PASSWORD", email)
            # Re-asserted every boot: the admin must never be left as a reader by a bad edit.
            user.role = ADMIN
            db.commit()
    finally:
        db.close()


def _ensure_demo() -> None:
    """Create or re-sync the read-only demo account, if one is configured.

    A reader can see everything and change nothing (see require_admin in routes). The point is
    to be able to show the wiki — including what Add source looks like — without handing over
    the ability to write to it.

    Absent DEMO_EMAIL, no such account exists; this is opt-in.
    """
    from wiki_api.auth_utils import hash_password, verify_password

    email = (os.environ.get("DEMO_EMAIL") or "").strip().lower()
    password = os.environ.get("DEMO_PASSWORD") or ""
    if not email or not password:
        return

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            db.add(User(email=email, hashed_password=hash_password(password), role=READER))
            db.commit()
            logger.info("Created read-only demo user %s", email)
        else:
            if not verify_password(password, user.hashed_password):
                user.hashed_password = hash_password(password)
            # Forced every boot: a demo account that drifted to admin would be a quiet
            # privilege escalation on a login whose password is public by design.
            user.role = READER
            db.commit()
    finally:
        db.close()


# --- keeping embeddings current -----------------------------------------------
#
# Registered as mapper events rather than called from each write path on purpose. Embeddings
# were originally set in exactly one place — new zettels from distillation — so captured
# sources, literature notes and anything written through the editor never had a vector, and an
# edited note kept its old one. Nothing failed loudly; "related" simply went quiet on new
# material and convergence stopped seeing it, which is how duplicate notes come back.
#
# Four explicit calls would work until someone adds a fifth write path. This cannot be missed.


def _set_embedding(doc: "Document") -> None:
    """Compute a document's vector. Leaves the old one alone if no model is available."""
    from wiki_api.services.embed import MODEL_NAME, embed_document

    blob = embed_document(doc.title or "", doc.body or "")
    if blob is None:
        # A stale vector still finds the note; None makes it invisible to every search.
        return
    doc.embedding = blob
    doc.embedding_model = MODEL_NAME
    doc.embedded_at = utcnow()


@event.listens_for(Document, "before_insert")
def _embed_new_document(_mapper, _connection, target: "Document") -> None:
    if target.embedding is None:
        _set_embedding(target)


@event.listens_for(Document, "before_update")
def _reembed_changed_document(_mapper, _connection, target: "Document") -> None:
    """Only when the text actually changed — a tag edit should not pay for a model call."""
    state = sa_inspect(target)
    if state.attrs.title.history.has_changes() or state.attrs.body.history.has_changes():
        _set_embedding(target)
