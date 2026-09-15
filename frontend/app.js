const $ = (id) => document.getElementById(id);
const chatHistory = [];
let sourcesCache = [];
let pollTimer = null;
let busy = false;

const SUGGESTIONS = [
  ["What is this website about?", "Get a quick overview"],
  ["Summarize the key points", "Main ideas in bullets"],
  ["What products or services are offered?", "Features and offerings"],
  ["How can I get in touch?", "Contact details and links"],
];

const ICON_PATHS = {
  url: "M12 21a9 9 0 100-18 9 9 0 000 18zm0 0c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3 7.5 7.03 7.5 12s2.015 9 4.5 9zM3.6 9h16.8M3.6 15h16.8",
  file: "M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z",
  trash: "M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0",
  copy: "M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 01-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 011.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 00-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 01-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 00-3.375-3.375h-1.5",
  check: "M4.5 12.75l6 6 9-13.5",
  alert: "M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z",
  arrow: "M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3",
  external: "M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25",
};

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const icon = (name, cls = "h-4 w-4", sw = 1.8) =>
  `<svg class="${cls}" fill="none" stroke="currentColor" stroke-width="${sw}" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="${ICON_PATHS[name]}"/></svg>`;
const hostOf = (u) => {
  try {
    return new URL(u).hostname.replace(/^www\./, "");
  } catch {
    return u;
  }
};

async function api(path, options = {}) {
  const res = await fetch(path, { cache: "no-store", ...options });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : body.detail?.[0]?.msg || detail;
    } catch {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

// ---------------- Toasts ----------------

function toast(message, type = "info") {
  const styles = {
    info: ["check", "text-emerald-600 dark:text-emerald-400"],
    error: ["alert", "text-red-600 dark:text-red-400"],
  }[type];
  const el = document.createElement("div");
  el.className =
    "pointer-events-auto flex animate-fade-up items-start gap-2.5 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm shadow-soft dark:border-slate-700 dark:bg-slate-900";
  el.setAttribute("role", type === "error" ? "alert" : "status");
  el.innerHTML = `<span class="mt-0.5 ${styles[1]}">${icon(styles[0], "h-4 w-4", 2)}</span><span class="flex-1 text-slate-700 dark:text-slate-200">${esc(message)}</span>`;
  $("toasts").appendChild(el);
  setTimeout(() => {
    el.style.transition = "opacity .2s";
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 200);
  }, 4000);
}

// ---------------- Layout: sidebar, tabs, theme ----------------

function setSidebar(open) {
  $("sidebar").classList.toggle("-translate-x-full", !open);
  $("scrim").hidden = !open;
}
$("openSidebar").onclick = () => setSidebar(true);
$("closeSidebar").onclick = () => setSidebar(false);
$("scrim").onclick = () => setSidebar(false);
document.addEventListener("keydown", (e) => e.key === "Escape" && setSidebar(false));

function selectTab(name) {
  document.querySelectorAll(".tab").forEach((t) => {
    const active = t.dataset.tab === name;
    t.setAttribute("aria-selected", active);
    t.className = t.className.replace(/ ?(bg-white|shadow-sm|text-slate-900|text-slate-500|dark:bg-slate-900|dark:text-white|dark:text-slate-400)/g, "");
    t.classList.add(...(active ? ["bg-white", "shadow-sm", "text-slate-900", "dark:bg-slate-900", "dark:text-white"] : ["text-slate-500", "dark:text-slate-400"]));
  });
  $("panelUrl").hidden = name !== "url";
  $("panelFiles").hidden = name !== "files";
}
document.querySelectorAll(".tab").forEach((t) => (t.onclick = () => selectTab(t.dataset.tab)));
selectTab("url");

$("themeToggle").onclick = () => {
  const dark = document.documentElement.classList.toggle("dark");
  try {
    localStorage.setItem("theme", dark ? "dark" : "light");
  } catch {}
};

$("maxPages").oninput = (e) => ($("maxPagesOut").textContent = e.target.value);

// ---------------- Sources ----------------

function statusLine(s) {
  if (s.status === "processing")
    return `<span class="inline-flex items-center gap-1.5 text-xs font-medium text-brand-600 dark:text-brand-400">
      <svg class="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" opacity=".25"/><path d="M22 12a10 10 0 00-10-10" stroke="currentColor" stroke-width="3" stroke-linecap="round"/></svg>
      ${s.kind === "url" ? "Crawling & indexing…" : "Indexing…"}</span>`;
  if (s.status === "failed")
    return `<span class="flex items-start gap-1 text-xs text-red-600 dark:text-red-400">${icon("alert", "mt-px h-3.5 w-3.5 shrink-0", 2)}<span class="line-clamp-2">${esc(s.error || "Failed")}</span></span>`;
  const pages = s.kind === "url" ? `${s.pages} page${s.pages === 1 ? "" : "s"} · ` : "";
  return `<span class="inline-flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400"><span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>${pages}${s.chunks} chunks</span>`;
}

function renderSources(sources) {
  sourcesCache = sources;
  const ready = sources.filter((s) => s.status === "ready");
  $("sourcesEmpty").hidden = sources.length > 0;
  $("statSources").textContent = sources.length;
  $("statChunks").textContent = ready.reduce((n, s) => n + (s.chunks || 0), 0).toLocaleString();
  $("chatSubtitle").textContent = ready.length
    ? `Grounded in ${ready.length} source${ready.length === 1 ? "" : "s"}`
    : sources.length
      ? "Indexing your sources…"
      : "Add sources to get started";

  $("sourceList").innerHTML = sources
    .map((s) => {
      const isUrl = s.kind === "url";
      const tint = isUrl
        ? "bg-sky-50 text-sky-600 dark:bg-sky-500/10 dark:text-sky-400"
        : "bg-violet-50 text-violet-600 dark:bg-violet-500/10 dark:text-violet-400";
      const title = isUrl ? hostOf(s.name) : s.name;
      return `
      <li class="group flex animate-fade-up items-center gap-3 rounded-xl border border-slate-200 bg-white p-2.5 transition-colors hover:border-slate-300 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-slate-700">
        <span class="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${tint}">${icon(s.kind)}</span>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-medium text-slate-800 dark:text-slate-100" title="${esc(s.name)}">${esc(title)}</p>
          ${statusLine(s)}
        </div>
        ${
          s.id
            ? `<button data-delete="${esc(s.id)}" aria-label="Remove ${esc(title)}"
          class="flex h-9 w-9 shrink-0 cursor-pointer items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-red-50 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500 dark:hover:bg-red-500/10 dark:hover:text-red-400">
          ${icon("trash")}</button>`
            : ""
        }
      </li>`;
    })
    .join("");
}

async function loadSources() {
  try {
    const sources = await api("/api/sources");
    const wasProcessing = sourcesCache.filter((s) => s.status === "processing" && s.id).map((s) => s.id);
    renderSources(sources);
    for (const s of sources) {
      if (!wasProcessing.includes(s.id)) continue;
      if (s.status === "ready") toast(`${s.kind === "url" ? hostOf(s.name) : s.name} is ready — ${s.chunks} chunks indexed`);
      if (s.status === "failed") toast(`${s.kind === "url" ? hostOf(s.name) : s.name}: ${s.error}`, "error");
    }
    clearTimeout(pollTimer);
    if (sources.some((s) => s.status === "processing")) pollTimer = setTimeout(loadSources, 2000);
  } catch (e) {
    console.error(e);
  }
}

$("sourceList").addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-delete]");
  if (!btn || !confirm("Remove this source and everything indexed from it?")) return;
  btn.disabled = true;
  try {
    await api(`/api/sources/${btn.dataset.delete}`, { method: "DELETE" });
    toast("Source removed");
  } catch (err) {
    toast(err.message, "error");
  }
  loadSources();
});

$("panelUrl").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("urlInput");
  const err = $("urlError");
  let url = input.value.trim();
  err.hidden = true;
  if (!url) {
    err.textContent = "Enter a website address, e.g. example.com";
    err.hidden = false;
    return input.focus();
  }
  if (!/^https?:\/\//i.test(url)) url = "https://" + url;
  const btn = $("urlBtn");
  btn.disabled = true;
  try {
    await api("/api/sources/url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, max_pages: Number($("maxPages").value) || 20 }),
    });
    input.value = "";
    await loadSources();
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
    input.focus();
  } finally {
    btn.disabled = false;
  }
});

async function uploadFiles(fileList) {
  const files = [...fileList];
  if (!files.length) return;
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  const zone = $("dropzone");
  zone.classList.add("pointer-events-none", "opacity-60");
  renderSources([...files.map((f) => ({ id: "", kind: "file", name: f.name, status: "processing" })), ...sourcesCache.filter((s) => s.id)]);
  try {
    const results = await api("/api/sources/files", { method: "POST", body: form });
    for (const s of results) {
      if (s.status === "ready") toast(`${s.name} is ready — ${s.chunks} chunks indexed`);
      else toast(`${s.name}: ${s.error}`, "error");
    }
  } catch (ex) {
    toast(ex.message, "error");
  } finally {
    zone.classList.remove("pointer-events-none", "opacity-60");
    $("fileInput").value = "";
    loadSources();
  }
}

$("fileInput").addEventListener("change", (e) => uploadFiles(e.target.files));
const zone = $("dropzone");
zone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    $("fileInput").click();
  }
});
const dragOn = ["border-brand-500", "bg-brand-50"];
["dragenter", "dragover"].forEach((t) => zone.addEventListener(t, (e) => (e.preventDefault(), zone.classList.add(...dragOn))));
["dragleave", "drop"].forEach((t) => zone.addEventListener(t, (e) => (e.preventDefault(), zone.classList.remove(...dragOn))));
zone.addEventListener("drop", (e) => uploadFiles(e.dataTransfer.files));

// ---------------- Chat ----------------

$("suggestions").innerHTML = SUGGESTIONS.map(
  ([q, hint]) => `
  <button data-suggest="${esc(q)}" class="group flex cursor-pointer items-center gap-3 rounded-xl border border-slate-200 bg-white/90 px-4 py-3 text-left shadow-sm transition-colors hover:border-brand-300 hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 dark:border-slate-800 dark:bg-slate-900/90 dark:hover:border-brand-500/50">
    <span class="min-w-0 flex-1">
      <span class="block text-sm font-medium text-slate-800 dark:text-slate-100">${esc(q)}</span>
      <span class="block text-xs text-slate-500 dark:text-slate-400">${esc(hint)}</span>
    </span>
    <span class="text-slate-300 transition-colors group-hover:text-brand-500 dark:text-slate-600">${icon("arrow", "h-4 w-4", 2)}</span>
  </button>`
).join("");
$("suggestions").addEventListener("click", (e) => {
  const b = e.target.closest("[data-suggest]");
  if (b) ask(b.dataset.suggest);
});

function renderMarkdown(text) {
  const html = DOMPurify.sanitize(marked.parse(text));
  return html.replace(/\[(\d+)\]/g, '<button type="button" class="cite" data-cite="$1" aria-label="Show source $1">$1</button>');
}

function showThread() {
  $("emptyChat").hidden = true;
  $("thread").hidden = false;
  $("newChat").disabled = false;
}

function addUserMessage(text) {
  $("thread").insertAdjacentHTML(
    "beforeend",
    `<div class="flex animate-fade-up justify-end">
      <div class="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-gradient-to-br from-brand-600 to-violet-600 px-4 py-2.5 text-[15px] leading-6 text-white shadow-sm">${esc(text)}</div>
    </div>`
  );
}

function addAssistantMessage() {
  const wrap = document.createElement("div");
  wrap.className = "msg flex animate-fade-up gap-3 sm:gap-4";
  wrap.innerHTML = `
    <div class="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-brand-500 to-violet-600 text-white shadow-sm">
      <svg class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z"/></svg>
    </div>
    <div class="min-w-0 flex-1 pt-0.5">
      <div class="thinking flex h-7 items-center gap-1" aria-label="Thinking">
        <span class="h-2 w-2 animate-dot rounded-full bg-brand-500"></span>
        <span class="h-2 w-2 animate-dot rounded-full bg-brand-500 [animation-delay:.15s]"></span>
        <span class="h-2 w-2 animate-dot rounded-full bg-brand-500 [animation-delay:.3s]"></span>
        <span class="ml-2 text-xs text-slate-500 dark:text-slate-400">Searching your sources…</span>
      </div>
      <div class="answer prose-chat text-[15px] text-slate-800 dark:text-slate-200"></div>
      <div class="sources mt-4" hidden></div>
      <div class="actions mt-2 flex items-center gap-1" hidden>
        <button class="copy flex h-8 cursor-pointer items-center gap-1.5 rounded-lg px-2 text-xs font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 dark:hover:bg-slate-800 dark:hover:text-slate-200">
          ${icon("copy", "h-3.5 w-3.5")}<span>Copy</span>
        </button>
      </div>
    </div>`;
  $("thread").appendChild(wrap);
  return wrap;
}

function renderSourceCards(el, sources) {
  if (!sources.length) return;
  el.dataset.sources = JSON.stringify(sources);
  el.hidden = false;
  el.innerHTML = `
    <button type="button" class="sources-btn inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:border-brand-300 hover:text-brand-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:text-brand-400">
      ${icon("file", "h-3.5 w-3.5")}<span>Sources (${sources.length})</span>
    </button>`;
}

// ---------------- Sources modal ----------------

function sourceCardHtml(s) {
  const isUrl = /^https?:\/\//.test(s.location);
  const label = isUrl ? hostOf(s.location) + new URL(s.location).pathname.replace(/\/$/, "") : s.name;
  const inner = `
    <span class="flex items-center gap-2">
      <span class="cite !m-0 !align-baseline">${s.n}</span>
      <span class="min-w-0 flex-1 truncate text-xs font-medium text-slate-700 dark:text-slate-200">${esc(s.name)}</span>
      ${isUrl ? `<span class="text-slate-400">${icon("external", "h-3.5 w-3.5")}</span>` : ""}
    </span>
    <span class="mt-1 block truncate text-[11px] text-slate-400">${esc(label)}</span>
    <span class="mt-1 line-clamp-2 block text-xs text-slate-500 dark:text-slate-400">${esc(s.snippet)}</span>`;
  const cls =
    "src-card block rounded-xl border border-slate-200 bg-white p-3 text-left transition-colors hover:border-brand-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-brand-500/50";
  return isUrl
    ? `<a data-source="${s.n}" href="${esc(s.location)}" target="_blank" rel="noopener noreferrer" class="${cls}">${inner}</a>`
    : `<div data-source="${s.n}" class="${cls}">${inner}</div>`;
}

function openSourcesModal(sources, highlight) {
  $("sourcesModalTitle").textContent = `Sources (${sources.length})`;
  $("sourcesModalList").innerHTML = sources.map(sourceCardHtml).join("");
  $("sourcesModalWrap").hidden = false;
  document.body.classList.add("overflow-hidden");
  if (highlight) {
    const card = $("sourcesModalList").querySelector(`[data-source="${highlight}"]`);
    if (card) {
      card.scrollIntoView({ behavior: "smooth", block: "center" });
      card.classList.add("!border-brand-500", "ring-2", "ring-brand-500/20");
      setTimeout(() => card.classList.remove("!border-brand-500", "ring-2", "ring-brand-500/20"), 1600);
    }
  }
}

function closeSourcesModal() {
  $("sourcesModalWrap").hidden = true;
  document.body.classList.remove("overflow-hidden");
}

$("sourcesModalClose").onclick = closeSourcesModal;
$("sourcesModalScrim").onclick = closeSourcesModal;
document.addEventListener("keydown", (e) => e.key === "Escape" && !$("sourcesModalWrap").hidden && closeSourcesModal());

function scrollToBottom(force = false) {
  const m = $("messages");
  if (force || m.scrollHeight - m.scrollTop - m.clientHeight < 160) m.scrollTop = m.scrollHeight;
}

$("thread").addEventListener("click", async (e) => {
  const cite = e.target.closest(".answer .cite");
  if (cite) {
    const sourcesEl = cite.closest(".msg").querySelector(".sources");
    const sources = JSON.parse(sourcesEl?.dataset.sources || "[]");
    if (sources.length) openSourcesModal(sources, cite.dataset.cite);
    return;
  }
  const sourcesBtn = e.target.closest(".sources-btn");
  if (sourcesBtn) {
    const sources = JSON.parse(sourcesBtn.closest(".sources").dataset.sources || "[]");
    if (sources.length) openSourcesModal(sources);
    return;
  }
  const copy = e.target.closest(".copy");
  if (copy) {
    try {
      await navigator.clipboard.writeText(copy.closest(".msg").dataset.raw || "");
      copy.querySelector("span").textContent = "Copied";
      setTimeout(() => (copy.querySelector("span").textContent = "Copy"), 1500);
    } catch {
      toast("Could not copy to clipboard", "error");
    }
  }
});

async function ask(question) {
  if (busy) return;
  busy = true;
  showThread();
  addUserMessage(question);
  const msg = addAssistantMessage();
  const answerEl = msg.querySelector(".answer");
  const thinking = msg.querySelector(".thinking");
  scrollToBottom(true);
  $("sendBtn").disabled = true;

  let answer = "";
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history: chatHistory }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf("\n\n")) !== -1) {
        const raw = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const event = raw.match(/^event: (.*)$/m)?.[1];
        const data = JSON.parse(raw.match(/^data: (.*)$/m)?.[1] ?? "null");
        if (event === "sources") renderSourceCards(msg.querySelector(".sources"), data);
        else if (event === "token") {
          thinking.hidden = true;
          answer += data;
          answerEl.innerHTML = renderMarkdown(answer);
          scrollToBottom();
        } else if (event === "error") throw new Error(data);
      }
    }
    msg.dataset.raw = answer;
    msg.querySelector(".actions").hidden = false;
    chatHistory.push({ role: "user", content: question }, { role: "assistant", content: answer });
  } catch (e) {
    thinking.hidden = true;
    answerEl.insertAdjacentHTML(
      "beforeend",
      `<div class="mt-2 flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300" role="alert">${icon("alert", "mt-0.5 h-4 w-4 shrink-0", 2)}<span>${esc(e.message)}</span></div>`
    );
  } finally {
    thinking.hidden = true;
    busy = false;
    $("sendBtn").disabled = false;
    scrollToBottom();
    $("question").focus();
  }
}

$("newChat").onclick = () => {
  chatHistory.length = 0;
  $("thread").innerHTML = "";
  $("thread").hidden = true;
  $("emptyChat").hidden = false;
  $("newChat").disabled = true;
  $("question").focus();
};

const q = $("question");
q.addEventListener("input", () => {
  q.style.height = "auto";
  q.style.height = Math.min(q.scrollHeight, 176) + "px";
});
q.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    $("chatForm").requestSubmit();
  }
});
$("chatForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = q.value.trim();
  if (!text || busy) return;
  q.value = "";
  q.style.height = "auto";
  ask(text);
});

// ---------------- Init ----------------

api("/api/status")
  .then((s) => ($("modelName").textContent = s.chat_model))
  .catch(() => {});
loadSources();
