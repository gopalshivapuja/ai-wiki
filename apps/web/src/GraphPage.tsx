import { useCallback, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { docPath, getGraph } from './api';
import { GraphView, TYPE_COLORS } from './GraphView';
import { useAsync } from './hooks';

export function GraphPage() {
  const [params] = useSearchParams();
  const [includeSources, setIncludeSources] = useState(true);
  const navigate = useNavigate();
  const focus = params.get('focus') || undefined;

  const { data, error, loading } = useAsync(() => getGraph(includeSources), [includeSources]);
  const onSelect = useCallback((slug: string) => navigate(docPath(slug)), [navigate]);

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

  const types = [...new Set(data.nodes.map((n) => n.type))];

  return (
    <div className="container graph-page">
      <div className="row space-between wrap">
        <p className="muted small">
          {data.nodes.length} documents · {data.edges.length} links · click a node to open it
        </p>
        <div className="row gap wrap">
          <label className="checkbox">
            <input
              type="checkbox"
              checked={includeSources}
              onChange={(e) => setIncludeSources(e.target.checked)}
            />
            Show sources
          </label>
          <div className="row gap wrap legend">
            {types.map((t) => (
              <span key={t} className="legend-item">
                <span
                  className="legend-dot"
                  style={{ background: TYPE_COLORS[t] || TYPE_COLORS.page }}
                />
                {t}
              </span>
            ))}
          </div>
        </div>
      </div>
      <GraphView data={data} onSelect={onSelect} focusSlug={focus} />
    </div>
  );
}
