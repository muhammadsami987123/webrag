"""Workspace lifecycle orchestration: creation, ingestion pipeline, reindex,
deletion, and lookups. This is the core wiring between the crawler,
extraction, chunking, embedding, and storage subsystems.
"""
from __future__ import annotations

import logging
import secrets
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.rag.chunking import chunk_document
from app.rag.embeddings import get_embedding_provider
from app.rag.extraction import compute_content_hash
from app.schemas.models import (
    CrawlConfig,
    SourceDocument,
    Workspace,
    WorkspaceStatus,
)
from app.services.crawler_service import crawl_workspace
from app.storage.document_store import DocumentStore
from app.storage.metadata_store import MetadataStore
from app.storage.vector_store import VectorStore
from app.utils.security import is_safe_url

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict], Awaitable[None]]

_document_store = DocumentStore()
_metadata_store = MetadataStore()
_vector_store = VectorStore(document_store=_document_store)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def create_workspace(root_url: str, crawl_config: CrawlConfig | None = None) -> Workspace:
    """Validate `root_url`, create a new pending Workspace, and persist it."""
    ok, reason = is_safe_url(root_url)
    if not ok:
        raise ValueError(reason)

    workspace_id = secrets.token_hex(6)
    workspace = Workspace(
        workspace_id=workspace_id,
        root_url=root_url,
        status=WorkspaceStatus.pending,
        crawl_config=crawl_config or CrawlConfig(),
    )
    _document_store.save_workspace(workspace)
    return workspace


def get_workspace(workspace_id: str) -> Workspace | None:
    return _document_store.load_workspace(workspace_id)


def list_workspaces() -> list[Workspace]:
    return _document_store.list_workspaces()


async def delete_workspace(workspace_id: str) -> None:
    _document_store.delete_workspace(workspace_id)


def _extract_topics(documents: list[SourceDocument], top_n: int = 10) -> list[str]:
    """Heuristic topic derivation: frequency-count H1/H2 heading text across
    all documents in the workspace, take the most common distinct ones."""
    counter: Counter[str] = Counter()
    for doc in documents:
        for heading in doc.headings:
            if heading.level in (1, 2):
                text = heading.text.strip()
                if text and len(text) <= 80:
                    counter[text] += 1
    return [text for text, _ in counter.most_common(top_n)]


async def _emit(progress_cb: ProgressCallback | None, workspace: Workspace) -> None:
    if progress_cb is not None:
        await progress_cb(workspace.model_dump(mode="json"))


async def run_ingestion(
    workspace_id: str,
    progress_cb: ProgressCallback | None = None,
    save_snapshot: bool = True,
) -> None:
    """Run the full crawl -> extract -> chunk -> embed -> index pipeline for
    a workspace, updating its status/progress fields as it goes."""
    workspace = _document_store.load_workspace(workspace_id)
    if workspace is None:
        logger.error("run_ingestion: workspace %s not found", workspace_id)
        return

    workspace.status = WorkspaceStatus.crawling
    workspace.updated_at = _now()
    _document_store.save_workspace(workspace)
    await _emit(progress_cb, workspace)

    embedder = None

    async def on_page(raw_doc: dict[str, Any]) -> None:
        nonlocal workspace, embedder
        if embedder is None:
            embedder = get_embedding_provider()
        try:
            workspace.status = WorkspaceStatus.processing
            url = raw_doc["url"]
            content_hash = raw_doc.get("content_hash", "")

            existing = _document_store.get_document_by_url(workspace_id, url)
            if existing is not None and existing.content_hash == content_hash and content_hash:
                # Unchanged content: skip re-chunking/re-embedding, reuse as-is.
                existing.status = "indexed"
                existing.updated_at = _now()
                _document_store.save_document(existing)
                _document_store.save_workspace(workspace)
                await _emit(progress_cb, workspace)
                return

            document_id = existing.document_id if existing is not None else secrets.token_hex(8)
            document = SourceDocument(
                document_id=document_id,
                workspace_id=workspace_id,
                url=url,
                canonical_url=raw_doc.get("canonical_url"),
                title=raw_doc.get("title") or url,
                content=raw_doc.get("content", ""),
                headings=raw_doc.get("headings", []),
                breadcrumbs=raw_doc.get("breadcrumbs", []),
                word_count=raw_doc.get("word_count", 0),
                content_hash=content_hash,
                published_at=raw_doc.get("published_at"),
                modified_at=raw_doc.get("modified_at"),
                status="indexed",
                updated_at=_now(),
            )
            _document_store.save_document(document)

            chunks = chunk_document(document)
            workspace.chunks_created += len(chunks)

            if chunks:
                texts = [c.content for c in chunks]
                workspace.status = WorkspaceStatus.embedding
                embeddings = await embedder.embed(texts)
                await _vector_store.add_chunks(workspace_id, chunks, embeddings)
                workspace.embeddings_created += len(embeddings)
            else:
                _document_store.save_chunks(workspace_id, document_id, [])

            _document_store.save_workspace(workspace)
            await _emit(progress_cb, workspace)
        except Exception:
            logger.exception("Failed processing page during ingestion for workspace %s", workspace_id)

    async def on_progress(pages_discovered: int, pages_processed: int) -> None:
        nonlocal workspace
        workspace.pages_discovered = pages_discovered
        workspace.pages_processed = pages_processed
        workspace.updated_at = _now()
        _document_store.save_workspace(workspace)
        await _emit(progress_cb, workspace)

    try:
        await crawl_workspace(
            workspace.root_url,
            workspace.crawl_config,
            on_page=on_page,
            on_progress=on_progress,
        )

        documents = _document_store.list_documents(workspace_id)

        if workspace.pages_discovered > 0 and not documents:
            workspace.status = WorkspaceStatus.failed
            workspace.error = (
                "We couldn't find enough readable content on this website, or every page "
                "failed during processing (check server logs for the underlying error, e.g. "
                "a misconfigured embedding/LLM provider)."
            )
            workspace.updated_at = _now()
            _document_store.save_workspace(workspace)
            await _emit(progress_cb, workspace)
            return

        workspace.topics = _extract_topics(documents)
        workspace.status = WorkspaceStatus.ready
        workspace.last_indexed_at = _now()
        workspace.updated_at = _now()
        workspace.error = None
        _document_store.save_workspace(workspace)
        await _emit(progress_cb, workspace)

        if save_snapshot:
            _metadata_store.save_snapshot(workspace_id, documents)
    except Exception as exc:
        logger.exception("Ingestion failed for workspace %s", workspace_id)
        workspace.status = WorkspaceStatus.failed
        workspace.error = str(exc)
        workspace.updated_at = _now()
        _document_store.save_workspace(workspace)
        await _emit(progress_cb, workspace)


async def reindex_workspace(workspace_id: str, progress_cb: ProgressCallback | None = None) -> dict:
    """Re-crawl a workspace, reusing embeddings for unchanged pages, and
    return a diff of new/changed/removed/unchanged URLs against the last
    snapshot."""
    workspace = _document_store.load_workspace(workspace_id)
    if workspace is None:
        raise ValueError(f"Workspace {workspace_id} not found")

    # Crawl + reprocess without overwriting the snapshot yet, so the diff
    # below compares against the state as of the *previous* indexing run.
    await run_ingestion(workspace_id, progress_cb=progress_cb, save_snapshot=False)

    documents = _document_store.list_documents(workspace_id)
    diff = _metadata_store.diff_against_last_snapshot(workspace_id, documents)

    await _vector_store.rebuild(workspace_id)

    workspace = _document_store.load_workspace(workspace_id)
    workspace.index_version += 1
    workspace.updated_at = _now()
    _document_store.save_workspace(workspace)

    _metadata_store.save_snapshot(workspace_id, documents)

    return diff
