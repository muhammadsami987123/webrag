from app.rag.reranking import LexicalOverlapReranker
from app.rag.retrieval import hybrid_retrieve, normalize_query
from app.schemas.models import Chunk


def _chunk(chunk_id: str, document_id: str, content: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        workspace_id="ws1",
        document_id=document_id,
        source_url=f"https://example.com/{document_id}",
        page_title=f"Title {document_id}",
        section="Intro",
        heading_path=["Intro"],
        chunk_index=0,
        content=content,
        content_hash="hash",
    )


class FakeEmbedder:
    dimension = 3

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Deterministic fake vector, content doesn't matter for this test
        # since the fake store ignores the vector and returns fixed scores.
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeVectorStore:
    """In-memory VectorStoreLike fake with overlapping results between the
    semantic and keyword search paths, to exercise merge/dedupe logic."""

    def __init__(self):
        self.chunk_a = _chunk("d1:0", "d1", "Authentication guide explains API keys and OAuth tokens.")
        self.chunk_b = _chunk("d2:0", "d2", "Billing FAQ covers invoices and payment methods.")
        self.chunk_c = _chunk("d3:0", "d3", "Rate limiting section describes request quotas.")

    async def search(self, workspace_id, query_vector, top_k, source_ids):
        # Semantic search: returns A (high), B (low). Restricts to source_ids
        # if provided.
        results = [(self.chunk_a, 0.95), (self.chunk_b, 0.40)]
        if source_ids is not None:
            results = [(c, s) for c, s in results if c.document_id in source_ids]
        return results[:top_k]

    async def keyword_search(self, workspace_id, query, top_k, source_ids):
        # Lexical search: returns A again (overlap -> must be deduped) plus C.
        results = [(self.chunk_a, 5.0), (self.chunk_c, 2.0)]
        if source_ids is not None:
            results = [(c, s) for c, s in results if c.document_id in source_ids]
        return results[:top_k]


def test_normalize_query_collapses_whitespace():
    assert normalize_query("  What   is  the\n rate limit?  ") == "What is the rate limit?"
    assert normalize_query("") == ""


async def test_hybrid_retrieve_merges_and_dedupes():
    store = FakeVectorStore()
    embedder = FakeEmbedder()
    reranker = LexicalOverlapReranker()

    results = await hybrid_retrieve(
        store=store,
        embedder=embedder,
        reranker=reranker,
        workspace_id="ws1",
        query="authentication API keys",
        top_k=5,
        candidate_k=10,
    )

    ids = [rc.chunk.chunk_id for rc in results]
    # chunk_a appeared in both semantic and keyword results -> must appear once only.
    assert ids.count("d1:0") == 1
    # All three unique chunks should be present since candidate_k is generous.
    assert set(ids) == {"d1:0", "d2:0", "d3:0"}

    # Results must be sorted descending by final_score.
    scores = [rc.final_score for rc in results]
    assert scores == sorted(scores, reverse=True)

    # chunk_a had both a strong semantic and strong keyword signal -> should
    # combine to be at or near the top before/after rerank influences order.
    a_result = next(rc for rc in results if rc.chunk.chunk_id == "d1:0")
    assert a_result.semantic_score == 0.95
    assert a_result.keyword_score == 5.0
    assert a_result.rerank_score is not None
    assert a_result.final_score == a_result.rerank_score


async def test_hybrid_retrieve_respects_source_ids_filter():
    store = FakeVectorStore()
    embedder = FakeEmbedder()
    reranker = LexicalOverlapReranker()

    results = await hybrid_retrieve(
        store=store,
        embedder=embedder,
        reranker=reranker,
        workspace_id="ws1",
        query="authentication",
        top_k=5,
        candidate_k=10,
        source_ids=["d1"],
    )

    ids = {rc.chunk.chunk_id for rc in results}
    assert ids == {"d1:0"}


async def test_hybrid_retrieve_respects_top_k():
    store = FakeVectorStore()
    embedder = FakeEmbedder()
    reranker = LexicalOverlapReranker()

    results = await hybrid_retrieve(
        store=store,
        embedder=embedder,
        reranker=reranker,
        workspace_id="ws1",
        query="authentication API keys",
        top_k=1,
        candidate_k=10,
    )

    assert len(results) == 1


async def test_hybrid_retrieve_empty_query_returns_empty():
    store = FakeVectorStore()
    embedder = FakeEmbedder()
    reranker = LexicalOverlapReranker()

    results = await hybrid_retrieve(
        store=store,
        embedder=embedder,
        reranker=reranker,
        workspace_id="ws1",
        query="   ",
        top_k=5,
        candidate_k=10,
    )

    assert results == []
