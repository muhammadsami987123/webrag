"""FAISS-backed vector store + BM25 keyword search over workspace chunks.

Drop-in implementation of the ``VectorStoreLike`` protocol expected by
``app.rag.retrieval`` (async methods with the exact signatures below).

Index layout per workspace (see document_store.py for the rest of the tree):

    storage/workspaces/<id>/index/faiss.index   # IndexIDMap2(IndexFlatIP(dim))
    storage/workspaces/<id>/index/id_map.json   # {"next_id": int, "dim": int,
                                                 #  "entries": {faiss_id: {"chunk_id", "document_id"}}}

Vectors are L2-normalized before being added/searched so inner product acts
as cosine similarity. Chunks are stored per-document (chunks/<doc>.json +
embeddings/<doc>.npy via DocumentStore); the FAISS index spans the whole
workspace and is the single fast-lookup structure over all of them.

``source_ids`` on ``search``/``keyword_search`` means "restrict to these
document_ids" (not chunk ids) -- the retrieval-pipeline agent passes document
ids through this parameter.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import faiss
import numpy as np
from rank_bm25 import BM25Okapi

from app.config import get_settings
from app.schemas.models import Chunk
from app.storage._atomic import atomic_write_json, read_json
from app.storage.document_store import DocumentStore


@dataclass
class _IndexState:
    index: "faiss.Index"
    dim: int
    next_id: int
    entries: dict[int, dict[str, str]] = field(default_factory=dict)  # faiss_id -> {chunk_id, document_id}
    chunk_to_faiss_id: dict[str, int] = field(default_factory=dict)


def _normalize(vecs: np.ndarray) -> np.ndarray:
    vecs = np.asarray(vecs, dtype=np.float32)
    if vecs.ndim == 1:
        vecs = vecs.reshape(1, -1)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return (vecs / norms).astype(np.float32)


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


class VectorStore:
    """FAISS + BM25 vector/keyword store, one logical index per workspace."""

    def __init__(self, base_path: Path | None = None, document_store: DocumentStore | None = None) -> None:
        self._settings = get_settings()
        self._base_path = Path(base_path) if base_path is not None else self._settings.storage_root
        self._doc_store = document_store or DocumentStore(base_path=self._base_path)

        self._index_cache: dict[str, _IndexState] = {}
        # workspace_id -> (signature, {chunk_id: Chunk})
        self._chunk_cache: dict[str, tuple[tuple, dict[str, Chunk]]] = {}
        # workspace_id -> (signature, BM25Okapi, list[Chunk])
        self._bm25_cache: dict[str, tuple[tuple, BM25Okapi, list[Chunk]]] = {}

    # ------------------------------------------------------------------ #
    # paths
    # ------------------------------------------------------------------ #
    def _index_dir(self, workspace_id: str) -> Path:
        d = self._base_path / "workspaces" / workspace_id / "index"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _index_path(self, workspace_id: str) -> Path:
        return self._index_dir(workspace_id) / "faiss.index"

    def _id_map_path(self, workspace_id: str) -> Path:
        return self._index_dir(workspace_id) / "id_map.json"

    def _chunks_dir(self, workspace_id: str) -> Path:
        return self._base_path / "workspaces" / workspace_id / "chunks"

    # ------------------------------------------------------------------ #
    # index state (lazy load/create + persist)
    # ------------------------------------------------------------------ #
    def _new_state(self, dim: int) -> _IndexState:
        flat = faiss.IndexFlatIP(dim)
        idmap = faiss.IndexIDMap2(flat)
        return _IndexState(index=idmap, dim=dim, next_id=0)

    def _load_state(self, workspace_id: str, dim_hint: int | None = None) -> _IndexState:
        if workspace_id in self._index_cache:
            return self._index_cache[workspace_id]

        idx_path = self._index_path(workspace_id)
        map_path = self._id_map_path(workspace_id)
        if idx_path.exists() and map_path.exists():
            index = faiss.read_index(str(idx_path))
            raw = read_json(map_path) or {}
            entries = {int(k): v for k, v in raw.get("entries", {}).items()}
            state = _IndexState(
                index=index,
                dim=int(raw.get("dim", dim_hint or self._settings.embedding_dim)),
                next_id=int(raw.get("next_id", 0)),
                entries=entries,
            )
            state.chunk_to_faiss_id = {v["chunk_id"]: k for k, v in entries.items()}
        else:
            dim = dim_hint or self._settings.embedding_dim
            state = self._new_state(dim)

        self._index_cache[workspace_id] = state
        return state

    def _save_state(self, workspace_id: str, state: _IndexState) -> None:
        faiss.write_index(state.index, str(self._index_path(workspace_id)))
        payload = {
            "next_id": state.next_id,
            "dim": state.dim,
            "entries": {str(k): v for k, v in state.entries.items()},
        }
        atomic_write_json(self._id_map_path(workspace_id), payload)
        self._index_cache[workspace_id] = state
        # index content changed: invalidate chunk/bm25 caches for this workspace
        self._chunk_cache.pop(workspace_id, None)
        self._bm25_cache.pop(workspace_id, None)

    # ------------------------------------------------------------------ #
    # chunk lookup cache (for turning faiss ids back into Chunk objects)
    # ------------------------------------------------------------------ #
    def _chunks_signature(self, workspace_id: str) -> tuple:
        chunks_dir = self._chunks_dir(workspace_id)
        if not chunks_dir.exists():
            return ()
        return tuple(sorted((p.name, p.stat().st_mtime_ns) for p in chunks_dir.glob("*.json")))

    def _get_all_chunks(self, workspace_id: str) -> dict[str, Chunk]:
        sig = self._chunks_signature(workspace_id)
        cached = self._chunk_cache.get(workspace_id)
        if cached is not None and cached[0] == sig:
            return cached[1]
        chunks = self._doc_store.load_all_chunks(workspace_id)
        by_id = {c.chunk_id: c for c in chunks}
        self._chunk_cache[workspace_id] = (sig, by_id)
        return by_id

    def _get_bm25(self, workspace_id: str) -> tuple[BM25Okapi | None, list[Chunk]]:
        sig = self._chunks_signature(workspace_id)
        cached = self._bm25_cache.get(workspace_id)
        if cached is not None and cached[0] == sig:
            return cached[1], cached[2]
        chunks = self._doc_store.load_all_chunks(workspace_id)
        if not chunks:
            self._bm25_cache[workspace_id] = (sig, None, [])
            return None, []
        tokenized = [_tokenize(c.content) for c in chunks]
        bm25 = BM25Okapi(tokenized)
        self._bm25_cache[workspace_id] = (sig, bm25, chunks)
        return bm25, chunks

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    async def search(
        self,
        workspace_id: str,
        query_vector: list[float],
        top_k: int,
        source_ids: list[str] | None = None,
    ) -> list[tuple[Chunk, float]]:
        state = self._load_state(workspace_id)
        if state.index.ntotal == 0:
            return []

        q = _normalize(np.asarray(query_vector, dtype=np.float32))
        if q.shape[1] != state.dim:
            # dimension mismatch against the persisted index: no meaningful results
            return []

        k = state.index.ntotal if source_ids else min(top_k, state.index.ntotal)
        scores, ids = state.index.search(q, k)
        scores = scores[0]
        ids = ids[0]

        chunks_by_id = self._get_all_chunks(workspace_id)
        source_filter = set(source_ids) if source_ids else None

        out: list[tuple[Chunk, float]] = []
        for faiss_id, score in zip(ids, scores):
            if faiss_id == -1:
                continue
            entry = state.entries.get(int(faiss_id))
            if entry is None:
                continue
            if source_filter is not None and entry["document_id"] not in source_filter:
                continue
            chunk = chunks_by_id.get(entry["chunk_id"])
            if chunk is None:
                continue
            out.append((chunk, float(score)))
            if len(out) >= top_k:
                break
        return out

    async def keyword_search(
        self,
        workspace_id: str,
        query: str,
        top_k: int,
        source_ids: list[str] | None = None,
    ) -> list[tuple[Chunk, float]]:
        bm25, chunks = self._get_bm25(workspace_id)
        if bm25 is None or not chunks:
            return []

        scores = bm25.get_scores(_tokenize(query))
        source_filter = set(source_ids) if source_ids else None

        ranked = sorted(
            ((chunk, float(score)) for chunk, score in zip(chunks, scores)),
            key=lambda pair: pair[1],
            reverse=True,
        )

        out: list[tuple[Chunk, float]] = []
        for chunk, score in ranked:
            if score <= 0.0:
                continue
            if source_filter is not None and chunk.document_id not in source_filter:
                continue
            out.append((chunk, score))
            if len(out) >= top_k:
                break
        return out

    async def add_chunks(
        self,
        workspace_id: str,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> None:
        if not chunks:
            return
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must be the same length")

        dim = len(embeddings[0])
        state = self._load_state(workspace_id, dim_hint=dim)

        # persist chunks + embeddings per document (grouped, order-preserving)
        by_doc: dict[str, list[int]] = {}
        for i, c in enumerate(chunks):
            by_doc.setdefault(c.document_id, []).append(i)
        for document_id, idxs in by_doc.items():
            doc_chunks = [chunks[i] for i in idxs]
            doc_embeddings = [embeddings[i] for i in idxs]
            self._doc_store.save_chunks(workspace_id, document_id, doc_chunks)
            self._doc_store.save_embeddings(workspace_id, document_id, doc_embeddings)

        vecs = _normalize(np.asarray(embeddings, dtype=np.float32))
        ids = np.arange(state.next_id, state.next_id + len(chunks), dtype=np.int64)
        state.index.add_with_ids(vecs, ids)

        for faiss_id, chunk in zip(ids.tolist(), chunks):
            state.entries[faiss_id] = {"chunk_id": chunk.chunk_id, "document_id": chunk.document_id}
            state.chunk_to_faiss_id[chunk.chunk_id] = faiss_id
        state.next_id += len(chunks)

        self._save_state(workspace_id, state)

    async def remove_document(self, workspace_id: str, document_id: str) -> None:
        state = self._load_state(workspace_id)
        ids_to_remove = [
            faiss_id for faiss_id, entry in state.entries.items() if entry["document_id"] == document_id
        ]
        if ids_to_remove:
            state.index.remove_ids(np.asarray(ids_to_remove, dtype=np.int64))
            for faiss_id in ids_to_remove:
                entry = state.entries.pop(faiss_id, None)
                if entry is not None:
                    state.chunk_to_faiss_id.pop(entry["chunk_id"], None)
            self._save_state(workspace_id, state)
        else:
            # still make sure caches reflect current on-disk chunk state
            self._chunk_cache.pop(workspace_id, None)
            self._bm25_cache.pop(workspace_id, None)

    async def rebuild(self, workspace_id: str) -> None:
        """Rebuilds the FAISS index from all stored per-document embeddings + chunks.

        Used after re-indexing or deletion (section 31) to guarantee the index
        matches what's actually on disk in chunks/ + embeddings/.
        """
        documents = self._doc_store.list_documents(workspace_id)

        dim: int | None = None
        pending: list[tuple[str, list[Chunk], np.ndarray]] = []
        for doc in sorted(documents, key=lambda d: d.document_id):
            doc_chunks = self._doc_store.load_chunks(workspace_id, doc.document_id)
            doc_embeddings = self._doc_store.load_embeddings(workspace_id, doc.document_id)
            if not doc_chunks or doc_embeddings is None or len(doc_embeddings) != len(doc_chunks):
                continue
            if dim is None:
                dim = int(doc_embeddings.shape[1])
            pending.append((doc.document_id, doc_chunks, doc_embeddings))

        state = self._new_state(dim or self._settings.embedding_dim)
        if pending:
            all_vecs: list[np.ndarray] = []
            all_ids: list[int] = []
            next_id = 0
            for _document_id, doc_chunks, doc_embeddings in pending:
                vecs = _normalize(np.asarray(doc_embeddings, dtype=np.float32))
                for chunk, vec in zip(doc_chunks, vecs):
                    fid = next_id
                    next_id += 1
                    state.entries[fid] = {"chunk_id": chunk.chunk_id, "document_id": chunk.document_id}
                    state.chunk_to_faiss_id[chunk.chunk_id] = fid
                    all_vecs.append(vec)
                    all_ids.append(fid)
            state.index.add_with_ids(np.stack(all_vecs).astype(np.float32), np.asarray(all_ids, dtype=np.int64))
            state.next_id = next_id

        self._save_state(workspace_id, state)
