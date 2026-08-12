import { useCallback, useEffect, useRef, useState } from 'react';
import { isJobActive, searchWiki, type Job, type SearchResult } from './api';

/** Fetch on mount and whenever deps change, ignoring responses that arrive out of order.
 *
 * Every page used to hand-roll this, and none of them guarded against a stale response —
 * navigating quickly between two documents could render the wrong one.
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    let ignore = false;
    setLoading(true);
    fnRef
      .current()
      .then((result) => {
        if (ignore) return;
        setData(result);
        setError(null);
      })
      .catch((err) => {
        if (ignore) return;
        setError((err as Error).message || 'Something went wrong');
        setData(null);
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });
    return () => {
      ignore = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, reload, setData };
}

/** Poll while work is in flight, and stop when it isn't.
 *
 * One implementation for both the job list and a single job. The two previous versions each
 * had a different bug: one never restarted after new work was queued and spawned a fresh
 * chain on every window focus, the other froze permanently after a single failed request.
 */
export function usePoll<T>(
  fetcher: () => Promise<T>,
  isActive: (value: T) => boolean,
  restartKey: unknown = 0,
  intervalMs = 2000,
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const activeRef = useRef(isActive);
  activeRef.current = isActive;

  const [nonce, setNonce] = useState(0);
  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;

    const tick = async () => {
      try {
        const value = await fetcherRef.current();
        if (stopped) return;
        setData(value);
        setError(null);
        if (activeRef.current(value)) timer = window.setTimeout(tick, intervalMs);
      } catch (err) {
        if (stopped) return;
        // Surfaced and retried once, rather than silently freezing forever.
        setError((err as Error).message);
        timer = window.setTimeout(tick, intervalMs * 3);
      }
    };
    tick();

    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [restartKey, nonce, intervalMs]);

  return { data, error, refresh };
}

export const jobsActive = (jobs: Job[]) => jobs.some(isJobActive);

/** Debounced search that owns its own state.
 *
 * Replaces a callback that mirrored four pieces of state from the search box into the page,
 * costing an extra render per keystroke and papering over an out-of-order response bug.
 */
export function useSearch(query: string, limit = 12) {
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const q = query.trim();
    if (!q) {
      setResults([]);
      setError(null);
      setLoading(false);
      return;
    }
    let ignore = false;
    setLoading(true);
    const timer = setTimeout(() => {
      searchWiki(q, limit)
        .then((data) => {
          if (ignore) return;
          setResults(data.results);
          setError(null);
        })
        .catch((err) => {
          if (ignore) return;
          // An outage used to be indistinguishable from "no results".
          setResults([]);
          setError((err as Error).message || 'Search failed');
        })
        .finally(() => {
          if (!ignore) setLoading(false);
        });
    }, 250);

    return () => {
      ignore = true;
      clearTimeout(timer);
    };
  }, [query, limit]);

  return { results, loading, error };
}
