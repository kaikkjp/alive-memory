"""Consolidation (sleep): three-tier processing pipeline.

Full sleep pipeline:
  1. Get unprocessed day_memory moments
  2. Per moment: gather hot context → cold search (full only) → LLM reflect
     → write journal MD → write facts to DB → mark processed
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
from alive_memory.consolidation.cold_search import find_cold_echoes
from alive_memory.consolidation.dreaming import dream
from alive_memory.consolidation.fact_extraction import TraitCache, write_extracted_facts
from alive_memory.consolidation.memory_updates import apply_reflection_to_hot_memory
from alive_memory.consolidation.reflection import reflect_daily_summary, reflect_on_moment
from alive_memory.consolidation.wake import WakeConfig, WakeHooks
from alive_memory.embeddings.base import EmbeddingProvider
from alive_memory.hot.reader import MemoryReader
from alive_memory.hot.writer import MemoryWriter
from alive_memory.llm.provider import LLMProvider
from alive_memory.storage.base import BaseStorage
from alive_memory.types import ColdEntryType, SleepReport

logger = logging.getLogger(__name__)


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
    wake_hooks: WakeHooks | None = None,
    wake_config: WakeConfig | None = None,
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
        wake_hooks: Optional WakeHooks protocol implementation.
        wake_config: Optional WakeConfig for the wake transition.

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
    trait_cache: TraitCache = {}

    # Get existing hot categories for LLM prompt
    existing_categories = reader.list_subdirs() if reader else []

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

        # LLM reflection + fact extraction (single call)
        if llm and writer and reader:
            result = await reflect_on_moment(
                moment,
                reader=reader,
                storage=storage,
                llm=llm,
                cold_echoes=cold_echoes,
                config=cfg,
                existing_categories=existing_categories,
            )

            if result.text:
                # Extract visitor name from metadata if present
                visitor_name = moment.metadata.get("visitor_name")
                thread_id = moment.metadata.get("thread_id")

                # Write reflection to hot memory (with dynamic categories)
                counts = apply_reflection_to_hot_memory(
                    moment, result.text,
                    writer=writer,
                    visitor_name=visitor_name,
                    thread_id=thread_id,
                    categories=result.categories,
                )
                report.journal_entries_written += counts.get("journal", 0)
                report.reflections.append(result.text)

                # Update existing categories for subsequent moments
                if result.categories:
                    for cat in result.categories:
                        if cat and cat not in existing_categories:
                            existing_categories.append(cat)

            # Write extracted facts (totems + traits) to storage
            if result.totems or result.traits:
                try:
                    session_id = moment.metadata.get("session_id")
                    await write_extracted_facts(
                        moment, totems=result.totems, traits=result.traits,
                        storage=storage, trait_cache=trait_cache,
                        source_session_id=session_id,
                    )
                except Exception:
                    logger.debug("Fact writing failed for moment %s", moment.id, exc_info=True)

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

    # Upsert visitors (full only — nap moments are re-processed during full sleep,
    # so upserting during nap would double-count the visit)
    if not is_nap:
        seen_visitors: set[str] = set()
        for moment in moments:
            visitor_name = moment.metadata.get("visitor_name")
            visitor_id = moment.metadata.get("visitor_id") or visitor_name
            if visitor_id and visitor_name and visitor_id not in seen_visitors:
                seen_visitors.add(visitor_id)
                try:
                    await storage.upsert_visitor(visitor_id, visitor_name)
                except Exception:
                    logger.debug("Failed to upsert visitor %s", visitor_id, exc_info=True)

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

        # Dreaming — cross-temporal synthesis
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
            # Persist dream insights to reflections
            if dreams and writer:
                for insight in dreams:
                    writer.append_reflection(insight, label="Dream Insight")

        # Batch embed to cold archive — all moments (no cap)
        embedded = 0
        if embedder:
            for moment in moments:
                try:
                    # Truncate to ~7000 chars to stay within embedding model token limits
                    embed_text = moment.content[:7000] if len(moment.content) > 7000 else moment.content
                    embedding = await embedder.embed(embed_text)
                    # Write to unified cold_memory table
                    session_id = moment.metadata.get("session_id")
                    turn_index = moment.metadata.get("turn_index")
                    role = moment.metadata.get("role")
                    await storage.store_cold_memory(
                        content=moment.content,
                        embedding=embedding,
                        entry_type=ColdEntryType.EVENT,
                        raw_content=moment.content,
                        metadata={
                            "event_type": moment.event_type.value,
                            "valence": moment.valence,
                            "salience": moment.salience,
                        },
                        source_moment_id=moment.id,
                        session_id=session_id,
                        turn_index=turn_index,
                        role=role,
                    )
                    embedded += 1
                except Exception:
                    logger.warning("Failed to embed moment %s to cold archive", moment.id, exc_info=True)
            report.cold_embeddings_added = embedded

        # Prune old hot files (safe because raw events are now in cold).
        # Only prune if cold_memory has been populated (this consolidation
        # cycle wrote to it), otherwise we'd lose pre-upgrade hot files
        # that haven't been backfilled yet.
        if writer and embedded > 0:
            hot_max_days = int(cfg.get("consolidation.hot_max_days", 7))
            for subdir in (reader.list_subdirs() if reader else []):
                if subdir == "self":
                    continue  # never prune self-knowledge
                try:
                    writer.prune_old_files(subdir, hot_max_days)
                except Exception:
                    logger.debug("Failed to prune %s", subdir, exc_info=True)

        # Flush processed moments from day_memory
        await storage.flush_day_memory()

    # Process whispers
    if whispers:
        from alive_memory.consolidation.whisper import process_whispers
        whisper_dreams = await process_whispers(whispers, storage)
        report.dreams.extend(whisper_dreams)

    # Wake phase (full only, if hooks provided)
    if not is_nap and wake_hooks is not None:
        from alive_memory.consolidation.wake import WakeConfig, run_wake_transition
        wake_cfg = wake_config if wake_config is not None else WakeConfig()
        wake_report = await run_wake_transition(
            storage,
            hooks=wake_hooks,
            embedder=embedder,
            config=wake_cfg,
        )
        report.wake_report = wake_report

    report.duration_ms = int(time.monotonic() * 1000) - start_ms

    # Log the consolidation
    await storage.log_consolidation(report)

    return report
