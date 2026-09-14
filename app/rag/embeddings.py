"""Provider-abstracted embedding service (section 9/36).

Supports OpenAI, Gemini, and a local sentence-transformers fallback so the
app is fully runnable/testable with no API keys configured.
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod

from app.config import get_settings


class EmbeddingProvider(ABC):
    """Abstract embedding provider."""

    dimension: int

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts, returning one vector per input text."""
        raise NotImplementedError


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self, api_key: str, model: str, dimension: int):
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model
        self.dimension = dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.embeddings.create(model=self._model, input=texts)
        return [item.embedding for item in response.data]


class GeminiEmbeddingProvider(EmbeddingProvider):
    def __init__(self, api_key: str, model: str, dimension: int):
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        self._genai = genai
        self._model = model if model.startswith("models/") else f"models/{model}"
        self.dimension = dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        import asyncio

        def _embed_one(text: str) -> list[float]:
            result = self._genai.embed_content(model=self._model, content=text)
            return list(result["embedding"])

        return await asyncio.gather(*(asyncio.to_thread(_embed_one, t) for t in texts))


class LocalEmbeddingProvider(EmbeddingProvider):
    """Free local fallback using sentence-transformers. Works with no API key."""

    _model_lock = threading.Lock()
    _model_cache: dict[str, object] = {}

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self._model_name = model_name
        self._model = self._load_model(model_name)
        self.dimension = int(self._model.get_sentence_embedding_dimension())

    @classmethod
    def _load_model(cls, model_name: str):
        with cls._model_lock:
            if model_name not in cls._model_cache:
                from sentence_transformers import SentenceTransformer

                cls._model_cache[model_name] = SentenceTransformer(model_name)
            return cls._model_cache[model_name]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        import asyncio

        def _encode() -> list[list[float]]:
            vectors = self._model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
            return [vector.tolist() for vector in vectors]

        return await asyncio.to_thread(_encode)


def get_embedding_provider() -> EmbeddingProvider:
    """Factory that reads settings.embedding_provider and constructs the provider.

    Raises a clear error only when a cloud provider is selected but its API
    key is missing. The local provider always works, with no key required.
    """
    settings = get_settings()
    provider = (settings.embedding_provider or "local").lower()

    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError(
                "EMBEDDING_PROVIDER is 'openai' but OPENAI_API_KEY is not configured. "
                "Set OPENAI_API_KEY, or set EMBEDDING_PROVIDER=local to use the free "
                "local embedding model instead."
            )
        return OpenAIEmbeddingProvider(
            api_key=settings.openai_api_key,
            model=settings.embedding_model,
            dimension=settings.embedding_dim,
        )

    if provider == "gemini":
        if not settings.gemini_api_key:
            raise ValueError(
                "EMBEDDING_PROVIDER is 'gemini' but GEMINI_API_KEY is not configured. "
                "Set GEMINI_API_KEY, or set EMBEDDING_PROVIDER=local to use the free "
                "local embedding model instead."
            )
        return GeminiEmbeddingProvider(
            api_key=settings.gemini_api_key,
            model=settings.embedding_model,
            dimension=settings.embedding_dim,
        )

    if provider == "local":
        return LocalEmbeddingProvider()

    raise ValueError(f"Unknown EMBEDDING_PROVIDER: {settings.embedding_provider!r}")
