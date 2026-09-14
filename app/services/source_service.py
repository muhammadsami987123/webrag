"""Thin service layer over DocumentStore for source (document) listing,
detail lookup, and deletion, keeping the vector index in sync."""
from __future__ import annotations

from app.schemas.models import SourceDocument
from app.storage.document_store import DocumentStore
from app.storage.vector_store import VectorStore

_document_store = DocumentStore()
_vector_store = VectorStore(document_store=_document_store)


def list_sources(workspace_id: str) -> list[SourceDocument]:
    return _document_store.list_documents(workspace_id)


def get_source(workspace_id: str, document_id: str) -> SourceDocument | None:
    return _document_store.load_document(workspace_id, document_id)


async def delete_source(workspace_id: str, document_id: str) -> bool:
    """Delete a single document (and its chunks/embeddings), remove it from
    the vector index, and rebuild the index. Returns False if not found."""
    doc = _document_store.load_document(workspace_id, document_id)
    if doc is None:
        return False

    _document_store.delete_document(workspace_id, document_id)
    await _vector_store.remove_document(workspace_id, document_id)
    await _vector_store.rebuild(workspace_id)
    return True
