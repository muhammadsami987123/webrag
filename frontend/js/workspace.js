import * as api from './api.js';
import { streamGetSSE, streamPostSSE } from './sse.js';

const params = new URLSearchParams(location.search);
const workspaceId = params.get('id');

// ---- DOM refs ----
const wsTitle = document.getElementById('ws-title');
const wsStatusBadge = document.getElementById('ws-status-badge');
const wsStats = document.getElementById('ws-stats');
const errorBanner = document.getElementById('error-banner');
const reindexBtn = document.getElementById('reindex-btn');
const debugToggle = document.getElementById('debug-toggle');

const progressView = document.getElementById('progress-view');
const progressUrl = document.getElementById('progress-url');
const stepperEl = document.getElementById('stepper');
const statDiscovered = document.getElementById('stat-discovered');
const statProcessed = document.getElementById('stat-processed');
const statChunks = document.getElementById('stat-chunks');
const statEmbeddings = document.getElementById('stat-embeddings');
const barPages = document.getElementById('bar-pages');
const barEmbed = document.getElementById('bar-embed');
const progressStatusLine = document.getElementById('progress-status-line');

const mainView = document.getElementById('main-view');
const sourcesList = document.getElementById('sources-list');
const sourcesCount = document.getElementById('sources-count');
const topicsList = document.getElementById('topics-list');
const scopeAllBtn = document.getElementById('scope-all');
const scopeSelectedBtn = document.getElementById('scope-selected');
const conversationEl = document.getElementById('conversation');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const chatSend = document.getElementById('chat-send');
const citationsPanel = document.getElementById('citations-panel');
const modeSelector = document.getElementById('mode-selector');

const leftPanel = document.getElementById('left-panel');
const rightPanel = document.getElementById('right-panel');
const scrim = document.getElementById('scrim');

if (!workspaceId) {
  showFatalError('No workspace ID was provided in the URL.');
}

// ---- State ----
let state = {
  workspace: null,
  sources: [],
  selectedSourceIds: new Set(),
  scope: 'all', // 'all' | 'selected'
  mode: 'ask',
  debug: false,
  lastCitations: [],
};

const STEPS = ['crawling', 'extracting', 'processing', 'embedding', 'ready'];

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str ?? '';
  return div.innerHTML;
}

function showFatalError(msg) {
  errorBanner.textContent = msg;
  errorBanner.classList.remove('hidden');
}

function statusBadgeClass(status) {
  const map = {
    ready: 'bg-[--accent-soft] text-accent',
    crawling: 'bg-[--amber-soft] text-[--amber]',
    extracting: 'bg-[--amber-soft] text-[--amber]',
    processing: 'bg-[--amber-soft] text-[--amber]',
    embedding: 'bg-[--amber-soft] text-[--amber]',
    error: 'bg-[--red-soft] text-[--red]',
  };
  return map[status] || 'bg-neutral-100 text-neutral-600';
}

function renderTopBar(ws) {
  wsTitle.textContent = ws.title || ws.root_url || 'Untitled workspace';
  wsStatusBadge.textContent = ws.status || 'unknown';
  wsStatusBadge.className = `text-[11px] font-medium px-2 py-0.5 rounded shrink-0 ${statusBadgeClass(ws.status)}`;
  wsStats.innerHTML = `
    <span>${ws.pages_processed ?? 0} pages</span>
    <span>${ws.chunks_created ?? 0} chunks</span>
    <span>${ws.embeddings_created ?? 0} embeddings</span>
    <span>${(ws.topics || []).length} topics</span>
  `;
}

// ---- Progress / crawl view ----
function renderStepper(currentStatus) {
  const idx = STEPS.indexOf((currentStatus || '').toLowerCase());
  stepperEl.innerHTML = STEPS.map((step, i) => {
    const done = idx >= 0 && i < idx;
    const active = i === idx;
    const circleCls = done
      ? 'bg-accent text-white border-accent'
      : active
      ? 'border-accent text-accent bg-[--accent-soft]'
      : 'border-[--line-strong] text-[--ink-faint]';
    const labelCls = active ? 'text-ink font-medium' : 'text-[--ink-faint]';
    return `
      <li class="flex items-center gap-2 ${i < STEPS.length - 1 ? 'flex-1' : ''}">
        <span class="w-6 h-6 rounded-full border flex items-center justify-center text-[11px] shrink-0 ${circleCls}">${i + 1}</span>
        <span class="text-xs ${labelCls} capitalize whitespace-nowrap">${step}</span>
        ${i < STEPS.length - 1 ? '<span class="flex-1 h-px bg-[--line]"></span>' : ''}
      </li>`;
  }).join('');
}

function updateProgress(data) {
  const discovered = data.pages_discovered ?? 0;
  const processed = data.pages_processed ?? 0;
  const chunks = data.chunks_created ?? 0;
  const embeddings = data.embeddings_created ?? 0;

  statDiscovered.textContent = discovered;
  statProcessed.textContent = processed;
  statChunks.textContent = chunks;
  statEmbeddings.textContent = embeddings;

  barPages.style.width = discovered > 0 ? `${Math.min(100, (processed / discovered) * 100)}%` : '0%';
  barEmbed.style.width = chunks > 0 ? `${Math.min(100, (embeddings / chunks) * 100)}%` : '0%';

  renderStepper(data.status);
  progressStatusLine.textContent = `Status: ${data.status || 'working'}…`;

  if ((data.status || '').toLowerCase() === 'ready') {
    finishIndexing();
  }
}

let progressCancel = null;

async function watchProgress() {
  progressView.classList.remove('hidden');
  mainView.classList.add('hidden');
  progressUrl.textContent = state.workspace.root_url || '';
  renderStepper(state.workspace.status);
  updateProgress(state.workspace);

  progressCancel = streamGetSSE(
    api.progressStreamUrl(workspaceId),
    (data) => updateProgress(data),
    (err) => {
      progressStatusLine.textContent = `Connection lost: ${err.message}. Retrying…`;
      setTimeout(pollFallback, 3000);
    }
  );
}

async function pollFallback() {
  try {
    const ws = await api.getWorkspace(workspaceId);
    state.workspace = ws;
    updateProgress(ws);
    if ((ws.status || '').toLowerCase() !== 'ready') {
      setTimeout(pollFallback, 4000);
    }
  } catch (_) {
    setTimeout(pollFallback, 5000);
  }
}

async function finishIndexing() {
  if (progressCancel) progressCancel();
  try {
    state.workspace = await api.getWorkspace(workspaceId);
  } catch (_) {}
  renderTopBar(state.workspace);
  progressView.classList.add('hidden');
  mainView.classList.remove('hidden');
  await loadWorkspaceData();
}

// ---- Sources & Topics ----
async function loadSources() {
  try {
    state.sources = (await api.getSources(workspaceId)) || [];
  } catch (err) {
    sourcesList.innerHTML = `<p class="text-xs text-[--red]">Unable to load sources: ${escapeHtml(err.message)}</p>`;
    return;
  }
  sourcesCount.textContent = `${state.sources.length} pages`;
  if (!state.sources.length) {
    sourcesList.innerHTML = '<p class="text-xs text-[--ink-faint]">No sources indexed yet.</p>';
    return;
  }
  sourcesList.innerHTML = state.sources
    .map((s) => {
      const id = s.document_id;
      return `
      <label class="flex items-start gap-2 py-1.5 px-1.5 rounded hover:bg-white cursor-pointer group">
        <input type="checkbox" data-doc-id="${escapeHtml(id)}" class="source-checkbox mt-0.5 w-3.5 h-3.5 accent-[--accent] shrink-0" />
        <span class="min-w-0 flex-1">
          <span class="block text-xs font-medium text-ink truncate">${escapeHtml(s.title || s.url || 'Untitled')}</span>
          <span class="block text-[11px] text-[--ink-faint] truncate">${escapeHtml(s.word_count ?? 0)} words</span>
        </span>
      </label>`;
    })
    .join('');

  sourcesList.querySelectorAll('.source-checkbox').forEach((cb) => {
    cb.addEventListener('change', () => {
      const id = cb.dataset.docId;
      if (cb.checked) state.selectedSourceIds.add(id);
      else state.selectedSourceIds.delete(id);
    });
  });
}

async function loadTopics() {
  try {
    const topics = (await api.getTopics(workspaceId)) || [];
    if (!topics.length) {
      topicsList.innerHTML = '<p class="text-xs text-[--ink-faint]">No topics identified yet.</p>';
      return;
    }
    topicsList.innerHTML = topics
      .map((t) => `<button data-topic="${escapeHtml(t)}" class="topic-chip px-2.5 py-1.5 rounded-full border border-[--line-strong] text-xs bg-white hover:border-accent hover:text-accent transition-colors min-h-[32px]">${escapeHtml(t)}</button>`)
      .join('');
    topicsList.querySelectorAll('.topic-chip').forEach((chip) => {
      chip.addEventListener('click', () => searchTopic(chip.dataset.topic));
    });
  } catch (err) {
    topicsList.innerHTML = `<p class="text-xs text-[--red]">Unable to load topics.</p>`;
  }
}

async function searchTopic(topic) {
  citationsPanel.innerHTML = `<p class="text-xs text-[--ink-faint]">Searching “${escapeHtml(topic)}”…</p>`;
  openRightDrawer();
  try {
    const results = (await api.search(workspaceId, topic)) || [];
    if (!results.length) {
      citationsPanel.innerHTML = '<p class="text-sm text-[--ink-faint]">No relevant source sections were found.</p>';
      return;
    }
    citationsPanel.innerHTML =
      `<p class="text-xs font-medium text-[--ink-faint] mb-1">Results for “${escapeHtml(topic)}”</p>` +
      results
        .map(
          (r) => `
        <div class="border border-[--line] rounded-md p-3 bg-white">
          <p class="text-xs font-medium truncate">${escapeHtml(r.source || '')}</p>
          <p class="text-[11px] text-[--ink-faint] mb-1.5">${escapeHtml(r.section || '')}</p>
          <p class="text-xs text-[--ink-soft] leading-relaxed">${escapeHtml(r.snippet || '')}</p>
          ${r.score !== undefined ? `<p class="text-[11px] text-[--ink-faint] mt-1.5">Score: ${Number(r.score).toFixed(2)}</p>` : ''}
        </div>`
        )
        .join('');
  } catch (err) {
    citationsPanel.innerHTML = `<p class="text-sm text-[--red]">${escapeHtml(err.message)}</p>`;
  }
}

// ---- Scope toggle ----
function setScope(scope) {
  state.scope = scope;
  const activeCls = ['bg-accent', 'text-white'];
  scopeAllBtn.classList.remove(...activeCls);
  scopeSelectedBtn.classList.remove(...activeCls);
  scopeAllBtn.classList.remove('text-[--ink-soft]');
  scopeSelectedBtn.classList.remove('text-[--ink-soft]');
  if (scope === 'all') {
    scopeAllBtn.classList.add(...activeCls);
    scopeSelectedBtn.classList.add('text-[--ink-soft]');
  } else {
    scopeSelectedBtn.classList.add(...activeCls);
    scopeAllBtn.classList.add('text-[--ink-soft]');
  }
}
scopeAllBtn.addEventListener('click', () => setScope('all'));
scopeSelectedBtn.addEventListener('click', () => setScope('selected'));

// ---- Mode selector ----
function setMode(mode) {
  state.mode = mode;
  modeSelector.querySelectorAll('.mode-btn').forEach((btn) => {
    if (btn.dataset.mode === mode) {
      btn.classList.add('bg-accent', 'text-white');
      btn.classList.remove('text-[--ink-soft]');
    } else {
      btn.classList.remove('bg-accent', 'text-white');
      btn.classList.add('text-[--ink-soft]');
    }
  });
}
modeSelector.querySelectorAll('.mode-btn').forEach((btn) => {
  btn.addEventListener('click', () => setMode(btn.dataset.mode));
});

// ---- Tabs (Notes / Highlights / Collections) ----
document.querySelectorAll('.tab-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach((b) => {
      b.classList.remove('border-accent', 'text-ink');
      b.classList.add('border-transparent', 'text-[--ink-faint]');
    });
    btn.classList.add('border-accent', 'text-ink');
    btn.classList.remove('border-transparent', 'text-[--ink-faint]');
    document.querySelectorAll('.tab-panel').forEach((p) => p.classList.add('hidden'));
    document.getElementById(`tab-${btn.dataset.tab}`).classList.remove('hidden');
  });
});

async function loadSidePanels() {
  const notesEl = document.getElementById('tab-notes');
  const highlightsEl = document.getElementById('tab-highlights');
  const collectionsEl = document.getElementById('tab-collections');

  notesEl.innerHTML = `
    <form id="note-form" class="flex gap-1.5 mb-2">
      <input id="note-input" type="text" placeholder="Add a note…" class="flex-1 min-w-0 px-2.5 py-2 text-xs rounded border border-[--line-strong] bg-white focus:outline-none focus:ring-1 focus:ring-accent" />
      <button type="submit" class="px-2.5 py-2 rounded bg-accent text-white text-xs min-h-[36px]">Add</button>
    </form>
    <div id="notes-items" class="space-y-1.5"></div>`;

  document.getElementById('note-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const input = document.getElementById('note-input');
    const content = input.value.trim();
    if (!content) return;
    try {
      await api.postNote(workspaceId, content);
      input.value = '';
      renderNotes();
    } catch (err) {
      showFatalError(err.message);
    }
  });

  async function renderNotes() {
    try {
      const notes = (await api.getNotes(workspaceId)) || [];
      const itemsEl = document.getElementById('notes-items');
      itemsEl.innerHTML = notes.length
        ? notes.map((n) => `<div class="text-xs bg-white border border-[--line] rounded px-2.5 py-2">${escapeHtml(n.content || n)}</div>`).join('')
        : '<p class="text-xs text-[--ink-faint]">No notes yet.</p>';
    } catch (_) {
      document.getElementById('notes-items').innerHTML = '<p class="text-xs text-[--ink-faint]">No notes yet.</p>';
    }
  }
  renderNotes();

  try {
    const highlights = (await api.getHighlights(workspaceId)) || [];
    highlightsEl.innerHTML = highlights.length
      ? highlights.map((h) => `<div class="text-xs bg-white border border-[--line] rounded px-2.5 py-2">${escapeHtml(h.text || h.content || JSON.stringify(h))}</div>`).join('')
      : '<p class="text-xs text-[--ink-faint]">No highlights yet.</p>';
  } catch (_) {
    highlightsEl.innerHTML = '<p class="text-xs text-[--ink-faint]">No highlights yet.</p>';
  }

  try {
    const collections = (await api.getCollections(workspaceId)) || [];
    collectionsEl.innerHTML = collections.length
      ? collections.map((c) => `<div class="text-xs bg-white border border-[--line] rounded px-2.5 py-2">${escapeHtml(c.name || c.title || JSON.stringify(c))}</div>`).join('')
      : '<p class="text-xs text-[--ink-faint]">No collections yet.</p>';
  } catch (_) {
    collectionsEl.innerHTML = '<p class="text-xs text-[--ink-faint]">No collections yet.</p>';
  }
}

// ---- Mobile drawers ----
function openLeftDrawer() {
  leftPanel.classList.remove('drawer-hidden-left');
  scrim.classList.remove('hidden');
}
function closeLeftDrawer() {
  leftPanel.classList.add('drawer-hidden-left');
  scrim.classList.add('hidden');
}
function openRightDrawer() {
  if (window.innerWidth >= 1024) return; // already visible on desktop
  rightPanel.classList.remove('drawer-hidden-right');
  scrim.classList.remove('hidden');
}
function closeRightDrawer() {
  rightPanel.classList.add('drawer-hidden-right');
  scrim.classList.add('hidden');
}
document.getElementById('open-left-drawer').addEventListener('click', openLeftDrawer);
document.getElementById('close-left-drawer').addEventListener('click', closeLeftDrawer);
document.getElementById('open-right-drawer').addEventListener('click', openRightDrawer);
document.getElementById('close-right-drawer').addEventListener('click', closeRightDrawer);
scrim.addEventListener('click', () => {
  closeLeftDrawer();
  closeRightDrawer();
});

// ---- Debug toggle ----
debugToggle.addEventListener('change', () => {
  state.debug = debugToggle.checked;
  renderCitations(state.lastCitations, state.lastGrounding);
});

// ---- Reindex ----
reindexBtn.addEventListener('click', async () => {
  reindexBtn.disabled = true;
  reindexBtn.textContent = 'Re-indexing…';
  try {
    await api.reindexWorkspace(workspaceId);
    state.workspace = await api.getWorkspace(workspaceId);
    renderTopBar(state.workspace);
    await watchProgress();
  } catch (err) {
    showFatalError(err.message);
  } finally {
    reindexBtn.disabled = false;
    reindexBtn.textContent = 'Re-index';
  }
});

// ---- Minimal markdown-lite renderer for compare/extract tables ----
function renderMarkdownLite(text) {
  if (!text) return '';
  const blocks = text.split(/\n\s*\n/);
  return blocks
    .map((block) => {
      const lines = block.split('\n').filter((l) => l.trim().length);
      const isTable = lines.length >= 2 && lines[0].includes('|') && /^[\s|:-]+$/.test(lines[1]);
      if (isTable) {
        const headerCells = lines[0].split('|').map((c) => c.trim()).filter(Boolean);
        const rows = lines.slice(2).map((l) => l.split('|').map((c) => c.trim()).filter(Boolean));
        return `<div class="overflow-x-auto"><table class="w-full text-xs border-collapse my-2">
          <thead><tr>${headerCells.map((h) => `<th class="text-left border-b border-[--line-strong] px-2 py-1.5 font-medium">${escapeHtml(h)}</th>`).join('')}</tr></thead>
          <tbody>${rows.map((r) => `<tr>${r.map((c) => `<td class="border-b border-[--line] px-2 py-1.5 align-top">${escapeHtml(c)}</td>`).join('')}</tr>`).join('')}</tbody>
        </table></div>`;
      }
      const escaped = escapeHtml(block).replace(/\n/g, '<br>');
      return `<p class="leading-relaxed">${escaped}</p>`;
    })
    .join('');
}

// ---- Citation markers -> pills ----
function renderAnswerHtml(answerText, citations) {
  const validIndices = new Set((citations || []).map((c) => c.index));
  const withTables = renderMarkdownLite(answerText);
  return withTables.replace(/\[(\d+)\]/g, (match, num) => {
    const n = Number(num);
    if (!validIndices.has(n)) return match;
    return `<button type="button" class="citation-pill" data-cite-index="${n}">${n}</button>`;
  });
}

function groundingBadge(grounding) {
  if (!grounding) return '';
  const g = String(grounding).toLowerCase();
  if (g.includes('insufficient') || g.includes('low')) {
    return `<div class="mt-2.5 px-3 py-2 rounded-md bg-[--amber-soft] text-[--amber] text-xs leading-relaxed">Insufficient evidence in the indexed sources — this answer may be incomplete.</div>`;
  }
  const label = g.includes('high') ? 'High grounding' : g.includes('moderate') ? 'Moderate grounding' : escapeHtml(grounding);
  return `<div class="mt-2.5 inline-flex items-center gap-1.5 text-[11px] text-[--ink-faint]"><span class="w-1.5 h-1.5 rounded-full bg-accent"></span>${label}</div>`;
}

// ---- Conversation rendering ----
function clearEmptyState() {
  const empty = document.getElementById('empty-state');
  if (empty) empty.remove();
}

function addUserMessage(text) {
  clearEmptyState();
  const el = document.createElement('div');
  el.className = 'rise-in flex justify-end';
  el.innerHTML = `<div class="max-w-[80%] bg-accent text-white text-sm rounded-md px-4 py-2.5 leading-relaxed">${escapeHtml(text)}</div>`;
  conversationEl.appendChild(el);
  conversationEl.scrollTop = conversationEl.scrollHeight;
  return el;
}

function addAssistantPlaceholder() {
  const el = document.createElement('div');
  el.className = 'rise-in flex justify-start';
  el.innerHTML = `<div class="max-w-[85%] w-full border border-[--line] bg-white rounded-md px-4 py-3">
      <p class="assistant-text text-sm leading-relaxed text-[--ink-soft] stream-cursor"></p>
    </div>`;
  conversationEl.appendChild(el);
  conversationEl.scrollTop = conversationEl.scrollHeight;
  return el.querySelector('.assistant-text');
}

function addErrorMessage(text) {
  clearEmptyState();
  const el = document.createElement('div');
  el.className = 'rise-in flex justify-start';
  el.innerHTML = `<div class="max-w-[85%] border border-[--red-soft] bg-[--red-soft] text-[--red] text-sm rounded-md px-4 py-2.5 leading-relaxed">${escapeHtml(text)}</div>`;
  conversationEl.appendChild(el);
  conversationEl.scrollTop = conversationEl.scrollHeight;
}

// ---- Citations panel ----
function renderCitations(citations, grounding) {
  state.lastCitations = citations || [];
  state.lastGrounding = grounding;

  if (!citations || !citations.length) {
    citationsPanel.innerHTML = '<p class="text-sm text-[--ink-faint]">Retrieved sources for the last answer will appear here.</p>';
    return;
  }

  citationsPanel.innerHTML = citations
    .map((c) => {
      const scoreLine = state.debug
        ? `<div class="mt-2 pt-2 border-t border-[--line] text-[11px] text-[--ink-faint] space-y-0.5">
            ${c.score !== undefined ? `<div>Similarity: ${Number(c.score).toFixed(3)}</div>` : ''}
            ${c.keyword_score !== undefined ? `<div>Keyword: ${Number(c.keyword_score).toFixed(3)}</div>` : ''}
            ${c.rerank_score !== undefined ? `<div>Rerank: ${Number(c.rerank_score).toFixed(3)}</div>` : ''}
          </div>`
        : '';
      return `
      <div id="citation-card-${c.index}" class="border border-[--line] rounded-md p-3 bg-white">
        <div class="flex items-start justify-between gap-2">
          <p class="text-xs font-semibold">[${c.index}] ${escapeHtml(c.title || 'Untitled source')}</p>
          ${c.score !== undefined && !state.debug ? `<span class="text-[10px] text-[--ink-faint] shrink-0">${Number(c.score).toFixed(2)}</span>` : ''}
        </div>
        ${c.section ? `<p class="text-[11px] text-[--ink-faint] mt-0.5">${escapeHtml(c.section)}</p>` : ''}
        ${c.url ? `<a href="${escapeHtml(c.url)}" target="_blank" rel="noopener noreferrer" class="inline-block mt-2 text-xs text-accent hover:underline">Open Original &rarr;</a>` : ''}
        ${scoreLine}
      </div>`;
    })
    .join('');
}

conversationEl.addEventListener('click', (e) => {
  const pill = e.target.closest('[data-cite-index]');
  if (!pill) return;
  const idx = pill.dataset.citeIndex;
  const card = document.getElementById(`citation-card-${idx}`);
  if (!card) return;
  openRightDrawer();
  card.scrollIntoView({ behavior: 'smooth', block: 'center' });
  card.classList.remove('flash-highlight');
  void card.offsetWidth;
  card.classList.add('flash-highlight');
});

// ---- Empty state + suggestions ----
async function renderEmptyState() {
  conversationEl.innerHTML = '';
  let suggestions = [];
  try {
    suggestions = (await api.getSuggestions(workspaceId)) || [];
  } catch (_) {}

  const el = document.createElement('div');
  el.id = 'empty-state';
  el.className = 'h-full flex flex-col items-center justify-center text-center px-6';
  el.innerHTML = `
    <p class="font-serif-edit text-lg text-ink mb-2">Ask your first question about this website.</p>
    <p class="text-sm text-[--ink-faint] mb-6">Answers are grounded in the indexed content, with citations.</p>
    <div id="suggestion-chips" class="flex flex-wrap justify-center gap-2 max-w-lg"></div>
  `;
  conversationEl.appendChild(el);

  const chipsEl = el.querySelector('#suggestion-chips');
  if (suggestions.length) {
    chipsEl.innerHTML = suggestions
      .map((s) => `<button class="suggestion-chip px-3 py-2 rounded-full border border-[--line-strong] bg-white text-xs hover:border-accent hover:text-accent transition-colors min-h-[36px]">${escapeHtml(s)}</button>`)
      .join('');
    chipsEl.querySelectorAll('.suggestion-chip').forEach((chip) => {
      chip.addEventListener('click', () => {
        chatInput.value = chip.textContent;
        chatInput.focus();
      });
    });
  }
}

// ---- Chat history ----
async function loadHistory() {
  try {
    const history = (await api.getChatHistory(workspaceId)) || [];
    if (!history.length) {
      await renderEmptyState();
      return;
    }
    conversationEl.innerHTML = '';
    history.forEach((msg) => {
      if (msg.role === 'user') {
        addUserMessage(msg.content || msg.message || '');
      } else {
        const target = addAssistantPlaceholder();
        target.classList.remove('stream-cursor', 'text-[--ink-soft]');
        target.classList.add('text-ink');
        target.innerHTML = renderAnswerHtml(msg.content || msg.answer || '', msg.citations || []);
      }
    });
  } catch (_) {
    await renderEmptyState();
  }
}

// ---- Sending a message ----
let sending = false;

chatForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (sending) return;
  const message = chatInput.value.trim();
  if (!message) return;

  sending = true;
  chatSend.disabled = true;
  chatInput.value = '';
  autoGrow();

  addUserMessage(message);
  const target = addAssistantPlaceholder();

  const body = {
    workspace_id: workspaceId,
    message,
    mode: state.mode,
    conversation_id: 'default',
  };
  if (state.scope === 'selected' && state.selectedSourceIds.size) {
    body.source_ids = Array.from(state.selectedSourceIds);
  }

  let accumulated = '';
  let finished = false;

  streamPostSSE(
    api.chatStreamEndpoint(),
    body,
    (evt) => {
      if (evt && typeof evt === 'object' && 'delta' in evt) {
        accumulated += evt.delta;
        target.textContent = accumulated;
        conversationEl.scrollTop = conversationEl.scrollHeight;
      } else if (evt && typeof evt === 'object' && evt.done) {
        finished = true;
        target.classList.remove('stream-cursor', 'text-[--ink-soft]');
        target.classList.add('text-ink');
        const finalText = evt.answer || accumulated;
        target.innerHTML = renderAnswerHtml(finalText, evt.citations || []);
        target.parentElement.insertAdjacentHTML('beforeend', groundingBadge(evt.grounding));
        renderCitations(evt.citations || [], evt.grounding);
        sending = false;
        chatSend.disabled = false;
        conversationEl.scrollTop = conversationEl.scrollHeight;
      }
    },
    (err) => {
      if (!finished) {
        target.parentElement.remove();
        addErrorMessage(err.message || 'Unable to reach the server. Please try again.');
      }
      sending = false;
      chatSend.disabled = false;
    }
  );
});

chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    chatForm.requestSubmit();
  }
});
function autoGrow() {
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + 'px';
}
chatInput.addEventListener('input', autoGrow);

// ---- Init ----
async function loadWorkspaceData() {
  await Promise.all([loadSources(), loadTopics(), loadSidePanels(), loadHistory()]);
}

setScope('all');
setMode('ask');

(async () => {
  if (!workspaceId) return;
  try {
    state.workspace = await api.getWorkspace(workspaceId);
  } catch (err) {
    showFatalError(`Unable to load this workspace: ${err.message}`);
    return;
  }
  renderTopBar(state.workspace);

  const status = (state.workspace.status || '').toLowerCase();
  if (status === 'ready') {
    mainView.classList.remove('hidden');
    await loadWorkspaceData();
  } else if (status === 'error') {
    showFatalError(state.workspace.error || 'Indexing failed for this workspace.');
    progressView.classList.remove('hidden');
    progressUrl.textContent = state.workspace.root_url || '';
    renderStepper('error');
    progressStatusLine.textContent = 'Indexing failed. You can try re-indexing from the top bar.';
  } else {
    await watchProgress();
  }
})();
