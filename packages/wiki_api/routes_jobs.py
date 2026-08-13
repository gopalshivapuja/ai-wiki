"""Ingest and background-job endpoints, mounted at /api/jobs."""

from __future__ import annotations

import base64
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from wiki_api.auth import get_current_user, require_admin
from wiki_api.database import Job, User, get_db, utcnow
from wiki_api.jobs.runner import enqueue, job_to_dict
from wiki_api.services.crawl import DEFAULT_MAX_DEPTH, DEFAULT_MAX_PAGES, HARD_MAX_PAGES
from wiki_api.services.fetch import MAX_PDF_BYTES

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_IMPORT_BYTES = 100_000_000


class Filing(BaseModel):
    """Where the notes from this source should be filed."""

    moc: str | None = Field(default=None, max_length=120)
    moc_title: str | None = Field(default=None, max_length=200)
    distill: bool = True


class UrlBody(Filing):
    url: str = Field(min_length=1, max_length=2000)


class ArxivBody(Filing):
    id_or_url: str = Field(min_length=1, max_length=500)


class CrawlBody(Filing):
    url: str = Field(min_length=1, max_length=2000)
    max_pages: int = Field(default=DEFAULT_MAX_PAGES, ge=1, le=HARD_MAX_PAGES)
    max_depth: int = Field(default=DEFAULT_MAX_DEPTH, ge=0, le=5)
    collection: str | None = Field(default=None, max_length=120)


class PasteBody(Filing):
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=1_000_000)


class SummarizeBody(Filing):
    source_slug: str = Field(min_length=1, max_length=200)


class ChannelBody(Filing):
    url: str = Field(min_length=1, max_length=2000)
    limit: int | None = Field(default=None, ge=1, le=500)


def _submit(db: Session, kind: str, params: dict, payload: str | None = None) -> dict:
    return job_to_dict(enqueue(db, kind, params, payload))


async def _read_upload(file: UploadFile, max_bytes: int) -> bytes:
    chunks, size = [], 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(413, f"File exceeds the {max_bytes // 1_000_000}MB limit")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/web")
def job_web(body: UrlBody, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return _submit(db, "web", body.model_dump())


@router.post("/arxiv")
def job_arxiv(body: ArxivBody, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return _submit(db, "arxiv", body.model_dump())


@router.post("/youtube")
def job_youtube(body: UrlBody, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return _submit(db, "youtube", body.model_dump())


@router.post("/transcribe")
def job_transcribe(
    body: UrlBody, db: Session = Depends(get_db), user: User = Depends(require_admin)
):
    from wiki_api.services.transcribe import is_configured, stt_provider

    if not is_configured():
        raise HTTPException(
            400,
            f"Transcription is not configured. Set STT_PROVIDER (currently '{stt_provider()}') "
            "and the matching API key.",
        )
    return _submit(db, "transcribe", body.model_dump())


@router.post("/youtube-channel")
def job_youtube_channel(
    body: ChannelBody, db: Session = Depends(get_db), user: User = Depends(require_admin)
):
    """Queue every video on a channel or playlist. Re-running skips what is already stored."""
    return _submit(db, "youtube-channel", body.model_dump())


@router.post("/crawl")
def job_crawl(body: CrawlBody, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return _submit(db, "crawl", body.model_dump())


@router.post("/paste")
def job_paste(body: PasteBody, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    return _submit(db, "paste", body.model_dump())


@router.post("/summarize")
def job_summarize(
    body: SummarizeBody, db: Session = Depends(get_db), user: User = Depends(require_admin)
):
    return _submit(db, "summarize", body.model_dump())


@router.post("/pdf")
async def job_pdf(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    moc: str | None = Form(default=None),
    moc_title: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Only .pdf files are supported")
    data = await _read_upload(file, MAX_PDF_BYTES)
    # Stored in the job row rather than on ephemeral disk, so a redeploy between upload and
    # execution cannot lose the file and retry works.
    return _submit(
        db,
        "pdf",
        {"title": title, "filename": file.filename, "moc": moc, "moc_title": moc_title},
        base64.b64encode(data).decode(),
    )


@router.post("/import")
async def job_import(
    file: UploadFile = File(...),
    distill: bool = Form(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Restore an export, or import any folder of markdown with YAML frontmatter.

    `distill` defaults to false because the usual case is a restore, whose notes arrive with
    the archive. Set it when importing captured material that has no notes yet.
    """
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(400, "Upload a .zip archive")
    data = await _read_upload(file, MAX_IMPORT_BYTES)
    return _submit(
        db,
        "import",
        {"filename": file.filename, "distill": distill},
        base64.b64encode(data).decode(),
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
def cancel_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status == "queued":
        job.status = "cancelled"
        job.error = "Cancelled before it started"
        job.finished_at = utcnow()
    elif job.status == "running":
        # Handlers are synchronous, so cancellation is cooperative: the job stops at its
        # next checkpoint (between crawled pages, for instance), not instantly.
        job.status = "cancelling"
    else:
        raise HTTPException(409, f"Job is already {job.status}")
    db.commit()
    db.refresh(job)
    return job_to_dict(job)


@router.post("/{job_id}/retry")
def retry_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status not in ("failed", "cancelled"):
        raise HTTPException(
            409, f"Only failed or cancelled jobs can be retried (this one is {job.status})"
        )
    # The payload travels with the job, so uploads retry like anything else.
    return _submit(db, job.kind, dict(job.params or {}), job.payload)
