"""Chat/research orchestration: retrieval -> grounded prompting -> LLM,
plus mode-specific helpers (summarize/compare/extract/topics/suggestions)
used by the corresponding API routers.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any, AsyncIterator

from app.config import get_settings
from app.rag.citations import compute_grounding_level, extract_citations
from app.rag.embeddings import get_embedding_provider
from app.rag.llm import get_llm_provider
from app.rag.prompting import build_context_block, build_system_prompt, build_user_prompt
from app.rag.reranking import get_reranker
from app.rag.retrieval import hybrid_retrieve, normalize_query
from app.schemas.models import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    DebugInfo,
    GroundingLevel,
    ResearchMode,
    RetrievedChunk,
)
from app.storage.document_store import DocumentStore
from app.storage.metadata_store import MetadataStore
from app.storage.vector_store import VectorStore

logger = logging.getLogger(__name__)

_document_store = DocumentStore()
_metadata_store = MetadataStore()
_vector_store = VectorStore(document_store=_document_store)

_HISTORY_LIMIT = 6


async def _retrieve(workspace_id: str, query: str, source_ids: list[str] | None) -> list[RetrievedChunk]:
    settings = get_settings()
    embedder = get_embedding_provider()
    reranker = get_reranker()
    return await hybrid_retrieve(
        _vector_store,
        embedder,
        reranker,
        workspace_id,
        query,
        top_k=settings.retrieval_top_k,
        candidate_k=settings.retrieval_candidate_k,
        source_ids=source_ids,
    )


async def answer_question(req: ChatRequest, stream: bool = False, debug: bool = False):
    """Answer a chat request. If stream=False, returns a ChatResponse. If
    stream=True, returns an async generator that yields text deltas and
    finally a dict sentinel {"citations": [...], "grounding": ..., "answer": ...}."""
    query = normalize_query(req.message)
    history = _metadata_store.load_chat_history(req.workspace_id, req.conversation_id)
    recent_history = history[-_HISTORY_LIMIT:] if history else None

    chunks = await _retrieve(req.workspace_id, query, req.source_ids)
    context = build_context_block(chunks)
    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(query, context, req.mode, conversation_history=recent_history)

    llm = get_llm_provider()

    user_message = ChatMessage(role="user", content=req.message)

    if not stream:
        answer = await llm.generate(system_prompt, user_prompt)
        citations = extract_citations(answer, chunks)
        grounding = compute_grounding_level(chunks, citations)

        _metadata_store.save_chat_message(req.workspace_id, req.conversation_id, user_message)
        assistant_message = ChatMessage(role="assistant", content=answer, citations=citations)
        _metadata_store.save_chat_message(req.workspace_id, req.conversation_id, assistant_message)

        debug_info = None
        if debug:
            debug_info = DebugInfo(query=query, retrieved=chunks, context=context)

        return ChatResponse(answer=answer, citations=citations, grounding=grounding, debug=debug_info)

    async def _stream_gen() -> AsyncIterator[Any]:
        accumulated: list[str] = []
        async for delta in llm.stream(system_prompt, user_prompt):
            accumulated.append(delta)
            yield delta

        full_answer = "".join(accumulated)
        citations = extract_citations(full_answer, chunks)
        grounding = compute_grounding_level(chunks, citations)

        _metadata_store.save_chat_message(req.workspace_id, req.conversation_id, user_message)
        assistant_message = ChatMessage(role="assistant", content=full_answer, citations=citations)
        _metadata_store.save_chat_message(req.workspace_id, req.conversation_id, assistant_message)

        yield {
            "done": True,
            "answer": full_answer,
            "citations": [c.model_dump(mode="json") for c in citations],
            "grounding": grounding.value,
        }

    return _stream_gen()


async def _grounded_llm_call(workspace_id: str, query: str, mode: ResearchMode, document_ids: list[str] | None = None) -> ChatResponse:
    chunks = await _retrieve(workspace_id, query, document_ids)
    context = build_context_block(chunks)
    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(query, context, mode)

    llm = get_llm_provider()
    answer = await llm.generate(system_prompt, user_prompt)
    citations = extract_citations(answer, chunks)
    grounding = compute_grounding_level(chunks, citations)
    return ChatResponse(answer=answer, citations=citations, grounding=grounding)


async def summarize_sources(
    workspace_id: str, document_ids: list[str] | None = None, hierarchical: bool = True
) -> ChatResponse:
    """Real grounded LLM summarization over the given (or all) documents."""
    if document_ids:
        titles = []
        for doc_id in document_ids:
            doc = _document_store.load_document(workspace_id, doc_id)
            if doc:
                titles.append(doc.title)
        query = "Summarize the following sources: " + ", ".join(titles) if titles else "Summarize the indexed content."
    else:
        query = "Summarize everything covered on this website."
    return await _grounded_llm_call(workspace_id, query, ResearchMode.summarize, document_ids)


async def compare_topics(workspace_id: str, query: str) -> ChatResponse:
    """Real grounded LLM comparison call."""
    return await _grounded_llm_call(workspace_id, query, ResearchMode.compare)


async def extract_structured(workspace_id: str, query: str) -> ChatResponse:
    """Real grounded LLM structured-extraction call."""
    return await _grounded_llm_call(workspace_id, query, ResearchMode.extract)


async def list_topics(workspace_id: str) -> list[str]:
    from app.services.workspace_service import get_workspace

    workspace = get_workspace(workspace_id)
    if workspace is None:
        return []
    return workspace.topics


async def get_ask_suggestions(workspace_id: str) -> list[str]:
    """Fast heuristic: derive ~6 questions from the workspace's actual
    topics/heading text, no LLM round trip."""
    from app.services.workspace_service import get_workspace

    workspace = get_workspace(workspace_id)
    topics = list(workspace.topics) if workspace else []

    if not topics:
        documents = _document_store.list_documents(workspace_id)
        counter: Counter[str] = Counter()
        for doc in documents:
            for heading in doc.headings:
                if heading.level in (1, 2) and heading.text.strip():
                    counter[heading.text.strip()] += 1
        topics = [t for t, _ in counter.most_common(6)]

    suggestions: list[str] = ["What is this website about?"]
    for topic in topics[:4]:
        suggestions.append(f"What does this site say about {topic}?")
    suggestions.append("Summarize the key points across all indexed pages.")

    return suggestions[:6]
