"""Central application configuration, loaded from environment variables."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="development", alias="APP_ENV")

    # LLM
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    llm_model: str = Field(default="gpt-4o-mini", alias="LLM_MODEL")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")

    # Embeddings
    embedding_provider: str = Field(default="local", alias="EMBEDDING_PROVIDER")
    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")
    embedding_dim: int = Field(default=1536, alias="EMBEDDING_DIM")

    # Reranker
    reranker_provider: str = Field(default="local", alias="RERANKER_PROVIDER")

    # Crawler
    max_crawl_pages: int = Field(default=50, alias="MAX_CRAWL_PAGES")
    max_crawl_depth: int = Field(default=3, alias="MAX_CRAWL_DEPTH")
    request_timeout: float = Field(default=10.0, alias="REQUEST_TIMEOUT")
    crawl_rate_limit_per_sec: float = Field(default=2.0, alias="CRAWL_RATE_LIMIT_PER_SEC")
    max_response_bytes: int = Field(default=5_000_000, alias="MAX_RESPONSE_BYTES")

    # Storage
    storage_path: str = Field(default="storage", alias="STORAGE_PATH")

    # Chunking
    chunk_size: int = Field(default=800, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=120, alias="CHUNK_OVERLAP")

    # Retrieval
    retrieval_top_k: int = Field(default=8, alias="RETRIEVAL_TOP_K")
    retrieval_candidate_k: int = Field(default=30, alias="RETRIEVAL_CANDIDATE_K")

    @property
    def storage_root(self) -> Path:
        p = Path(self.storage_path)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def workspace_dir(self, workspace_id: str) -> Path:
        d = self.storage_root / "workspaces" / workspace_id
        d.mkdir(parents=True, exist_ok=True)
        return d


@lru_cache
def get_settings() -> Settings:
    return Settings()
