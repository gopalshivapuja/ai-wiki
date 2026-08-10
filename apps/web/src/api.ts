const API_BASE = import.meta.env.VITE_API_URL || '';

function authHeaders(): HeadersInit {
  const token = localStorage.getItem('wiki_token');
  const h: HeadersInit = { 'Content-Type': 'application/json' };
  if (token) h['Authorization'] = `Bearer ${token}`;
  return h;
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...options.headers },
  });
  if (res.status === 401) {
    localStorage.removeItem('wiki_token');
    window.location.href = '/login';
    throw new Error('Unauthorized');
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

export interface SearchResult {
  score: number;
  slug: string;
  title: string;
  path: string;
  snippet: string;
  type: string;
}

export interface PageData {
  slug: string;
  title: string;
  content: string;
  body: string;
  frontmatter: Record<string, unknown>;
  path: string;
  backlinks: { slug: string; title: string; path: string }[];
}

export interface GraphData {
  nodes: { id: string; slug: string; title: string; type: string; link_count: number }[];
  edges: { source: string; target: string }[];
}

export async function login(email: string, password: string) {
  const data = await api<{ access_token: string }>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  localStorage.setItem('wiki_token', data.access_token);
  return data;
}

export async function searchWiki(q: string, limit = 12) {
  return api<{ results: SearchResult[] }>(`/api/search?q=${encodeURIComponent(q)}&limit=${limit}`);
}

export async function getPage(slug: string) {
  return api<PageData>(`/api/pages/${encodeURIComponent(slug)}`);
}

export async function getGraph() {
  return api<GraphData>('/api/graph');
}

export async function queryLLM(question: string) {
  return api<{ answer: string }>('/api/llm/query', {
    method: 'POST',
    body: JSON.stringify({ question }),
  });
}

export async function getMe() {
  return api<{ email: string; role: string }>('/api/auth/me');
}
