"""Hybrid (semantic + lexical) retrieval pipeline (sections 11/12/13/22/23)."""
from __future__ import annotations

import asyncio
import re
from typing import Protocol

from app.rag.embeddings import EmbeddingProvider
from app.rag.reranking import Reranker
from app.schemas.models import Chunk, RetrievedChunk

_WHITESPACE_RE = re.compile(r"\s+")


class VectorStoreLike(Protocol):
    async def search(
        self,
        workspace_id: str,
        query_vector: list[float],
        top_k: int,
        source_ids: list[str] | None,
    ) -> list[tuple[Chunk, float]]: ...

    async def keyword_search(
        self,
        workspace_id: str,
        query: str,
        top_k: int,
        source_ids: list[str] | None,
    ) -> list[tuple[Chunk, float]]: ...


def normalize_query(query: str) -> str:
    """Trim and collapse whitespace in a raw user query."""
    return _WHITESPACE_RE.sub(" ", (query or "").strip())


def _min_max_normalize(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    values = list(scores.values())
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        # All equal (including a single result): treat as fully relevant.
        return {k: 1.0 for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


async def hybrid_retrieve(
    store: VectorStoreLike,
    embedder: EmbeddingProvider,
    reranker: Reranker,
    workspace_id: str,
    query: str,
    top_k: int,
    candidate_k: int,
    source_ids: list[str] | None = None,
    semantic_weight: float = 0.7,
    keyword_weight: float = 0.3,
) -> list[RetrievedChunk]:
    """Embed the query, run semantic + lexical retrieval concurrently, merge
    and dedupe by chunk_id via a weighted, min-max-normalized combined score,
    rerank the top `candidate_k`, and return the top `top_k` RetrievedChunks
    sorted by final_score.
    """
    normalized = normalize_query(query)
    if not normalized:
        return []

    query_vectors = await embedder.embed([normalized])
    query_vector = query_vectors[0] if query_vectors else []

    semantic_results, keyword_results = await asyncio.gather(
        store.search(workspace_id, query_vector, candidate_k, source_ids),
        store.keyword_search(workspace_id, normalized, candidate_k, source_ids),
    )

    semantic_raw: dict[str, float] = {}
    keyword_raw: dict[str, float] = {}
    chunks_by_id: dict[str, Chunk] = {}

    for chunk, score in semantic_results:
        semantic_raw[chunk.chunk_id] = max(semantic_raw.get(chunk.chunk_id, float("-inf")), score)
        chunks_by_id[chunk.chunk_id] = chunk

    for chunk, score in keyword_results:
        keyword_raw[chunk.chunk_id] = max(keyword_raw.get(chunk.chunk_id, float("-inf")), score)
        chunks_by_id.setdefault(chunk.chunk_id, chunk)

    semantic_norm = _min_max_normalize(semantic_raw)
    keyword_norm = _min_max_normalize(keyword_raw)

    all_ids = set(chunks_by_id.keys())
    combined: list[RetrievedChunk] = []
    for chunk_id in all_ids:
        sem = semantic_norm.get(chunk_id, 0.0)
        kw = keyword_norm.get(chunk_id, 0.0)
        combined_score = semantic_weight * sem + keyword_weight * kw
        combined.append(
            RetrievedChunk(
                chunk=chunks_by_id[chunk_id],
                semantic_score=semantic_raw.get(chunk_id, 0.0),
                keyword_score=keyword_raw.get(chunk_id, 0.0),
                rerank_score=None,
                final_score=combined_score,
            )
        )

    combined.sort(key=lambda rc: rc.final_score, reverse=True)
    candidates = combined[:candidate_k]

    reranked = await reranker.rerank(normalized, candidates)

    for rc in reranked:
        rc.final_score = rc.rerank_score if rc.rerank_score is not None else rc.final_score

    reranked.sort(key=lambda rc: rc.final_score, reverse=True)
    return reranked[:top_k]
