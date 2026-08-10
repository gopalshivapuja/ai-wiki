"""Database models and session."""

from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{os.environ.get('WIKI_DB_PATH', '/tmp/wiki.db')}",
)
# Railway Postgres uses postgres:// — SQLAlchemy needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="admin")
    is_active = Column(Boolean, default=True)
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

        admin_email = get_admin_email()
        admin_password = os.environ.get("ADMIN_PASSWORD", "changeme")
        existing = db.query(User).filter(User.email == admin_email).first()
        if not existing:
            db.add(
                User(
                    email=admin_email,
                    hashed_password=hash_password(admin_password),
                    role="admin",
                )
            )
            db.commit()
    finally:
        db.close()
