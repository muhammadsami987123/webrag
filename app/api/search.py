"""Standalone semantic/hybrid search endpoint (bypasses chat/LLM)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings
from app.rag.embeddings import get_embedding_provider
from app.rag.reranking import get_reranker
from app.rag.retrieval import hybrid_retrieve
from app.services import workspace_service
from app.storage.document_store import DocumentStore
from app.storage.vector_store import VectorStore

router = APIRouter(prefix="/api/workspaces", tags=["search"])

_document_store = DocumentStore()
_vector_store = VectorStore(document_store=_document_store)


@router.get("/{workspace_id}/search")
async def search(workspace_id: str, q: str = Query(..., min_length=1)) -> list[dict]:
    if workspace_service.get_workspace(workspace_id) is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    settings = get_settings()
    embedder = get_embedding_provider()
    reranker = get_reranker()

    results = await hybrid_retrieve(
        _vector_store,
        embedder,
        reranker,
        workspace_id,
        q,
        top_k=settings.retrieval_top_k,
        candidate_k=settings.retrieval_candidate_k,
    )

    return [
        {
            "source": rc.chunk.source_url,
            "title": rc.chunk.page_title,
            "section": rc.chunk.section,
            "snippet": rc.chunk.content[:400],
            "score": rc.final_score,
        }
        for rc in results
    ]
