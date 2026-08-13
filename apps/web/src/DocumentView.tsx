import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  deleteDoc,
  docPath,
  getDoc,
  getRevisions,
  restoreRevision,
  summarizeSource,
  type DocDetail,
} from './api';
import { Connections } from './Connections';
import { useAsync } from './hooks';
import { JobWatcher } from './JobsPanel';
import { Markdown } from './Markdown';
import { Toc } from './Toc';

export function DocumentView() {
  const { slug = '' } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const { data: doc, error, loading, reload } = useAsync<DocDetail>(() => getDoc(slug), [slug]);
  const [jobId, setJobId] = useState<number | null>(null);
  const [showRevisions, setShowRevisions] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  if (loading) return <div className="container muted">Loading…</div>;

  if (error || !doc) {
    return (
      <div className="container">
        <div className="empty-state">
          <h2>Nothing here</h2>
          {/* Reports the real error rather than always claiming the note is missing. */}
          <p className="muted">{error}</p>
          <div className="row gap">
            <Link className="button-link" to={`/edit/new?title=${encodeURIComponent(slug.replace(/-/g, ' '))}`}>
              Write this note
            </Link>
            <Link to="/">Back to search</Link>
          </div>
        </div>
      </div>
    );
  }

  const isSource = doc.doc_class === 'source';

  const remove = async () => {
    if (!window.confirm(`Delete “${doc.title}” permanently?`)) return;
    try {
      await deleteDoc(slug);
      navigate('/browse');
    } catch (err) {
      setActionError((err as Error).message);
    }
  };

  return (
    <div className="container page-layout">
      <article>
        <header className="page-header">
          <div className="row gap wrap">
            <span className="badge">{doc.type}</span>
            {isSource && <span className="badge source-badge">captured source</span>}
            {doc.tags.map((t) => (
              <Link key={t} className="badge tag" to={`/browse?tag=${encodeURIComponent(t)}`}>
                #{t}
              </Link>
            ))}
          </div>
          <div className="row gap">
            {!isSource && (
              <Link className="button-link" to={`/edit/${encodeURIComponent(doc.slug)}`}>
                Edit
              </Link>
            )}
            {isSource && !doc.summary && (
              <button onClick={async () => setJobId((await summarizeSource(slug)).id)} disabled={jobId !== null}>
                Summarize with AI
              </button>
            )}
          </div>
        </header>

        {isSource && (
          <p className="muted small">
            Captured material, kept exactly as it arrived. Notes about it live separately, so a
            re-summary can never overwrite what you wrote.
          </p>
        )}
        {actionError && <p className="error">{actionError}</p>}
        {jobId !== null && (
          <JobWatcher
            jobId={jobId}
            onDone={() => {
              setJobId(null);
              reload();
            }}
          />
        )}

        <Markdown content={doc.body} links={doc.links} selfSlug={doc.slug} />

        <Connections slug={doc.slug} />
      </article>

      <aside className="sidebar">
        <Toc markdown={doc.body} />
        {doc.summary && (
          <section>
            <h3>Literature note</h3>
            <Link to={docPath(doc.summary.slug)}>{doc.summary.title}</Link>
          </section>
        )}
        {doc.derived_from && (
          <section>
            <h3>Summarised from</h3>
            <Link to={docPath(doc.derived_from.slug)}>{doc.derived_from.title}</Link>
          </section>
        )}

        <section>
          <h3>Linked from ({doc.backlinks.length})</h3>
          {doc.backlinks.length === 0 ? (
            <p className="muted small">
              Nothing links here yet. Mention <code>[[{doc.slug}]]</code> in another note to
              connect it.
            </p>
          ) : (
            <ul>
              {doc.backlinks.map((b) => (
                <li key={b.slug}>
                  <Link to={docPath(b.slug)}>{b.title}</Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        {doc.links.length > 0 && (
          <section>
            <h3>Links to ({doc.links.length})</h3>
            <ul>
              {doc.links.map((l) => (
                <li key={l.target}>
                  {l.exists && l.slug ? (
                    <Link to={docPath(l.slug)}>{l.display}</Link>
                  ) : (
                    <Link className="red-link" to={`/edit/new?title=${encodeURIComponent(l.target)}`}>
                      {l.display}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        <section>
          <h3>Details</h3>
          <p className="muted small">
            {doc.url && (
              <>
                <a href={doc.url} target="_blank" rel="noreferrer noopener">
                  Open original ↗
                </a>
                <br />
              </>
            )}
            Updated {doc.updated_at ? new Date(doc.updated_at).toLocaleDateString() : 'unknown'}
          </p>
          {doc.revision_count > 0 && (
            <button className="ghost small" onClick={() => setShowRevisions((v) => !v)}>
              {showRevisions ? 'Hide' : `History (${doc.revision_count})`}
            </button>
          )}
          {showRevisions && <RevisionList slug={slug} onRestore={reload} />}
        </section>

        <section>
          <h3>Danger zone</h3>
          <button className="ghost danger small" onClick={remove}>
            Delete
          </button>
        </section>
      </aside>
    </div>
  );
}

function RevisionList({ slug, onRestore }: { slug: string; onRestore: () => void }) {
  const { data, loading, reload } = useAsync(() => getRevisions(slug), [slug]);
  if (loading) return <p className="muted small">Loading history…</p>;
  if (!data?.revisions.length) return <p className="muted small">No earlier versions.</p>;

  return (
    <ul className="revision-list">
      {data.revisions.map((r) => (
        <li key={r.id}>
          <span className="muted small">
            {r.created_at ? new Date(r.created_at).toLocaleString() : ''}
          </span>
          <button
            className="ghost small"
            onClick={async () => {
              if (!window.confirm('Restore this version? The current text is saved to history.'))
                return;
              await restoreRevision(slug, r.id);
              reload();
              onRestore();
            }}
          >
            Restore
          </button>
        </li>
      ))}
    </ul>
  );
}
