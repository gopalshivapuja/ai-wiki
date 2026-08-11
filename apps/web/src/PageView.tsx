import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ApiError, getPage, type PageData } from './api';
import { useAuth } from './auth';
import { Markdown } from './Markdown';

export function PageView() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const { isAuthed } = useAuth();
  const [page, setPage] = useState<PageData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sourceFallback, setSourceFallback] = useState<string | null>(null);

  useEffect(() => {
    if (!slug) return;
    setPage(null);
    setError(null);
    setSourceFallback(null);
    getPage(slug)
      .then(setPage)
      .catch((err: ApiError) => {
        // A raw source may exist under this slug even when no page does.
        if (err.status === 404) setSourceFallback(slug);
        setError(err.message || 'Could not load this page');
      });
  }, [slug]);

  if (error) {
    return (
      <div className="container">
        <div className="empty-state">
          <h2>No note here yet</h2>
          <p className="muted">
            Nothing is stored at <code>{slug}</code>.
          </p>
          <div className="row gap">
            {sourceFallback && (
              <Link className="button-link" to={`/source/${encodeURIComponent(sourceFallback)}`}>
                Look for a raw source with this name
              </Link>
            )}
            {isAuthed && (
              <button
                onClick={() =>
                  navigate(`/edit/new?title=${encodeURIComponent((slug || '').replace(/-/g, ' '))}`)
                }
              >
                Create this note
              </button>
            )}
            <Link to="/">Back to search</Link>
          </div>
        </div>
      </div>
    );
  }

  if (!page) return <div className="container muted">Loading…</div>;

  return (
    <div className="container page-layout">
      <article>
        <header className="page-header">
          <div className="row gap wrap">
            <span className="badge">{page.type}</span>
            {page.tags.map((t) => (
              <Link key={t} className="badge tag" to={`/browse?tag=${encodeURIComponent(t)}`}>
                #{t}
              </Link>
            ))}
          </div>
          {isAuthed && (
            <Link className="button-link" to={`/edit/${encodeURIComponent(page.slug)}`}>
              Edit
            </Link>
          )}
        </header>

        <Markdown content={page.body} links={page.links} />
      </article>

      <aside className="sidebar">
        <section>
          <h3>Linked from ({page.backlinks.length})</h3>
          {page.backlinks.length === 0 ? (
            <p className="muted small">
              No other note links here yet. Mention <code>[[{page.slug}]]</code> somewhere to
              connect it.
            </p>
          ) : (
            <ul>
              {page.backlinks.map((b) => (
                <li key={b.slug}>
                  <Link to={`/wiki/${encodeURIComponent(b.slug)}`}>{b.title}</Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        {page.links.length > 0 && (
          <section>
            <h3>Links to ({page.links.length})</h3>
            <ul>
              {page.links.map((l) => (
                <li key={l.target}>
                  {l.exists && l.slug ? (
                    <Link to={`/wiki/${encodeURIComponent(l.slug)}`}>{l.display}</Link>
                  ) : (
                    <span className="red-link" title="This note does not exist yet">
                      {l.display}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        {page.source_refs.length > 0 && (
          <section>
            <h3>From source</h3>
            <ul>
              {page.source_refs.map((s) => (
                <li key={s}>
                  <Link to={`/source/${encodeURIComponent(s)}`}>{s}</Link>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section>
          <h3>Details</h3>
          <p className="muted small">
            Updated {page.updated_at ? new Date(page.updated_at).toLocaleDateString() : 'unknown'}
            <br />
            <Link to={`/graph?focus=${encodeURIComponent(page.slug)}`}>Show in graph →</Link>
          </p>
        </section>
      </aside>
    </div>
  );
}
