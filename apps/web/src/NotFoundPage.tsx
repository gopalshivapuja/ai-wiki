import { Link, useLocation } from 'react-router-dom';

export function NotFoundPage() {
  const { pathname } = useLocation();
  return (
    <div className="container">
      <div className="empty-state">
        <h1>Nothing here</h1>
        <p className="muted">
          <code>{pathname}</code> is not a page in this wiki.
        </p>
        <div className="row gap">
          <Link to="/">Search</Link>
          <Link to="/browse">Browse all notes</Link>
        </div>
      </div>
    </div>
  );
}
