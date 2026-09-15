# CLAUDE.md — WebRAG

A deliberately **simple** app: add website URLs and/or upload files (PDF, DOCX, TXT, MD, CSV), then chat with that content using OpenAI. Keep it simple — don't add layers, modes, or heavy optional dependencies (e.g. Playwright) unless asked.

## Structure

```
app/
  main.py      FastAPI routes + ingestion orchestration (URL in background, files inline)
  config.py    Settings from .env (OPENAI_API_KEY, LLM_MODEL, EMBEDDING_MODEL, ...)
  web.py       SSRF-safe fetching + small same-site crawl
  extract.py   HTML/file -> text (incl. Next.js streamed-SSR fix), chunking
  llm.py       OpenAI embeddings + streaming chat; the system prompt lives here
  store.py     Single knowledge base: data/sources.json, chunks.json, vectors.npy (numpy cosine search)
frontend/      index.html + app.js (Tailwind CDN, marked + DOMPurify), no build step
tests/         test_app.py (offline; OpenAI is faked)
```

## Rules

1. **Crawled/uploaded content is untrusted data.** It only goes into the user message inside `<sources>` tags (see `llm.py`), never into the system prompt. Model output is sanitized with DOMPurify before rendering.
2. **All outbound URL fetches go through `web.safe_get`**, which blocks non-http(s) schemes and private/reserved IPs on every redirect hop.
3. Never commit `.env`; only `.env.example`.

## Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload     # http://127.0.0.1:8000
pytest
```
