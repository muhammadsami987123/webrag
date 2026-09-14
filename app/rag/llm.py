"""LLM provider abstraction (section 36). No hardcoded keys, no fake/offline provider."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.config import get_settings


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, system: str, user: str) -> str:
        """Generate a full completion for the given system/user prompts."""
        raise NotImplementedError

    @abstractmethod
    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        """Stream text deltas for the given system/user prompts."""
        raise NotImplementedError
        yield ""  # pragma: no cover - makes this an async generator for type checkers


class OpenAILLMProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def generate(self, system: str, user: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            stream=True,
        )
        async for event in stream:
            delta = event.choices[0].delta.content if event.choices else None
            if delta:
                yield delta


class GeminiLLMProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        self._genai = genai
        self._model_name = model
        self._model = genai.GenerativeModel(model_name=model)

    async def generate(self, system: str, user: str) -> str:
        import asyncio

        def _generate() -> str:
            model = self._genai.GenerativeModel(
                model_name=self._model_name, system_instruction=system
            )
            response = model.generate_content(user)
            return response.text or ""

        return await asyncio.to_thread(_generate)

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        import asyncio
        import queue as queue_module

        model = self._genai.GenerativeModel(
            model_name=self._model_name, system_instruction=system
        )

        q: queue_module.Queue = queue_module.Queue()
        _SENTINEL = object()

        def _run() -> None:
            try:
                response = model.generate_content(user, stream=True)
                for chunk in response:
                    if chunk.text:
                        q.put(chunk.text)
            finally:
                q.put(_SENTINEL)

        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(None, _run)

        while True:
            item = await asyncio.to_thread(q.get)
            if item is _SENTINEL:
                break
            yield item

        await future


def get_llm_provider() -> LLMProvider:
    """Factory that reads settings.llm_provider and constructs the LLM provider.

    Raises a clear, descriptive exception if no API key is configured for the
    selected provider. There is no fake/offline LLM provider by design.
    """
    settings = get_settings()
    provider = (settings.llm_provider or "openai").lower()

    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError(
                "LLM_PROVIDER is 'openai' but OPENAI_API_KEY is not configured. "
                "Set OPENAI_API_KEY in the environment, or set LLM_PROVIDER=gemini "
                "with GEMINI_API_KEY instead."
            )
        return OpenAILLMProvider(api_key=settings.openai_api_key, model=settings.llm_model)

    if provider == "gemini":
        if not settings.gemini_api_key:
            raise ValueError(
                "LLM_PROVIDER is 'gemini' but GEMINI_API_KEY is not configured. "
                "Set GEMINI_API_KEY in the environment, or set LLM_PROVIDER=openai "
                "with OPENAI_API_KEY instead."
            )
        return GeminiLLMProvider(api_key=settings.gemini_api_key, model=settings.llm_model)

    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")
