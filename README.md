# WebRAG

**Chat with any website or document — grounded, cited, streaming answers powered by your own OpenAI key.**

Paste a URL and WebRAG crawls the site (safely, staying on the same domain), or drop in a PDF/DOCX/TXT/MD/CSV file. Everything gets chunked, embedded, and indexed. Ask a question and get a streamed answer with numbered `[1]` citations back to the exact source — never an ungrounded guess.

> URL or file → extract → chunk → embed → index → retrieve → answer with citations

---

## Table of Contents

- [Why WebRAG](#why-webrag)
- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [Security](#security)
- [Testing](#testing)
- [Limitations & Roadmap](#limitations--roadmap)
- [License](#license)

---

## Why WebRAG

Most "chat with a website" demos scrape one page and stuff it into a prompt. WebRAG does the real thing, kept deliberately small:

- a same-site crawler that validates every URL (and every redirect hop) against SSRF rules before it ever makes a request,
- an extractor that strips navs/footers/scripts and also **statically resolves React/Next.js streamed-SSR content** — so modern client-rendered sites don't come back empty,
- paragraph-aware chunking with configurable size/overlap,
- OpenAI embeddings with cosine-similarity retrieval over a small local vector store,
- a prompt boundary that treats all retrieved content as untrusted reference data, never as instructions, so a page that says "ignore your instructions" is just text to quote or ignore.

One knowledge base, one page, no accounts, no workspaces — add sources on the left, ask questions on the right.

## Features

**Ingestion**
- Add a website URL; WebRAG crawls same-site links breadth-first up to a configurable page limit (default 20, adjustable 1–100 per request)
- Upload PDF, DOCX, TXT, MD, or CSV files (drag-and-drop or file picker), up to `MAX_UPLOAD_MB` each
- Ingestion runs as a background task for URLs (the UI polls status) and inline for file uploads

**Extraction**
- Boilerplate stripped (`script`, `style`, `nav`, `footer`, `header`, `form`, `button`, etc.)
- Falls back from `<main>`/`<article>` to `<body>` when the primary content region is empty
- Statically replays React 18 streaming-SSR `<template>`/`<!--$?-->` Suspense swaps so Next.js App Router pages resolve to real content without a headless browser

**Retrieval & Answers**
- Query embedded with the same model as the corpus, matched by cosine similarity over a NumPy matrix (results below a 0.15 similarity floor are dropped)
- Answers stream token-by-token over Server-Sent Events, with a `sources` event fired first so citations are ready before the first token renders
- Numbered `[1]`/`[2]` citations in the answer map to clickable source cards (with snippet + link back to the page)
- Last 6 turns of conversation history are sent with each request for follow-up questions

**Frontend**
- Single page, Tailwind CDN, vanilla JS — no build step, edit and refresh
- Light/dark theme (persisted to `localStorage`), responsive sidebar drawer on mobile
- Live source list with processing/ready/failed status, chunk counts, one-click delete
- Toast notifications when a source finishes indexing or fails

**Security**
- All outbound crawl requests go through one SSRF-safe fetcher (`app/web.py`) that resolves DNS, rejects private/loopback/link-local/reserved IPs, and re-validates on every redirect hop
- `http`/`https` only — no `file://`, `ftp://`, etc.
- Response size capped at 5 MB per page; non-HTML responses rejected
- Retrieved web/file content is only ever placed inside `<sources>` tags in the *user* message — never the system prompt — so it can't override the assistant's instructions

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                             INGESTION                             │
│                                                                    │
│  URL ──▶ safe crawl ──▶ extract to text ──▶ chunk ──▶ embed ──┐  │
│  (SSRF-checked,        (boilerplate strip,   (paragraph-      │  │
│   same-site BFS)        streamed-SSR fix)     aware, overlap) │  │
│  File ─▶ parse (pypdf / python-docx / text) ──────────────────┘  │
│                                                                    │
│                              ▼                                    │
│                 store.py — sources.json / chunks.json / vectors.npy
└──────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────┐
│                              RETRIEVAL                            │
│                                                                    │
│  Question ──▶ embed ──▶ cosine similarity search ──▶ top-K chunks │
└──────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────┐
│                              GENERATION                           │
│                                                                    │
│  <sources> (untrusted, user-role only) + question ──▶ OpenAI ──▶  │
│  streamed answer with [n] citations, over SSE                     │
└──────────────────────────────────────────────────────────────────┘
```

## Tech Stack

**Backend:** Python, FastAPI, Pydantic Settings, Uvicorn, httpx (SSRF-safe fetch), BeautifulSoup + lxml (extraction), pypdf, python-docx, NumPy (vector search), OpenAI SDK (embeddings + streaming chat)

**Frontend:** Plain HTML, Tailwind CSS (CDN, no build step), vanilla JavaScript, `marked` + `DOMPurify` (sanitized Markdown rendering), Fetch API + Server-Sent Events

**Storage:** Flat files under `data/` — `sources.json`, `chunks.json`, `vectors.npy` — written atomically with a Windows-safe retry on file-lock contention

## Project Structure

```
app/
  main.py       FastAPI routes: add URL/files, list/delete sources, streaming chat
  config.py     Settings loaded from .env (pydantic-settings)
  web.py        SSRF-safe HTTP fetch + same-site BFS crawler
  extract.py    HTML/file → text (incl. streamed-SSR fix), text → chunks
  llm.py        OpenAI embeddings + streaming chat; system prompt lives here
  store.py      Single knowledge base: sources, chunks, vectors, atomic persistence
frontend/
  index.html    Single-page UI (Tailwind CDN)
  app.js        All UI behavior — sources, uploads, chat, theming
tests/
  test_app.py   Offline tests (extraction, chunking, SSRF guard, API with OpenAI faked)
data/           Created at runtime — sources.json, chunks.json, vectors.npy
```

## Quickstart

```bash
# 1. Clone
git clone <this-repo>
cd ragweb

# 2. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
copy .env.example .env        # Windows; use `cp` on macOS/Linux
# then edit .env and set OPENAI_API_KEY=sk-...

# 5. Run the dev server
uvicorn app.main:app --reload

# 6. Open the app
# http://127.0.0.1:8000
```

Add a website URL or upload a file from the sidebar, wait for it to say "Ready," then ask a question.

## Configuration

All settings are read from `.env` (see `.env.example`) via `app/config.py`:

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | *(empty)* | Required for embeddings and chat. The app runs but refuses to embed/chat without it. |
| `LLM_MODEL` | `gpt-4o-mini` | Chat completion model used to generate answers. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model used for both corpus and query vectors. |
| `DATA_DIR` | `data` | Where `sources.json`, `chunks.json`, and `vectors.npy` are persisted. |
| `MAX_PAGES` | `20` | Default crawl page limit (overridable per-request, 1–100). |
| `MAX_UPLOAD_MB` | `20` | Max size per uploaded file. |
| `REQUEST_TIMEOUT` | `15.0` | Per-request HTTP timeout (seconds) for crawling. |
| `CHUNK_SIZE` | `1000` | Target characters per chunk. |
| `CHUNK_OVERLAP` | `150` | Character overlap between consecutive chunks. |
| `TOP_K` | `6` | Number of chunks retrieved per question. |

## API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Serves the frontend. |
| `GET` | `/api/status` | Whether `OPENAI_API_KEY` is configured, and the active chat model. |
| `GET` | `/api/sources` | List all sources with status (`processing`/`ready`/`failed`), page/chunk counts. |
| `POST` | `/api/sources/url` | Add a website. Body: `{ "url": "...", "max_pages": 20 }`. Returns `202` immediately; crawling/indexing runs in the background. |
| `POST` | `/api/sources/files` | Upload one or more files (`multipart/form-data`, field `files`). Parses and indexes synchronously; returns each source's final status. |
| `DELETE` | `/api/sources/{id}` | Remove a source and every chunk/vector derived from it. |
| `POST` | `/api/chat` | Ask a question. Body: `{ "question": "...", "history": [{"role": "...", "content": "..."}] }`. Returns a `text/event-stream` of `sources` (once), `token` (repeated), and `done`/`error` events. |

## Security

- **SSRF protection** (`app/web.py`): every URL — the one you paste and every link the crawler follows — is resolved via DNS and checked with `ipaddress.is_global` before any request is made; this check re-runs on every redirect hop, so a public URL that redirects to `169.254.169.254` or `localhost` is caught, not just the first hop. Only `http`/`https` schemes are accepted; internal-looking hostnames (`.local`, `.internal`, `localhost`) are rejected outright.
- **Prompt-injection boundary** (`app/llm.py`): retrieved content is interpolated only inside a `<sources>` block of the *user* message, wrapped per-chunk in `<source id="n" title="...">`. The system prompt is fixed and instructs the model to treat sources as untrusted reference data and never follow instructions found inside them.
- **Output sanitization**: the assistant's Markdown response is rendered with `marked` and then sanitized with `DOMPurify` before being inserted into the DOM.
- **Response limits**: crawled pages are capped at 5 MB; non-HTML content types are rejected before the body is read.

## Testing

```bash
pytest
```

`tests/test_app.py` covers, entirely offline (OpenAI calls are monkeypatched):
- streamed-SSR HTML extraction and paragraph chunking,
- DOCX/TXT parsing and rejection of unsupported file types,
- the SSRF guard against loopback, link-local, cloud-metadata, and non-HTTP URLs,
- the full upload → chat (with citations) → delete flow through the FastAPI app,
- graceful handling of unsupported uploads.

## Limitations & Roadmap

- **Single knowledge base.** There's no per-project/workspace separation — every source you add is searchable by every question. Multi-workspace support is a natural next step if you need isolation.
- **No reranking or keyword search.** Retrieval is pure cosine similarity over OpenAI embeddings; a BM25/hybrid stage would help with exact terms, IDs, or version numbers.
- **No JS-rendering fallback.** The streamed-SSR fix handles React/Next.js server-streamed content statically, but a fully client-fetched SPA (data loaded after mount, with no SSR payload at all) will still index thin. No headless browser dependency is used by design.
- **Single-process, filesystem storage.** `data/*.json` and `vectors.npy` are rewritten atomically on every change; this is fine for one deployment but isn't built for concurrent writers or horizontal scaling.
- **No auth.** This is a single-user local/self-hosted tool as shipped.

## License

MIT — see [LICENSE](LICENSE).
