"""In-process background job runner.

The queue is the `jobs` table, not memory: a redeploy replaces the container, and anything
held only in an asyncio.Queue would vanish with it. An in-memory event is a low-latency
wakeup hint so a freshly enqueued job does not wait for the next poll.

Deliberately not fastapi.BackgroundTasks — that has no identity to poll, no persistence, no
cancellation, and Starlette awaits it inside the response cycle, so a 90-second model call
would hold the connection open.

ONE worker, ONE process. `reap_orphans` marks every running job failed at boot, which is
only correct while this is true — do not run uvicorn with --workers > 1 without giving jobs
an owner id first. Set JOB_RUNNER_ENABLED=0 to run a web-only process.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from wiki_api.database import Job, session_scope, utcnow

logger = logging.getLogger(__name__)

JOB_TIMEOUT_SECONDS = int(os.environ.get("JOB_TIMEOUT_SECONDS", "1800"))
SHUTDOWN_GRACE_SECONDS = float(os.environ.get("SHUTDOWN_GRACE_SECONDS", "25"))
# Retention for the queue table. A payload is dead weight once its job has finished and is
# past retrying; the row itself is worth keeping longer, since /api/jobs is the only history
# of what was ingested.
JOB_PAYLOAD_TTL_SECONDS = int(os.environ.get("JOB_PAYLOAD_TTL_SECONDS", str(24 * 3600)))
JOB_ROW_TTL_SECONDS = int(os.environ.get("JOB_ROW_TTL_SECONDS", str(30 * 24 * 3600)))
POLL_INTERVAL = float(os.environ.get("JOB_POLL_INTERVAL", "10"))
RUNNER_ENABLED = os.environ.get("JOB_RUNNER_ENABLED", "1") not in ("0", "false", "False")

ACTIVE_STATUSES = ("queued", "running", "cancelling")


class JobCancelled(Exception):
    """Raised inside a handler when the user cancels or the deadline passes."""


@dataclass
class JobContext:
    """How a handler reports progress and notices cancellation.

    Each method opens its own short session so a progress write survives even if the
    handler's own transaction later rolls back.
    """

    job_id: int
    deadline: float

    def progress(self, current: int, total: int | None = None, message: str = "") -> None:
        with session_scope() as db:
            db.query(Job).filter(Job.id == self.job_id).update(
                {
                    "progress_current": current,
                    "progress_total": total,
                    "progress_message": (message or "")[:200],
                }
            )

    def should_stop(self) -> bool:
        if time.monotonic() > self.deadline:
            return True
        with session_scope() as db:
            return db.query(Job.status).filter(Job.id == self.job_id).scalar() == "cancelling"


# Handlers own their database sessions and open them only around actual DB work. Handing a
# handler a session meant a transcription held a pooled connection for its entire ~10-minute
# run, and a connection dropped in the meantime failed the final write after paying for it.
JobHandler = Callable[[dict, JobContext], dict]


def job_to_dict(j: Job) -> dict:
    def iso(dt: datetime | None) -> str | None:
        return dt.isoformat() if dt else None

    return {
        "id": j.id,
        "kind": j.kind,
        "status": j.status,
        "params": j.params or {},
        "progress": {
            "current": j.progress_current or 0,
            "total": j.progress_total,
            "message": j.progress_message or "",
        },
        "result": j.result,
        "error": j.error,
        "created_at": iso(j.created_at),
        "started_at": iso(j.started_at),
        "finished_at": iso(j.finished_at),
    }


def enqueue(db: Session, kind: str, params: dict, payload: str | None = None) -> Job:
    job = Job(kind=kind, params=params, payload=payload, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    if _RUNNER:
        _RUNNER.notify()
    return job


def reap_orphans() -> int:
    """Fail jobs left running by a previous process.

    Not re-queued: a half-finished transcription has already been paid for, and the user
    should decide whether to retry. The `started_at` filter keeps a booting container from
    killing the outgoing container's in-flight work during an overlapping deploy.
    """
    cutoff = utcnow() - timedelta(seconds=SHUTDOWN_GRACE_SECONDS + 10)
    with session_scope() as db:
        stale = (
            db.query(Job)
            .filter(Job.status.in_(("running", "cancelling")), Job.started_at < cutoff)
            .all()
        )
        for job in stale:
            job.status = "failed"
            job.error = "Interrupted by a server restart"
            job.finished_at = utcnow()
        count = len(stale)
    if count:
        logger.warning("Reaped %d job(s) interrupted by a restart", count)
    return count


FINISHED = ("done", "failed", "cancelled")


def sweep_finished_jobs() -> dict:
    """Drop upload bytes from finished jobs, and delete the old rows entirely.

    Job.payload carries the uploaded file (base64 PDFs and import archives) so a redeploy
    between enqueue and execution cannot lose it. Nothing ever removed it afterwards, so the
    queue table grew without bound and a hobby-tier database paid to store every PDF twice —
    once as the source document, once as the upload that created it.

    A payload is only useful while the job might still run or be retried, which is what makes
    dropping it from a finished job safe. Unfinished jobs are never touched.
    """
    payload_cutoff = utcnow() - timedelta(seconds=JOB_PAYLOAD_TTL_SECONDS)
    row_cutoff = utcnow() - timedelta(seconds=JOB_ROW_TTL_SECONDS)

    with session_scope() as db:
        stale_payloads = (
            db.query(Job)
            .filter(
                Job.status.in_(FINISHED),
                Job.payload.isnot(None),
                Job.finished_at < payload_cutoff,
            )
            .all()
        )
        freed = 0
        for job in stale_payloads:
            freed += len(job.payload or "")
            job.payload = None

        deleted = (
            db.query(Job)
            .filter(Job.status.in_(FINISHED), Job.finished_at < row_cutoff)
            .delete(synchronize_session=False)
        )

    if freed or deleted:
        logger.info(
            "Job sweep: cleared %d payload(s) (%.1f MB), deleted %d row(s)",
            len(stale_payloads),
            freed / 1_000_000,
            deleted,
        )
    return {"payloads_cleared": len(stale_payloads), "bytes_freed": freed, "rows_deleted": deleted}


def _finish(job_id: int, status: str, result: dict | None = None, error: str | None = None) -> None:
    # A fresh session on purpose: if the handler's session died we must still record this.
    with session_scope() as db:
        job = db.get(Job, job_id)
        if not job:
            return
        job.status = status
        job.result = result
        job.error = error
        job.finished_at = utcnow()


def _queue_distillation(kind: str, params: dict, result: object) -> None:
    """Queue distillation for every source a job captured.

    The single place this decision is made. Handlers used to each decide for themselves,
    which is why arXiv never summarised, crawl and paste defaulted to off, and import never
    did — so whether the wiki grew a graph depended on which button was pressed.
    """
    if kind == "distill" or not isinstance(result, dict):
        return
    # Import defaults to off: the common case is restoring a backup, whose notes come with
    # it, and re-distilling would create a second literature note for every source. Pass
    # distill=true when importing freshly captured material that has no notes yet.
    if not params.get("distill", kind != "import"):
        return
    sources = [s for s in (result.get("sources") or []) if s]
    if not sources:
        return

    with session_scope() as db:
        for slug in sources:
            enqueue(
                db,
                "distill",
                {
                    "source_slug": slug,
                    "moc": params.get("moc"),
                    "moc_title": params.get("moc_title"),
                },
            )
    logger.info("Queued distillation for %d source(s) from a %s job", len(sources), kind)


def _execute_job(job_id: int) -> None:
    from wiki_api.jobs.handlers import HANDLERS

    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != "running":
            return
        kind, params, payload = job.kind, dict(job.params or {}), job.payload

    handler = HANDLERS.get(kind)
    if handler is None:
        _finish(job_id, "failed", error=f"Unknown job kind: {kind}")
        return

    ctx = JobContext(job_id=job_id, deadline=time.monotonic() + JOB_TIMEOUT_SECONDS)
    if payload is not None:
        params["_payload"] = payload

    try:
        result = handler(params, ctx)
        _queue_distillation(kind, params, result)
    except JobCancelled as exc:
        logger.info("Job %s (%s) cancelled: %s", job_id, kind, exc)
        _finish(job_id, "cancelled", error=str(exc))
    except Exception as exc:
        logger.exception("Job %s (%s) failed", job_id, kind)
        _finish(job_id, "failed", error=f"{type(exc).__name__}: {exc}"[:4000])
    else:
        _finish(job_id, "done", result=result)


class JobRunner:
    def __init__(self, poll_interval: float = POLL_INTERVAL):
        self.poll_interval = poll_interval
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._stopping = False
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        global _RUNNER
        if not RUNNER_ENABLED:
            logger.info("Job runner disabled by JOB_RUNNER_ENABLED")
            return
        _RUNNER = self
        self._loop = asyncio.get_running_loop()
        await asyncio.to_thread(reap_orphans)
        # Runs after reaping so a job just marked failed can shed its payload in the same pass.
        await asyncio.to_thread(sweep_finished_jobs)
        self._stopping = False
        self._task = asyncio.create_task(self._loop_forever(), name="job-worker")
        logger.info("Job runner started")

    async def stop(self, grace: float = SHUTDOWN_GRACE_SECONDS) -> None:
        global _RUNNER
        self._stopping = True
        self._wake.set()
        if self._task:
            # Wait for in-flight work rather than orphaning a live DB session. Railway sends
            # SIGKILL about 30s after SIGTERM, so the grace period stays under that.
            _done, pending = await asyncio.wait({self._task}, timeout=grace)
            for t in pending:
                t.cancel()
            if pending:
                logger.warning("Job worker still busy at shutdown; it will be reaped on boot")
        self._task = None
        _RUNNER = None

    def notify(self) -> None:
        """Wake the worker immediately. Safe to call from a request thread."""
        loop = self._loop
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(self._wake.set)

    async def _loop_forever(self) -> None:
        while not self._stopping:
            try:
                job_id = await asyncio.to_thread(self._claim_next)
            except Exception:
                logger.exception("Job worker failed to claim a job")
                job_id = None

            if job_id is None:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=self.poll_interval)
                self._wake.clear()
                continue

            try:
                # The whole handler runs in one worker thread: handlers are ordinary sync
                # functions, and a sync Session must stay on a single thread.
                await asyncio.to_thread(_execute_job, job_id)
            except Exception:
                logger.exception("Job %s crashed the worker loop", job_id)
                _finish(job_id, "failed", error="Worker crashed")

    @staticmethod
    def _claim_next() -> int | None:
        """Atomically move the oldest queued job to running and return its id."""
        sql = text(
            """
            UPDATE jobs SET status = 'running', started_at = now()
            WHERE id = (
                SELECT id FROM jobs WHERE status = 'queued'
                ORDER BY created_at LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id
            """
        )
        with session_scope() as db:
            row = db.execute(sql).first()
            return row[0] if row else None


_RUNNER: JobRunner | None = None
