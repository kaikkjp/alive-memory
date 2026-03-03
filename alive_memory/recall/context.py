"""Contextual recall: mood-congruent, drive-coupled retrieval.

Provides high-level recall functions that apply cognitive state
as a filter/bias on memory retrieval.
"""

from __future__ import annotations

from alive_memory.config import AliveConfig
from alive_memory.embeddings.base import EmbeddingProvider
from alive_memory.recall.hippocampus import recall
from alive_memory.storage.base import BaseStorage
from alive_memory.types import CognitiveState, Memory


async def mood_congruent_recall(
    query: str,
    storage: BaseStorage,
    state: CognitiveState,
    *,
    embedder: EmbeddingProvider | None = None,
    limit: int = 5,
    config: AliveConfig | None = None,
) -> list[Memory]:
    """Retrieve memories biased toward current mood.

    Mood-congruent recall: when sad, sad memories surface more easily.
    When happy, positive memories are more accessible.
    This is a standard finding in cognitive psychology.
    """
    # Use standard recall — weighting already handles mood congruence
    return await recall(
        query=query,
        storage=storage,
        state=state,
        embedder=embedder,
        limit=limit,
        config=config,
    )


async def drive_coupled_recall(
    drive_name: str,
    storage: BaseStorage,
    state: CognitiveState,
    *,
    embedder: EmbeddingProvider | None = None,
    limit: int = 5,
    config: AliveConfig | None = None,
) -> list[Memory]:
    """Retrieve memories coupled to a specific drive.

    When a drive is active, memories associated with that drive
    become more accessible.
    """
    # Use drive name as query, recall weighting handles drive coupling
    return await recall(
        query=drive_name,
        storage=storage,
        state=state,
        embedder=embedder,
        limit=limit,
        config=config,
    )
