import { listWorkspaces, deleteWorkspace } from './api.js';

const grid = document.getElementById('workspace-grid');
const countLabel = document.getElementById('count-label');
const errorBanner = document.getElementById('error-banner');

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str ?? '';
  return div.innerHTML;
}

function statusBadge(status) {
  const map = {
    ready: 'bg-[--accent-soft] text-accent',
    crawling: 'bg-[--amber-soft] text-[--amber]',
    extracting: 'bg-[--amber-soft] text-[--amber]',
    processing: 'bg-[--amber-soft] text-[--amber]',
    embedding: 'bg-[--amber-soft] text-[--amber]',
    error: 'bg-[--red-soft] text-[--red]',
  };
  const cls = map[status] || 'bg-neutral-100 text-neutral-600';
  return `<span class="text-[11px] font-medium px-2 py-0.5 rounded ${cls}">${escapeHtml(status || 'unknown')}</span>`;
}

function card(w) {
  const id = w.workspace_id || w.id;
  const title = w.title || w.root_url || 'Untitled workspace';
  const created = w.created_at ? new Date(w.created_at).toLocaleDateString() : '';
  return `
  <div class="relative group border border-[--line] rounded-md p-4 bg-white hover:border-[--line-strong] transition-colors">
    <a href="/workspace.html?id=${encodeURIComponent(id)}" class="block">
      <div class="flex items-start justify-between gap-2">
        <p class="font-medium text-sm leading-snug line-clamp-2 pr-6">${escapeHtml(title)}</p>
        ${statusBadge(w.status)}
      </div>
      <p class="mt-1.5 text-xs text-[--ink-faint] truncate">${escapeHtml(w.root_url || '')}</p>
      <div class="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-[--ink-soft]">
        <span>${w.pages_processed ?? 0} pages</span>
        <span>${w.chunks_created ?? 0} chunks</span>
        <span>${(w.topics || []).length} topics</span>
      </div>
      ${created ? `<p class="mt-2 text-[11px] text-[--ink-faint]">Created ${created}</p>` : ''}
    </a>
    <button data-id="${escapeHtml(id)}" class="delete-btn absolute top-3 right-3 text-[--ink-faint] hover:text-[--red] transition-colors text-xs min-w-[44px] min-h-[44px] flex items-center justify-center -m-2" title="Delete workspace" aria-label="Delete workspace">
      ✕
    </button>
  </div>`;
}

async function load() {
  try {
    const workspaces = await listWorkspaces();
    countLabel.textContent = workspaces.length ? `${workspaces.length} workspace${workspaces.length === 1 ? '' : 's'}` : '';

    if (!workspaces.length) {
      grid.innerHTML = '<p class="text-sm text-[--ink-faint] col-span-full">Your research workspace is empty. <a href="/index.html" class="text-accent hover:underline">Create one</a> to get started.</p>';
      return;
    }

    grid.innerHTML = workspaces.map(card).join('');

    grid.querySelectorAll('.delete-btn').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const id = btn.dataset.id;
        if (!confirm('Delete this workspace and all its indexed data? This cannot be undone.')) return;
        btn.disabled = true;
        try {
          await deleteWorkspace(id);
          load();
        } catch (err) {
          errorBanner.textContent = err.message;
          errorBanner.classList.remove('hidden');
          btn.disabled = false;
        }
      });
    });
  } catch (err) {
    errorBanner.textContent = `Unable to load workspaces: ${err.message}`;
    errorBanner.classList.remove('hidden');
    grid.innerHTML = '';
  }
}

load();
