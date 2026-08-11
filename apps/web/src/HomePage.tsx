import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { searchWiki, type SearchResult } from './api';

export function HomePage() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    setLoading(true);
    try {
      const data = await searchWiki(q);
      setResults(data.results);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => doSearch(query), 300);
    return () => clearTimeout(t);
  }, [query, doSearch]);

  return (
    <div className="search-hero">
      <h1>🧠 LLM Wiki</h1>
      <div className="search-box">
        <input
          autoFocus
          type="search"
          placeholder="Search your knowledge base…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && results[0]) navigate(`/wiki/${results[0].slug}`);
          }}
        />
      </div>

      {loading && <p style={{ color: 'var(--muted)' }}>Searching…</p>}

      {results.length > 0 && (
        <div className="results">
          {results.map((r) => (
            <div key={r.slug} className="result-item" onClick={() => navigate(`/wiki/${r.slug}`)}>
              <div className="result-meta">
                <span className="badge">{r.type}</span>
                score {r.score.toFixed(2)}
              </div>
              <div className="result-title">{r.title}</div>
              {r.snippet && <div className="result-snippet">{r.snippet}</div>}
            </div>
          ))}
        </div>
      )}

        {!query && (
        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', justifyContent: 'center' }}>
          <Link to="/graph">Explore Graph →</Link>
          <Link to="/ask">Ask AI →</Link>
          <Link to="/manage">Add Sources →</Link>
        </div>
      )}
    </div>
  );
}
