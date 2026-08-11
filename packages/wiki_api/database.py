"""Database models — PostgreSQL is the single source of truth."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://wiki:wiki@localhost:5432/wiki")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # Small pool on purpose: background jobs each take a short-lived connection, and Railway's
    # Postgres has a modest connection limit. See CLAUDE.md for the cost rationale.
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=int(os.environ.get("DB_POOL_SIZE", "5")),
        max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "5")),
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def utcnow() -> datetime:
    """Timezone-aware UTC now. Use everywhere instead of the deprecated datetime.utcnow()."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="admin")
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Page(Base):
    __tablename__ = "pages"

    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, index=True, nullable=False)
    uid = Column(String, nullable=True, index=True)
    title = Column(String, nullable=False)
    page_type = Column(String, default="page", index=True)
    body = Column(Text, nullable=False, default="")
    tags = Column(JSON, default=list)
    source_refs = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RawSource(Base):
    __tablename__ = "raw_sources"

    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, index=True, nullable=False)
    title = Column(String, nullable=False)
    source_type = Column(String, default="web")
    url = Column(String, nullable=True)
    body = Column(Text, nullable=False, default="")
    extra = Column(JSON, default=dict)
    # Set for crawled pages so a docs crawl can be viewed/deleted as one unit.
    collection = Column(String, nullable=True, index=True)
    # Distinguishes two different URLs that slugify to the same title.
    url_hash = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True)
    action = Column(String, nullable=False)
    summary = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class Job(Base):
    """A background job. The DB is the queue — see wiki_api/jobs/runner.py."""

    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True)
    kind = Column(String, nullable=False, index=True)
    # queued | running | cancelling | done | failed | cancelled
    status = Column(String, nullable=False, default="queued", index=True)
    params = Column(JSON, default=dict)
    progress_current = Column(Integer, default=0)
    progress_total = Column(Integer, nullable=True)
    progress_message = Column(String, default="")
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, index=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


def get_db() -> Iterator[Session]:
    """Request-scoped session. Closed when the response is returned.

    Never capture this in a background task — use session_scope() there instead.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Task-owned session with commit/rollback/close.

    Background jobs must use this: the get_db() session belongs to a request and is closed
    the moment that response is sent.
    """
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
    """Create the admin on first boot, and keep the password in sync with ADMIN_PASSWORD.

    Without the sync step, a deploy that started with the default 'changeme' would keep
    accepting it forever — later ADMIN_PASSWORD changes only ever applied to a fresh database.
    """
    from wiki_api.auth_utils import get_admin_email, hash_password, verify_password

    email = get_admin_email()
    password = os.environ.get("ADMIN_PASSWORD", "changeme")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            db.add(User(email=email, hashed_password=hash_password(password), role="admin"))
            db.commit()
            logger.info("Created admin user %s", email)
        elif not verify_password(password, user.hashed_password):
            user.hashed_password = hash_password(password)
            user.is_active = 1
            db.commit()
            logger.info("Updated admin password for %s from ADMIN_PASSWORD", email)
    finally:
        db.close()
