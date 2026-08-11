const API = '/api';

function headers(): HeadersInit {
  const token = localStorage.getItem('wiki_token');
  const h: HeadersInit = { 'Content-Type': 'application/json' };
  if (token) h['Authorization'] = `Bearer ${token}`;
  return h;
}

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API}${path}`, { ...options, headers: { ...headers(), ...options.headers } });
  if (res.status === 401) {
    localStorage.removeItem('wiki_token');
    throw new Error('Login required');
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(typeof err.detail === 'string' ? err.detail : res.statusText);
  }
  return res.json();
}

export interface SearchResult {
  score: number;
  slug: string;
  title: string;
  snippet: string;
  type: string;
}

export interface PageData {
  slug: string;
  title: string;
  body: string;
  content: string;
  type: string;
  tags: string[];
  backlinks: { slug: string; title: string; type: string }[];
}

export interface GraphData {
  nodes: { id: string; slug: string; title: string; type: string; link_count: number }[];
  edges: { source: string; target: string }[];
}

export const searchWiki = (q: string, limit = 12) =>
  api<{ results: SearchResult[] }>(`/search?q=${encodeURIComponent(q)}&limit=${limit}`);

export const getPage = (slug: string) => api<PageData>(`/pages/${encodeURIComponent(slug)}`);

export const getGraph = () => api<GraphData>('/graph');

export const getStats = () => api<Record<string, number>>('/stats');

export const getSources = () => api<{ sources: { slug: string; title: string; type: string; url?: string }[] }>('/sources');

export const getLog = () => api<{ entries: { action: string; summary: string; created_at: string }[] }>('/log');

export const login = async (email: string, password: string) => {
  const data = await api<{ access_token: string }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  localStorage.setItem('wiki_token', data.access_token);
  return data;
};

export const queryLLM = (question: string) =>
  api<{ answer: string }>('/llm/query', { method: 'POST', body: JSON.stringify({ question }) });

export const ingestWeb = (url: string) =>
  api<{ slug: string; title: string }>('/ingest/web', { method: 'POST', body: JSON.stringify({ url }) });

export const ingestArxiv = (id_or_url: string) =>
  api<{ slug: string; title: string }>('/ingest/arxiv', { method: 'POST', body: JSON.stringify({ id_or_url }) });

export const ingestYoutube = (url: string) =>
  api<{ slug: string; title: string }>('/ingest/youtube', { method: 'POST', body: JSON.stringify({ url }) });

export const summarizeSource = (source_slug: string) =>
  api<{ slug: string; title: string }>('/llm/summarize', { method: 'POST', body: JSON.stringify({ source_slug }) });

export const newZettel = (title: string) =>
  api<{ slug: string; title: string }>('/zettels', { method: 'POST', body: JSON.stringify({ title }) });
