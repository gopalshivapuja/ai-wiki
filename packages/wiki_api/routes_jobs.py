"""Job endpoints. Mounted at /api/jobs.

Everything here either costs money or writes, so all routes require authentication.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from wiki_api.auth import get_current_user
from wiki_api.database import Job, User, get_db, utcnow
from wiki_api.jobs.runner import TooManyJobs, enqueue, job_to_dict
from wiki_api.services.crawl import DEFAULT_MAX_DEPTH, DEFAULT_MAX_PAGES, HARD_MAX_PAGES
from wiki_api.services.fetch import MAX_PDF_BYTES

logger = logging.getLogger(__name__)
router = APIRouter()


class UrlBody(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    summarize: bool = True


class ArxivBody(BaseModel):
    id_or_url: str = Field(min_length=1, max_length=500)


class CrawlBody(BaseModel):
    url: str = Field(min_length=1, max_length=2000)
    max_pages: int = Field(default=DEFAULT_MAX_PAGES, ge=1, le=HARD_MAX_PAGES)
    max_depth: int = Field(default=DEFAULT_MAX_DEPTH, ge=0, le=5)
    collection: str | None = Field(default=None, max_length=120)
    summarize: bool = False


class PasteBody(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=1_000_000)
    summarize: bool = False


class SummarizeBody(BaseModel):
    source_slug: str = Field(min_length=1, max_length=200)


def _submit(db: Session, kind: str, params: dict) -> dict:
    try:
        job = enqueue(db, kind, params)
    except TooManyJobs as exc:
        raise HTTPException(429, str(exc)) from exc
    return job_to_dict(job)


@router.post("/web")
def job_web(body: UrlBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _submit(db, "web", body.model_dump())


@router.post("/arxiv")
def job_arxiv(
    body: ArxivBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return _submit(db, "arxiv", body.model_dump())


@router.post("/youtube")
def job_youtube(
    body: UrlBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return _submit(db, "youtube", body.model_dump())


@router.post("/transcribe")
def job_transcribe(
    body: UrlBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    from wiki_api.services.transcribe import is_configured, stt_provider

    if not is_configured():
        raise HTTPException(
            400,
            f"Transcription is not configured. Set STT_PROVIDER (currently '{stt_provider()}') "
            "and the matching API key.",
        )
    return _submit(db, "transcribe", body.model_dump())


@router.post("/crawl")
def job_crawl(
    body: CrawlBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return _submit(db, "crawl", body.model_dump())


@router.post("/paste")
def job_paste(
    body: PasteBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return _submit(db, "paste", body.model_dump())


@router.post("/summarize")
def job_summarize(
    body: SummarizeBody, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return _submit(db, "summarize", body.model_dump())


@router.post("/pdf")
async def job_pdf(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    summarize: bool = Form(default=True),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Only .pdf files are supported")

    # Streamed to disk rather than read into memory — a 25MB upload should not become a
    # 25MB bytes object in a 512MB container.
    tmp = Path(tempfile.gettempdir()) / f"wiki-upload-{utcnow().strftime('%Y%m%d%H%M%S%f')}.pdf"
    size = 0
    try:
        with tmp.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_PDF_BYTES:
                    raise HTTPException(
                        413, f"PDF exceeds the {MAX_PDF_BYTES // 1_000_000}MB limit"
                    )
                out.write(chunk)
    except HTTPException:
        tmp.unlink(missing_ok=True)
        raise
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    return _submit(
        db,
        "pdf",
        {
            "upload_path": str(tmp),
            "title": title,
            "filename": file.filename,
            "summarize": summarize,
        },
    )


@router.get("")
def list_jobs(
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    jobs = db.query(Job).order_by(Job.created_at.desc(), Job.id.desc()).limit(limit).all()
    return {"jobs": [job_to_dict(j) for j in jobs]}


@router.get("/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job_to_dict(job)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status == "queued":
        job.status = "cancelled"
        job.error = "Cancelled before it started"
        job.finished_at = utcnow()
    elif job.status == "running":
        # Handlers are synchronous, so cancellation is cooperative: the job stops at its next
        # checkpoint (between crawled pages, for instance), not instantly.
        job.status = "cancelling"
    else:
        raise HTTPException(409, f"Job is already {job.status}")
    db.commit()
    db.refresh(job)
    return job_to_dict(job)


@router.post("/{job_id}/retry")
def retry_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status not in ("failed", "cancelled"):
        raise HTTPException(
            409, f"Only failed or cancelled jobs can be retried (this one is {job.status})"
        )
    if job.kind == "pdf":
        raise HTTPException(409, "Re-upload the PDF instead — the temporary file is gone")
    return _submit(db, job.kind, dict(job.params or {}))
