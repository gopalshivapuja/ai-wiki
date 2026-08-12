import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { askLLM, createDoc, docPath, getModelStatus, type DocClass } from './api';
import { useAsync } from './hooks';
import { Markdown } from './Markdown';

interface Answer {
  id: number;
  question: string;
  answer: string;
  citations: { slug: string; title: string; doc_class: DocClass }[];
}

export function AskPage() {
  const [question, setQuestion] = useState('');
  const [history, setHistory] = useState<Answer[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { data: models } = useAsync(() => getModelStatus(), []);
  const navigate = useNavigate();

  const ask = async (e: React.FormEvent) => {
    e.preventDefault();
    const q = question.trim();
    if (!q) return;
    setLoading(true);
    setError(null);
    try {
      const res = await askLLM(q);
      setHistory((h) => [{ id: Date.now(), question: q, ...res }, ...h]);
      setQuestion('');
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const saveAsNote = async (a: Answer) => {
    try {
      const body = `# ${a.question}\n\n${a.answer}\n\n## Sources\n\n${a.citations
        .map((c) => `- [[${c.slug}|${c.title}]]`)
        .join('\n')}\n`;
      const created = await createDoc({ title: a.question.slice(0, 120), body, type: 'zettel' });
      navigate(`/edit/${encodeURIComponent(created.slug)}`);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const misconfigured = models && (!models.api_key_set || models.usable_count === 0);

  return (
    <div className="container">
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
              None of the configured models are available.
              {models.invalid.length > 0 && (
                <>
                  {' '}
                  Unknown to OpenRouter: <code>{models.invalid.join(', ')}</code>.
                </>
              )}
              {models.free_available.length > 0 && (
                <>
                  {' '}
                  Try <code>OPENROUTER_MODEL={models.free_available[0]}</code>, or leave it unset to
                  auto-select.
                </>
              )}
            </p>
          )}
        </div>
      )}

      <form className="row gap" onSubmit={ask}>
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="What does the transformer paper say about attention?"
          aria-label="Your question"
          maxLength={2000}
          autoFocus
        />
        <button disabled={loading || !question.trim()}>{loading ? 'Thinking…' : 'Ask'}</button>
      </form>

      {error && <p className="error">{error}</p>}
      {loading && <p className="muted">Searching your notes and asking the model…</p>}

      {history.length === 0 && !loading && (
        <div className="empty-state">
          <p className="muted">Ask anything about the material you have collected.</p>
        </div>
      )}

      {history.map((a) => (
        <section className="panel ask-answer" key={a.id}>
          <h2>{a.question}</h2>
          <Markdown
            content={a.answer}
            // Citations are real documents, so they render as working links rather than
            // the greyed-out dead links sources used to get.
            links={a.citations.map((c) => ({
              target: c.slug,
              slug: c.slug,
              display: c.title,
              exists: true,
            }))}
          />
          {a.citations.length > 0 && (
            <div className="citations">
              <h3>Sources</h3>
              <ul>
                {a.citations.map((c) => (
                  <li key={c.slug}>
                    <Link to={docPath(c.slug)}>{c.title}</Link>
                    <span className="badge">{c.doc_class}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <button className="ghost small" onClick={() => saveAsNote(a)}>
            Save as a note
          </button>
        </section>
      ))}
    </div>
  );
}
