"""Contextual recall: mood-congruent, drive-coupled retrieval.

Simplified for three-tier architecture — delegates to hippocampus
which uses MemoryReader grep.
"""

from __future__ import annotations

from alive_memory.config import AliveConfig
from alive_memory.hot.reader import MemoryReader
from alive_memory.recall.hippocampus import recall
from alive_memory.types import CognitiveState, RecallContext


async def mood_congruent_recall(
    query: str,
    reader: MemoryReader,
    state: CognitiveState,
    *,
    limit: int = 10,
    config: AliveConfig | None = None,
) -> RecallContext:
    """Retrieve memories biased toward current mood.

    Delegates to standard recall — mood congruence is handled
    by the natural content of journal entries and reflections.
    """
    return await recall(
        query=query,
        reader=reader,
        state=state,
        limit=limit,
        config=config,
    )


async def drive_coupled_recall(
    drive_name: str,
    reader: MemoryReader,
    state: CognitiveState,
    *,
    limit: int = 10,
    config: AliveConfig | None = None,
) -> RecallContext:
    """Retrieve memories coupled to a specific drive."""
    return await recall(
        query=drive_name,
        reader=reader,
        state=state,
        limit=limit,
        config=config,
    )
