"""Consolidation (sleep): three-tier processing pipeline.

Full sleep pipeline:
  1. Get unprocessed day_memory moments
  2. Per moment: gather hot context → cold search (full only) → LLM reflect
     → write journal MD → apply memory_updates → mark processed
  3. Write daily summary → batch embed to cold → flush day_memory

Nap mode:
  - Process top N moments by salience
  - No cold search
  - Marks nap_processed=1 only
"""

from __future__ import annotations

import logging
import time

from alive_memory.config import AliveConfig

logger = logging.getLogger(__name__)
from alive_memory.consolidation.cold_search import find_cold_echoes
from alive_memory.consolidation.dreaming import dream
from alive_memory.consolidation.memory_updates import apply_reflection_to_hot_memory
from alive_memory.consolidation.reflection import reflect_daily_summary, reflect_on_moment
from alive_memory.embeddings.base import EmbeddingProvider
from alive_memory.hot.reader import MemoryReader
from alive_memory.hot.writer import MemoryWriter
from alive_memory.llm.provider import LLMProvider
from alive_memory.storage.base import BaseStorage
from alive_memory.types import SleepReport


async def consolidate(
    storage: BaseStorage,
    *,
    writer: MemoryWriter | None = None,
    reader: MemoryReader | None = None,
    llm: LLMProvider | None = None,
    embedder: EmbeddingProvider | None = None,
    config: AliveConfig | None = None,
    whispers: list[dict] | None = None,
    depth: str = "full",
) -> SleepReport:
    """Run the consolidation (sleep) pipeline.

    Args:
        storage: Storage backend (day_memory + cold_embeddings).
        writer: MemoryWriter for hot memory (Tier 2 writes).
        reader: MemoryReader for hot memory (Tier 2 reads for context).
        llm: LLM provider (needed for reflection and dreaming).
        embedder: Embedding provider (needed for cold archive writes).
        config: Configuration parameters.
        whispers: Config changes to process as dream perceptions.
        depth: "full" for complete consolidation, "nap" for light.

    Returns:
        SleepReport with statistics.
    """
    cfg = config or AliveConfig()
    start_ms = int(time.monotonic() * 1000)
    report = SleepReport(depth=depth)

    is_nap = depth == "nap"

    # Step 1: Get unprocessed moments
    moments = await storage.get_unprocessed_moments(nap=is_nap)
    if not moments:
        report.duration_ms = int(time.monotonic() * 1000) - start_ms
        return report

    # For naps, only process the top N most salient moments
    if is_nap:
        nap_count = cfg.get("consolidation.nap_moment_count", 5)
        moments = sorted(moments, key=lambda m: m.salience, reverse=True)
        moments = moments[:int(nap_count)]

    all_cold_echoes: list[dict] = []

    # Step 2: Per-moment processing
    for moment in moments:
        cold_echoes: list[dict] = []

        # Cold search (full only) — find echoes from older memories
        if not is_nap and embedder:
            cold_echoes = await find_cold_echoes(
                moment, storage, embedder, limit=3
            )
            all_cold_echoes.extend(cold_echoes)
            report.cold_echoes_found += len(cold_echoes)

        # LLM reflection (if LLM available and writer exists)
        if llm and writer and reader:
            reflection = await reflect_on_moment(
                moment,
                reader=reader,
                storage=storage,
                llm=llm,
                cold_echoes=cold_echoes,
                config=cfg,
            )

            if reflection:
                # Extract visitor name from metadata if present
                visitor_name = moment.metadata.get("visitor_name")
                thread_id = moment.metadata.get("thread_id")

                # Write reflection to hot memory
                counts = apply_reflection_to_hot_memory(
                    moment, reflection,
                    writer=writer,
                    visitor_name=visitor_name,
                    thread_id=thread_id,
                )
                report.journal_entries_written += counts.get("journal", 0)
                report.reflections.append(reflection)
        elif writer:
            # No LLM — write raw moment to journal
            writer.append_journal(
                moment.content,
                date=moment.timestamp,
                moment_id=moment.id,
            )
            report.journal_entries_written += 1

        # Mark processed
        await storage.mark_moment_processed(moment.id, nap=is_nap)
        report.moments_processed += 1

    # Step 3 (full only): Daily summary + batch embed + flush
    if not is_nap:
        # Daily summary
        if llm and writer:
            summary = await reflect_daily_summary(
                moments, storage=storage, llm=llm, config=cfg,
            )
            if summary:
                writer.append_reflection(summary, label="Daily Summary")
                report.reflections_written += 1

        # Dreaming
        if llm:
            dream_count = int(cfg.get("consolidation.dream_count", 3))
            dreams = await dream(
                moments,
                cold_echoes=all_cold_echoes,
                llm=llm,
                count=dream_count,
                config=cfg,
            )
            report.dreams = dreams

        # Batch embed to cold archive (max 50 per cycle)
        if embedder:
            embed_limit = int(cfg.get("consolidation.cold_embed_limit", 50))
            embedded = 0
            for moment in moments[:embed_limit]:
                try:
                    embedding = await embedder.embed(moment.content)
                    await storage.store_cold_embedding(
                        content=moment.content,
                        embedding=embedding,
                        source_moment_id=moment.id,
                        metadata={
                            "event_type": moment.event_type.value,
                            "valence": moment.valence,
                            "salience": moment.salience,
                        },
                    )
                    embedded += 1
                except Exception:
                    logger.warning("Failed to embed moment %s to cold archive", moment.id, exc_info=True)
            report.cold_embeddings_added = embedded

        # Flush processed moments from day_memory
        await storage.flush_day_memory()

    # Process whispers
    if whispers:
        from alive_memory.consolidation.whisper import process_whispers
        whisper_dreams = await process_whispers(whispers, storage)
        report.dreams.extend(whisper_dreams)

    report.duration_ms = int(time.monotonic() * 1000) - start_ms

    # Log the consolidation
    await storage.log_consolidation(report)

    return report
