"""Memory retrieval: embed query → search → re-rank → return.

Extracted from engine/pipeline/hippocampus.py.
Stripped: journal/totem/collection/visitor retrieval (application-specific).
Kept: generic vector search + re-ranking pipeline.
"""

from __future__ import annotations

from alive_memory.config import AliveConfig
from alive_memory.embeddings.base import EmbeddingProvider
from alive_memory.recall.weighting import score_memory
from alive_memory.storage.base import BaseStorage
from alive_memory.types import CognitiveState, Memory


async def recall(
    query: str,
    storage: BaseStorage,
    state: CognitiveState,
    *,
    embedder: EmbeddingProvider | None = None,
    limit: int = 5,
    min_strength: float = 0.0,
    config: AliveConfig | None = None,
) -> list[Memory]:
    """Retrieve memories relevant to a query.

    Pipeline: embed query → vector search → re-rank by cognitive state → return

    Args:
        query: Search query text.
        storage: Storage backend.
        state: Current cognitive state (for mood-congruent recall).
        embedder: Embedding provider (if None, falls back to text search).
        limit: Maximum results.
        min_strength: Filter out memories below this strength.
        config: Configuration parameters.

    Returns:
        List of memories ordered by relevance score.
    """
    cfg = config or AliveConfig()
    search_limit = limit * 3  # Over-fetch for re-ranking

    if embedder:
        # Vector search
        try:
            query_embedding = await embedder.embed(query)
            candidates = await storage.search_memories(
                embedding=query_embedding,
                limit=search_limit,
                filters={"min_strength": min_strength} if min_strength > 0 else None,
            )
        except Exception:
            # Fallback to text search on embedding failure
            candidates = await storage.search_memories_by_text(
                query=query, limit=search_limit
            )
    else:
        # Text search fallback
        candidates = await storage.search_memories_by_text(
            query=query, limit=search_limit
        )

    # Filter by minimum strength
    if min_strength > 0:
        candidates = [m for m in candidates if m.strength >= min_strength]

    # Re-rank by cognitive state
    scored = []
    for mem in candidates:
        score = score_memory(mem, state, config=cfg)
        scored.append((score, mem))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Update recall counts for returned memories
    results = [mem for _, mem in scored[:limit]]
    for mem in results:
        try:
            await storage.update_memory_recall(mem.id)
            mem.recall_count += 1
        except Exception:
            pass  # best-effort

    return results
