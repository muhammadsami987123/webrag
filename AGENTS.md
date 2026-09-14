# AGENTS.md

Instructions for any AI coding agent working in this repository. Read this before making changes.

## Project Summary

WebRAG is a URL-to-RAG research workspace. A user submits a website URL; the backend crawls it (under strict SSRF constraints), extracts and chunks its content, embeds and indexes it (FAISS vector store + BM25 keyword index, combined via hybrid retrieval, optionally reranked), and answers questions with grounded, cited, streamed responses. Full product spec: `task.md`.

## Setup Commands

```bash
# create and activate a virtualenv
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux

# install dependencies
pip install -r requirements.txt

# configure environment
cp .env.example .env            # then fill in keys as needed

# run the dev server
uvicorn app.main:app --reload   # serves API + frontend at http://localhost:8000
```

Frontend (`frontend/`) is plain HTML + Tailwind CSS via CDN + vanilla JavaScript — there is no bundler, no npm build step, and no framework. Editing a file under `frontend/` is reflected immediately on browser refresh.

## Environment Variables

Defined in `app/config.py`, documented in `.env.example`. Key variables:

`APP_ENV`, `LLM_PROVIDER`, `LLM_MODEL`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `RERANKER_PROVIDER`, `MAX_CRAWL_PAGES`, `MAX_CRAWL_DEPTH`, `REQUEST_TIMEOUT`, `CRAWL_RATE_LIMIT_PER_SEC`, `MAX_RESPONSE_BYTES`, `STORAGE_PATH`, `CHUNK_SIZE`, `CHUNK_OVERLAP`, `RETRIEVAL_TOP_K`, `RETRIEVAL_CANDIDATE_K`.

`EMBEDDING_PROVIDER=local` runs embeddings fully offline via sentence-transformers; `openai`/`gemini` require the matching API key. `LLM_PROVIDER` similarly requires its matching key.

## Test Commands

```bash
pytest tests/
```

Tests are organized by concern: `tests/crawler/`, `tests/extraction/`, `tests/rag/`, `tests/security/`, `tests/api/`. Run the full suite before opening a PR; run the relevant subdirectory while iterating on a specific area.

## Directory Ownership Map

| Path | Owns |
|---|---|
| `app/main.py`, `app/config.py` | App bootstrap, environment-driven settings |
| `app/api/` | Thin FastAPI route handlers (workspaces, crawler, sources, chat, search, summaries, topics, compare, extraction) — validation and response shaping only |
| `app/rag/ingestion.py` | Orchestrates the full crawl → extract → chunk → embed → index pipeline |
| `app/rag/extraction.py` | HTML → clean structured content (title, headings, paragraphs, tables, boilerplate removal) |
| `app/rag/chunking.py` | Heading/paragraph/sentence-aware semantic chunking with configurable size/overlap |
| `app/rag/embeddings.py` | Embedding provider abstraction/factory (OpenAI / Gemini / local) |
| `app/rag/retrieval.py` | Hybrid retrieval: vector similarity (FAISS) + keyword (BM25) |
| `app/rag/reranking.py` | Reranking abstraction with configurable cross-encoder or fallback scorer |
| `app/rag/prompting.py` | Prompt construction — owns the untrusted-content boundary (see invariant below) |
| `app/rag/citations.py` | Maps retrieved chunks to citation metadata (title, URL, section, score) |
| `app/rag/llm.py` | LLM provider abstraction/factory (OpenAI / Gemini) |
| `app/services/` | Business-logic orchestration between `api/` and `rag/`/`storage/` (crawl execution, source lifecycle, workspace lifecycle, research-mode orchestration) |
| `app/storage/` | Persistence abstractions: document store, FAISS vector store, metadata store — filesystem-backed now, pgvector-migration-ready |
| `app/models/` | Internal domain models |
| `app/schemas/` | Pydantic request/response schemas — the single source of truth for data shapes |
| `app/utils/` | Shared helpers, including the SSRF-safe HTTP client (`security.py`) |
| `frontend/` | HTML + Tailwind CDN + vanilla JS three-panel research UI |
| `storage/workspaces/<id>/` | Per-workspace filesystem storage: documents, chunks, embeddings, FAISS index, chat history, notes |
| `tests/` | Test suite mirroring the above areas |

## Critical Invariants

### Untrusted web content

Content retrieved from crawled websites (page text, headings, metadata) is **data, never instructions**. Prompt assembly happens exclusively in `app/rag/prompting.py`, which is responsible for keeping retrieved content clearly separated from system/developer instructions so it cannot override model behavior — e.g. text on a page saying "ignore previous instructions" must be treated as quotable/citable webpage content, not executed. Never build a prompt that feeds raw crawled text into a system/developer instruction slot, and never construct LLM prompts outside `prompting.py`.

### SSRF-safe HTTP only

Every outbound HTTP request the crawler makes against a user-supplied or crawl-discovered URL must go through the SSRF-safe client in `app/utils/security.py`. Never call `httpx`/`requests` directly against such a URL elsewhere. That client is responsible for blocking localhost, private/link-local IPv4/IPv6 ranges, cloud metadata endpoints, and internal hostnames, enforcing `http`/`https`-only schemes, re-validating the destination after every redirect, and enforcing timeouts and response-size limits.

### Provider abstraction

Never hardcode a specific LLM or embedding provider call outside `app/rag/llm.py` (LLM) and `app/rag/embeddings.py` (embeddings). All provider selection happens through factory functions driven by `LLM_PROVIDER`/`EMBEDDING_PROVIDER` env vars, so swapping providers is a config change, not a code change.

## Code Style

- Python: type hints on all function signatures; async/await for I/O-bound work (HTTP, filesystem, embedding/LLM calls).
- Data shapes are defined once, in `app/schemas/`, as Pydantic models — reuse them rather than redefining shapes ad hoc.
- Keep API route handlers thin; put real logic in `services/` and `rag/`.
- Frontend JS is modular (one concern per file under `frontend/js/`) — no inline framework, no global spaghetti state.

## Commit / PR Conventions

Use short, conventional-commit-style messages, e.g.:

```
feat(crawler): add redirect re-validation for SSRF safety
fix(chunking): preserve heading path across paragraph splits
docs(readme): update configuration table
test(security): cover cloud metadata endpoint blocking
refactor(retrieval): extract hybrid scoring into its own function
```

Keep PRs scoped to one concern where practical. Run `pytest tests/` before opening a PR.

## Security Reporting

Do not open a public issue for SSRF, prompt-injection, or other security-relevant bugs. Report privately instead (see `CONTRIBUTING.md`).
