"""Database models — PostgreSQL is the single source of truth."""

from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://wiki:wiki@localhost:5432/wiki")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="admin")
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)


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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RawSource(Base):
    __tablename__ = "raw_sources"

    id = Column(Integer, primary_key=True)
    slug = Column(String, unique=True, index=True, nullable=False)
    title = Column(String, nullable=False)
    source_type = Column(String, default="web")
    url = Column(String, nullable=True)
    body = Column(Text, nullable=False, default="")
    extra = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True)
    action = Column(String, nullable=False)
    summary = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        from wiki_api.auth_utils import get_admin_email, hash_password

        if not db.query(User).filter(User.email == get_admin_email()).first():
            db.add(
                User(
                    email=get_admin_email(),
                    hashed_password=hash_password(os.environ.get("ADMIN_PASSWORD", "changeme")),
                    role="admin",
                )
            )
            db.commit()
    finally:
        db.close()
