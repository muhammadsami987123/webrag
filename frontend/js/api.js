// WebRAG API client — one function per backend endpoint.
// All functions throw a readable Error on non-2xx responses.

const BASE = '/api';

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(BASE + path, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
  } catch (err) {
    throw new Error('Network error: unable to reach the server. Please check your connection and try again.');
  }

  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      message = body.detail || body.error || body.message || message;
    } catch (_) {
      /* response wasn't JSON */
    }
    throw new Error(message);
  }

  if (res.status === 204) return null;

  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch (_) {
    return text;
  }
}

function qs(params) {
  const clean = Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== null && v !== '');
  if (!clean.length) return '';
  return '?' + new URLSearchParams(clean).toString();
}

// ---- Workspaces ----
export const createWorkspace = (url, crawl_config) =>
  request('/workspaces', { method: 'POST', body: JSON.stringify({ url, crawl_config }) });

export const listWorkspaces = () => request('/workspaces');

export const getWorkspace = (id) => request(`/workspaces/${id}`);

export const deleteWorkspace = (id) => request(`/workspaces/${id}`, { method: 'DELETE' });

export const reindexWorkspace = (id) => request(`/workspaces/${id}/reindex`, { method: 'POST' });

export const progressStreamUrl = (id) => `${BASE}/workspaces/${id}/progress/stream`;

// ---- Sources ----
export const getSources = (id) => request(`/workspaces/${id}/sources`);

export const getSource = (id, docId) => request(`/workspaces/${id}/sources/${docId}`);

export const deleteSource = (id, docId) => request(`/workspaces/${id}/sources/${docId}`, { method: 'DELETE' });

// ---- Chat ----
export const chat = (body) => request('/chat', { method: 'POST', body: JSON.stringify(body) });

export const chatStreamEndpoint = () => `${BASE}/chat/stream`;

export const getChatHistory = (id, conversationId = 'default') =>
  request(`/workspaces/${id}/chat/history${qs({ conversation_id: conversationId })}`);

// ---- Search ----
export const search = (id, q) => request(`/workspaces/${id}/search${qs({ q })}`);

// ---- Research operations ----
export const summarize = (id, document_ids) =>
  request(`/workspaces/${id}/summarize`, { method: 'POST', body: JSON.stringify({ document_ids }) });

export const getTopics = (id) => request(`/workspaces/${id}/topics`);

export const getSuggestions = (id) => request(`/workspaces/${id}/suggestions`);

export const compare = (id, query) =>
  request(`/workspaces/${id}/compare`, { method: 'POST', body: JSON.stringify({ query }) });

export const extract = (id, query) =>
  request(`/workspaces/${id}/extract`, { method: 'POST', body: JSON.stringify({ query }) });

// ---- Notes / Highlights / Collections ----
export const getNotes = (id) => request(`/workspaces/${id}/notes`);
export const postNote = (id, content) =>
  request(`/workspaces/${id}/notes`, { method: 'POST', body: JSON.stringify({ content }) });

export const getHighlights = (id) => request(`/workspaces/${id}/highlights`);
export const postHighlight = (id, data) =>
  request(`/workspaces/${id}/highlights`, { method: 'POST', body: JSON.stringify(data) });

export const getCollections = (id) => request(`/workspaces/${id}/collections`);
export const postCollection = (id, data) =>
  request(`/workspaces/${id}/collections`, { method: 'POST', body: JSON.stringify(data) });

// ---- Health ----
export const health = () => request('/health');
