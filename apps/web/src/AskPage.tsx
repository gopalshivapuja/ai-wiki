import { useState } from 'react';
import { Link } from 'react-router-dom';
import { queryLLM } from './api';
import { Markdown } from './Markdown';

export function AskPage() {
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function handleAsk(e: React.FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError('');
    try {
      const res = await queryLLM(question);
      setAnswer(res.answer);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Query failed — login required for AI features');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="container">
      <p style={{ marginBottom: '1.5rem' }}><Link to="/">← Search</Link></p>
      <h1 style={{ marginBottom: '1rem', fontWeight: 400 }}>Ask your wiki</h1>
      <form onSubmit={handleAsk} style={{ display: 'flex', gap: '0.75rem', marginBottom: '1.5rem' }}>
        <input
          placeholder="What is scaled dot-product attention?"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <button type="submit" disabled={loading}>{loading ? '…' : 'Ask'}</button>
      </form>
      {error && <p className="error">{error} — <Link to="/login">Login</Link></p>}
      {answer && (
        <div className="ask-panel">
          <Markdown content={answer} />
        </div>
      )}
    </div>
  );
}
