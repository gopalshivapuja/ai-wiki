import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { login } from './api';
import { useAuth } from './auth';

export function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const { signedIn } = useAuth();

  const from = (location.state as { from?: string } | null)?.from || '/';

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      // Set the session directly from the login response. Re-verifying against /me here
      // raced the redirect and bounced straight back to this form.
      signedIn(email);
      navigate(from, { replace: true });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-card">
      <h1>Your wiki</h1>
      <form onSubmit={submit}>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          aria-label="Email"
          autoComplete="username"
          required
          autoFocus
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          aria-label="Password"
          autoComplete="current-password"
          required
        />
        <button disabled={busy}>{busy ? 'Signing in…' : 'Log in'}</button>
      </form>
      {error && <p className="error">{error}</p>}
    </div>
  );
}
