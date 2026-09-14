"""Citation extraction and grounding-level computation (sections 15, 34, 35)."""
from __future__ import annotations

import re

from app.schemas.models import Citation, GroundingLevel, RetrievedChunk

_CITATION_MARKER_RE = re.compile(r"\[(\d+)\]")

# Thresholds for evidence-based grounding (section 35): based on retrieval
# scores, not LLM self-report.
_HIGH_SCORE_THRESHOLD = 0.55
_MODERATE_SCORE_THRESHOLD = 0.3


def extract_citations(answer_text: str, chunks: list[RetrievedChunk]) -> list[Citation]:
    """Parse [n] markers actually present in answer_text and map ONLY those
    indices to the corresponding numbered context chunk. Never fabricates a
    citation for an index that wasn't in the numbered context, and never
    includes a source that wasn't retrieved.
    """
    if not answer_text or not chunks:
        return []

    found_indices: list[int] = []
    seen: set[int] = set()
    for match in _CITATION_MARKER_RE.finditer(answer_text):
        idx = int(match.group(1))
        if idx not in seen:
            seen.add(idx)
            found_indices.append(idx)

    citations: list[Citation] = []
    for idx in found_indices:
        # Context blocks are 1-indexed in the prompt; map back to the list.
        if idx < 1 or idx > len(chunks):
            continue  # never fabricate a citation for an index not in context
        rc = chunks[idx - 1]
        chunk = rc.chunk
        citations.append(
            Citation(
                index=idx,
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                title=chunk.page_title,
                url=chunk.source_url,
                section=chunk.section,
                score=rc.final_score,
            )
        )

    return citations


def compute_grounding_level(
    chunks: list[RetrievedChunk], citations: list[Citation]
) -> GroundingLevel:
    """Determine grounding level from retrieval evidence (top scores and
    whether any citations were actually produced), not the LLM's self-report.
    """
    if not chunks or not citations:
        return GroundingLevel.insufficient

    top_score = max((rc.final_score for rc in chunks), default=0.0)

    if top_score >= _HIGH_SCORE_THRESHOLD and len(citations) >= 1:
        return GroundingLevel.high
    if top_score >= _MODERATE_SCORE_THRESHOLD:
        return GroundingLevel.moderate
    return GroundingLevel.insufficient
