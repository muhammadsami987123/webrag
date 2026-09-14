"""Retrieval/reranking abstraction (section 13).

Default is a genuine local cross-encoder reranker (no API key required); a
pure lexical-overlap heuristic is available as a graceful-degradation
fallback if the cross-encoder model cannot be loaded (e.g. no network).
"""
from __future__ import annotations

import math
import re
import threading
from abc import ABC, abstractmethod
from collections import Counter

from app.config import get_settings
from app.schemas.models import RetrievedChunk

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


class Reranker(ABC):
    @abstractmethod
    async def rerank(self, query: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Score `candidates` against `query`, set rerank_score, and return
        them re-sorted by rerank_score descending."""
        raise NotImplementedError


class CrossEncoderReranker(Reranker):
    """Real local cross-encoder reranker via sentence-transformers."""

    _model_lock = threading.Lock()
    _model_cache: dict[str, object] = {}

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self._model_name = model_name
        self._model = self._load_model(model_name)

    @classmethod
    def _load_model(cls, model_name: str):
        with cls._model_lock:
            if model_name not in cls._model_cache:
                from sentence_transformers import CrossEncoder

                cls._model_cache[model_name] = CrossEncoder(model_name)
            return cls._model_cache[model_name]

    async def rerank(self, query: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if not candidates:
            return []
        import asyncio

        pairs = [(query, rc.chunk.content) for rc in candidates]

        def _score() -> list[float]:
            scores = self._model.predict(pairs)
            return [float(s) for s in scores]

        scores = await asyncio.to_thread(_score)
        for rc, score in zip(candidates, scores):
            rc.rerank_score = score
        return sorted(candidates, key=lambda rc: rc.rerank_score or 0.0, reverse=True)


class LexicalOverlapReranker(Reranker):
    """Pure heuristic fallback: token overlap + BM25-like scoring.

    Used automatically if the cross-encoder model fails to load (e.g. no
    network access to download it), so the app degrades gracefully instead
    of crashing.
    """

    _k1 = 1.5
    _b = 0.75

    async def rerank(self, query: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if not candidates:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            for rc in candidates:
                rc.rerank_score = 0.0
            return list(candidates)

        doc_tokens = [_tokenize(rc.chunk.content) for rc in candidates]
        doc_lens = [len(toks) for toks in doc_tokens]
        avg_len = (sum(doc_lens) / len(doc_lens)) if doc_lens else 0.0

        n_docs = len(candidates)
        df: Counter[str] = Counter()
        for toks in doc_tokens:
            for term in set(toks):
                df[term] += 1

        for rc, toks, dlen in zip(candidates, doc_tokens, doc_lens):
            term_counts = Counter(toks)
            score = 0.0
            for term in set(query_tokens):
                if term not in term_counts:
                    continue
                tf = term_counts[term]
                idf = math.log(1 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
                denom = tf + self._k1 * (1 - self._b + self._b * (dlen / avg_len if avg_len else 1))
                score += idf * (tf * (self._k1 + 1)) / (denom or 1)
            rc.rerank_score = score

        return sorted(candidates, key=lambda rc: rc.rerank_score or 0.0, reverse=True)


def get_reranker() -> Reranker:
    """Factory based on settings.reranker_provider ('cross_encoder'|'local'|'lexical')."""
    settings = get_settings()
    provider = (settings.reranker_provider or "local").lower()

    if provider in ("lexical", "heuristic", "none"):
        return LexicalOverlapReranker()

    # Default: real local cross-encoder, with graceful fallback if it can't load.
    try:
        return CrossEncoderReranker()
    except Exception:
        return LexicalOverlapReranker()
