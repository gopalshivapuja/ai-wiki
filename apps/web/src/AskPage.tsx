import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { askLLMStream, createDoc, docPath, getModelStatus, type Citation } from './api';
import { useAsync } from './hooks';
import { Markdown } from './Markdown';

interface Answer {
  id: number;
  question: string;
  answer: string;
  citations: Citation[];
  streaming: boolean;
  error?: string;
}

export function AskPage() {
  const [question, setQuestion] = useState('');
  const [history, setHistory] = useState<Answer[]>([]);
  const [busy, setBusy] = useState(false);
  const { data: models } = useAsync(() => getModelStatus(), []);
  const navigate = useNavigate();
  const abortRef = useRef<(() => void) | null>(null);

  // Abandon an in-flight answer if the page goes away.
  useEffect(() => () => abortRef.current?.(), []);

  const update = (id: number, patch: Partial<Answer>) =>
    setHistory((h) => h.map((a) => (a.id === id ? { ...a, ...patch } : a)));

  const ask = (e: React.FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (!q || busy) return;

    const id = Date.now();
    setHistory((h) => [
      { id, question: q, answer: '', citations: [], streaming: true },
      ...h,
    ]);
    setQuestion('');
    setBusy(true);

    abortRef.current = askLLMStream(q, {
      onCitations: (citations) => update(id, { citations }),
      onText: (chunk) =>
        setHistory((h) => h.map((a) => (a.id === id ? { ...a, answer: a.answer + chunk } : a))),
      onDone: () => {
        update(id, { streaming: false });
        setBusy(false);
      },
      onError: (message) => {
        update(id, { streaming: false, error: message });
        setBusy(false);
      },
    });
  };

  const saveAsNote = async (a: Answer) => {
    try {
      const body = `# ${a.question}\n\n${a.answer}\n\n## Sources\n\n${a.citations
        .map((c) => `- [[${c.slug}|${c.title}]]`)
        .join('\n')}\n`;
      const created = await createDoc({ title: a.question.slice(0, 120), body, type: 'zettel' });
      navigate(`/edit/${encodeURIComponent(created.slug)}`);
    } catch (err) {
      update(a.id, { error: (err as Error).message });
    }
  };

  const misconfigured = models && (!models.api_key_set || models.usable_count === 0);

  return (
    <div className="container reading">
      <h1>Ask your wiki</h1>
      <p className="muted">
        Answers come only from what you have added, with links to the notes they came from.
      </p>

      {misconfigured && (
        <div className="panel warning">
          <strong>AI is not configured yet.</strong>
          {!models?.api_key_set ? (
            <p className="small">
              Set <code>OPENROUTER_API_KEY</code> in your environment and restart.
            </p>
          ) : (
            <p className="small">
              No model is currently available.
              {models.free_available.length > 0 && (
                <>
                  {' '}
                  Try <code>OPENROUTER_MODEL={models.free_available[0]}</code>, or leave it unset
                  to auto-select.
                </>
              )}
            </p>
          )}
        </div>
      )}

      <form className="row gap ask-form" onSubmit={ask}>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="What does the transformer paper say about attention?"
          aria-label="Your question"
          maxLength={2000}
          autoFocus
        />
        <button disabled={busy || !question.trim()}>{busy ? 'Thinking…' : 'Ask'}</button>
      </form>

      {history.length === 0 && (
        <div className="empty-state">
          <p className="muted">Ask anything about the material you have collected.</p>
        </div>
      )}

      {history.map((a) => (
        <section className="panel ask-answer" key={a.id}>
          <h2>{a.question}</h2>

          {a.citations.length > 0 && (
            <div className="citations-inline">
              <span className="muted small">Reading:</span>
              {a.citations.map((c) => (
                <Link key={c.slug} className="badge tag" to={docPath(c.slug)}>
                  {c.title}
                </Link>
              ))}
            </div>
          )}

          {a.answer ? (
            <Markdown
              content={a.answer}
              links={a.citations.flatMap((c) => [
                { target: c.slug, slug: c.slug, display: c.title, exists: true },
                // Models often cite by title rather than slug.
                { target: c.title, slug: c.slug, display: c.title, exists: true },
              ])}
            />
          ) : (
            a.streaming && <p className="muted small">Searching your notes…</p>
          )}

          {a.streaming && a.answer && <span className="cursor-blink" aria-hidden="true" />}
          {a.error && <p className="error small">{a.error}</p>}

          {!a.streaming && a.answer && !a.error && (
            <button className="ghost small" onClick={() => saveAsNote(a)}>
              Save as a note
            </button>
          )}
        </section>
      ))}
    </div>
  );
}
