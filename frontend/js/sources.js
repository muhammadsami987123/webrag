import { getSources, getWorkspace } from './api.js';

const params = new URLSearchParams(location.search);
const workspaceId = params.get('workspace') || params.get('id');

const tbody = document.getElementById('sources-tbody');
const countEl = document.getElementById('source-count');
const searchInput = document.getElementById('search-input');
const sortSelect = document.getElementById('sort-select');
const errorBanner = document.getElementById('error-banner');
const wsLink = document.getElementById('ws-link');

let allSources = [];

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str ?? '';
  return div.innerHTML;
}

function statusPill(status) {
  const map = {
    ready: 'bg-[--accent-soft] text-accent',
    indexed: 'bg-[--accent-soft] text-accent',
    processing: 'bg-[--amber-soft] text-[--amber]',
    error: 'bg-[--red-soft] text-[--red]',
  };
  const cls = map[status] || 'bg-neutral-100 text-neutral-600';
  return `<span class="text-[11px] font-medium px-2 py-0.5 rounded ${cls}">${escapeHtml(status || 'unknown')}</span>`;
}

function render() {
  const query = searchInput.value.trim().toLowerCase();
  const sortKey = sortSelect.value;

  let rows = allSources.filter(
    (s) => !query || (s.title || '').toLowerCase().includes(query) || (s.url || '').toLowerCase().includes(query)
  );

  rows.sort((a, b) => {
    if (sortKey === 'word_count') return (b.word_count || 0) - (a.word_count || 0);
    if (sortKey === 'updated_at') return new Date(b.updated_at || 0) - new Date(a.updated_at || 0);
    if (sortKey === 'status') return (a.status || '').localeCompare(b.status || '');
    return (a.title || '').localeCompare(b.title || '');
  });

  countEl.textContent = `${rows.length} of ${allSources.length} pages`;

  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="px-4 py-8 text-center text-[--ink-faint]">No relevant source sections were found.</td></tr>';
    return;
  }

  tbody.innerHTML = rows
    .map((s) => {
      const updated = s.updated_at ? new Date(s.updated_at).toLocaleDateString() : '—';
      return `
      <tr class="border-b border-[--line] last:border-0 hover:bg-paper cursor-pointer source-row" data-doc-id="${escapeHtml(s.document_id)}">
        <td class="px-4 py-3 font-medium max-w-xs truncate">${escapeHtml(s.title || 'Untitled')}</td>
        <td class="px-4 py-3 text-[--ink-faint] max-w-xs truncate">${escapeHtml(s.url || '')}</td>
        <td class="px-4 py-3 tabular-nums">${s.word_count ?? '—'}</td>
        <td class="px-4 py-3">${statusPill(s.status)}</td>
        <td class="px-4 py-3 text-[--ink-faint]">${updated}</td>
      </tr>`;
    })
    .join('');

  tbody.querySelectorAll('.source-row').forEach((row) => {
    row.addEventListener('click', () => {
      const docId = row.dataset.docId;
      window.location.href = `/source.html?workspace=${encodeURIComponent(workspaceId)}&doc=${encodeURIComponent(docId)}`;
    });
  });
}

async function init() {
  if (!workspaceId) {
    errorBanner.textContent = 'No workspace ID was provided in the URL.';
    errorBanner.classList.remove('hidden');
    tbody.innerHTML = '';
    return;
  }
  wsLink.href = `/workspace.html?id=${encodeURIComponent(workspaceId)}`;

  try {
    const ws = await getWorkspace(workspaceId);
    wsLink.textContent = ws.title || ws.root_url || 'Workspace';
  } catch (_) {}

  try {
    allSources = (await getSources(workspaceId)) || [];
    render();
  } catch (err) {
    errorBanner.textContent = `Unable to load sources: ${err.message}`;
    errorBanner.classList.remove('hidden');
    tbody.innerHTML = '';
  }
}

searchInput.addEventListener('input', render);
sortSelect.addEventListener('change', render);

init();
