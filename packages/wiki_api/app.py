"""LLM Wiki — single web app (API + frontend + PostgreSQL)."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

VERSION = "0.4.0"


def _resolve_static_dir() -> Path:
    """Locate the built SPA.

    STATIC_DIR wins (the Docker image sets it). Otherwise try the two layouts a developer
    actually has: the CI-style <repo>/static copy, then Vite's <repo>/apps/web/dist.
    """
    env = os.environ.get("STATIC_DIR")
    if env:
        return Path(env)
    repo = Path(__file__).resolve().parents[2]
    for candidate in (repo / "static", repo / "apps" / "web" / "dist"):
        if candidate.is_dir():
            return candidate
    return repo / "apps" / "web" / "dist"


STATIC_DIR = _resolve_static_dir()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from wiki_api.database import ensure_users, init_db, session_scope
    from wiki_api.jobs.runner import JobRunner
    from wiki_api.schema_ddl import apply_schema_ddl
    from wiki_api.services.archive import default_seed_dir, seed_if_empty
    from wiki_api.startup import check_secrets, wait_for_database

    check_secrets()
    # The app container and the database service usually start together, so the first
    # connect attempt often lands before the database is listening.
    wait_for_database()

    # Order matters: create_all() must make the tables before apply_schema_ddl() adds the
    # generated column and indexes, and both must precede any read of seeded content.
    init_db()
    apply_schema_ddl()
    # After the DDL: these read columns the DDL is responsible for adding to tables that
    # already exist, which create_all() never touches.
    ensure_users()
    with session_scope() as db:
        seed_if_empty(db, default_seed_dir())

    runner = JobRunner()
    await runner.start()
    try:
        yield
    finally:
        await runner.stop()


app = FastAPI(title="LLM Wiki", version=VERSION, lifespan=lifespan)

from wiki_api.auth import router as auth_router  # noqa: E402
from wiki_api.routes import router as api_router  # noqa: E402
from wiki_api.routes_jobs import router as jobs_router  # noqa: E402

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(api_router, prefix="/api", tags=["wiki"])
app.include_router(jobs_router, prefix="/api/jobs", tags=["jobs"])


@app.get("/health")
def health():
    # Deliberately does not touch the database: a saturated worker or a slow query must not
    # fail the Railway healthcheck and trigger a restart loop.
    return {"status": "ok", "version": VERSION}


# --- SPA ----------------------------------------------------------------------
# Registered unconditionally. The previous version only mounted these when STATIC_DIR
# existed at import time, so a missing build produced a bare 404 with no explanation.

if (STATIC_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")
else:
    logger.warning(
        "No built frontend at %s — API only. Build it with: "
        "cd apps/web && npm install && npm run build",
        STATIC_DIR,
    )


@app.get("/{full_path:path}", include_in_schema=False)
async def spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404, "Not found")

    root = STATIC_DIR.resolve()
    index = root / "index.html"
    if not index.is_file():
        raise HTTPException(
            503,
            "Frontend not built. Run `cd apps/web && npm run build`, or set STATIC_DIR.",
        )

    if full_path:
        # Resolve and confirm the result is still inside STATIC_DIR. Without this,
        # `GET /..%2f..%2fetc/passwd` escapes the static root — uvicorn percent-decodes the
        # path and does not remove dot segments, and this handler bypasses the traversal
        # protection that StaticFiles would otherwise provide.
        try:
            candidate = (root / full_path).resolve()
        except (OSError, ValueError):
            return FileResponse(index)
        if candidate.is_relative_to(root) and candidate.is_file():
            return FileResponse(candidate)

    return FileResponse(index)
