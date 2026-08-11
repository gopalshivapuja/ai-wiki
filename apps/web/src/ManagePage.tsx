import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  crawlSite,
  deleteSource,
  getLog,
  getSources,
  ingestArxiv,
  ingestWeb,
  ingestYoutube,
  pasteText,
  summarizeSource,
  transcribeUrl,
  uploadPdf,
  type Job,
  type SourceSummary,
} from './api';
import { JobsPanel } from './JobsPanel';

type Tab = 'web' | 'docs' | 'youtube' | 'arxiv' | 'pdf' | 'paste';

const TABS: { id: Tab; label: string; hint: string }[] = [
  { id: 'web', label: 'Web page', hint: 'An article, blog post, or single page' },
  { id: 'docs', label: 'Docs site', hint: 'Crawl a documentation section' },
  { id: 'youtube', label: 'Video', hint: 'YouTube captions, or speech-to-text' },
  { id: 'arxiv', label: 'arXiv', hint: 'A paper id or URL' },
  { id: 'pdf', label: 'PDF', hint: 'Upload a file' },
  { id: 'paste', label: 'Paste text', hint: 'Notes with no URL' },
];

export function ManagePage() {
  const [params, setParams] = useSearchParams();
  const collection = params.get('collection');
  const [tab, setTab] = useState<Tab>('web');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sources, setSources] = useState<SourceSummary[]>([]);
  const [log, setLog] = useState<{ action: string; summary: string; created_at: string }[]>([]);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    getSources(collection || undefined)
      .then((d) => setSources(d.sources))
      .catch((err) => setError(err.message));
    getLog()
      .then((d) => setLog(d.entries))
      .catch(() => setLog([]));
  }, [reload, collection]);

  const submit = async (fn: () => Promise<Job>) => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await fn();
      setMessage('Queued — watch its progress below.');
      setReload((n) => n + 1);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="container">
      <h1>Add a source</h1>
      <p className="muted">
        Everything you add is captured as an immutable source, then summarized into a linked note
        you can edit.
      </p>

      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            className={`tab${tab === t.id ? ' active' : ''}`}
            onClick={() => {
              setTab(t.id);
              setMessage(null);
              setError(null);
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <section className="panel">
        <p className="muted small">{TABS.find((t) => t.id === tab)?.hint}</p>
        {tab === 'web' && <WebForm busy={busy} onSubmit={submit} />}
        {tab === 'docs' && <DocsForm busy={busy} onSubmit={submit} />}
        {tab === 'youtube' && <VideoForm busy={busy} onSubmit={submit} />}
        {tab === 'arxiv' && <ArxivForm busy={busy} onSubmit={submit} />}
        {tab === 'pdf' && <PdfForm busy={busy} onSubmit={submit} />}
        {tab === 'paste' && <PasteForm busy={busy} onSubmit={submit} />}
        {message && <p className="success">{message}</p>}
        {error && <p className="error">{error}</p>}
      </section>

      <JobsPanel onSettled={() => setReload((n) => n + 1)} />

      <section className="panel">
        <div className="row space-between">
          <h2>Sources ({sources.length})</h2>
          {collection && (
            <button className="ghost small" onClick={() => setParams({})}>
              Clear “{collection}” filter
            </button>
          )}
        </div>
        {sources.length === 0 ? (
          <p className="muted small">No sources yet. Add one above.</p>
        ) : (
          <ul className="source-list">
            {sources.map((s) => (
              <li key={s.slug}>
                <div className="row space-between wrap">
                  <div>
                    <span className="badge">{s.type}</span>
                    <Link to={`/source/${encodeURIComponent(s.slug)}`}>{s.title}</Link>
                    {s.collection && (
                      <button
                        className="badge tag as-button"
                        onClick={() => setParams({ collection: s.collection! })}
                      >
                        {s.collection}
                      </button>
                    )}
                  </div>
                  <div className="row gap">
                    {s.summary_slug ? (
                      <Link className="small" to={`/wiki/${encodeURIComponent(s.summary_slug)}`}>
                        View note
                      </Link>
                    ) : (
                      <button
                        className="ghost small"
                        onClick={() => submit(() => summarizeSource(s.slug))}
                        disabled={busy}
                      >
                        Summarize
                      </button>
                    )}
                    <button
                      className="ghost small danger"
                      onClick={async () => {
                        if (!window.confirm(`Delete source “${s.title}”?`)) return;
                        await deleteSource(s.slug);
                        setReload((n) => n + 1);
                      }}
                    >
                      Delete
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel">
        <h2>Recent activity</h2>
        {log.length === 0 ? (
          <p className="muted small">Nothing recorded yet.</p>
        ) : (
          <ul className="log-list">
            {log.slice(0, 15).map((e, i) => (
              <li key={i}>
                <span className="badge">{e.action}</span>
                {e.summary}
                <span className="muted small"> · {new Date(e.created_at).toLocaleString()}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

// --- forms -------------------------------------------------------------------

interface FormProps {
  busy: boolean;
  onSubmit: (fn: () => Promise<Job>) => Promise<void>;
}

function SummarizeToggle({
  checked,
  onChange,
  label = 'Summarize into a note with AI',
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label?: string;
}) {
  return (
    <label className="checkbox">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

function WebForm({ busy, onSubmit }: FormProps) {
  const [url, setUrl] = useState('');
  const [summarize, setSummarize] = useState(true);
  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(() => ingestWeb(url.trim(), summarize)).then(() => setUrl(''));
      }}
    >
      <div className="row gap">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.com/article"
          required
        />
        <button disabled={busy || !url.trim()}>Add</button>
      </div>
      <SummarizeToggle checked={summarize} onChange={setSummarize} />
    </form>
  );
}

function DocsForm({ busy, onSubmit }: FormProps) {
  const [url, setUrl] = useState('');
  const [maxPages, setMaxPages] = useState(25);
  const [maxDepth, setMaxDepth] = useState(2);
  const [summarize, setSummarize] = useState(false);
  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(() =>
          crawlSite({ url: url.trim(), max_pages: maxPages, max_depth: maxDepth, summarize }),
        ).then(() => setUrl(''));
      }}
    >
      <div className="row gap">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://docs.example.com/guide/"
          required
        />
        <button disabled={busy || !url.trim()}>Crawl</button>
      </div>
      <div className="row gap wrap">
        <label className="field">
          Max pages
          <input
            type="number"
            min={1}
            max={50}
            value={maxPages}
            onChange={(e) => setMaxPages(Number(e.target.value))}
          />
        </label>
        <label className="field">
          Link depth
          <input
            type="number"
            min={0}
            max={5}
            value={maxDepth}
            onChange={(e) => setMaxDepth(Number(e.target.value))}
          />
        </label>
      </div>
      <SummarizeToggle
        checked={summarize}
        onChange={setSummarize}
        label="Summarize every crawled page (one AI call each — slow and uses your quota)"
      />
      <p className="muted small">
        Follows links on the same site at or below this URL’s folder. Capped at 50 pages.
      </p>
    </form>
  );
}

function VideoForm({ busy, onSubmit }: FormProps) {
  const [url, setUrl] = useState('');
  const [summarize, setSummarize] = useState(true);
  return (
    <form className="stack" onSubmit={(e) => e.preventDefault()}>
      <input
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="https://www.youtube.com/watch?v=…"
      />
      <SummarizeToggle checked={summarize} onChange={setSummarize} />
      <div className="row gap wrap">
        <button
          disabled={busy || !url.trim()}
          onClick={() => onSubmit(() => ingestYoutube(url.trim(), summarize)).then(() => setUrl(''))}
        >
          Use captions
        </button>
        <button
          className="ghost"
          disabled={busy || !url.trim()}
          onClick={() => onSubmit(() => transcribeUrl(url.trim(), summarize)).then(() => setUrl(''))}
        >
          Transcribe audio
        </button>
      </div>
      <p className="muted small">
        Captions are free and instant. Transcription downloads the audio and sends it to a
        speech-to-text API (about $0.36 per hour of audio) — use it when a video has no captions.
      </p>
    </form>
  );
}

function ArxivForm({ busy, onSubmit }: FormProps) {
  const [value, setValue] = useState('');
  return (
    <form
      className="row gap"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(() => ingestArxiv(value.trim())).then(() => setValue(''));
      }}
    >
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="1706.03762 or https://arxiv.org/abs/1706.03762"
        required
      />
      <button disabled={busy || !value.trim()}>Add</button>
    </form>
  );
}

function PdfForm({ busy, onSubmit }: FormProps) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [summarize, setSummarize] = useState(true);
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        if (!file) return;
        onSubmit(() => uploadPdf(file, title.trim() || undefined, summarize)).then(() => {
          setFile(null);
          setTitle('');
          if (inputRef.current) inputRef.current.value = '';
        });
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        required
      />
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Title (optional — taken from the PDF otherwise)"
      />
      <SummarizeToggle checked={summarize} onChange={setSummarize} />
      <button disabled={busy || !file}>Upload</button>
      <p className="muted small">Text-based PDFs up to 25MB. Scanned images would need OCR.</p>
    </form>
  );
}

function PasteForm({ busy, onSubmit }: FormProps) {
  const [title, setTitle] = useState('');
  const [text, setText] = useState('');
  const [summarize, setSummarize] = useState(false);
  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(() => pasteText(title.trim(), text, summarize)).then(() => {
          setTitle('');
          setText('');
        });
      }}
    >
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Title"
        required
      />
      <textarea
        rows={10}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Paste anything — meeting notes, an email, a transcript…"
        required
      />
      <SummarizeToggle checked={summarize} onChange={setSummarize} />
      <button disabled={busy || !title.trim() || !text.trim()}>Save</button>
    </form>
  );
}
