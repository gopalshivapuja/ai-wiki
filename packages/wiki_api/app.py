"""LLM Wiki — single web app (API + frontend + PostgreSQL)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

STATIC_DIR = Path(os.environ.get("STATIC_DIR", Path(__file__).resolve().parents[2] / "static"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    from wiki_api.database import init_db
    from wiki_api.database import SessionLocal
    from wiki_api.services.seed import seed_if_empty

    init_db()
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()
    yield


app = FastAPI(title="LLM Wiki", version="0.2.0", lifespan=lifespan)

from wiki_api.auth import router as auth_router  # noqa: E402
from wiki_api.routes import router as api_router  # noqa: E402

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(api_router, prefix="/api", tags=["wiki"])


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.2.0"}


# Serve React SPA
if STATIC_DIR.exists():
    assets = STATIC_DIR / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        index = STATIC_DIR / "index.html"
        if full_path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(404)
        file = STATIC_DIR / full_path
        if file.is_file():
            return FileResponse(file)
        return FileResponse(index)
