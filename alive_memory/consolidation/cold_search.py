"""Cold search — find echoes from the cold archive during sleep.

During full consolidation, each day moment is searched against
the cold embedding archive to find "cold echoes" — older memories
that resonate with today's experiences.

Used during sleep only. NOT used for real-time recall.
"""

from __future__ import annotations

import logging

from alive_memory.embeddings.base import EmbeddingProvider
from alive_memory.storage.base import BaseStorage
from alive_memory.types import DayMoment

logger = logging.getLogger(__name__)


async def find_cold_echoes(
    moment: DayMoment,
    storage: BaseStorage,
    embedder: EmbeddingProvider,
    *,
    limit: int = 3,
    min_score: float = 0.3,
) -> list[dict]:
    """Search cold archive for memories that echo a day moment.

    Args:
        moment: The day moment to find echoes for.
        storage: Storage backend (for cold_embeddings table).
        embedder: Embedding provider to vectorize the moment.
        limit: Max echoes to return.
        min_score: Minimum cosine similarity to qualify as an echo.

    Returns:
        List of cold echo dicts with keys: id, content, score, metadata.
    """
    try:
        embed_text = moment.content[:7000] if len(moment.content) > 7000 else moment.content
        embedding = await embedder.embed(embed_text)
    except Exception:
        logger.warning("Failed to embed moment for cold search: %s", moment.id, exc_info=True)
        return []

    results = await storage.search_cold(embedding=embedding, limit=limit)

    # Filter by minimum score
    echoes = [r for r in results if r.get("score", 0) >= min_score]
    return echoes
