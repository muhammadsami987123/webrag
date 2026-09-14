import { createWorkspace, listWorkspaces } from './api.js';

const form = document.getElementById('create-form');
const urlInput = document.getElementById('url-input');
const submitBtn = document.getElementById('submit-btn');
const formError = document.getElementById('form-error');
const recentEl = document.getElementById('recent-workspaces');

function isValidHttpUrl(value) {
  try {
    const u = new URL(value);
    return u.protocol === 'http:' || u.protocol === 'https:';
  } catch (_) {
    return false;
  }
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  formError.classList.add('hidden');
  const url = urlInput.value.trim();

  if (!isValidHttpUrl(url)) {
    formError.textContent = 'Please enter a valid public HTTP/HTTPS URL.';
    formError.classList.remove('hidden');
    return;
  }

  submitBtn.disabled = true;
  submitBtn.textContent = 'Building…';

  try {
    const workspace = await createWorkspace(url);
    const id = workspace.workspace_id || workspace.id;
    if (!id) throw new Error('Workspace was created but no ID was returned.');
    window.location.href = `/workspace.html?id=${encodeURIComponent(id)}`;
  } catch (err) {
    formError.textContent = err.message || 'Unable to reach this website. Please try again.';
    formError.classList.remove('hidden');
    submitBtn.disabled = false;
    submitBtn.textContent = 'Build Knowledge Base';
  }
});

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
  return `<span class="text-[11px] font-medium px-2 py-0.5 rounded ${cls}">${status || 'unknown'}</span>`;
}

async function loadRecent() {
  try {
    const workspaces = await listWorkspaces();
    if (!workspaces || !workspaces.length) {
      recentEl.innerHTML = '<p class="text-sm text-[--ink-faint] col-span-full">Your research workspace is empty. Paste a URL above to get started.</p>';
      return;
    }
    recentEl.innerHTML = workspaces
      .slice(0, 6)
      .map((w) => {
        const id = w.workspace_id || w.id;
        const title = w.title || w.root_url || 'Untitled workspace';
        return `
        <a href="/workspace.html?id=${encodeURIComponent(id)}" class="block border border-[--line] rounded-md p-4 bg-white hover:border-[--line-strong] transition-colors">
          <div class="flex items-start justify-between gap-2">
            <p class="font-medium text-sm leading-snug line-clamp-2">${escapeHtml(title)}</p>
            ${statusBadge(w.status)}
          </div>
          <p class="mt-1.5 text-xs text-[--ink-faint] truncate">${escapeHtml(w.root_url || '')}</p>
          <p class="mt-3 text-xs text-[--ink-soft]">${w.pages_processed ?? 0} pages · ${w.chunks_created ?? 0} chunks</p>
        </a>`;
      })
      .join('');
  } catch (err) {
    recentEl.innerHTML = `<p class="text-sm text-[--red] col-span-full">Unable to load workspaces: ${escapeHtml(err.message)}</p>`;
  }
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str ?? '';
  return div.innerHTML;
}

loadRecent();
