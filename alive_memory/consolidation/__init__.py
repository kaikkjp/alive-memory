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
from alive_memory.consolidation.reflection import reflect_daily_summary, reflect_on_batch, reflect_on_moment
from alive_memory.consolidation.wake import WakeConfig, WakeHooks
from alive_memory.embeddings.base import EmbeddingProvider
from alive_memory.hot.reader import MemoryReader
from alive_memory.hot.writer import MemoryWriter
from alive_memory.llm.provider import LLMProvider
from alive_memory.storage.base import BaseStorage
from alive_memory.types import ColdEntryType, DayMoment, SleepReport

logger = logging.getLogger(__name__)


async def _apply_reflection(
    moment: DayMoment,
    result,
    writer: MemoryWriter,
    storage: BaseStorage,
    trait_cache: TraitCache,
    existing_categories: list[str],
    report: SleepReport,
) -> None:
    """Write a single-moment reflection result to hot memory and storage."""
    if result.text:
        visitor_name = moment.metadata.get("visitor_name")
        thread_id = moment.metadata.get("thread_id")

        counts = apply_reflection_to_hot_memory(
            moment, result.text,
            writer=writer,
            visitor_name=visitor_name,
            thread_id=thread_id,
            categories=result.categories,
        )
        report.journal_entries_written += counts.get("journal", 0)
        report.reflections.append(result.text)

        if result.categories:
            for cat in result.categories:
                if cat and cat not in existing_categories:
                    existing_categories.append(cat)

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


async def _apply_batch_reflection(
    batch: list[DayMoment],
    result,
    writer: MemoryWriter,
    storage: BaseStorage,
    trait_cache: TraitCache,
    existing_categories: list[str],
    report: SleepReport,
) -> None:
    """Write a batch reflection without corrupting per-moment provenance.

    Reflection text is written as a general reflection (no visitor/thread).
    Facts are written per-moment by matching visitor names from the batch.
    """
    if result.text:
        # Write batch reflection as general entry — no visitor/thread attribution
        writer.append_reflection(result.text, label="Batch Summary")
        report.reflections.append(result.text)

        if result.categories:
            for cat in result.categories:
                if cat and cat not in existing_categories:
                    existing_categories.append(cat)

    # Build visitor→moment lookup for fact routing
    visitor_moments: dict[str, DayMoment] = {}
    for moment in batch:
        vname = moment.metadata.get("visitor_name") or moment.metadata.get("visitor_id")
        if vname:
            visitor_moments[vname.lower()] = moment

    # Route extracted facts to the correct moment by matching visitor names
    if result.totems or result.traits:
        # Default moment for unmatched facts: use the batch's most salient moment
        default_moment = max(batch, key=lambda m: m.salience)

        for totem in (result.totems or []):
            # Try to match totem to a specific moment via context/entity
            matched = _match_fact_to_moment(totem, visitor_moments, default_moment)
            try:
                await write_extracted_facts(
                    matched, totems=[totem], traits=[],
                    storage=storage, trait_cache=trait_cache,
                    source_session_id=matched.metadata.get("session_id"),
                )
            except Exception:
                logger.debug("Batch totem write failed", exc_info=True)

        for trait in (result.traits or []):
            matched = _match_fact_to_moment(trait, visitor_moments, default_moment)
            try:
                await write_extracted_facts(
                    matched, totems=[], traits=[trait],
                    storage=storage, trait_cache=trait_cache,
                    source_session_id=matched.metadata.get("session_id"),
                )
            except Exception:
                logger.debug("Batch trait write failed", exc_info=True)


def _match_fact_to_moment(
    fact: dict,
    visitor_moments: dict[str, DayMoment],
    default: DayMoment,
) -> DayMoment:
    """Best-effort match a fact dict to the moment it came from."""
    # Check common fields for visitor name references
    for field in ("entity", "context", "trait_value", "trait_key"):
        val = str(fact.get(field, "")).lower()
        for vname, moment in visitor_moments.items():
            if vname in val:
                return moment
    return default


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
    # Cache embeddings from cold search to reuse in batch embed step
    moment_embeddings: dict[str, list[float]] = {}

    # Get existing hot categories for LLM prompt
    existing_categories = reader.list_subdirs() if reader else []

    # Salience thresholds for tiered reflection
    high_threshold = float(cfg.get("consolidation.high_salience_threshold", 0.50))
    med_threshold = float(cfg.get("consolidation.med_salience_threshold", 0.40))
    med_batch_size = int(cfg.get("consolidation.med_batch_size", 8))

    # Partition moments into tiers
    high_moments: list[DayMoment] = []
    med_moments: list[DayMoment] = []
    low_moments: list[DayMoment] = []
    for moment in moments:
        if moment.salience >= high_threshold:
            high_moments.append(moment)
        elif moment.salience >= med_threshold:
            med_moments.append(moment)
        else:
            low_moments.append(moment)

    logger.info(
        "Consolidation tiers: %d high, %d medium, %d low (of %d total)",
        len(high_moments), len(med_moments), len(low_moments), len(moments),
    )

    # Step 2a: Cold search for ALL moments (needed for cold archive embedding)
    # Cache echoes per-moment so high-tier reflection can use them.
    moment_cold_echoes: dict[str, list[dict]] = {}
    for moment in moments:
        if not is_nap and embedder:
            cold_echoes, embedding = await find_cold_echoes(
                moment, storage, embedder, limit=3
            )
            if embedding is not None:
                moment_embeddings[moment.id] = embedding
            if cold_echoes:
                moment_cold_echoes[moment.id] = cold_echoes
            all_cold_echoes.extend(cold_echoes)
            report.cold_echoes_found += len(cold_echoes)

    # Step 2b: High salience — individual LLM reflection (full detail)
    for moment in high_moments:
        if llm and writer and reader:
            result = await reflect_on_moment(
                moment,
                reader=reader,
                storage=storage,
                llm=llm,
                cold_echoes=moment_cold_echoes.get(moment.id),
                config=cfg,
                existing_categories=existing_categories,
            )
            await _apply_reflection(
                moment, result, writer, storage, trait_cache,
                existing_categories, report,
            )
        elif writer:
            writer.append_journal(moment.content, date=moment.timestamp, moment_id=moment.id)
            report.journal_entries_written += 1

        await storage.mark_moment_processed(moment.id, nap=is_nap)
        report.moments_processed += 1

    # Step 2c: Medium salience — batched reflection (small groups)
    # Always write raw content to journal so recall can find it.
    for i in range(0, len(med_moments), med_batch_size):
        batch = med_moments[i:i + med_batch_size]
        if writer:
            for moment in batch:
                writer.append_journal(moment.content, date=moment.timestamp, moment_id=moment.id)
                report.journal_entries_written += 1
        if llm and writer and reader:
            result = await reflect_on_batch(
                batch,
                reader=reader,
                storage=storage,
                llm=llm,
                config=cfg,
                existing_categories=existing_categories,
            )
            await _apply_batch_reflection(
                batch, result, writer, storage, trait_cache,
                existing_categories, report,
            )

        for moment in batch:
            await storage.mark_moment_processed(moment.id, nap=is_nap)
            report.moments_processed += 1

    # Step 2d: Low salience — one big batch (minimal LLM cost)
    # Always write raw content to journal so recall can find it.
    if low_moments:
        if writer:
            for moment in low_moments:
                writer.append_journal(moment.content, date=moment.timestamp, moment_id=moment.id)
                report.journal_entries_written += 1
        if llm and writer and reader:
            result = await reflect_on_batch(
                low_moments,
                reader=reader,
                storage=storage,
                llm=llm,
                config=cfg,
                existing_categories=existing_categories,
            )
            await _apply_batch_reflection(
                low_moments, result, writer, storage, trait_cache,
                existing_categories, report,
            )

        for moment in low_moments:
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
                    # Reuse embedding from cold search if available
                    embedding = moment_embeddings.get(moment.id)
                    if embedding is None:
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
