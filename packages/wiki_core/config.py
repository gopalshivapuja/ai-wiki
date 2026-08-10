"""Paths and environment configuration."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(os.environ.get("WIKI_BASE_DIR", Path(__file__).resolve().parent.parent.parent))
SOURCES_DIR = BASE_DIR / "sources"
WIKI_DIR = BASE_DIR / "wiki"
ATOMIC_DIR = WIKI_DIR / "atomic"
INDEX_FILE = WIKI_DIR / "index.md"
LOG_FILE = WIKI_DIR / "log.md"
ENV_FILE = BASE_DIR / ".env"


def load_dotenv() -> None:
    if not ENV_FILE.exists():
        return
    try:
        from dotenv import load_dotenv as _load
        _load(ENV_FILE)
    except ImportError:
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def ensure_directories() -> None:
    for sub in ("youtube", "web", "pdfs", "documents", "assets"):
        (SOURCES_DIR / sub).mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "templates").mkdir(parents=True, exist_ok=True)
    ATOMIC_DIR.mkdir(parents=True, exist_ok=True)
    for sub in ("concepts", "entities", "sources", "syntheses"):
        (WIKI_DIR / sub).mkdir(parents=True, exist_ok=True)
