from app.rag.citations import compute_grounding_level, extract_citations
from app.schemas.models import Chunk, GroundingLevel, RetrievedChunk


def _rc(chunk_id: str, document_id: str, final_score: float) -> RetrievedChunk:
    chunk = Chunk(
        chunk_id=chunk_id,
        workspace_id="ws1",
        document_id=document_id,
        source_url=f"https://example.com/{document_id}",
        page_title=f"Title {document_id}",
        section="Intro",
        heading_path=["Intro"],
        chunk_index=0,
        content="Some retrieved content.",
        content_hash="abc123",
    )
    return RetrievedChunk(
        chunk=chunk,
        semantic_score=final_score,
        keyword_score=final_score,
        rerank_score=final_score,
        final_score=final_score,
    )


def test_extract_citations_only_includes_present_indices():
    chunks = [_rc("d1:0", "d1", 0.9), _rc("d2:0", "d2", 0.8), _rc("d3:0", "d3", 0.7)]
    answer = "The setup requires two steps [1] and a config change [2]."

    citations = extract_citations(answer, chunks)

    assert len(citations) == 2
    assert [c.index for c in citations] == [1, 2]
    assert citations[0].document_id == "d1"
    assert citations[1].document_id == "d2"
    # d3 was retrieved but never cited in the text -> must not appear.
    assert all(c.document_id != "d3" for c in citations)


def test_extract_citations_never_fabricates_out_of_range_index():
    chunks = [_rc("d1:0", "d1", 0.9)]
    answer = "This claims something from source [1] and also cites [5] which doesn't exist."

    citations = extract_citations(answer, chunks)

    assert len(citations) == 1
    assert citations[0].index == 1


def test_extract_citations_dedupes_repeated_markers():
    chunks = [_rc("d1:0", "d1", 0.9), _rc("d2:0", "d2", 0.8)]
    answer = "Point one [1]. Point two [1]. Point three [2]. Repeated again [1]."

    citations = extract_citations(answer, chunks)

    assert [c.index for c in citations] == [1, 2]


def test_extract_citations_empty_answer_or_no_chunks():
    chunks = [_rc("d1:0", "d1", 0.9)]
    assert extract_citations("", chunks) == []
    assert extract_citations("Some answer with [1].", []) == []


def test_grounding_level_high_with_strong_score_and_citations():
    chunks = [_rc("d1:0", "d1", 0.8)]
    citations = extract_citations("Answer [1].", chunks)
    assert compute_grounding_level(chunks, citations) == GroundingLevel.high


def test_grounding_level_insufficient_with_no_citations():
    chunks = [_rc("d1:0", "d1", 0.9)]
    assert compute_grounding_level(chunks, []) == GroundingLevel.insufficient


def test_grounding_level_insufficient_with_no_chunks():
    assert compute_grounding_level([], []) == GroundingLevel.insufficient


def test_grounding_level_moderate_for_mid_scores():
    chunks = [_rc("d1:0", "d1", 0.4)]
    citations = extract_citations("Answer [1].", chunks)
    assert compute_grounding_level(chunks, citations) == GroundingLevel.moderate
