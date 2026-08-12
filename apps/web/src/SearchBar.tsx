import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { docPath, type SearchResult } from './api';
import { useSearch } from './hooks';

/** Renders the «…» markers Postgres ts_headline emits, without injecting HTML. */
export function Snippet({ text }: { text: string }) {
  const parts = useMemo(() => text.split(/(«[^»]*»)/g), [text]);
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith('«') && part.endsWith('»') ? (
          <mark key={i}>{part.slice(1, -1)}</mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

/** Compact search for the nav: owns its own query and shows a dropdown. */
export function NavSearch() {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const { results, loading, error } = useSearch(query, 8);
  const navigate = useNavigate();
  const boxRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onClickAway = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onClickAway);
    return () => document.removeEventListener('mousedown', onClickAway);
  }, []);

  useEffect(() => setActive(-1), [results]);

  const go = (r: SearchResult) => {
    setOpen(false);
    setQuery('');
    navigate(docPath(r.slug));
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
    <div className="search-box compact" ref={boxRef}>
      <span className="search-icon" aria-hidden="true">
        🔍
      </span>
      <input
        type="search"
        value={query}
        placeholder="Search…"
        aria-label="Search the wiki"
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
      />
      {open && query.trim() && (
        <div className="search-dropdown">
          {loading && <div className="dropdown-empty">Searching…</div>}
          {!loading && error && <div className="dropdown-empty error">{error}</div>}
          {!loading && !error && results.length === 0 && (
            <div className="dropdown-empty">No matches for “{query.trim()}”</div>
          )}
          {results.map((r, i) => (
            <button
              key={r.slug}
              className={`dropdown-item${i === active ? ' active' : ''}`}
              onMouseEnter={() => setActive(i)}
              onClick={() => go(r)}
            >
              <span className="badge">{r.type}</span>
              {r.title}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
