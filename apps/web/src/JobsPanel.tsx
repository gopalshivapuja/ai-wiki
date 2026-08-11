import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { cancelJob, getJob, isJobActive, listJobs, retryJob, type Job } from './api';

const POLL_MS = 2000;

const STATUS_LABEL: Record<Job['status'], string> = {
  queued: 'Queued',
  running: 'Running',
  cancelling: 'Cancelling',
  done: 'Done',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

function describe(job: Job): string {
  const p = job.params as Record<string, string>;
  return p.url || p.id_or_url || p.title || p.source_slug || p.filename || job.kind;
}

function resultLinks(job: Job) {
  const result = job.result as Record<string, unknown> | null;
  if (!result) return null;
  const slug = result.slug as string | undefined;
  const summaries = (result.summaries as { slug?: string }[] | undefined) || [];
  const note = summaries.find((s) => s.slug)?.slug;
  return (
    <span className="row gap small">
      {slug && <Link to={`/source/${encodeURIComponent(slug)}`}>View source</Link>}
      {note && note !== slug && <Link to={`/wiki/${encodeURIComponent(note)}`}>View note</Link>}
      {typeof result.pages === 'number' && <span className="muted">{result.pages} pages</span>}
    </span>
  );
}

/** Compact inline watcher for a single job. */
export function JobWatcher({ jobId, onDone }: { jobId: number; onDone?: (job: Job) => void }) {
  const [job, setJob] = useState<Job | null>(null);

  useEffect(() => {
    let stop = false;
    const tick = () => {
      getJob(jobId)
        .then((j) => {
          if (stop) return;
          setJob(j);
          if (!isJobActive(j)) onDone?.(j);
          else setTimeout(tick, POLL_MS);
        })
        .catch(() => {});
    };
    tick();
    return () => {
      stop = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  if (!job) return <p className="muted small">Starting…</p>;
  if (job.status === 'failed') return <p className="error small">{job.error}</p>;
  if (job.status === 'done') return <p className="success small">Done. {resultLinks(job)}</p>;
  return (
    <p className="muted small">
      {STATUS_LABEL[job.status]}… {job.progress.message}
    </p>
  );
}

export function JobsPanel({ onSettled }: { onSettled?: () => void }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = () =>
    listJobs(15)
      .then((d) => {
        setJobs(d.jobs);
        setError(null);
        return d.jobs;
      })
      .catch((err) => {
        setError(err.message);
        return [] as Job[];
      });

  useEffect(() => {
    let timer: number | undefined;
    let cancelled = false;
    let wasActive = false;

    const loop = async () => {
      const current = await refresh();
      if (cancelled) return;
      const active = current.some(isJobActive);
      if (wasActive && !active) onSettled?.();
      wasActive = active;
      // Only poll while something is actually running — no endless background traffic.
      if (active) timer = window.setTimeout(loop, POLL_MS);
    };
    loop();

    const onFocus = () => loop();
    window.addEventListener('focus', onFocus);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      window.removeEventListener('focus', onFocus);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const act = async (fn: (id: number) => Promise<Job>, id: number) => {
    try {
      await fn(id);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <section className="panel">
      <div className="row space-between">
        <h2>Activity</h2>
        <button className="ghost small" onClick={() => void refresh()}>
          Refresh
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      {jobs.length === 0 && !error && (
        <p className="muted small">Nothing yet. Anything you add above shows its progress here.</p>
      )}

      <ul className="job-list">
        {jobs.map((job) => (
          <li key={job.id} className={`job job-${job.status}`}>
            <div className="row space-between">
              <div>
                <span className="badge">{job.kind}</span>
                <strong>{describe(job)}</strong>
              </div>
              <span className={`status status-${job.status}`}>{STATUS_LABEL[job.status]}</span>
            </div>

            {isJobActive(job) && (
              <div className="job-progress">
                <progress
                  value={job.progress.current}
                  max={job.progress.total || undefined}
                  aria-label="Job progress"
                />
                <span className="muted small">
                  {job.progress.message ||
                    (job.progress.total
                      ? `${job.progress.current}/${job.progress.total}`
                      : 'Working…')}
                </span>
                <button className="ghost small" onClick={() => act(cancelJob, job.id)}>
                  Cancel
                </button>
              </div>
            )}

            {job.status === 'done' && resultLinks(job)}
            {(job.status === 'failed' || job.status === 'cancelled') && (
              <div className="row gap">
                <span className="error small">{job.error}</span>
                {job.kind !== 'pdf' && (
                  <button className="ghost small" onClick={() => act(retryJob, job.id)}>
                    Retry
                  </button>
                )}
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
