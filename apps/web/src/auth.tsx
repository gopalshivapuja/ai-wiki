import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { getToken, logout as apiLogout, me, setUnauthorizedHandler } from './api';

interface AuthState {
  email: string | null;
  loading: boolean;
  isAuthed: boolean;
  signedIn: (email: string) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthState>({
  email: null,
  loading: true,
  isAuthed: false,
  signedIn: () => {},
  logout: () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [email, setEmail] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // A 401 from anywhere means the session is gone; drop it once, centrally.
    setUnauthorizedHandler(() => setEmail(null));
    if (!getToken()) {
      setLoading(false);
      return;
    }
    let ignore = false;
    // Verified against the server rather than trusting that a token exists: it may have
    // expired, in which case the nav would otherwise still show "Log out".
    me()
      .then((u) => !ignore && setEmail(u.email))
      .catch(() => !ignore && setEmail(null))
      .finally(() => !ignore && setLoading(false));
    return () => {
      ignore = true;
      setUnauthorizedHandler(null);
    };
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      email,
      loading,
      isAuthed: Boolean(email),
      // Set directly from the login response. Re-fetching /me here raced the redirect and
      // bounced the user straight back to the login form.
      signedIn: (e: string) => {
        setEmail(e);
        setLoading(false);
      },
      logout: () => {
        apiLogout();
        setEmail(null);
      },
    }),
    [email, loading],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);

/** The wiki is private: everything except /login sits behind this. */
export function RequireAuth({ children }: { children: React.ReactElement }) {
  const { isAuthed, loading } = useAuth();
  const location = useLocation();

  if (loading) return <div className="container muted">Checking your session…</div>;
  if (!isAuthed) {
    return <Navigate to="/login" state={{ from: location.pathname + location.search }} replace />;
  }
  return children;
}

export const useRequireAuthCallback = () => {
  const { logout } = useAuth();
  return useCallback(() => logout(), [logout]);
};
