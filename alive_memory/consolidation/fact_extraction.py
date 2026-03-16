"""Fact writing — write structured facts (totems + traits) to storage.

Processes the structured output from reflect_on_moment() and writes
totems and traits to the storage backend. No LLM calls — the LLM
produces facts as part of the reflection prompt (single call).

This mirrors Shopkeeper's hippocampus_write pattern where the cortex
outputs memory_updates and hippocampus_write processes them into DB writes.
"""

from __future__ import annotations

import logging
import time

from alive_memory.embeddings.base import EmbeddingProvider
from alive_memory.storage.base import BaseStorage
from alive_memory.types import DayMoment

logger = logging.getLogger(__name__)

# Trait dedup cooldown — prevents writing the same trait within a short window.
# Without this, the LLM reads back its own trait and reinforces it (feedback loop).
TRAIT_COOLDOWN_SECONDS = 300

# Type alias for the dedup cache: (visitor_id, category, key) → (value, timestamp)
TraitCache = dict[tuple[str, str, str], tuple[str, float]]


def _trait_is_duplicate(
    visitor_id: str, category: str, key: str, value: str,
    cache: TraitCache,
) -> bool:
    """Check if this trait was already written recently."""
    now = time.monotonic()
    cache_key = (visitor_id, category, key)

    # Prune stale entries
    stale = [
        k for k, (_, ts) in cache.items()
        if now - ts > TRAIT_COOLDOWN_SECONDS
    ]
    for k in stale:
        del cache[k]

    if cache_key in cache:
        cached_value, _ = cache[cache_key]
        if cached_value == value:
            return True

    cache[cache_key] = (value, now)
    return False


async def write_extracted_facts(
    moment: DayMoment,
    *,
    totems: list[dict],
    traits: list[dict],
    storage: BaseStorage,
    trait_cache: TraitCache | None = None,
    embedder: EmbeddingProvider | None = None,
) -> dict[str, int]:
    """Write pre-extracted totems and traits to storage.

    Called after reflect_on_moment() which produces facts as part of
    its single LLM call. This function only does DB writes.

    Args:
        moment: The source day moment.
        totems: Totem dicts from ReflectionResult.
        traits: Trait dicts from ReflectionResult.
        storage: Storage backend.

    Returns:
        Dict with counts: {totems: N, traits: N}
    """
    counts = {"totems": 0, "traits": 0}

    visitor_id = moment.metadata.get("visitor_id") or moment.metadata.get("visitor_name")

    # Process totems
    for totem in totems:
        entity = totem.get("entity", "").strip()
        if not entity:
            continue
        try:
            totem_weight = float(totem.get("weight", 0.5))
            totem_context = totem.get("context", "")
            totem_category = totem.get("category", "general")
            await storage.insert_totem(
                entity=entity,
                visitor_id=visitor_id,
                weight=totem_weight,
                context=totem_context,
                category=totem_category,
                source_moment_id=moment.id,
            )
            # Embed totem into unified cold_memory
            if embedder is not None:
                try:
                    embed_text = f"{entity}: {totem_context}" if totem_context else entity
                    embedding = await embedder.embed(embed_text)
                    await storage.store_cold_memory(
                        content=f"{entity} — {totem_context}" if totem_context else entity,
                        embedding=embedding,
                        entry_type="totem",
                        visitor_id=visitor_id,
                        weight=totem_weight,
                        category=totem_category,
                        source_moment_id=moment.id,
                    )
                except Exception:
                    logger.debug("Failed to embed totem %r to cold_memory", entity, exc_info=True)
            counts["totems"] += 1
        except Exception:
            logger.debug("Failed to insert totem %r", entity, exc_info=True)

    # Process traits
    for trait in traits:
        cat = trait.get("trait_category", "").strip()
        key = trait.get("trait_key", "").strip()
        val = trait.get("trait_value", "").strip()
        if not (cat and key and val and visitor_id):
            continue

        # Dedup check (skip if no cache provided)
        if trait_cache is not None and _trait_is_duplicate(visitor_id, cat, key, val, trait_cache):
            logger.debug("Trait dedup: skipped %s=%s", key, val)
            continue

        try:
            # Check for contradiction
            existing = await storage.get_latest_trait(visitor_id, cat, key)
            if existing and existing.trait_value != val:
                logger.info(
                    "Trait contradiction: %s.%s was %r, now %r",
                    cat, key, existing.trait_value, val,
                )

            trait_confidence = float(trait.get("confidence", 0.5))
            await storage.insert_trait(
                visitor_id=visitor_id,
                trait_category=cat,
                trait_key=key,
                trait_value=val,
                confidence=trait_confidence,
                source_moment_id=moment.id,
            )
            # Embed trait into unified cold_memory
            if embedder is not None:
                try:
                    embed_text = f"{cat}/{key}: {val}"
                    embedding = await embedder.embed(embed_text)
                    await storage.store_cold_memory(
                        content=f"{key}: {val}",
                        embedding=embedding,
                        entry_type="trait",
                        visitor_id=visitor_id,
                        weight=trait_confidence,
                        category=cat,
                        source_moment_id=moment.id,
                    )
                except Exception:
                    logger.debug("Failed to embed trait %s=%s to cold_memory", key, val, exc_info=True)
            counts["traits"] += 1
        except Exception:
            logger.debug("Failed to insert trait %s=%s", key, val, exc_info=True)

    return counts
