"""Embedding provider protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for embedding text into vectors."""

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for the given text."""
        ...

    @property
    def dimensions(self) -> int:
        """Number of dimensions in the embedding vectors."""
        ...
