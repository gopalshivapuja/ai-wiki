import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  getLog, getSources, ingestArxiv, ingestWeb, ingestYoutube, newZettel, summarizeSource,
} from './api';

export function ManagePage() {
  const [webUrl, setWebUrl] = useState('');
  const [arxivId, setArxivId] = useState('');
  const [youtubeUrl, setYoutubeUrl] = useState('');
  const [zettelTitle, setZettelTitle] = useState('');
  const [summarizeSlug, setSummarizeSlug] = useState('');
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');
  const [sources, setSources] = useState<{ slug: string; title: string; type: string }[]>([]);
  const [log, setLog] = useState<{ action: string; summary: string; created_at: string }[]>([]);
  const navigate = useNavigate();

  async function load() {
    try {
      const [s, l] = await Promise.all([getSources(), getLog()]);
      setSources(s.sources);
      setLog(l.entries);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Load failed');
    }
  }

  useEffect(() => { load(); }, []);

  async function run(action: () => Promise<{ slug: string; title: string }>) {
    setErr('');
    setMsg('Working…');
    try {
      const r = await action();
      setMsg(`Done: ${r.title}`);
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed');
      setMsg('');
    }
  }

  return (
    <div className="container">
      <p style={{ marginBottom: '1.5rem' }}>
        <Link to="/">← Search</Link>
        <span style={{ color: 'var(--muted)', marginLeft: '1rem' }}>Add sources & pages</span>
      </p>

      {err && <p className="error">{err} — <Link to="/login">Login</Link></p>}
      {msg && <p style={{ color: 'var(--green)', marginBottom: '1rem' }}>{msg}</p>}

      <div className="ask-panel" style={{ marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.1rem', marginBottom: '1rem', fontWeight: 500 }}>Ingest Web Article</h2>
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <input placeholder="https://example.com/article" value={webUrl} onChange={(e) => setWebUrl(e.target.value)} />
          <button onClick={() => run(() => ingestWeb(webUrl))}>Ingest</button>
        </div>
      </div>

      <div className="ask-panel" style={{ marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.1rem', marginBottom: '1rem', fontWeight: 500 }}>Ingest arXiv Paper</h2>
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <input placeholder="2301.00000 or arxiv URL" value={arxivId} onChange={(e) => setArxivId(e.target.value)} />
          <button onClick={() => run(() => ingestArxiv(arxivId))}>Ingest</button>
        </div>
      </div>

      <div className="ask-panel" style={{ marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.1rem', marginBottom: '1rem', fontWeight: 500 }}>Ingest YouTube</h2>
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <input placeholder="YouTube URL or video ID" value={youtubeUrl} onChange={(e) => setYoutubeUrl(e.target.value)} />
          <button onClick={() => run(() => ingestYoutube(youtubeUrl))}>Ingest</button>
        </div>
      </div>

      <div className="ask-panel" style={{ marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.1rem', marginBottom: '1rem', fontWeight: 500 }}>New Atomic Zettel</h2>
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <input placeholder="Concept title" value={zettelTitle} onChange={(e) => setZettelTitle(e.target.value)} />
          <button onClick={async () => {
            setErr(''); setMsg('Working…');
            try {
              const r = await newZettel(zettelTitle);
              setMsg(`Created: ${r.title}`);
              navigate(`/wiki/${r.slug}`);
            } catch (e) {
              setErr(e instanceof Error ? e.message : 'Failed');
              setMsg('');
            }
          }}>Create</button>
        </div>
      </div>

      <div className="ask-panel" style={{ marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.1rem', marginBottom: '1rem', fontWeight: 500 }}>AI Summarize Source</h2>
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <input placeholder="source-slug" value={summarizeSlug} onChange={(e) => setSummarizeSlug(e.target.value)} />
          <button onClick={() => run(() => summarizeSource(summarizeSlug))}>Summarize</button>
        </div>
      </div>

      <div className="page-layout">
        <div className="sidebar">
          <h3>Sources ({sources.length})</h3>
          <ul>
            {sources.map((s) => (
              <li key={s.slug}>{s.title} <span className="badge">{s.type}</span></li>
            ))}
          </ul>
        </div>
        <div className="sidebar">
          <h3>Activity Log</h3>
          <ul>
            {log.map((e, i) => (
              <li key={i} style={{ fontSize: '0.85rem', marginBottom: '0.5rem' }}>
                <span className="badge">{e.action}</span> {e.summary}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
