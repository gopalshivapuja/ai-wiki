import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { hitPath, searchWiki, type SearchResult } from './api';

interface Props {
  compact?: boolean;
  autoFocus?: boolean;
  onResults?: (results: SearchResult[], query: string, loading: boolean, error: string | null) => void;
}

/** Highlights the «…» markers Postgres ts_headline emits, without injecting HTML. */
export function Snippet({ text }: { text: string }) {
  const parts = useMemo(() => text.split(/(«[^»]*»)/g), [text]);
  return (
    <span>
      {parts.map((part, i) =>
        part.startsWith('«') && part.endsWith('»') ? (
          <mark key={i}>{part.slice(1, -1)}</mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </span>
  );
}

export function SearchBar({ compact = false, autoFocus = false, onResults }: Props) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const navigate = useNavigate();
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setResults([]);
      setError(null);
      setLoading(false);
      onResults?.([], '', false, null);
      return;
    }
    setLoading(true);
    onResults?.(results, q, true, null);
    const timer = setTimeout(() => {
      searchWiki(q, compact ? 8 : 15)
        .then((data) => {
          setResults(data.results);
          setError(null);
          setActive(-1);
          onResults?.(data.results, q, false, null);
        })
        .catch((err) => {
          // Surfaced rather than swallowed: an outage used to look identical to "no results".
          const message = err?.message || 'Search failed';
          setResults([]);
          setError(message);
          onResults?.([], q, false, message);
        })
        .finally(() => setLoading(false));
    }, 250);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, compact]);

  useEffect(() => {
    if (!compact) return;
    const onClickAway = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onClickAway);
    return () => document.removeEventListener('mousedown', onClickAway);
  }, [compact]);

  const go = (r: SearchResult) => {
    setOpen(false);
    setQuery('');
    navigate(hitPath(r));
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((i) => Math.min(i + 1, results.length - 1));
      setOpen(true);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, -1));
    } else if (e.key === 'Enter') {
      const pick = results[active >= 0 ? active : 0];
      if (pick) go(pick);
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  };

  return (
    <div className={compact ? 'search-box compact' : 'search-box'} ref={boxRef}>
      <span className="search-icon" aria-hidden="true">
        🔍
      </span>
      <input
        type="search"
        value={query}
        autoFocus={autoFocus}
        placeholder={compact ? 'Search…' : 'Search your knowledge base'}
        aria-label="Search the wiki"
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {compact && open && query.trim() && (
        <div className="search-dropdown">
          {loading && <div className="dropdown-empty">Searching…</div>}
          {!loading && error && <div className="dropdown-empty error">{error}</div>}
          {!loading && !error && results.length === 0 && (
            <div className="dropdown-empty">No matches for “{query.trim()}”</div>
          )}
          {results.map((r, i) => (
            <button
              key={`${r.kind}:${r.slug}`}
              className={`dropdown-item${i === active ? ' active' : ''}`}
              onMouseEnter={() => setActive(i)}
              onClick={() => go(r)}
            >
              <span className="badge">{r.kind === 'source' ? r.type : r.type}</span>
              {r.title}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
