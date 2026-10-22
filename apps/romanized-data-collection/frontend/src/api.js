// Accept the backend URL with or without a trailing slash or /api; request paths already start with /api.
const BASE = (import.meta.env.VITE_API_URL || '').trim().replace(/\/+$/, '').replace(/\/api$/, '');
const TOKEN_KEY = 'rn-token';

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => (t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY));

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function request(method, path, body) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let res;
  try {
    res = await fetch(BASE + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, 'Cannot reach the server. Check your internet connection.');
  }
  if (res.status === 401 && path !== '/api/auth/login') {
    setToken(null);
    window.location.assign('/login');
  }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      msg = typeof data.detail === 'string' ? data.detail : data.detail?.[0]?.msg || msg;
    } catch { /* not JSON */ }
    throw new ApiError(res.status, msg);
  }
  return res;
}

export const api = {
  get: async (p) => (await request('GET', p)).json(),
  post: async (p, b = {}) => (await request('POST', p, b)).json(),
  put: async (p, b = {}) => (await request('PUT', p, b)).json(),
  patch: async (p, b = {}) => (await request('PATCH', p, b)).json(),
  del: async (p) => (await request('DELETE', p)).json(),
  async download(p) {
    const res = await request('GET', p);
    const name = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') || '')?.[1] || 'download';
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement('a'), { href: url, download: name });
    a.click();
    URL.revokeObjectURL(url);
  },
};
