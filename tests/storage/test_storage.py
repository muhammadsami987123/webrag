"""Tests for app.storage.document_store / vector_store / metadata_store.

Uses tmp_path-injected base_path constructors so nothing touches real
storage/ on disk.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.schemas.models import Chunk, ChatMessage, SourceDocument, Workspace
from app.storage.document_store import DocumentStore
from app.storage.metadata_store import MetadataStore
from app.storage.vector_store import VectorStore


def make_workspace(workspace_id: str = "ws1") -> Workspace:
    return Workspace(workspace_id=workspace_id, root_url="https://example.com")


def make_document(workspace_id: str, document_id: str, url: str, content_hash: str = "h1") -> SourceDocument:
    return SourceDocument(
        document_id=document_id,
        workspace_id=workspace_id,
        url=url,
        title=f"Title {document_id}",
        content="hello world " * 10,
        content_hash=content_hash,
    )


def make_chunk(workspace_id: str, document_id: str, chunk_id: str, index: int, content: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        workspace_id=workspace_id,
        document_id=document_id,
        source_url=f"https://example.com/{document_id}",
        page_title="Title",
        chunk_index=index,
        content=content,
    )


# --------------------------------------------------------------------- #
# DocumentStore
# --------------------------------------------------------------------- #
def test_workspace_round_trip(tmp_path):
    store = DocumentStore(base_path=tmp_path)
    ws = make_workspace()
    store.save_workspace(ws)

    loaded = store.load_workspace("ws1")
    assert loaded is not None
    assert loaded.workspace_id == "ws1"
    assert loaded.root_url == "https://example.com"

    all_ws = store.list_workspaces()
    assert len(all_ws) == 1
    assert all_ws[0].workspace_id == "ws1"


def test_workspace_delete_leaves_no_files(tmp_path):
    store = DocumentStore(base_path=tmp_path)
    ws = make_workspace()
    store.save_workspace(ws)
    doc = make_document("ws1", "d1", "https://example.com/a")
    store.save_document(doc)
    store.save_chunks("ws1", "d1", [make_chunk("ws1", "d1", "c1", 0, "hello")])
    store.save_embeddings("ws1", "d1", [[0.1, 0.2, 0.3]])

    ws_dir = tmp_path / "workspaces" / "ws1"
    assert ws_dir.exists()

    store.delete_workspace("ws1")
    assert not ws_dir.exists()
    assert store.load_workspace("ws1") is None


def test_document_and_chunk_round_trip(tmp_path):
    store = DocumentStore(base_path=tmp_path)
    doc = make_document("ws1", "d1", "https://example.com/a")
    store.save_document(doc)

    loaded_doc = store.load_document("ws1", "d1")
    assert loaded_doc is not None
    assert loaded_doc.url == "https://example.com/a"

    by_url = store.get_document_by_url("ws1", "https://example.com/a")
    assert by_url is not None
    assert by_url.document_id == "d1"

    chunks = [make_chunk("ws1", "d1", f"c{i}", i, f"content {i}") for i in range(3)]
    store.save_chunks("ws1", "d1", chunks)
    loaded_chunks = store.load_chunks("ws1", "d1")
    assert [c.chunk_id for c in loaded_chunks] == ["c0", "c1", "c2"]

    doc2 = make_document("ws1", "d2", "https://example.com/b")
    store.save_document(doc2)
    store.save_chunks("ws1", "d2", [make_chunk("ws1", "d2", "e0", 0, "other")])

    all_chunks = store.load_all_chunks("ws1")
    assert {c.chunk_id for c in all_chunks} == {"c0", "c1", "c2", "e0"}

    all_docs = store.list_documents("ws1")
    assert {d.document_id for d in all_docs} == {"d1", "d2"}


def test_delete_document_removes_chunks_and_embeddings(tmp_path):
    store = DocumentStore(base_path=tmp_path)
    doc = make_document("ws1", "d1", "https://example.com/a")
    store.save_document(doc)
    store.save_chunks("ws1", "d1", [make_chunk("ws1", "d1", "c1", 0, "hello")])
    store.save_embeddings("ws1", "d1", [[0.1, 0.2]])

    store.delete_document("ws1", "d1")

    assert store.load_document("ws1", "d1") is None
    assert store.load_chunks("ws1", "d1") == []
    assert store.load_embeddings("ws1", "d1") is None
    assert store.get_document_by_url("ws1", "https://example.com/a") is None


# --------------------------------------------------------------------- #
# VectorStore
# --------------------------------------------------------------------- #
def _unit(vec: list[float]) -> list[float]:
    arr = np.asarray(vec, dtype=np.float32)
    return (arr / np.linalg.norm(arr)).tolist()


@pytest.mark.asyncio
async def test_add_chunks_and_search_top_results(tmp_path):
    doc_store = DocumentStore(base_path=tmp_path)
    vs = VectorStore(base_path=tmp_path, document_store=doc_store)

    chunks = [
        make_chunk("ws1", "d1", "c0", 0, "the quick brown fox"),
        make_chunk("ws1", "d1", "c1", 1, "jumps over the lazy dog"),
        make_chunk("ws1", "d1", "c2", 2, "completely unrelated content"),
    ]
    embeddings = [
        _unit([1.0, 0.0, 0.0]),
        _unit([0.9, 0.1, 0.0]),
        _unit([0.0, 0.0, 1.0]),
    ]
    await vs.add_chunks("ws1", chunks, embeddings)

    # embeddings.npy persisted
    saved = doc_store.load_embeddings("ws1", "d1")
    assert saved is not None
    assert saved.shape == (3, 3)

    results = await vs.search("ws1", _unit([1.0, 0.0, 0.0]), top_k=2)
    assert len(results) == 2
    result_ids = [c.chunk_id for c, _ in results]
    assert result_ids[0] == "c0"
    assert "c2" not in result_ids
    # cosine similarity scores, best match near 1.0
    assert results[0][1] == pytest.approx(1.0, abs=1e-4)


@pytest.mark.asyncio
async def test_search_source_ids_filters_by_document(tmp_path):
    vs = VectorStore(base_path=tmp_path)

    chunks_d1 = [make_chunk("ws1", "d1", "a0", 0, "alpha")]
    chunks_d2 = [make_chunk("ws1", "d2", "b0", 0, "beta")]
    await vs.add_chunks("ws1", chunks_d1, [_unit([1.0, 0.0])])
    await vs.add_chunks("ws1", chunks_d2, [_unit([0.99, 0.01])])

    results = await vs.search("ws1", _unit([1.0, 0.0]), top_k=5, source_ids=["d2"])
    assert len(results) == 1
    assert results[0][0].document_id == "d2"


@pytest.mark.asyncio
async def test_keyword_search_finds_lexical_matches(tmp_path):
    doc_store = DocumentStore(base_path=tmp_path)
    vs = VectorStore(base_path=tmp_path, document_store=doc_store)

    doc_store.save_chunks(
        "ws1",
        "d1",
        [
            make_chunk("ws1", "d1", "c0", 0, "faiss vector search is fast"),
            make_chunk("ws1", "d1", "c1", 1, "bm25 keyword search is lexical"),
            make_chunk("ws1", "d1", "c2", 2, "completely unrelated banana content"),
        ],
    )

    results = await vs.keyword_search("ws1", "keyword search", top_k=5)
    assert results, "expected at least one lexical match"
    top_chunk_ids = [c.chunk_id for c, _ in results]
    assert "c1" in top_chunk_ids
    assert top_chunk_ids[0] == "c1"


@pytest.mark.asyncio
async def test_remove_document_and_rebuild(tmp_path):
    doc_store = DocumentStore(base_path=tmp_path)
    vs = VectorStore(base_path=tmp_path, document_store=doc_store)

    doc_store.save_document(make_document("ws1", "d1", "https://example.com/a"))
    doc_store.save_document(make_document("ws1", "d2", "https://example.com/b"))

    await vs.add_chunks("ws1", [make_chunk("ws1", "d1", "c0", 0, "alpha")], [_unit([1.0, 0.0])])
    await vs.add_chunks("ws1", [make_chunk("ws1", "d2", "c1", 0, "beta")], [_unit([0.0, 1.0])])

    await vs.remove_document("ws1", "d1")
    results = await vs.search("ws1", _unit([1.0, 0.0]), top_k=5)
    assert all(c.document_id != "d1" for c, _ in results)

    # simulate the doc's on-disk chunk/embedding files also being deleted
    doc_store.delete_document("ws1", "d1")

    await vs.rebuild("ws1")
    results_after_rebuild = await vs.search("ws1", _unit([0.0, 1.0]), top_k=5)
    assert len(results_after_rebuild) == 1
    assert results_after_rebuild[0][0].document_id == "d2"


# --------------------------------------------------------------------- #
# MetadataStore
# --------------------------------------------------------------------- #
def test_notes_highlights_collections(tmp_path):
    store = MetadataStore(base_path=tmp_path)

    note = store.add_note("ws1", text="a note")
    assert note["id"]
    assert store.list_notes("ws1")[0]["text"] == "a note"
    store.delete_note("ws1", note["id"])
    assert store.list_notes("ws1") == []

    store.add_highlight("ws1", text="highlighted text", chunk_id="c0")
    assert len(store.list_highlights("ws1")) == 1

    store.add_collection("ws1", name="My Collection", document_ids=["d1"])
    assert store.list_collections("ws1")[0]["name"] == "My Collection"


def test_chat_history_round_trip(tmp_path):
    store = MetadataStore(base_path=tmp_path)
    msg = ChatMessage(role="user", content="hello")
    store.save_chat_message("ws1", "conv1", msg)
    store.save_chat_message("ws1", "conv1", ChatMessage(role="assistant", content="hi there"))

    history = store.load_chat_history("ws1", "conv1")
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[1].content == "hi there"


def test_snapshot_diff_detects_new_changed_removed(tmp_path):
    store = MetadataStore(base_path=tmp_path)

    docs_v1 = [
        make_document("ws1", "d1", "https://example.com/a", content_hash="hash_a1"),
        make_document("ws1", "d2", "https://example.com/b", content_hash="hash_b1"),
    ]
    store.save_snapshot("ws1", docs_v1)

    docs_v2 = [
        make_document("ws1", "d1", "https://example.com/a", content_hash="hash_a1"),  # unchanged
        make_document("ws1", "d2", "https://example.com/b", content_hash="hash_b2"),  # changed
        make_document("ws1", "d3", "https://example.com/c", content_hash="hash_c1"),  # new
        # https://example.com/... nothing removed except implicitly none here
    ]

    diff = store.diff_against_last_snapshot("ws1", docs_v2)
    assert diff["new"] == ["https://example.com/c"]
    assert diff["changed"] == ["https://example.com/b"]
    assert diff["unchanged_count"] == 1
    assert diff["removed"] == []

    # now simulate url a being removed entirely
    docs_v3 = [docs_v2[1], docs_v2[2]]
    store.save_snapshot("ws1", docs_v2)
    diff2 = store.diff_against_last_snapshot("ws1", docs_v3)
    assert diff2["removed"] == ["https://example.com/a"]
    assert diff2["new"] == []
    assert diff2["unchanged_count"] == 2
