import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { login } from './api';
import { useAuth } from './auth';

export function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const { refresh } = useAuth();

  const from = (location.state as { from?: string } | null)?.from || '/';

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      refresh();
      navigate(from, { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-card">
      <h1>Log in</h1>
      <form onSubmit={submit}>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          autoComplete="username"
          required
          autoFocus
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          autoComplete="current-password"
          required
        />
        <button disabled={busy}>{busy ? 'Signing in…' : 'Log in'}</button>
      </form>
      {error && <p className="error">{error}</p>}
      <p className="muted small" style={{ marginTop: '1rem' }}>
        Reading is open to everyone. Adding sources, editing notes, and asking the AI need an
        account. <Link to="/">Browse without logging in →</Link>
      </p>
    </div>
  );
}
