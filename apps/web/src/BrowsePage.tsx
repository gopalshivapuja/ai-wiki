import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { getStats, getTags, listPages } from './api';
import { useAuth } from './auth';

interface PageRow {
  slug: string;
  title: string;
  type: string;
  tags: string[];
}

export function BrowsePage() {
  const [params, setParams] = useSearchParams();
  const tag = params.get('tag');
  const type = params.get('type');
  const { isAuthed } = useAuth();

  const [pages, setPages] = useState<PageRow[]>([]);
  const [tags, setTags] = useState<{ tag: string; count: number }[]>([]);
  const [stats, setStats] = useState<Record<string, number> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    listPages({ tag: tag || undefined, type: type || undefined })
      .then((d) => {
        setPages(d.pages);
        setError(null);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [tag, type]);

  useEffect(() => {
    getTags().then((d) => setTags(d.tags)).catch(() => setTags([]));
    getStats().then(setStats).catch(() => setStats(null));
  }, []);

  const byType = useMemo(() => {
    const groups = new Map<string, PageRow[]>();
    for (const p of pages) {
      if (!groups.has(p.type)) groups.set(p.type, []);
      groups.get(p.type)!.push(p);
    }
    return [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [pages]);

  const setFilter = (key: 'tag' | 'type', value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  };

  return (
    <div className="container">
      <div className="row space-between wrap">
        <h1>Browse</h1>
        {isAuthed && (
          <Link className="button-link" to="/edit/new">
            New note
          </Link>
        )}
      </div>

      {stats && (
        <p className="muted small">
          {stats.total_pages} notes · {stats.zettels} zettels · {stats.concepts} concepts ·{' '}
          {stats.entities} entities · {stats.mocs} maps of content · {stats.total_sources} sources
        </p>
      )}

      {(tag || type) && (
        <p className="row gap">
          <span className="muted small">Filtered by</span>
          {type && (
            <button className="badge as-button" onClick={() => setFilter('type', null)}>
              type: {type} ✕
            </button>
          )}
          {tag && (
            <button className="badge as-button" onClick={() => setFilter('tag', null)}>
              #{tag} ✕
            </button>
          )}
        </p>
      )}

      {tags.length > 0 && (
        <section className="panel">
          <h2>Tags</h2>
          <div className="row gap wrap">
            {tags.slice(0, 40).map((t) => (
              <button
                key={t.tag}
                className={`badge tag as-button${tag === t.tag ? ' active' : ''}`}
                onClick={() => setFilter('tag', tag === t.tag ? null : t.tag)}
              >
                #{t.tag} <span className="muted">{t.count}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {error && <p className="error">{error}</p>}
      {loading && <p className="muted">Loading…</p>}

      {!loading && pages.length === 0 && (
        <div className="empty-state">
          <p>No notes match this filter.</p>
          {isAuthed && <Link to="/edit/new">Create one →</Link>}
        </div>
      )}

      {byType.map(([groupType, rows]) => (
        <section className="panel" key={groupType}>
          <div className="row space-between">
            <h2>
              {groupType} <span className="muted small">({rows.length})</span>
            </h2>
            <button className="ghost small" onClick={() => setFilter('type', groupType)}>
              Only these
            </button>
          </div>
          <ul className="page-list">
            {rows.map((p) => (
              <li key={p.slug}>
                <Link to={`/wiki/${encodeURIComponent(p.slug)}`}>{p.title}</Link>
                {p.tags.slice(0, 4).map((t) => (
                  <button
                    key={t}
                    className="badge tag as-button"
                    onClick={() => setFilter('tag', t)}
                  >
                    #{t}
                  </button>
                ))}
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
