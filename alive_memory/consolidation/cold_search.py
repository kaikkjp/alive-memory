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
from alive_memory.types import ColdEntryType, DayMoment

logger = logging.getLogger(__name__)


async def find_cold_echoes(
    moment: DayMoment,
    storage: BaseStorage,
    embedder: EmbeddingProvider,
    *,
    limit: int = 3,
    min_score: float = 0.3,
    visual_sources: list | None = None,
    visual_boundary: int | None = None,
) -> tuple[list[dict], list[float] | None]:
    """Search cold archive for memories that echo a day moment.

    Args:
        moment: The day moment to find echoes for.
        storage: Storage backend (for cold_embeddings table).
        embedder: Embedding provider to vectorize the moment.
        limit: Max echoes to return.
        min_score: Minimum cosine similarity to qualify as an echo.
        visual_sources: List of VisualSource objects to search (optional).
        visual_boundary: Max boundary value for visual search filtering (optional).

    Returns:
        Tuple of (echoes, embedding). The embedding is returned so callers
        can reuse it for cold archive storage without a redundant API call.
    """
    try:
        embed_text = moment.content[:7000] if len(moment.content) > 7000 else moment.content
        embedding = await embedder.embed(embed_text)
    except Exception:
        logger.warning("Failed to embed moment for cold search: %s", moment.id, exc_info=True)
        return [], None

    results = await storage.search_cold_memory(
        embedding=embedding, limit=limit, entry_type=ColdEntryType.EVENT,
    )

    # Filter by minimum score (search_cold_memory uses blended score)
    echoes = [r for r in results if r.get("cosine_score", r.get("score", 0)) >= min_score]

    # Search visual sources for cross-temporal visual connections
    if visual_sources:
        try:
            from alive_memory.visual.search import search_visual
        except ImportError:
            logger.debug("Visual search module not available, skipping in cold search")
            visual_sources = None

    if visual_sources:
        for source in visual_sources:
            try:
                matches = await search_visual(
                    source, embed_text, limit=limit, boundary=visual_boundary,
                )
                for match in matches:
                    echoes.append({
                        "content": f"[visual] {match.filepath}",
                        "cosine_score": match.score,
                        "entry_type": "visual",
                        "metadata": match.metadata,
                    })
            except Exception:
                logger.debug("Visual source cold search failed", exc_info=True)

    return echoes, embedding
