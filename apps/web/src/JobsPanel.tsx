import { Link } from 'react-router-dom';
import {
  cancelJob,
  docPath,
  getJob,
  isJobActive,
  listJobs,
  retryJob,
  type Job,
} from './api';
import { usePoll } from './hooks';

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

function ResultLinks({ job }: { job: Job }) {
  const result = job.result as Record<string, unknown> | null;
  if (!result) return null;
  const slug = result.slug as string | undefined;
  const summaries = (result.summaries as { slug?: string; error?: string }[] | undefined) || [];
  const note = summaries.find((s) => s.slug && !s.error)?.slug;
  const failedSummary = summaries.find((s) => s.error);

  return (
    <span className="row gap small wrap">
      {slug && <Link to={docPath(slug)}>View source</Link>}
      {note && note !== slug && <Link to={docPath(note)}>View note</Link>}
      {typeof result.pages === 'number' && <span className="muted">{result.pages} pages</span>}
      {typeof result.imported === 'number' && (
        <span className="muted">{result.imported} documents imported</span>
      )}
      {failedSummary && <span className="muted">summary failed: {failedSummary.error}</span>}
    </span>
  );
}

/** Inline watcher for one job. */
export function JobWatcher({ jobId, onDone }: { jobId: number; onDone?: (job: Job) => void }) {
  const { data: job } = usePoll(
    () => getJob(jobId),
    (j) => {
      const active = isJobActive(j);
      if (!active) onDone?.(j);
      return active;
    },
    jobId,
  );

  if (!job) return <p className="muted small">Starting…</p>;
  if (job.status === 'failed') return <p className="error small">{job.error}</p>;
  if (job.status === 'done')
    return (
      <p className="success small">
        Done. <ResultLinks job={job} />
      </p>
    );
  return (
    <p className="muted small">
      {STATUS_LABEL[job.status]}… {job.progress.message}
    </p>
  );
}

export function JobsPanel({ reloadKey = 0 }: { reloadKey?: number }) {
  const { data, error, refresh } = usePoll(
    () => listJobs(15),
    (d) => d.jobs.some(isJobActive),
    reloadKey,
  );
  const jobs = data?.jobs ?? [];

  const act = async (fn: (id: number) => Promise<Job>, id: number) => {
    await fn(id);
    refresh();
  };

  return (
    <section className="panel">
      <div className="row space-between">
        <h2>Activity</h2>
        <button className="ghost small" onClick={refresh}>
          Refresh
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      {jobs.length === 0 && !error && (
        <p className="muted small">Nothing yet. Anything you add above shows its progress here.</p>
      )}

      <ul className="job-list">
        {jobs.map((job) => (
          <li key={job.id} className="job">
            <div className="row space-between wrap">
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

            {job.status === 'done' && <ResultLinks job={job} />}
            {(job.status === 'failed' || job.status === 'cancelled') && (
              <div className="row gap wrap">
                <span className="error small">{job.error}</span>
                <button className="ghost small" onClick={() => act(retryJob, job.id)}>
                  Retry
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
