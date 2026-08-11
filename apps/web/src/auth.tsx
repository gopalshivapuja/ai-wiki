import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { AUTH_EVENT, getToken, logout as apiLogout, me } from './api';

interface AuthState {
  email: string | null;
  loading: boolean;
  isAuthed: boolean;
  logout: () => void;
  refresh: () => void;
}

const AuthContext = createContext<AuthState>({
  email: null,
  loading: true,
  isAuthed: false,
  logout: () => {},
  refresh: () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [email, setEmail] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    if (!getToken()) {
      setEmail(null);
      setLoading(false);
      return;
    }
    // Verify against the server rather than trusting the presence of a token: it may have
    // expired, in which case the nav would otherwise still show "Logout".
    me()
      .then((u) => setEmail(u.email))
      .catch(() => setEmail(null))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    refresh();
    // api.ts fires this on login and on any 401; 'storage' covers other tabs.
    window.addEventListener(AUTH_EVENT, refresh);
    window.addEventListener('storage', refresh);
    return () => {
      window.removeEventListener(AUTH_EVENT, refresh);
      window.removeEventListener('storage', refresh);
    };
  }, [refresh]);

  const value = useMemo<AuthState>(
    () => ({
      email,
      loading,
      isAuthed: Boolean(email),
      logout: () => {
        apiLogout();
        setEmail(null);
      },
      refresh,
    }),
    [email, loading, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);

/** Redirects to /login instead of rendering a page that will only 401. */
export function RequireAuth({ children }: { children: React.ReactElement }) {
  const { isAuthed, loading } = useAuth();
  const location = useLocation();

  if (loading) return <div className="container muted">Checking your session…</div>;
  if (!isAuthed) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  return children;
}
