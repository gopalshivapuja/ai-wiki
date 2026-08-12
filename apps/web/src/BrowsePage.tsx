import { useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { docPath, getOrphans, getStats, getTags, listDocs, type DocSummary } from './api';
import { useAsync } from './hooks';

export function BrowsePage() {
  const [params, setParams] = useSearchParams();
  const tag = params.get('tag');
  const type = params.get('type');
  const view = params.get('view');

  const docs = useAsync(
    () => listDocs({ tag: tag || undefined, type: type || undefined, doc_class: 'note' }),
    [tag, type],
  );
  const tags = useAsync(() => getTags(), []);
  const stats = useAsync(() => getStats(), []);
  const orphanData = useAsync(() => getOrphans(), []);

  const byType = useMemo(() => {
    const groups = new Map<string, DocSummary[]>();
    for (const d of docs.data?.documents ?? []) {
      if (!groups.has(d.type)) groups.set(d.type, []);
      groups.get(d.type)!.push(d);
    }
    return [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [docs.data]);

  const setFilter = (key: 'tag' | 'type' | 'view', value: string | null) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next);
  };

  const orphans = orphanData.data;

  return (
    <div className="container">
      <div className="row space-between wrap">
        <h1>Browse</h1>
        <div className="row gap">
          <Link className="button-link" to="/browse?view=loose">
            Loose ends
          </Link>
          <Link className="button-link" to="/edit/new">
            New note
          </Link>
        </div>
      </div>

      {stats.data && (
        <p className="muted small">
          {stats.data.total_notes} notes · {stats.data.zettels} zettels · {stats.data.concepts}{' '}
          concepts · {stats.data.entities} entities · {stats.data.mocs} maps of content ·{' '}
          {stats.data.total_sources} sources
        </p>
      )}

      {view === 'loose' && orphans && (
        <section className="panel">
          <div className="row space-between">
            <h2>Loose ends</h2>
            <button className="ghost small" onClick={() => setFilter('view', null)}>
              Back to all
            </button>
          </div>
          <p className="muted small">
            A Zettelkasten is only as good as its links. These are the notes nothing points at, and
            the notes you have referenced but never written.
          </p>

          <h3>Nothing links here ({orphans.unlinked.length})</h3>
          {orphans.unlinked.length === 0 ? (
            <p className="muted small">Every note is linked from somewhere. Nice.</p>
          ) : (
            <ul className="page-list">
              {orphans.unlinked.map((o) => (
                <li key={o.slug}>
                  <Link to={docPath(o.slug)}>{o.title}</Link>
                </li>
              ))}
            </ul>
          )}

          <h3>Referenced but not written ({orphans.wanted.length})</h3>
          {orphans.wanted.length === 0 ? (
            <p className="muted small">No dangling links.</p>
          ) : (
            <ul className="page-list">
              {orphans.wanted.map((w) => (
                <li key={w.target}>
                  <Link to={`/edit/new?title=${encodeURIComponent(w.target)}`}>{w.target}</Link>
                  <span className="muted small"> — mentioned {w.mentions}×</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {view !== 'loose' && (
        <>
          {(tag || type) && (
            <p className="row gap wrap">
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

          {(tags.data?.tags.length ?? 0) > 0 && (
            <section className="panel">
              <h2>Tags</h2>
              <div className="row gap wrap">
                {tags.data?.tags.slice(0, 40).map((t) => (
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

          {docs.error && <p className="error">{docs.error}</p>}
          {docs.loading && <p className="muted">Loading…</p>}
          {!docs.loading && byType.length === 0 && (
            <div className="empty-state">
              <p>No notes match this filter.</p>
              <Link to="/edit/new">Write one →</Link>
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
                {rows.map((d) => (
                  <li key={d.slug}>
                    <Link to={docPath(d.slug)}>{d.title}</Link>
                    {d.tags.slice(0, 4).map((t) => (
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
        </>
      )}
    </div>
  );
}
