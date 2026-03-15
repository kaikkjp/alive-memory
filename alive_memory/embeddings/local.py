"""Local embedding model using a simple hash-based approach.

This is a fallback for when no external embedding API is available.
Not suitable for production semantic search — use OpenAI or similar.
"""

from __future__ import annotations

import hashlib
import math


class LocalEmbeddingProvider:
    """Hash-based local embedding provider.

    Produces deterministic embeddings based on text content.
    Useful for testing and development. For production, use
    OpenAIEmbeddingProvider or a sentence-transformer model.
    """

    def __init__(self, dimensions: int = 384):
        self._dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        """Generate a deterministic embedding from text hash."""
        return _hash_embed(text, self._dimensions)

    @property
    def dimensions(self) -> int:
        return self._dimensions


def _hash_embed(text: str, dims: int) -> list[float]:
    """Create a deterministic embedding by hashing text in chunks.

    Produces a unit-norm vector of the given dimensionality.
    Words that overlap will have higher cosine similarity.
    """
    vector = [0.0] * dims

    # Hash individual words and their bigrams for overlap sensitivity
    words = text.lower().split()
    tokens = words + [f"{a} {b}" for a, b in zip(words, words[1:], strict=False)]

    for token in tokens:
        h = hashlib.sha256(token.encode()).digest()
        for i in range(min(dims, len(h))):
            # Map each byte to [-1, 1] and accumulate
            vector[i % dims] += (h[i] / 128.0) - 1.0

    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vector))
    if norm > 0:
        vector = [x / norm for x in vector]

    return vector
