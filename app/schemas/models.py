"""Shared Pydantic schemas used across crawler, RAG pipeline, storage and API layers.

This module is the contract between all subsystems — do not duplicate these
shapes elsewhere; import from here.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class CrawlScope(str, Enum):
    single_page = "single_page"
    linked_pages = "linked_pages"
    entire_domain = "entire_domain"
    selected_path = "selected_path"


class WorkspaceStatus(str, Enum):
    pending = "pending"
    crawling = "crawling"
    extracting = "extracting"
    processing = "processing"
    embedding = "embedding"
    ready = "ready"
    failed = "failed"


class CrawlConfig(BaseModel):
    scope: CrawlScope = CrawlScope.linked_pages
    max_pages: int = 25
    max_depth: int = 2
    allowed_path_prefix: str | None = None
    content_types: list[str] = Field(default_factory=lambda: ["articles", "documentation", "general"])


class Workspace(BaseModel):
    workspace_id: str
    root_url: str
    title: str | None = None
    status: WorkspaceStatus = WorkspaceStatus.pending
    crawl_config: CrawlConfig = Field(default_factory=CrawlConfig)
    pages_discovered: int = 0
    pages_processed: int = 0
    chunks_created: int = 0
    embeddings_created: int = 0
    topics: list[str] = Field(default_factory=list)
    error: str | None = None
    index_version: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_indexed_at: datetime | None = None


class Heading(BaseModel):
    level: int
    text: str


class SourceDocument(BaseModel):
    document_id: str
    workspace_id: str
    url: str
    canonical_url: str | None = None
    title: str
    content: str
    headings: list[Heading] = Field(default_factory=list)
    breadcrumbs: list[str] = Field(default_factory=list)
    source_type: Literal["webpage", "documentation"] = "webpage"
    word_count: int = 0
    content_hash: str = ""
    published_at: str | None = None
    modified_at: str | None = None
    status: Literal["indexed", "changed", "removed", "failed"] = "indexed"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Chunk(BaseModel):
    chunk_id: str
    workspace_id: str
    document_id: str
    source_url: str
    page_title: str
    section: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    chunk_index: int
    content: str
    content_hash: str = ""


class RetrievedChunk(BaseModel):
    chunk: Chunk
    semantic_score: float = 0.0
    keyword_score: float = 0.0
    rerank_score: float | None = None
    final_score: float = 0.0


class Citation(BaseModel):
    index: int
    document_id: str
    chunk_id: str
    title: str
    url: str
    section: str | None = None
    score: float = 0.0


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    citations: list[Citation] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ResearchMode(str, Enum):
    ask = "ask"
    research = "research"
    compare = "compare"
    summarize = "summarize"
    explain = "explain"
    extract = "extract"


class ChatRequest(BaseModel):
    workspace_id: str
    message: str
    mode: ResearchMode = ResearchMode.ask
    source_ids: list[str] | None = None  # None = entire knowledge base
    conversation_id: str = "default"


class GroundingLevel(str, Enum):
    high = "high"
    moderate = "moderate"
    insufficient = "insufficient"


class DebugInfo(BaseModel):
    query: str
    retrieved: list[RetrievedChunk] = Field(default_factory=list)
    context: str = ""


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    grounding: GroundingLevel = GroundingLevel.moderate
    debug: DebugInfo | None = None
