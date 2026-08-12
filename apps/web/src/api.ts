const API = '/api';
const TOKEN_KEY = 'wiki_token';

let onUnauthorized: (() => void) | null = null;

/** AuthProvider registers here so a 401 anywhere can clear the session exactly once. */
export const setUnauthorizedHandler = (fn: (() => void) | null) => {
  onUnauthorized = fn;
};

export const getToken = () => localStorage.getItem(TOKEN_KEY);

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/** Turn any FastAPI error body into something a human can read.
 *
 * Validation errors arrive as a *list* of objects, and res.statusText is empty over HTTP/2,
 * so the naive version rendered "Request failed" — or, for the array, "[object Object]".
 */
function extractDetail(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => {
        const field = Array.isArray(d.loc) ? d.loc.slice(1).join('.') : '';
        return field ? `${field}: ${d.msg}` : d.msg || 'invalid value';
      })
      .join('; ');
  }
  if (detail && typeof detail === 'object' && 'message' in detail) {
    return String((detail as { message: unknown }).message);
  }
  return `Request failed (${status})`;
}

async function handleError(res: Response, path: string): Promise<never> {
  const body = await res.json().catch(() => null);
  // The login endpoint owns its own 401 — otherwise a wrong password reported
  // "Login required" and logged you out of an existing session.
  if (res.status === 401 && !path.startsWith('/auth/login')) {
    localStorage.removeItem(TOKEN_KEY);
    onUnauthorized?.();
    throw new ApiError('Your session has expired. Please log in again.', 401);
  }
  throw new ApiError(extractDetail(body, res.status), res.status);
}

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(`${API}${path}`, { ...options, headers });
  } catch {
    throw new ApiError('Could not reach the server. Is it running?', 0);
  }
  if (!res.ok) await handleError(res, path);
  if (res.status === 204) return undefined as T;
  return res.json();
}

async function upload<T>(path: string, form: FormData): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API}${path}`, {
    method: 'POST',
    body: form, // no Content-Type — the browser sets the multipart boundary
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) await handleError(res, path);
  return res.json();
}

// --- types -------------------------------------------------------------------

export type DocClass = 'note' | 'source';

export interface DocSummary {
  slug: string;
  uid: string | null;
  title: string;
  doc_class: DocClass;
  type: string;
  tags: string[];
  url: string | null;
  collection: string | null;
  immutable: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface WikiLink {
  target: string;
  slug: string | null;
  display: string;
  exists: boolean;
}

export interface DocDetail extends DocSummary {
  body: string;
  backlinks: { slug: string; title: string; type: string; doc_class: DocClass }[];
  links: WikiLink[];
  derived_from: { slug: string; title: string } | null;
  summary: { slug: string; title: string } | null;
  revision_count: number;
}

export interface SearchResult {
  score: number;
  slug: string;
  title: string;
  snippet: string;
  type: string;
  doc_class: DocClass;
}

export interface GraphData {
  nodes: {
    id: string;
    slug: string;
    title: string;
    type: string;
    doc_class: DocClass;
    link_count: number;
  }[];
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

export interface Revision {
  id: number;
  title: string;
  created_at: string | null;
  preview: string;
}

export interface ModelStatus {
  invalid: string[];
  usable_count: number;
  free_available: string[];
  api_key_set: boolean;
}

export interface Stats {
  total_notes: number;
  total_sources: number;
  zettels: number;
  concepts: number;
  entities: number;
  literature: number;
  mocs: number;
  total_wikilinks: number;
  avg_links_per_note: number;
}

export const isJobActive = (j: Job) =>
  j.status === 'queued' || j.status === 'running' || j.status === 'cancelling';

/** One namespace, so one path. */
export const docPath = (slug: string) => `/doc/${encodeURIComponent(slug)}`;

// --- auth --------------------------------------------------------------------

export const login = async (email: string, password: string) => {
  const data = await api<{ access_token: string }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  localStorage.setItem(TOKEN_KEY, data.access_token);
  return data;
};

export const logout = () => localStorage.removeItem(TOKEN_KEY);
export const me = () => api<{ email: string }>('/auth/me');

// --- documents ---------------------------------------------------------------

export const searchWiki = (q: string, limit = 12, includeSources = true) =>
  api<{ results: SearchResult[] }>(
    `/search?q=${encodeURIComponent(q)}&limit=${limit}&include_sources=${includeSources}`,
  );

export const listDocs = (params: {
  doc_class?: DocClass;
  type?: string;
  tag?: string;
  collection?: string;
} = {}) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) q.set(k, v);
  const qs = q.toString();
  return api<{ documents: DocSummary[] }>(`/documents${qs ? `?${qs}` : ''}`);
};

export const getDoc = (slug: string) => api<DocDetail>(`/documents/${encodeURIComponent(slug)}`);

export const createDoc = (body: { title: string; body?: string; type?: string; tags?: string[] }) =>
  api<DocSummary>('/documents', { method: 'POST', body: JSON.stringify(body) });

export const updateDoc = (
  slug: string,
  patch: { title?: string; body?: string; tags?: string[]; type?: string },
) =>
  api<DocDetail>(`/documents/${encodeURIComponent(slug)}`, {
    method: 'PUT',
    body: JSON.stringify(patch),
  });

export const deleteDoc = (slug: string) =>
  api<void>(`/documents/${encodeURIComponent(slug)}`, { method: 'DELETE' });

export const getRevisions = (slug: string) =>
  api<{ revisions: Revision[] }>(`/documents/${encodeURIComponent(slug)}/revisions`);

export const restoreRevision = (slug: string, id: number) =>
  api<DocDetail>(`/documents/${encodeURIComponent(slug)}/restore/${id}`, { method: 'POST' });

export const getTags = () => api<{ tags: { tag: string; count: number }[] }>('/tags');
export const getGraph = (includeSources = true) =>
  api<GraphData>(`/graph?include_sources=${includeSources}`);
export const getOrphans = () =>
  api<{ unlinked: { slug: string; title: string }[]; wanted: { target: string; mentions: number }[] }>(
    '/orphans',
  );
export const getStats = () => api<Stats>('/stats');
export const getLog = () =>
  api<{ entries: { action: string; summary: string; created_at: string | null }[] }>('/log');
export const getModelStatus = () => api<ModelStatus>('/llm/models');

export const askLLM = (question: string) =>
  api<{ answer: string; citations: { slug: string; title: string; doc_class: DocClass }[] }>(
    '/llm/query',
    { method: 'POST', body: JSON.stringify({ question }) },
  );

/** Download the whole wiki as a zip. The only copy that isn't in the database. */
export const exportUrl = () => `${API}/export`;

export const downloadExport = async () => {
  const token = getToken();
  const res = await fetch(exportUrl(), {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (!res.ok) await handleError(res, '/export');
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `ai-wiki-${new Date().toISOString().slice(0, 10)}.zip`;
  a.click();
  URL.revokeObjectURL(url);
};

// --- jobs --------------------------------------------------------------------

const job = (path: string, body: unknown) =>
  api<Job>(`/jobs${path}`, { method: 'POST', body: JSON.stringify(body) });

export const ingestWeb = (url: string, summarize = true) => job('/web', { url, summarize });
export const ingestArxiv = (id_or_url: string) => job('/arxiv', { id_or_url });
export const ingestYoutube = (url: string, summarize = true) => job('/youtube', { url, summarize });
export const transcribeUrl = (url: string, summarize = true) =>
  job('/transcribe', { url, summarize });
export const crawlSite = (body: {
  url: string;
  max_pages?: number;
  max_depth?: number;
  collection?: string;
  summarize?: boolean;
}) => job('/crawl', body);
export const pasteText = (title: string, text: string, summarize = false) =>
  job('/paste', { title, text, summarize });
export const summarizeSource = (source_slug: string) => job('/summarize', { source_slug });

export const uploadPdf = (file: File, title?: string, summarize = true) => {
  const form = new FormData();
  form.append('file', file);
  if (title) form.append('title', title);
  form.append('summarize', String(summarize));
  return upload<Job>('/jobs/pdf', form);
};

export const importArchive = (file: File) => {
  const form = new FormData();
  form.append('file', file);
  return upload<Job>('/jobs/import', form);
};

export const listJobs = (limit = 25) => api<{ jobs: Job[] }>(`/jobs?limit=${limit}`);
export const getJob = (id: number) => api<Job>(`/jobs/${id}`);
export const cancelJob = (id: number) => api<Job>(`/jobs/${id}/cancel`, { method: 'POST' });
export const retryJob = (id: number) => api<Job>(`/jobs/${id}/retry`, { method: 'POST' });
