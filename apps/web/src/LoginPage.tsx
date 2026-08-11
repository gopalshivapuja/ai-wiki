import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { login } from './api';

export function LoginPage() {
  const [email, setEmail] = useState('admin@example.com');
  const [password, setPassword] = useState('changeme');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      await login(email, password);
      navigate('/');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-card">
      <h1>🧠 LLM Wiki</h1>
      <form onSubmit={handleSubmit}>
        <input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={loading}>{loading ? 'Signing in…' : 'Sign in'}</button>
      </form>
      <p style={{ marginTop: '1rem', fontSize: '0.85rem', color: 'var(--muted)' }}>
        Default: admin@example.com / changeme
      </p>
      <Link to="/" style={{ display: 'block', marginTop: '1rem', fontSize: '0.9rem' }}>
        ← Continue without login (read-only)
      </Link>
    </div>
  );
}
