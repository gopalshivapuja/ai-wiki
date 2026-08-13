import { useState } from 'react';
import { Link } from 'react-router-dom';
import { docPath, getRandomNote, getStats, listDocs } from './api';
import { useAsync, useSearch } from './hooks';
import { Snippet } from './SearchBar';

export function HomePage() {
  const [query, setQuery] = useState('');
  const { results, loading, error } = useSearch(query, 15);
  const { data: stats } = useAsync(() => getStats(), []);

  const idle = !query.trim();
  const empty = stats && stats.total_notes === 0 && stats.total_sources === 0;

  return (
    <div className={idle ? 'search-hero' : 'search-hero searching'}>
      <h1>What do you want to know?</h1>

      <div className="search-box">
        <span className="search-icon" aria-hidden="true">
          🔍
        </span>
        <input
          type="search"
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search your knowledge base"
          aria-label="Search your knowledge base"
        />
      </div>

      {idle && (
        <>
          {stats && !empty && (
            <p className="muted small">
              {stats.total_notes} notes · {stats.total_sources} sources ·{' '}
              {stats.total_wikilinks} links
            </p>
          )}
          {!empty && <StartHere />}
          {!empty && <RandomNote />}
          <div className="quick-links">
            <Link to="/browse">Browse all notes</Link>
            <Link to="/ask">Ask AI</Link>
            <Link to="/manage">Add a source</Link>
          </div>
          {empty && (
            <div className="empty-state">
              <p>Your wiki is empty.</p>
              <Link to="/manage">Add your first source →</Link>
            </div>
          )}
        </>
      )}

      {!idle && (
        <div className="results">
          {loading && <p className="muted small">Searching…</p>}
          {!loading && error && <p className="error">{error}</p>}
          {!loading && !error && results.length === 0 && (
            <div className="empty-state">
              <p>
                No results for <strong>“{query}”</strong>.
              </p>
              <p className="muted small">
                Try different words, or <Link to="/manage">add a source</Link> about it.
              </p>
            </div>
          )}
          {results.map((r) => (
            <Link className="result-item" key={r.slug} to={docPath(r.slug)}>
              <div className="result-meta">
                <span className="badge">{r.type}</span>
                {r.doc_class === 'source' && <span className="badge source-badge">source</span>}
              </div>
              <div className="result-title">{r.title}</div>
              {r.snippet && (
                <div className="result-snippet">
                  <Snippet text={r.snippet} />
                </div>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

/** The maps of content, as the way in.
 *
 * A search box only helps once you know what to search for. These are the curated entry
 * points, and they are the honest answer to "where do I start" in a wiki of 400 notes. */
function StartHere() {
  const { data } = useAsync(() => listDocs({ type: 'moc', doc_class: 'note' }), []);
  const mocs = data?.documents ?? [];
  if (mocs.length === 0) return null;

  return (
    <section className="start-here">
      <h2 className="section-label">Start here</h2>
      <div className="hub-grid">
        {mocs.map((m) => (
          <Link className="hub-card" key={m.slug} to={docPath(m.slug)}>
            <span className="hub-title">{m.title}</span>
            <span className="muted small">map of content</span>
          </Link>
        ))}
      </div>
    </section>
  );
}

/** One note at random.
 *
 * The oldest Zettelkasten habit: you find the link you would never have thought to search
 * for. Refreshes in place so it can be spun until something catches. */
function RandomNote() {
  const [nonce, setNonce] = useState(0);
  const { data, loading } = useAsync(() => getRandomNote(), [nonce]);
  if (!data && !loading) return null;

  return (
    <section className="random-note">
      <div className="row space-between">
        <h2 className="section-label">Something to read</h2>
        <button className="ghost small" onClick={() => setNonce((n) => n + 1)}>
          Another ↻
        </button>
      </div>
      {data && (
        <Link className="random-card" to={docPath(data.slug)}>
          <span className="badge">{data.type}</span>
          <span className="random-title">{data.title}</span>
          {data.preview && <span className="muted small">{data.preview}</span>}
        </Link>
      )}
    </section>
  );
}
