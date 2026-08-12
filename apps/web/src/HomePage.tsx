import { useState } from 'react';
import { Link } from 'react-router-dom';
import { docPath, getStats } from './api';
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
          <div className="quick-links">
            <Link to="/browse">Browse all notes</Link>
            <Link to="/graph">Knowledge graph</Link>
            <Link to="/ask">Ask AI</Link>
            <Link to="/manage">Add a source</Link>
          </div>
          {stats && !empty && (
            <p className="muted small">
              {stats.total_notes} notes · {stats.total_sources} sources ·{' '}
              {stats.total_wikilinks} links
            </p>
          )}
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
