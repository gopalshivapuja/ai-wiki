import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getStats, hitPath, type SearchResult } from './api';
import { SearchBar, Snippet } from './SearchBar';

export function HomePage() {
  const [results, setResults] = useState<SearchResult[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<Record<string, number> | null>(null);

  useEffect(() => {
    getStats().then(setStats).catch(() => setStats(null));
  }, []);

  const idle = !query.trim();
  const empty = stats && stats.total_pages === 0 && stats.total_sources === 0;

  return (
    <div className={idle ? 'search-hero' : 'search-hero searching'}>
      <h1>What do you want to know?</h1>

      <SearchBar
        autoFocus
        onResults={(r, q, isLoading, err) => {
          setResults(r);
          setQuery(q);
          setLoading(isLoading);
          setError(err);
        }}
      />

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
              {stats.total_pages} notes · {stats.total_sources} sources · {stats.total_wikilinks} links
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
            <Link className="result-item" key={`${r.kind}:${r.slug}`} to={hitPath(r)}>
              <div className="result-meta">
                <span className="badge">{r.type}</span>
                {r.kind === 'source' && <span className="badge source-badge">raw source</span>}
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
