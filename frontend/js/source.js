import { getSource } from './api.js';

const params = new URLSearchParams(location.search);
const workspaceId = params.get('workspace');
const docId = params.get('doc');

const errorBanner = document.getElementById('error-banner');
const article = document.getElementById('source-article');
const loadingMsg = document.getElementById('loading-msg');
const sourcesLink = document.getElementById('sources-link');

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str ?? '';
  return div.innerHTML;
}

function paragraphize(content) {
  if (!content) return '<p class="text-[--ink-faint]">No extracted content available.</p>';
  return content
    .split(/\n\s*\n/)
    .filter((p) => p.trim())
    .map((p) => `<p>${escapeHtml(p)}</p>`)
    .join('');
}

async function init() {
  if (!workspaceId || !docId) {
    errorBanner.textContent = 'Missing workspace or document ID in the URL.';
    errorBanner.classList.remove('hidden');
    loadingMsg.classList.add('hidden');
    return;
  }
  sourcesLink.href = `/sources.html?workspace=${encodeURIComponent(workspaceId)}`;

  try {
    const src = await getSource(workspaceId, docId);
    loadingMsg.classList.add('hidden');
    article.classList.remove('hidden');

    document.title = `WebRAG — ${src.title || 'Source'}`;
    document.getElementById('src-title').textContent = src.title || 'Untitled source';
    document.getElementById('src-url').textContent = src.url || '';
    document.getElementById('src-words').textContent = `${src.word_count ?? 0} words`;
    document.getElementById('src-updated').textContent = src.updated_at
      ? `Indexed ${new Date(src.updated_at).toLocaleDateString()}`
      : '';
    const openOriginal = document.getElementById('src-open-original');
    openOriginal.href = src.url || '#';

    if (src.headings && src.headings.length) {
      const headingsWrap = document.getElementById('src-headings');
      headingsWrap.classList.remove('hidden');
      const list = document.getElementById('src-headings-list');
      list.innerHTML = src.headings
        .map((h) => `<li class="truncate">${escapeHtml(typeof h === 'string' ? h : h.text || '')}</li>`)
        .join('');
    }

    document.getElementById('src-content').innerHTML = paragraphize(src.content);
  } catch (err) {
    loadingMsg.classList.add('hidden');
    errorBanner.textContent = `Unable to load this source: ${err.message}`;
    errorBanner.classList.remove('hidden');
  }
}

init();
