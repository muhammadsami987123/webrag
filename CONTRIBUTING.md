# Contributing to WebRAG

Thanks for your interest in contributing. This document covers the practical steps for getting set up and submitting changes.

## Local Setup

```bash
git clone <your-fork-url> ragweb
cd ragweb

python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux

pip install -r requirements.txt

cp .env.example .env            # fill in LLM/embedding provider keys, or set
                                 # EMBEDDING_PROVIDER=local to run fully offline

uvicorn app.main:app --reload   # http://localhost:8000
```

The frontend is plain HTML + Tailwind CSS (CDN) + vanilla JavaScript — there is no build step. Changes under `frontend/` are reflected on a browser refresh.

## Branch Naming

Use a short, prefixed branch name describing the change:

```
feat/hybrid-retrieval-tuning
fix/crawler-redirect-loop
docs/api-overview
test/ssrf-metadata-endpoint
refactor/prompting-context-builder
```

## Commit Messages

Follow a conventional-commit-ish style, short and imperative:

```
feat(chunking): add configurable overlap between chunks
fix(retrieval): correct BM25 score normalization
docs(readme): clarify local embedding setup
test(crawler): add duplicate URL detection cases
refactor(citations): simplify chunk-to-citation mapping
```

## Before Opening a PR

Run the full test suite and make sure it passes:

```bash
pytest tests/
```

If you touched the crawler, extraction, chunking, retrieval, reranking, citations, or security-relevant code, add or update tests under the matching `tests/` subdirectory (`crawler/`, `extraction/`, `rag/`, `security/`, `api/`).

Keep PRs scoped to a single concern where practical, and describe what changed and why in the PR description.

## Code of Conduct

Be respectful.

## Reporting Security Issues

Do not open a public issue for SSRF bypasses, prompt-injection vectors, or other security vulnerabilities. Instead, report them privately by email to **marsaempower@gmail.com** with enough detail to reproduce the issue. Please allow time for a fix before any public disclosure.
