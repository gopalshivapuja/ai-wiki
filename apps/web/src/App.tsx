import { lazy, Suspense } from 'react';
import { BrowserRouter, Link, NavLink, Route, Routes, useNavigate } from 'react-router-dom';
import { AuthProvider, RequireAuth, useAuth } from './auth';
import { BrowsePage } from './BrowsePage';
import { HomePage } from './HomePage';
import { LoginPage } from './LoginPage';
import { ManagePage } from './ManagePage';
import { NotFoundPage } from './NotFoundPage';
import { ScrollToTop } from './ScrollToTop';
import { ThemeProvider, ThemeToggle } from './theme';
import { NavSearch } from './SearchBar';
import './index.css';

// The markdown + KaTeX pipeline (~450KB) is not needed to search, and vis-network (~600KB)
// now loads only inside a document's Connections panel, and only once it is opened.
const DocumentView = lazy(() => import('./DocumentView').then((m) => ({ default: m.DocumentView })));
const EditorPage = lazy(() => import('./EditorPage').then((m) => ({ default: m.EditorPage })));
const AskPage = lazy(() => import('./AskPage').then((m) => ({ default: m.AskPage })));

function Nav() {
  const { isAuthed, logout } = useAuth();
  const navigate = useNavigate();

  if (!isAuthed) return null;

  return (
    <nav className="nav">
      <Link to="/" className="logo">
        ai<span className="logo-dot">·</span>wiki
      </Link>
      <div className="nav-search">
        <NavSearch />
      </div>
      <NavLink to="/browse">Browse</NavLink>
      <NavLink to="/ask">Ask AI</NavLink>
      <NavLink to="/manage">Add source</NavLink>
      <div className="spacer" />
      <ThemeToggle />
      <button
        className="ghost"
        onClick={() => {
          logout();
          navigate('/login');
        }}
      >
        Log out
      </button>
    </nav>
  );
}

/** Everything except /login is private — literature notes reproduce the substance of the
 *  sources they summarise, so a public/private split by document class protected nothing. */
const guarded = (element: React.ReactElement) => <RequireAuth>{element}</RequireAuth>;

export default function App() {
  return (
    <BrowserRouter>
      <ThemeProvider>
      <AuthProvider>
        <ScrollToTop />
        <Nav />
        <Suspense fallback={<div className="container muted">Loading…</div>}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={guarded(<HomePage />)} />
            <Route path="/browse" element={guarded(<BrowsePage />)} />
            <Route path="/doc/:slug" element={guarded(<DocumentView />)} />
            <Route path="/edit/:slug" element={guarded(<EditorPage />)} />
            <Route path="/ask" element={guarded(<AskPage />)} />
            <Route path="/manage" element={guarded(<ManagePage />)} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </Suspense>
      </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  );
}
