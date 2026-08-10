import { BrowserRouter, Link, Route, Routes } from 'react-router-dom';
import { AskPage } from './AskPage';
import { GraphPage } from './GraphPage';
import { HomePage } from './HomePage';
import { LoginPage } from './LoginPage';
import { PageView } from './PageView';
import './index.css';

function Nav() {
  const token = localStorage.getItem('wiki_token');
  return (
    <nav className="nav">
      <Link to="/" className="logo">🧠 LLM Wiki</Link>
      <Link to="/graph">Graph</Link>
      <Link to="/ask">Ask AI</Link>
      <div className="spacer" />
      {token ? (
        <button className="ghost" onClick={() => { localStorage.removeItem('wiki_token'); window.location.href = '/'; }}>
          Logout
        </button>
      ) : (
        <Link to="/login">Login</Link>
      )}
    </nav>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Nav />
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/wiki/:slug" element={<PageView />} />
        <Route path="/graph" element={<GraphPage />} />
        <Route path="/ask" element={<AskPage />} />
        <Route path="/login" element={<LoginPage />} />
      </Routes>
    </BrowserRouter>
  );
}
