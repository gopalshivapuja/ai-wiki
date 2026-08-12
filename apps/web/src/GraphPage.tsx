import { useCallback, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { docPath, getGraph, getOrphans } from './api';
import { GraphView, TYPE_COLORS } from './GraphView';
import { useAsync } from './hooks';

export function GraphPage() {
  const [params] = useSearchParams();
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const navigate = useNavigate();
  const focus = params.get('focus') || undefined;

  const { data, error, loading } = useAsync(() => getGraph(true), []);
  const orphans = useAsync(() => getOrphans(), []);
  const onSelect = useCallback((slug: string) => navigate(docPath(slug)), [navigate]);

  const types = useMemo(
    () => [...new Set((data?.nodes ?? []).map((n) => n.type))].sort(),
    [data],
  );

  const toggle = (t: string) =>
    setHidden((h) => {
      const next = new Set(h);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });

  if (error) {
    return (
      <div className="container">
        <div className="empty-state">
          <h2>The graph could not load</h2>
          <p className="error">{error}</p>
          <button onClick={() => window.location.reload()}>Try again</button>
        </div>
      </div>
    );
  }
  if (loading || !data) return <div className="container muted">Loading graph…</div>;

  if (data.nodes.length === 0) {
    return (
      <div className="container">
        <div className="empty-state">
          <h2>Nothing to draw yet</h2>
          <p className="muted">The graph fills in as you add notes and link them together.</p>
          <Link to="/manage">Add a source →</Link>
        </div>
      </div>
    );
  }

  const shown = data.nodes.filter((n) => !hidden.has(n.type)).length;
  const loose = orphans.data;

  return (
    <div className="container graph-page">
      <div className="graph-toolbar">
        <p className="muted small">
          {shown} of {data.nodes.length} documents · {data.edges.length} links · hover to isolate,
          click to open
        </p>
        <div className="spacer" style={{ flex: 1 }} />
        <div className="legend">
          {types.map((t) => (
            <button
              key={t}
              className={`legend-item${hidden.has(t) ? ' off' : ''}`}
              onClick={() => toggle(t)}
              title={hidden.has(t) ? `Show ${t}` : `Hide ${t}`}
            >
              <span
                className="legend-dot"
                style={{ background: TYPE_COLORS[t] || TYPE_COLORS.page }}
              />
              {t}
            </button>
          ))}
        </div>
      </div>

      <GraphView data={data} onSelect={onSelect} focusSlug={focus} hiddenTypes={hidden} />

      {loose && (loose.unlinked.length > 0 || loose.wanted.length > 0) && (
        <section className="panel">
          <h2>Loose ends</h2>
          <p className="muted small">
            A Zettelkasten is only as useful as its links. These notes are not yet connected.
          </p>
          <div className="row gap wrap" style={{ alignItems: 'flex-start', gap: '2rem' }}>
            {loose.unlinked.length > 0 && (
              <div>
                <h3>Nothing links here ({loose.unlinked.length})</h3>
                <ul className="page-list">
                  {loose.unlinked.slice(0, 8).map((o) => (
                    <li key={o.slug}>
                      <Link to={docPath(o.slug)}>{o.title}</Link>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {loose.wanted.length > 0 && (
              <div>
                <h3>Referenced but not written ({loose.wanted.length})</h3>
                <ul className="page-list">
                  {loose.wanted.slice(0, 8).map((w) => (
                    <li key={w.target}>
                      <Link to={`/edit/new?title=${encodeURIComponent(w.target)}`}>{w.target}</Link>
                      <span className="muted small"> — mentioned {w.mentions}×</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
