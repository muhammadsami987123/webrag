# WebRAG

**NotebookLM for websites, built as a serious RAG engineering product.**

Paste a website URL. WebRAG crawls it (safely), extracts and chunks the real content, embeds it, indexes it, and lets you interrogate it with grounded, cited, streaming answers — not a chatbot wrapper that forwards your URL to an LLM and hopes for the best.

> URL → Crawl → Understand → Index → Retrieve → Reason → Cite → Research

---

## Table of Contents

- [Why WebRAG](#why-webrag)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [API Overview](#api-overview)
- [Security](#security)
- [Testing](#testing)
- [Roadmap & Limitations](#roadmap--limitations)
- [Contributing](#contributing)
- [License](#license)

---

## Why WebRAG

Most "chat with a website" tools either scrape a single page and stuff it into a prompt, or fake a retrieval step entirely. WebRAG is a real RAG system end to end: a scoped, SSRF-hardened crawler; a content-extraction pipeline that strips boilerplate while preserving heading structure; heading/paragraph-aware chunking; a pluggable embedding layer (OpenAI, Gemini, or local sentence-transformers); a FAISS vector index combined with BM25 keyword search for hybrid retrieval; an optional reranking stage; and a prompting architecture that treats retrieved web content as untrusted data, never as instructions.

The interface is a three-panel research workspace — Sources, Conversation, Context — in the spirit of NotebookLM, purpose-built for interrogating a specific website rather than an open-ended chat.

## Key Features

**Crawling**
- SSRF-protected crawler with configurable scope (single page, page + links, entire domain, or a selected path)
- robots.txt awareness, domain/subdomain scoping, redirect validation, duplicate/URL-fragment/tracking-parameter normalization
- Configurable max pages, max depth, request timeout, and per-second rate limiting

**Extraction & Chunking**
- Boilerplate removal (nav, footers, cookie banners, ads, scripts, repeated menus)
- Preserves title, headings, paragraphs, lists, tables, canonical URL, publish/modified dates, and breadcrumbs
- Heading-aware, paragraph/sentence-boundary-respecting chunking with configurable size and overlap, retaining full heading-path metadata per chunk

**Hybrid Retrieval & Reranking**
- Semantic search via FAISS vector similarity
- Lexical/keyword search via BM25 for exact terms, API names, version numbers
- Combined hybrid scoring with a configurable reranking stage (cross-encoder, with a lightweight fallback when no reranker is configured)

**Grounded Answers & Citations**
- Answers are generated only from retrieved chunks, with clickable citations back to the exact source section
- Explicit hallucination control: when evidence is insufficient, WebRAG says so instead of guessing
- Retrieval-based grounding confidence, not the model's self-reported confidence

**Streaming Chat**
- Real token-by-token streaming over Server-Sent Events, with citations attached as they resolve
- Conversation memory for follow-up questions, without letting prior turns override retrieved evidence

**Research Modes**
- **Ask** — fast grounded answer
- **Research** — deeper multi-source synthesis
- **Compare** — structured comparison across sources
- **Summarize** — page, selection, or whole-workspace summarization (hierarchical for large sites)
- **Explain** — concept explanation grounded strictly in indexed content
- **Extract** — structured extraction (tables of endpoints, plans, integrations, etc.)

**Workspace & Source Management**
- Topic extraction, dynamically generated ask-suggestions, source selection scoping ("ask selected sources" vs. "ask entire knowledge base")
- Re-indexing with content-hash based change detection — new/changed/removed pages, embeddings reused for unchanged content
- Notes, highlights, saved questions, collections, and research threads
- RAG debug panel (similarity, keyword, and rerank scores, final context, citation mapping) — developer-only

**Security**
- Strong SSRF protection (private/link-local IP ranges, cloud metadata endpoints, internal hostnames, redirect re-validation)
- `file://`, `ftp://`, `gopher://` and other non-HTTP(S) schemes are rejected outright
- Prompt-injection resistant prompting architecture — retrieved web content can never override system instructions

## Architecture

```
                              ┌─────────────────────────────────────────────────┐
                              │                  INGESTION                      │
                              │                                                 │
   URL ──▶ Crawl ──▶ Extract ──▶ Chunk ──▶ Embed ──▶ Index (FAISS + BM25)       │
        (SSRF-safe)  (clean    (heading-  (pluggable  (per-workspace vector    │
                      content)  aware)     provider)    + metadata store)      │
                              └─────────────────────────────────────────────────┘
                                                    │
                                                    ▼
                              ┌─────────────────────────────────────────────────┐
                              │                   RETRIEVAL                     │
                              │                                                 │
   Query ──▶ Normalize ──▶ Hybrid Search ──▶ Rerank ──▶ Context Build           │
                          (vector + BM25)  (cross-encoder /                    │
                                            fallback score)                    │
                              └─────────────────────────────────────────────────┘
                                                    │
                                                    ▼
                              ┌─────────────────────────────────────────────────┐
                              │                   GENERATION                    │
                              │                                                 │
   Grounded Context ──▶ LLM (streamed) ──▶ Answer + Citations                  │
   (untrusted-data                        (source, section,                   │
    prompt guard)                          chunk, score)                      │
                              └─────────────────────────────────────────────────┘
```

Three-panel research UI:

```
┌───────────────────────────────────────────────────────┐
│ WebRAG                                      Settings   │
├──────────────┬─────────────────────────┬──────────────┤
│ SOURCES      │ RESEARCH                │ CONTEXT      │
│              │                         │              │
│ 47 pages     │ User question           │ Retrieved    │
│              │                         │ Sources      │
│ ✓ API Docs   │ AI answer...            │              │
│ ✓ Security   │ [1] [2]                 │ Source #1    │
│ ✓ Pricing    │                         │ Source #2    │
│              │                         │              │
│ TOPICS       │ Ask a question...       │ Preview      │
│              │                         │              │
│ API          │                         │              │
│ Security     │                         │              │
└──────────────┴─────────────────────────┴──────────────┘
```

## Tech Stack

**Backend:** Python, FastAPI, Pydantic, Uvicorn, FAISS, BM25, httpx, background tasks + SSE for streaming ingestion/chat progress

**Frontend:** Plain HTML, Tailwind CSS (CDN, no build step), modular vanilla JavaScript, Fetch API + Server-Sent Events

**Storage:** Local filesystem-backed per-workspace document/chunk/embedding/FAISS-index storage, designed for a future PostgreSQL + pgvector migration

**LLM / Embeddings:** Pluggable providers — OpenAI, Gemini, or a local sentence-transformers model — selected entirely via environment variables, never hardcoded

## Project Structure

```
app/
  main.py                 FastAPI app entrypoint
  config.py                Environment-driven settings
  api/                      HTTP route handlers
    workspaces.py           Workspace CRUD + status
    crawler.py               Crawl configuration + trigger endpoints
    sources.py                Source library + source viewer endpoints
    chat.py                    Streaming chat (SSE)
    search.py                   Semantic/keyword search endpoint
    summaries.py                  Page/selection/workspace summarization
    topics.py                      Auto-extracted topics
    compare.py                      Comparison mode
    extraction.py                    Structured extraction mode
  rag/                      Core RAG pipeline
    ingestion.py             Orchestrates crawl → extract → chunk → embed → index
    extraction.py             Content extraction (boilerplate removal, structure)
    chunking.py                 Heading/paragraph-aware semantic chunking
    embeddings.py                 Embedding provider abstraction/factory
    retrieval.py                   Hybrid (vector + BM25) retrieval
    reranking.py                     Reranking abstraction + fallback scorer
    prompting.py                      Grounded prompt construction, injection defense
    citations.py                       Citation extraction/mapping
    llm.py                              LLM provider abstraction/factory
  services/                 Business logic orchestration
    crawler_service.py       SSRF-safe crawl execution
    source_service.py         Source lifecycle management
    workspace_service.py       Workspace lifecycle, persistence
    research_service.py         Research-mode orchestration (Ask/Research/Compare/...)
  storage/                  Persistence abstractions
    document_store.py        Document/page storage
    vector_store.py           FAISS index read/write per workspace
    metadata_store.py          Chunk/workspace metadata
  models/                   Internal domain models
  schemas/                  Pydantic request/response schemas (single source of truth)
  utils/                    Shared helpers (incl. SSRF-safe HTTP client)
frontend/
  css/                      Tailwind-based styling
  js/                       Modular vanilla JS (workspace, chat, sources, topics, search)
storage/
  workspaces/<id>/           Per-workspace filesystem storage
    documents/ chunks/ embeddings/ index/ metadata.json
tests/
  crawler/ extraction/ rag/ security/ api/
```

## Quickstart

```bash
# 1. Clone
git clone <your-fork-url> ragweb
cd ragweb

# 2. Create a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
```

Fill in `.env` with either:
- a configured LLM provider key (`OPENAI_API_KEY` or `GEMINI_API_KEY`, matching `LLM_PROVIDER`), **or**
- `EMBEDDING_PROVIDER=local` to run embeddings fully offline with a local sentence-transformers model (an LLM key is still required for answer generation)

```bash
# 5. Run the dev server
uvicorn app.main:app --reload

# 6. Open the app
# http://localhost:8000
```

No build step is required for the frontend — it is plain HTML/Tailwind CDN/vanilla JS served directly by FastAPI, so edits are reflected on a browser refresh.

## Configuration

All configuration is environment-driven (see `app/config.py` and `.env.example`).

| Variable | Description | Default |
|---|---|---|
| `APP_ENV` | Application environment (`development`, `production`, etc.) | `development` |
| `LLM_PROVIDER` | Answer-generation provider (`openai`, `gemini`) | `openai` |
| `LLM_MODEL` | Model name for the selected LLM provider | provider default |
| `OPENAI_API_KEY` | OpenAI API key (required if `LLM_PROVIDER=openai` or `EMBEDDING_PROVIDER=openai`) | — |
| `GEMINI_API_KEY` | Gemini API key (required if `LLM_PROVIDER=gemini` or `EMBEDDING_PROVIDER=gemini`) | — |
| `EMBEDDING_PROVIDER` | Embedding provider (`openai`, `gemini`, `local`) | `local` |
| `EMBEDDING_MODEL` | Embedding model name | provider default |
| `EMBEDDING_DIM` | Embedding vector dimensionality (must match the model) | model default |
| `RERANKER_PROVIDER` | Reranker backend (`cross-encoder`, `none`) | `none` |
| `MAX_CRAWL_PAGES` | Maximum pages crawled per workspace | `50` |
| `MAX_CRAWL_DEPTH` | Maximum crawl depth from the seed URL | `3` |
| `REQUEST_TIMEOUT` | Per-request HTTP timeout (seconds) | `10` |
| `CRAWL_RATE_LIMIT_PER_SEC` | Max outbound requests per second during a crawl | `2` |
| `MAX_RESPONSE_BYTES` | Max response body size accepted per page | `5_000_000` |
| `STORAGE_PATH` | Root path for per-workspace filesystem storage | `storage/workspaces` |
| `CHUNK_SIZE` | Target chunk size (characters/tokens, per chunker) | `800` |
| `CHUNK_OVERLAP` | Overlap between adjacent chunks | `120` |
| `RETRIEVAL_TOP_K` | Number of chunks returned to the LLM after reranking | `8` |
| `RETRIEVAL_CANDIDATE_K` | Number of candidates retrieved before reranking | `30` |

## API Overview

| Module | Endpoints (purpose) |
|---|---|
| `api/workspaces.py` | Create, list, fetch, and delete research workspaces; knowledge-base status (pages, chunks, embeddings, topics, last indexed) |
| `api/crawler.py` | Configure and trigger a crawl/re-index, stream crawl progress, view change-detection results |
| `api/sources.py` | List sources, fetch a single source for the source viewer, source selection scoping |
| `api/chat.py` | Streaming (SSE) grounded chat with conversation memory and citations |
| `api/search.py` | Semantic + keyword search across the indexed knowledge base |
| `api/summaries.py` | Page / selected-sources / whole-workspace summarization |
| `api/topics.py` | Auto-extracted topics and topic-scoped retrieval |
| `api/compare.py` | Structured multi-source comparison mode |
| `api/extraction.py` | Structured data extraction mode (endpoints, plans, integrations, etc.) |

## Security

WebRAG accepts arbitrary user-supplied URLs, so security is treated as a first-class concern rather than an afterthought:

- **SSRF protection** — every outbound crawl request is resolved and validated against private IPv4/IPv6 ranges, loopback, link-local addresses, cloud metadata endpoints, and internal hostnames, with the destination re-validated after every redirect hop. Only `http://` and `https://` schemes are permitted; `file://`, `ftp://`, and `gopher://` are rejected outright.
- **Resource limits** — request timeouts, response-size caps, crawl page/depth limits, and rate limiting all bound the blast radius of a hostile or misbehaving target site.
- **Prompt-injection defense** — retrieved website content is explicitly treated as untrusted data in the prompting layer (`app/rag/prompting.py`). Instructions embedded in scraped text (e.g. "ignore previous instructions...") are never allowed to influence system behavior; only the system/developer instructions author the model's behavior.
- **Grounding integrity** — citations are only ever generated from chunks that were actually retrieved; the system will explicitly say when it lacks sufficient evidence rather than fabricate an answer.

See spec sections 42–43 in `task.md` for the full security and prompt-injection requirements this implementation is built against.

## Testing

```bash
pytest tests/
```

Test coverage spans:
- **Crawler** — URL validation, redirect handling, robots.txt behavior, domain restrictions, duplicate-URL detection, SSRF protection, timeouts
- **Extraction** — main-content extraction, navigation removal, heading preservation, duplicate-content removal
- **RAG** — chunking, embedding, retrieval, hybrid search, reranking, citation mapping, grounding
- **Security** — SSRF, malicious redirects, prompt injection, oversized responses
- **API** — workspace creation, crawl status, search, chat, re-indexing, deletion

## Roadmap & Limitations

- **Storage is local-first by design.** Vector search runs on FAISS with a filesystem-backed per-workspace store — no external services required for a single-node deployment. The storage layer (`app/storage/`) is deliberately abstracted so a PostgreSQL + pgvector backend can be introduced later without touching the RAG pipeline.
- **Reranking is optional.** With no external cross-encoder configured, a lightweight fallback scorer is used instead of a no-op.
- **Single-node ingestion.** Crawling and embedding run as background tasks within the FastAPI process; horizontally scaling ingestion (a task queue/worker pool) is a natural next step for larger deployments.
- **No multi-tenant auth yet.** Workspaces are local to a single deployment; adding authentication/authorization is out of scope for the current version.

## Contributing

Contributions are welcome. Please see [CONTRIBUTING.md](CONTRIBUTING.md) for local setup, branch naming, commit conventions, and how to run the test suite before opening a PR.

## License

MIT — see [LICENSE](LICENSE).
