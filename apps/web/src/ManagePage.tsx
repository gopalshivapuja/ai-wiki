import { useRef, useState } from 'react';
import { useAuth } from './auth';
import { Link, useSearchParams } from 'react-router-dom';
import {
  crawlSite,
  deleteDoc,
  docPath,
  downloadExport,
  getLog,
  importArchive,
  ingestArxiv,
  ingestWeb,
  ingestYoutube,
  listDocs,
  pasteText,
  summarizeSource,
  transcribeUrl,
  uploadPdf,
  type Job,
} from './api';
import { useAsync } from './hooks';
import { JobsPanel, JobWatcher } from './JobsPanel';

type Tab = 'web' | 'docs' | 'video' | 'arxiv' | 'pdf' | 'paste';

const TABS: { id: Tab; label: string; hint: string }[] = [
  { id: 'web', label: 'Web page', hint: 'An article, blog post, or single page' },
  { id: 'docs', label: 'Docs site', hint: 'Crawl a documentation section' },
  { id: 'video', label: 'Video', hint: 'YouTube captions, or speech-to-text' },
  { id: 'arxiv', label: 'arXiv', hint: 'A paper id or URL' },
  { id: 'pdf', label: 'PDF', hint: 'Upload a file' },
  { id: 'paste', label: 'Paste text', hint: 'Notes with no URL' },
];

export function ManagePage() {
  const { canEdit } = useAuth();
  const [params, setParams] = useSearchParams();
  const collection = params.get('collection');
  const [tab, setTab] = useState<Tab>('web');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const sources = useAsync(
    () => listDocs({ doc_class: 'source', collection: collection || undefined }),
    [collection, reloadKey],
  );
  const log = useAsync(() => getLog(), [reloadKey]);

  const submit = async (fn: () => Promise<Job>) => {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await fn();
      setMessage('Queued — watch its progress below.');
      setReloadKey((n) => n + 1);
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
        Everything you add is captured unchanged, then summarised into a linked note you can edit.
      </p>

      {!canEdit && (
        <p className="demo-banner">
          <strong>Read-only demo.</strong> Every form here works exactly as it does for the
          owner, so you can see what adding a source involves — but nothing is saved, and the
          wiki is left untouched.
        </p>
      )}

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
        {tab === 'web' && (
          <SimpleForm
            label="Add"
            placeholder="https://example.com/article"
            busy={busy}
            withSummarize
            onSubmit={(v, s) => submit(() => ingestWeb(v, s))}
          />
        )}
        {tab === 'arxiv' && (
          <SimpleForm
            label="Add"
            placeholder="1706.03762 or https://arxiv.org/abs/1706.03762"
            busy={busy}
            onSubmit={(v) => submit(() => ingestArxiv(v))}
          />
        )}
        {tab === 'docs' && <DocsForm busy={busy} onSubmit={submit} />}
        {tab === 'video' && <VideoForm busy={busy} onSubmit={submit} />}
        {tab === 'pdf' && <PdfForm busy={busy} onSubmit={submit} />}
        {tab === 'paste' && <PasteForm busy={busy} onSubmit={submit} />}
        {message && <p className="success">{message}</p>}
        {error && <p className="error">{error}</p>}
      </section>

      <JobsPanel reloadKey={reloadKey} />

      <section className="panel">
        <div className="row space-between wrap">
          <h2>Sources ({sources.data?.documents.length ?? 0})</h2>
          {collection && (
            <button className="ghost small" onClick={() => setParams({})}>
              Clear “{collection}” filter
            </button>
          )}
        </div>
        {sources.error && <p className="error">{sources.error}</p>}
        {sources.data?.documents.length === 0 && (
          <p className="muted small">No sources yet. Add one above.</p>
        )}
        <ul className="source-list">
          {sources.data?.documents.map((s) => (
            <li key={s.slug}>
              <div className="row space-between wrap">
                <div>
                  <span className="badge">{s.type}</span>
                  <Link to={docPath(s.slug)}>{s.title}</Link>
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
                  <button
                    className="ghost small"
                    disabled={busy}
                    onClick={() => submit(() => summarizeSource(s.slug))}
                  >
                    Summarize
                  </button>
                  <button
                    className="ghost small danger"
                    onClick={async () => {
                      if (!window.confirm(`Delete source “${s.title}”?`)) return;
                      await deleteDoc(s.slug);
                      setReloadKey((n) => n + 1);
                    }}
                  >
                    Delete
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <BackupPanel onImported={() => setReloadKey((n) => n + 1)} />

      <section className="panel">
        <h2>Recent activity</h2>
        {log.data?.entries.length === 0 && <p className="muted small">Nothing recorded yet.</p>}
        <ul className="log-list">
          {log.data?.entries.slice(0, 15).map((e, i) => (
            <li key={i}>
              <span className="badge">{e.action}</span>
              {e.summary}
              {e.created_at && (
                <span className="muted small"> · {new Date(e.created_at).toLocaleString()}</span>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function BackupPanel({ onImported }: { onImported: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  return (
    <section className="panel">
      <h2>Backup</h2>
      <p className="muted small">
        Your notes live in one database. Download a copy — it is plain markdown, readable in any
        editor, and re-importable here.
      </p>
      <div className="row gap wrap">
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError(null);
            try {
              await downloadExport();
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Download everything
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".zip,application/zip"
          aria-label="Archive to import"
          onChange={async (e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            setError(null);
            try {
              const job = await importArchive(file);
              setJobId(job.id);
            } catch (err) {
              setError((err as Error).message);
            }
            if (fileRef.current) fileRef.current.value = '';
          }}
        />
      </div>
      {error && <p className="error">{error}</p>}
      {jobId !== null && (
        <JobWatcher
          jobId={jobId}
          onDone={() => {
            setJobId(null);
            onImported();
          }}
        />
      )}
    </section>
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

/** One text field and a button — the shape shared by the web and arXiv forms. */
function SimpleForm({
  label,
  placeholder,
  busy,
  withSummarize = false,
  onSubmit,
}: {
  label: string;
  placeholder: string;
  busy: boolean;
  withSummarize?: boolean;
  onSubmit: (value: string, summarize: boolean) => Promise<void>;
}) {
  const [value, setValue] = useState('');
  const [summarize, setSummarize] = useState(true);
  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(value.trim(), summarize).then(() => setValue(''));
      }}
    >
      <div className="row gap">
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={placeholder}
          aria-label={placeholder}
          required
        />
        <button disabled={busy || !value.trim()}>{label}</button>
      </div>
      {withSummarize && <SummarizeToggle checked={summarize} onChange={setSummarize} />}
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
          aria-label="Documentation URL"
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
        label="Summarize every crawled page (one AI call each — slow, and uses your quota)"
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
  const captions = () => onSubmit(() => ingestYoutube(url.trim(), summarize)).then(() => setUrl(''));

  return (
    <form
      className="stack"
      onSubmit={(e) => {
        e.preventDefault();
        captions();
      }}
    >
      <input
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        placeholder="https://www.youtube.com/watch?v=…"
        aria-label="Video URL"
      />
      <SummarizeToggle checked={summarize} onChange={setSummarize} />
      <div className="row gap wrap">
        <button type="submit" disabled={busy || !url.trim()}>
          Use captions
        </button>
        <button
          type="button"
          className="ghost"
          disabled={busy || !url.trim()}
          onClick={() => onSubmit(() => transcribeUrl(url.trim(), summarize)).then(() => setUrl(''))}
        >
          Transcribe audio
        </button>
      </div>
      <p className="muted small">
        Captions are free and instant. Transcription downloads the audio and sends it to a
        speech-to-text API (about $0.36 per hour) — use it when a video has no captions. Note that
        YouTube often blocks downloads from cloud servers.
      </p>
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
        aria-label="PDF file"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        required
      />
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Title (optional — taken from the PDF otherwise)"
        aria-label="Title"
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
        aria-label="Title"
        required
      />
      <textarea
        rows={10}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Paste anything — meeting notes, an email, a transcript…"
        aria-label="Text to store"
        required
      />
      <SummarizeToggle checked={summarize} onChange={setSummarize} />
      <button disabled={busy || !title.trim() || !text.trim()}>Save</button>
    </form>
  );
}
