"""Filesystem-backed persistence for workspaces, documents, and chunks.

Layout under settings.workspace_dir(workspace_id) (see app/config.py):

    storage/workspaces/<id>/
        workspace.json
        documents/<document_id>.json
        documents/_url_index.json      # {url: document_id} maintained on save
        chunks/<document_id>.json      # list[Chunk]
        embeddings/<document_id>.npy   # float32 (n_chunks, dim), row i -> chunks[i]

All reads/writes are JSON via pydantic's model_dump(mode="json") / model_validate,
written atomically (temp file + os.replace) to avoid partial-write corruption.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np

from app.config import get_settings
from app.schemas.models import Chunk, SourceDocument, Workspace
from app.storage._atomic import atomic_write_json, read_json

_URL_INDEX_FILE = "_url_index.json"


class DocumentStore:
    """CRUD persistence for Workspace / SourceDocument / Chunk records.

    Accepts an optional ``base_path`` (defaults to ``get_settings().storage_root``)
    so tests can inject a ``tmp_path`` without touching global settings.
    """

    def __init__(self, base_path: Path | None = None) -> None:
        self._settings = get_settings()
        self._base_path = Path(base_path) if base_path is not None else self._settings.storage_root

    # ------------------------------------------------------------------ #
    # path helpers
    # ------------------------------------------------------------------ #
    def workspace_dir(self, workspace_id: str) -> Path:
        d = self._base_path / "workspaces" / workspace_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _documents_dir(self, workspace_id: str) -> Path:
        d = self.workspace_dir(workspace_id) / "documents"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _chunks_dir(self, workspace_id: str) -> Path:
        d = self.workspace_dir(workspace_id) / "chunks"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _embeddings_dir(self, workspace_id: str) -> Path:
        d = self.workspace_dir(workspace_id) / "embeddings"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _document_path(self, workspace_id: str, document_id: str) -> Path:
        return self._documents_dir(workspace_id) / f"{document_id}.json"

    def _chunks_path(self, workspace_id: str, document_id: str) -> Path:
        return self._chunks_dir(workspace_id) / f"{document_id}.json"

    def _embeddings_path(self, workspace_id: str, document_id: str) -> Path:
        return self._embeddings_dir(workspace_id) / f"{document_id}.npy"

    def _url_index_path(self, workspace_id: str) -> Path:
        return self._documents_dir(workspace_id) / _URL_INDEX_FILE

    # ------------------------------------------------------------------ #
    # workspace
    # ------------------------------------------------------------------ #
    def save_workspace(self, ws: Workspace) -> None:
        path = self.workspace_dir(ws.workspace_id) / "workspace.json"
        atomic_write_json(path, ws.model_dump(mode="json"))

    def load_workspace(self, workspace_id: str) -> Workspace | None:
        path = self.workspace_dir(workspace_id) / "workspace.json"
        data = read_json(path)
        if data is None:
            return None
        return Workspace.model_validate(data)

    def list_workspaces(self) -> list[Workspace]:
        root = self._base_path / "workspaces"
        if not root.exists():
            return []
        out: list[Workspace] = []
        for d in sorted(root.iterdir()):
            if not d.is_dir():
                continue
            data = read_json(d / "workspace.json")
            if data is not None:
                out.append(Workspace.model_validate(data))
        return out

    def delete_workspace(self, workspace_id: str) -> None:
        """Recursively deletes the entire workspace directory (section 44)."""
        d = self._base_path / "workspaces" / workspace_id
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    # ------------------------------------------------------------------ #
    # documents
    # ------------------------------------------------------------------ #
    def save_document(self, doc: SourceDocument) -> None:
        path = self._document_path(doc.workspace_id, doc.document_id)
        atomic_write_json(path, doc.model_dump(mode="json"))

        # maintain url -> document_id index for change-detection reuse
        index_path = self._url_index_path(doc.workspace_id)
        index = read_json(index_path) or {}
        index[doc.url] = doc.document_id
        atomic_write_json(index_path, index)

    def load_document(self, workspace_id: str, document_id: str) -> SourceDocument | None:
        data = read_json(self._document_path(workspace_id, document_id))
        if data is None:
            return None
        return SourceDocument.model_validate(data)

    def list_documents(self, workspace_id: str) -> list[SourceDocument]:
        docs_dir = self._documents_dir(workspace_id)
        out: list[SourceDocument] = []
        for f in sorted(docs_dir.glob("*.json")):
            if f.name == _URL_INDEX_FILE:
                continue
            data = read_json(f)
            if data is not None:
                out.append(SourceDocument.model_validate(data))
        return out

    def delete_document(self, workspace_id: str, document_id: str) -> None:
        doc = self.load_document(workspace_id, document_id)

        doc_path = self._document_path(workspace_id, document_id)
        if doc_path.exists():
            doc_path.unlink()

        chunks_path = self._chunks_path(workspace_id, document_id)
        if chunks_path.exists():
            chunks_path.unlink()

        emb_path = self._embeddings_path(workspace_id, document_id)
        if emb_path.exists():
            emb_path.unlink()

        if doc is not None:
            index_path = self._url_index_path(workspace_id)
            index = read_json(index_path) or {}
            if index.get(doc.url) == document_id:
                del index[doc.url]
                atomic_write_json(index_path, index)

    def get_document_by_url(self, workspace_id: str, url: str) -> SourceDocument | None:
        index = read_json(self._url_index_path(workspace_id)) or {}
        document_id = index.get(url)
        if document_id is None:
            return None
        return self.load_document(workspace_id, document_id)

    # ------------------------------------------------------------------ #
    # chunks
    # ------------------------------------------------------------------ #
    def save_chunks(self, workspace_id: str, document_id: str, chunks: list[Chunk]) -> None:
        path = self._chunks_path(workspace_id, document_id)
        atomic_write_json(path, [c.model_dump(mode="json") for c in chunks])

    def load_chunks(self, workspace_id: str, document_id: str) -> list[Chunk]:
        data = read_json(self._chunks_path(workspace_id, document_id))
        if not data:
            return []
        return [Chunk.model_validate(item) for item in data]

    def load_all_chunks(self, workspace_id: str) -> list[Chunk]:
        chunks_dir = self._chunks_dir(workspace_id)
        out: list[Chunk] = []
        for f in sorted(chunks_dir.glob("*.json")):
            data = read_json(f)
            if data:
                out.extend(Chunk.model_validate(item) for item in data)
        return out

    # ------------------------------------------------------------------ #
    # embeddings (used by VectorStore to keep embeddings.npy in sync)
    # ------------------------------------------------------------------ #
    def save_embeddings(self, workspace_id: str, document_id: str, embeddings: list[list[float]]) -> None:
        import os
        import uuid

        arr = np.asarray(embeddings, dtype=np.float32)
        path = self._embeddings_path(workspace_id, document_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex}")
        # Write via an open file handle (not a filename) so numpy does not
        # try to append/guess a ".npy" suffix on the temp path.
        with open(tmp, "wb") as fh:
            np.save(fh, arr, allow_pickle=False)
        os.replace(tmp, path)

    def load_embeddings(self, workspace_id: str, document_id: str) -> np.ndarray | None:
        path = self._embeddings_path(workspace_id, document_id)
        if not path.exists():
            return None
        return np.load(path, allow_pickle=False)
