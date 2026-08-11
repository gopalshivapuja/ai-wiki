import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { getPage, type PageData } from './api';
import { Markdown } from './Markdown';

export function PageView() {
  const { slug } = useParams<{ slug: string }>();
  const [page, setPage] = useState<PageData | null>(null);
  const [error, setError] = useState('');
  const navigate = useNavigate();

  useEffect(() => {
    if (!slug) return;
    getPage(slug)
      .then(setPage)
      .catch((e) => setError(e.message));
  }, [slug]);

  if (error) return <div className="container"><p className="error">{error}</p></div>;
  if (!page) return <div className="container"><p style={{ color: 'var(--muted)' }}>Loading…</p></div>;

  const tags = page.tags || [];
  const fmType = page.type || 'page';

  return (
    <div className="container">
      <p style={{ marginBottom: '1rem' }}>
        <Link to="/">← Search</Link>
        {' · '}
        <Link to={`/graph?focus=${page.slug}`}>Graph</Link>
      </p>

      <div className="page-layout">
        <article>
          <p style={{ marginBottom: '0.5rem' }}>
            <span className="badge">{fmType}</span>
            {tags.map((t) => (
              <span key={t} className="badge">{t}</span>
            ))}
          </p>
          <Markdown content={page.body} />
        </article>

        <aside className="sidebar">
          <h3>Backlinks ({page.backlinks.length})</h3>
          {page.backlinks.length === 0 ? (
            <p style={{ fontSize: '0.85rem', color: 'var(--muted)' }}>No backlinks yet</p>
          ) : (
            <ul>
              {page.backlinks.map((b) => (
                <li key={b.slug}>
                  <a
                    href={`/wiki/${b.slug}`}
                    onClick={(e) => { e.preventDefault(); navigate(`/wiki/${b.slug}`); }}
                  >
                    {b.title}
                  </a>
                </li>
              ))}
            </ul>
          )}
          <h3 style={{ marginTop: '1.5rem' }}>Type</h3>
          <p style={{ fontSize: '0.8rem', color: 'var(--muted)' }}>{fmType}</p>
        </aside>
      </div>
    </div>
  );
}
