"""API-based embeddings (OpenAI, etc.)."""

from __future__ import annotations

import os


class OpenAIEmbeddingProvider:
    """Embedding provider using OpenAI's embedding API.

    Usage:
        provider = OpenAIEmbeddingProvider(api_key="sk-...")
        vector = await provider.embed("Hello world")
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "text-embedding-3-small",
    ):
        try:
            import openai
        except ImportError:
            raise ImportError(
                "openai package required: pip install openai"
            )
        self._client = openai.AsyncOpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY")
        )
        self._model = model
        # Dimension map for known models
        self._dim_map = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
        )
        return response.data[0].embedding

    @property
    def dimensions(self) -> int:
        return self._dim_map.get(self._model, 1536)
