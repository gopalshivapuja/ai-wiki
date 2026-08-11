import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { deleteSource, getSource, summarizeSource, type SourceData } from './api';
import { useAuth } from './auth';
import { JobWatcher } from './JobsPanel';
import { Markdown } from './Markdown';

export function SourceView() {
  const { slug = '' } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const { isAuthed } = useAuth();
  const [source, setSource] = useState<SourceData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);

  const load = () => {
    setError(null);
    getSource(slug)
      .then(setSource)
      .catch((err) => setError(err.message));
  };

  useEffect(load, [slug]);

  if (error) {
    return (
      <div className="container">
        <div className="empty-state">
          <h2>Source not available</h2>
          <p className="muted">{error}</p>
          <Link to="/">Back to search</Link>
        </div>
      </div>
    );
  }
  if (!source) return <div className="container muted">Loading…</div>;

  const summarize = async () => {
    try {
      const job = await summarizeSource(slug);
      setJobId(job.id);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const remove = async () => {
    if (!window.confirm(`Delete the source “${source.title}”? Its notes are kept.`)) return;
    await deleteSource(slug);
    navigate('/manage');
  };

  return (
    <div className="container page-layout">
      <article>
        <header className="page-header">
          <div className="row gap wrap">
            <span className="badge">{source.type}</span>
            <span className="badge source-badge">raw source</span>
            {source.collection && (
              <Link className="badge tag" to={`/manage?collection=${encodeURIComponent(source.collection)}`}>
                {source.collection}
              </Link>
            )}
          </div>
        </header>
        <p className="muted small">
          Raw captured material. Notes stay separate so a re-summary can never overwrite what you
          wrote.
        </p>
        <Markdown content={source.body} />
      </article>

      <aside className="sidebar">
        <section>
          <h3>Source</h3>
          {source.url && (
            <p className="small">
              <a href={source.url} target="_blank" rel="noreferrer noopener">
                Open original ↗
              </a>
            </p>
          )}
          <p className="muted small">
            Captured {source.created_at ? new Date(source.created_at).toLocaleDateString() : '—'}
          </p>
        </section>

        <section>
          <h3>Literature note</h3>
          {source.summary_slug ? (
            <Link to={`/wiki/${encodeURIComponent(source.summary_slug)}`}>View the AI summary</Link>
          ) : (
            <p className="muted small">Not summarized yet.</p>
          )}
          {isAuthed && (
            <div className="row gap" style={{ marginTop: '0.75rem' }}>
              <button onClick={summarize} disabled={jobId !== null}>
                {source.summary_slug ? 'Re-summarize' : 'Summarize with AI'}
              </button>
            </div>
          )}
          {jobId !== null && (
            <JobWatcher
              jobId={jobId}
              onDone={() => {
                setJobId(null);
                load();
              }}
            />
          )}
        </section>

        {isAuthed && (
          <section>
            <h3>Danger zone</h3>
            <button className="ghost danger" onClick={remove}>
              Delete source
            </button>
          </section>
        )}
      </aside>
    </div>
  );
}
