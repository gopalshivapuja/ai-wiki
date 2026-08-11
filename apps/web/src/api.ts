const API = '/api';
const TOKEN_KEY = 'wiki_token';

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

/** Fires whenever the token is gained or lost, so the nav can react without a reload. */
export const AUTH_EVENT = 'wiki-auth-changed';
const notifyAuthChange = () => window.dispatchEvent(new Event(AUTH_EVENT));

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

function headers(extra?: HeadersInit): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json' };
  const token = getToken();
  if (token) h.Authorization = `Bearer ${token}`;
  return { ...h, ...(extra as Record<string, string>) };
}

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, { ...options, headers: headers(options.headers) });
  } catch {
    throw new ApiError('Could not reach the server. Is it running?', 0);
  }

  if (res.status === 401) {
    clearToken();
    notifyAuthChange();
    throw new ApiError('Login required', 401);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = body?.detail;
    const message =
      typeof detail === 'string' ? detail : detail?.message || res.statusText || 'Request failed';
    throw new ApiError(message, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// --- types -------------------------------------------------------------------

export type Kind = 'page' | 'source';

export interface SearchResult {
  score: number;
  slug: string;
  title: string;
  snippet: string;
  type: string;
  kind: Kind;
}

export interface WikiLink {
  target: string;
  slug: string | null;
  display: string;
  exists: boolean;
}

export interface PageData {
  slug: string;
  uid: string | null;
  title: string;
  body: string;
  type: string;
  tags: string[];
  source_refs: string[];
  created_at: string | null;
  updated_at: string | null;
  backlinks: { slug: string; title: string; type: string }[];
  links: WikiLink[];
}

export interface SourceData {
  slug: string;
  title: string;
  type: string;
  url: string | null;
  collection: string | null;
  body: string;
  created_at: string | null;
  summary_slug: string | null;
}

export interface SourceSummary {
  slug: string;
  title: string;
  type: string;
  url?: string | null;
  collection?: string | null;
  created_at?: string | null;
  summary_slug: string | null;
}

export interface GraphData {
  nodes: { id: string; slug: string; title: string; type: string; link_count: number }[];
  edges: { source: string; target: string }[];
}

export interface Job {
  id: number;
  kind: string;
  status: 'queued' | 'running' | 'cancelling' | 'done' | 'failed' | 'cancelled';
  params: Record<string, unknown>;
  progress: { current: number; total: number | null; message: string };
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface ModelStatus {
  configured: string[];
  valid: string[];
  invalid: string[];
  usable_count: number;
  will_use: string | null;
  free_available: string[];
  api_key_set: boolean;
  catalogue_error: string | null;
}

export const ACTIVE_JOB_STATUSES = ['queued', 'running', 'cancelling'];
export const isJobActive = (j: Job) => ACTIVE_JOB_STATUSES.includes(j.status);

/** Where a search hit lives — pages and sources are separate namespaces. */
export const hitPath = (r: { kind: Kind; slug: string }) =>
  r.kind === 'source' ? `/source/${encodeURIComponent(r.slug)}` : `/wiki/${encodeURIComponent(r.slug)}`;

// --- reads -------------------------------------------------------------------

export const searchWiki = (q: string, limit = 12) =>
  api<{ results: SearchResult[] }>(`/search?q=${encodeURIComponent(q)}&limit=${limit}`);

export const getPage = (slug: string) => api<PageData>(`/pages/${encodeURIComponent(slug)}`);

export const listPages = (params: { type?: string; tag?: string } = {}) => {
  const q = new URLSearchParams();
  if (params.type) q.set('type', params.type);
  if (params.tag) q.set('tag', params.tag);
  const qs = q.toString();
  return api<{ pages: { slug: string; title: string; type: string; tags: string[] }[] }>(
    `/pages${qs ? `?${qs}` : ''}`,
  );
};

export const getTags = () => api<{ tags: { tag: string; count: number }[] }>('/tags');
export const getGraph = () => api<GraphData>('/graph');
export const getStats = () => api<Record<string, number>>('/stats');
export const getSource = (slug: string) => api<SourceData>(`/sources/${encodeURIComponent(slug)}`);
export const getSources = (collection?: string) =>
  api<{ sources: SourceSummary[] }>(
    `/sources${collection ? `?collection=${encodeURIComponent(collection)}` : ''}`,
  );
export const getLog = () =>
  api<{ entries: { action: string; summary: string; created_at: string }[] }>('/log');
export const getModelStatus = () => api<ModelStatus>('/llm/models');

// --- auth --------------------------------------------------------------------

export const login = async (email: string, password: string) => {
  const data = await api<{ access_token: string }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  setToken(data.access_token);
  notifyAuthChange();
  return data;
};

export const logout = () => {
  clearToken();
  notifyAuthChange();
};

export const me = () => api<{ email: string; role: string }>('/auth/me');

// --- writes ------------------------------------------------------------------

export const createZettel = (title: string, body?: string) =>
  api<{ slug: string; title: string }>('/zettels', {
    method: 'POST',
    body: JSON.stringify({ title, body }),
  });

export const updatePage = (
  slug: string,
  patch: { title?: string; body?: string; tags?: string[]; type?: string },
) =>
  api<PageData>(`/pages/${encodeURIComponent(slug)}`, {
    method: 'PUT',
    body: JSON.stringify(patch),
  });

export const deletePage = (slug: string) =>
  api<void>(`/pages/${encodeURIComponent(slug)}`, { method: 'DELETE' });

export const deleteSource = (slug: string) =>
  api<void>(`/sources/${encodeURIComponent(slug)}`, { method: 'DELETE' });

export const askLLM = (question: string) =>
  api<{ answer: string; citations: { slug: string; title: string; kind: Kind }[] }>('/llm/query', {
    method: 'POST',
    body: JSON.stringify({ question }),
  });

// --- jobs --------------------------------------------------------------------

const job = (path: string, body: unknown) =>
  api<Job>(`/jobs${path}`, { method: 'POST', body: JSON.stringify(body) });

export const ingestWeb = (url: string, summarize = true) => job('/web', { url, summarize });
export const ingestArxiv = (id_or_url: string) => job('/arxiv', { id_or_url });
export const ingestYoutube = (url: string, summarize = true) => job('/youtube', { url, summarize });
export const transcribeUrl = (url: string, summarize = true) => job('/transcribe', { url, summarize });
export const crawlSite = (body: {
  url: string;
  max_pages?: number;
  max_depth?: number;
  summarize?: boolean;
}) => job('/crawl', body);
export const pasteText = (title: string, text: string, summarize = false) =>
  job('/paste', { title, text, summarize });
export const summarizeSource = (source_slug: string) => job('/summarize', { source_slug });

export const uploadPdf = async (file: File, title?: string, summarize = true) => {
  const form = new FormData();
  form.append('file', file);
  if (title) form.append('title', title);
  form.append('summarize', String(summarize));

  const token = getToken();
  const res = await fetch(`${API}/jobs/pdf`, {
    method: 'POST',
    body: form, // no Content-Type — the browser sets the multipart boundary
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (res.status === 401) {
    clearToken();
    notifyAuthChange();
    throw new ApiError('Login required', 401);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(body?.detail || 'Upload failed', res.status);
  }
  return (await res.json()) as Job;
};

export const listJobs = (limit = 25) => api<{ jobs: Job[] }>(`/jobs?limit=${limit}`);
export const getJob = (id: number) => api<Job>(`/jobs/${id}`);
export const cancelJob = (id: number) => api<Job>(`/jobs/${id}/cancel`, { method: 'POST' });
export const retryJob = (id: number) => api<Job>(`/jobs/${id}/retry`, { method: 'POST' });
