import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { getGraph, type GraphData } from './api';
import { GraphView } from './GraphView';

export function GraphPage() {
  const [data, setData] = useState<GraphData | null>(null);
  const [params] = useSearchParams();
  const focus = params.get('focus') || undefined;
  const navigate = useNavigate();

  useEffect(() => {
    getGraph().then(setData).catch(console.error);
  }, []);

  return (
    <div className="container" style={{ maxWidth: '1200px' }}>
      <p style={{ marginBottom: '1rem' }}>
        <Link to="/">← Search</Link>
        {data && <span style={{ color: 'var(--muted)', marginLeft: '1rem' }}>{data.nodes.length} notes · {data.edges.length} links</span>}
      </p>
      {data ? (
        <GraphView data={data} focusSlug={focus} onSelect={(slug) => navigate(`/wiki/${slug}`)} />
      ) : (
        <p style={{ color: 'var(--muted)' }}>Loading graph…</p>
      )}
    </div>
  );
}
