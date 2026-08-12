import { createContext, useContext, useEffect, useMemo, useState } from 'react';

export type Theme = 'light' | 'dark' | 'system';

const KEY = 'wiki_theme';

interface ThemeState {
  theme: Theme;
  setTheme: (t: Theme) => void;
}

const ThemeContext = createContext<ThemeState>({ theme: 'system', setTheme: () => {} });

function apply(theme: Theme) {
  const root = document.documentElement;
  if (theme === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', theme);
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(
    () => (localStorage.getItem(KEY) as Theme) || 'system',
  );

  useEffect(() => {
    apply(theme);
  }, [theme]);

  const value = useMemo<ThemeState>(
    () => ({
      theme,
      setTheme: (t: Theme) => {
        localStorage.setItem(KEY, t);
        setThemeState(t);
      },
    }),
    [theme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => useContext(ThemeContext);

const ORDER: Theme[] = ['system', 'light', 'dark'];
const ICON: Record<Theme, string> = { system: '🖥', light: '☀', dark: '☾' };
const LABEL: Record<Theme, string> = {
  system: 'Match system theme',
  light: 'Light theme',
  dark: 'Dark theme',
};

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const next = ORDER[(ORDER.indexOf(theme) + 1) % ORDER.length];
  return (
    <button
      className="ghost icon-button"
      onClick={() => setTheme(next)}
      title={`${LABEL[theme]} — click for ${LABEL[next].toLowerCase()}`}
      aria-label={LABEL[theme]}
    >
      <span aria-hidden="true">{ICON[theme]}</span>
    </button>
  );
}
