"""Consolidation (sleep): orchestrates all consolidation phases.

Extracted from engine/sleep/__init__.py.
The consolidation pipeline runs these phases in order:
  1. Strengthening — rehearse and strengthen accessed memories
  2. Decay — apply time-based strength decay
  3. Merging — combine similar memories
  4. Pruning — remove very weak memories
  5. Dreaming — LLM-driven recombination of memory fragments
  6. Reflection — LLM-driven self-model update
"""

from __future__ import annotations

import time

from alive_memory.config import AliveConfig
from alive_memory.consolidation.decay import apply_decay
from alive_memory.consolidation.dreaming import dream
from alive_memory.consolidation.merging import merge_similar
from alive_memory.consolidation.pruning import prune_weak
from alive_memory.consolidation.reflection import reflect
from alive_memory.consolidation.strengthening import strengthen
from alive_memory.llm.provider import LLMProvider
from alive_memory.storage.base import BaseStorage
from alive_memory.types import ConsolidationReport


async def consolidate(
    storage: BaseStorage,
    *,
    llm: LLMProvider | None = None,
    config: AliveConfig | None = None,
    whispers: list[dict] | None = None,
    depth: str = "full",
) -> ConsolidationReport:
    """Run the full consolidation pipeline.

    Args:
        storage: Storage backend.
        llm: LLM provider (needed for dreaming and reflection).
        config: Configuration parameters.
        whispers: Config changes to process as dream perceptions.
        depth: "full" for complete consolidation, "nap" for light consolidation
               (skips dreaming and reflection).

    Returns:
        ConsolidationReport with statistics from each phase.
    """
    cfg = config or AliveConfig()
    start_ms = int(time.monotonic() * 1000)
    report = ConsolidationReport()

    # Fetch memories eligible for consolidation
    min_age = 0.5 if depth == "nap" else 1.0
    memories = await storage.get_memories_for_consolidation(min_age_hours=min_age)

    if not memories:
        report.duration_ms = int(time.monotonic() * 1000) - start_ms
        return report

    # Phase 1: Strengthen recently recalled memories
    strengthened = await strengthen(memories, storage, config=cfg)
    report.memories_strengthened = strengthened

    # Phase 2: Apply time-based decay
    weakened = await apply_decay(memories, storage, config=cfg)
    report.memories_weakened = weakened

    # Phase 3: Merge similar memories
    merged = await merge_similar(memories, storage, config=cfg)
    report.memories_merged = merged

    # Phase 4: Prune very weak memories
    pruned = await prune_weak(storage, config=cfg)
    report.memories_pruned = pruned

    # Phases 5-6: Only in full consolidation (not nap)
    if depth == "full" and llm:
        # Phase 5: Dreaming — recombine memory fragments
        dream_count = cfg.get("consolidation.dream_count", 3)
        dreams = await dream(storage, llm, count=dream_count, config=cfg)
        report.dreams = dreams

        # Phase 6: Reflection — update self-model
        reflection_count = cfg.get("consolidation.reflection_count", 2)
        reflections = await reflect(storage, llm, count=reflection_count, config=cfg)
        report.reflections = reflections

    # Process whispers (config changes as dream perceptions)
    if whispers:
        from alive_memory.consolidation.whisper import process_whispers
        whisper_dreams = await process_whispers(whispers, storage)
        report.dreams.extend(whisper_dreams)

    report.duration_ms = int(time.monotonic() * 1000) - start_ms

    # Log the consolidation
    await storage.log_consolidation(report)

    return report
