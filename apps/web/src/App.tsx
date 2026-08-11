import { lazy, Suspense } from 'react';
import { BrowserRouter, Link, NavLink, Route, Routes, useNavigate } from 'react-router-dom';
import { AskPage } from './AskPage';
import { AuthProvider, RequireAuth, useAuth } from './auth';
import { BrowsePage } from './BrowsePage';
import { EditorPage } from './EditorPage';
import { HomePage } from './HomePage';
import { LoginPage } from './LoginPage';
import { ManagePage } from './ManagePage';
import { NotFoundPage } from './NotFoundPage';
import { PageView } from './PageView';
import { SearchBar } from './SearchBar';
import { SourceView } from './SourceView';
import './index.css';

// vis-network is ~600KB and only the graph needs it — keep it out of the initial bundle.
const GraphPage = lazy(() => import('./GraphPage').then((m) => ({ default: m.GraphPage })));

function Nav() {
  const { isAuthed, logout } = useAuth();
  const navigate = useNavigate();

  return (
    <nav className="nav">
      <Link to="/" className="logo">
        <span aria-hidden="true">🧠</span> LLM Wiki
      </Link>
      <div className="nav-search">
        <SearchBar compact />
      </div>
      <NavLink to="/browse">Browse</NavLink>
      <NavLink to="/graph">Graph</NavLink>
      <NavLink to="/ask">Ask AI</NavLink>
      <NavLink to="/manage">Add source</NavLink>
      <div className="spacer" />
      {isAuthed ? (
        <button
          className="ghost"
          onClick={() => {
            logout();
            navigate('/');
          }}
        >
          Log out
        </button>
      ) : (
        <NavLink to="/login">Log in</NavLink>
      )}
    </nav>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Nav />
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/browse" element={<BrowsePage />} />
          <Route path="/wiki/:slug" element={<PageView />} />
          <Route path="/source/:slug" element={<SourceView />} />
          <Route
            path="/graph"
            element={
              <Suspense fallback={<div className="container muted">Loading graph…</div>}>
                <GraphPage />
              </Suspense>
            }
          />
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/edit/:slug"
            element={
              <RequireAuth>
                <EditorPage />
              </RequireAuth>
            }
          />
          <Route
            path="/ask"
            element={
              <RequireAuth>
                <AskPage />
              </RequireAuth>
            }
          />
          <Route
            path="/manage"
            element={
              <RequireAuth>
                <ManagePage />
              </RequireAuth>
            }
          />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
