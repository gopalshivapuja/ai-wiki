"""In-process background job runner.

The queue lives in the `jobs` table, not in memory: a Railway redeploy replaces the
container, and anything held only in an asyncio.Queue would vanish with it. An in-memory
event is used solely as a low-latency wakeup hint so a freshly enqueued job does not wait
for the next poll.

Deliberately not fastapi.BackgroundTasks — that has no identity to poll, no persistence, no
cancellation, and Starlette awaits it inside the response cycle, so a 90-second LLM call
would hold the connection open.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import anyio
from sqlalchemy import text
from sqlalchemy.orm import Session

from wiki_api.database import Job, engine, session_scope, utcnow

logger = logging.getLogger(__name__)

JOB_CONCURRENCY = int(os.environ.get("JOB_CONCURRENCY", "2"))
MAX_PENDING_JOBS = int(os.environ.get("MAX_PENDING_JOBS", "20"))
JOB_TIMEOUT_SECONDS = int(os.environ.get("JOB_TIMEOUT_SECONDS", "1800"))
SHUTDOWN_GRACE_SECONDS = float(os.environ.get("SHUTDOWN_GRACE_SECONDS", "25"))
POLL_INTERVAL = float(os.environ.get("JOB_POLL_INTERVAL", "10"))

ACTIVE_STATUSES = ("queued", "running", "cancelling")


class JobCancelled(Exception):
    """Raised inside a handler when the user cancels or the deadline passes."""


@dataclass
class JobContext:
    """Handle a handler uses to report progress and notice cancellation.

    Every method opens its own short-lived session so a progress write survives even if the
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

    def cancelled(self) -> bool:
        with session_scope() as db:
            status = db.query(Job.status).filter(Job.id == self.job_id).scalar()
        return status == "cancelling"

    def check_stop(self) -> None:
        if time.monotonic() > self.deadline:
            raise JobCancelled(f"Exceeded the {JOB_TIMEOUT_SECONDS}s time limit")
        if self.cancelled():
            raise JobCancelled("Cancelled")

    def should_stop(self) -> bool:
        return time.monotonic() > self.deadline or self.cancelled()


JobHandler = Callable[[Session, dict, JobContext], dict]


def job_to_dict(j: Job) -> dict:
    def iso(dt: datetime | None) -> str | None:
        return dt.isoformat() if dt else None

    return {
        "id": j.id,
        "kind": j.kind,
        "status": j.status,
        "params": _public_params(j.params or {}),
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


def _public_params(params: dict) -> dict:
    """Hide server-side scratch paths from API responses."""
    return {k: v for k, v in params.items() if k not in ("upload_path",)}


def enqueue(db: Session, kind: str, params: dict) -> Job:
    pending = db.query(Job).filter(Job.status.in_(ACTIVE_STATUSES)).count()
    if pending >= MAX_PENDING_JOBS:
        raise TooManyJobs(f"{pending} jobs are already queued or running")
    job = Job(kind=kind, params=params, status="queued")
    db.add(job)
    db.commit()
    db.refresh(job)
    _RUNNER and _RUNNER.notify()
    return job


class TooManyJobs(Exception):
    """The pending-job cap was hit. Maps to HTTP 429."""


def reap_orphans() -> int:
    """Fail jobs left 'running' by a previous process.

    Not re-queued: a half-finished transcription has already spent money, and the user
    should decide whether to retry. Retrying is cheap anyway — upsert_source skips sources
    that were already stored.
    """
    with session_scope() as db:
        stale = db.query(Job).filter(Job.status.in_(("running", "cancelling"))).all()
        for job in stale:
            job.status = "failed"
            job.error = "Interrupted by a server restart"
            job.finished_at = utcnow()
        count = len(stale)
    if count:
        logger.warning("Reaped %d job(s) interrupted by a restart", count)
    return count


def _finish(job_id: int, status: str, result: dict | None = None, error: str | None = None) -> None:
    # A fresh session on purpose: if the handler's session died, we must still record the outcome.
    with session_scope() as db:
        job = db.get(Job, job_id)
        if not job:
            return
        job.status = status
        job.result = result
        job.error = error
        job.finished_at = utcnow()


def _execute_job(job_id: int) -> None:
    from wiki_api.jobs.handlers import HANDLERS

    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != "running":
            return
        kind = job.kind
        params = dict(job.params or {})

    handler = HANDLERS.get(kind)
    if handler is None:
        _finish(job_id, "failed", error=f"Unknown job kind: {kind}")
        return

    ctx = JobContext(job_id=job_id, deadline=time.monotonic() + JOB_TIMEOUT_SECONDS)
    try:
        with session_scope() as db:
            result = handler(db, params, ctx)
    except JobCancelled as exc:
        logger.info("Job %s (%s) cancelled: %s", job_id, kind, exc)
        _finish(job_id, "cancelled", error=str(exc))
    except Exception as exc:
        logger.exception("Job %s (%s) failed", job_id, kind)
        _finish(job_id, "failed", error=f"{type(exc).__name__}: {exc}"[:4000])
    else:
        _finish(job_id, "done", result=result)


class JobRunner:
    def __init__(self, concurrency: int = JOB_CONCURRENCY, poll_interval: float = POLL_INTERVAL):
        self.concurrency = max(1, concurrency)
        self.poll_interval = poll_interval
        # A limiter of our own rather than anyio's shared default pool, so background work
        # can never starve the threads that serve requests.
        self._limiter = anyio.CapacityLimiter(self.concurrency)
        self._tasks: list[asyncio.Task] = []
        self._wake = asyncio.Event()
        self._stopping = False
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        global _RUNNER
        _RUNNER = self
        self._loop = asyncio.get_running_loop()
        await asyncio.to_thread(reap_orphans)
        self._stopping = False
        self._tasks = [
            asyncio.create_task(self._loop_forever(i), name=f"job-worker-{i}")
            for i in range(self.concurrency)
        ]
        logger.info("Job runner started with %d worker(s)", self.concurrency)

    async def stop(self, grace: float = SHUTDOWN_GRACE_SECONDS) -> None:
        self._stopping = True
        self._wake.set()
        if not self._tasks:
            return
        # Wait for in-flight work rather than orphaning a live DB session. Railway sends
        # SIGKILL about 30s after SIGTERM, so the grace period stays under that.
        _done, pending = await asyncio.wait(self._tasks, timeout=grace)
        for task in pending:
            task.cancel()
        if pending:
            logger.warning(
                "%d job worker(s) still busy at shutdown; they will be reaped", len(pending)
            )
        self._tasks = []

    def notify(self) -> None:
        """Wake a worker immediately. Safe to call from a request thread."""
        loop = self._loop
        if loop and not loop.is_closed():
            loop.call_soon_threadsafe(self._wake.set)

    async def _loop_forever(self, worker_id: int) -> None:
        while not self._stopping:
            try:
                job_id = await asyncio.to_thread(self._claim_next)
            except Exception:
                logger.exception("Job worker %d failed to claim a job", worker_id)
                job_id = None

            if job_id is None:
                # Sleep until notified, or poll again after the interval.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=self.poll_interval)
                self._wake.clear()
                continue

            try:
                # The whole handler runs in one worker thread: handlers are ordinary sync
                # functions using a sync Session, which must stay on a single thread.
                # abandon_on_cancel=False so shutdown waits instead of orphaning it.
                await anyio.to_thread.run_sync(
                    _execute_job, job_id, limiter=self._limiter, abandon_on_cancel=False
                )
            except Exception:
                logger.exception("Job %s crashed the worker loop", job_id)
                _finish(job_id, "failed", error="Worker crashed")

    @staticmethod
    def _claim_next() -> int | None:
        """Atomically move the oldest queued job to running and return its id."""
        if engine.dialect.name == "postgresql":
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

        # SQLite: no SKIP LOCKED, so claim with a conditional UPDATE and check rowcount.
        with session_scope() as db:
            job_id = (
                db.query(Job.id)
                .filter(Job.status == "queued")
                .order_by(Job.created_at, Job.id)
                .limit(1)
                .scalar()
            )
            if job_id is None:
                return None
            updated = (
                db.query(Job)
                .filter(Job.id == job_id, Job.status == "queued")
                .update({"status": "running", "started_at": utcnow()})
            )
            return job_id if updated == 1 else None


_RUNNER: JobRunner | None = None


def get_runner() -> JobRunner | None:
    return _RUNNER
