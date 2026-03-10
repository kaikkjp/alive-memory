"""Memory retrieval: visitor-aware lookup + keyword search + structured facts.

Recall pipeline:
  1. If visitor_id provided: direct lookup of visitor profile, totems, traits
  2. If no visitor_id: attempt to identify visitor from query via known names
  3. Grep hot memory (journal, visitors, self, reflections, threads)
  4. Search totems and traits tables by keyword (fallback)
  5. Return RecallContext with aggregated results
"""

from __future__ import annotations

import logging

from alive_memory.config import AliveConfig
from alive_memory.hot.reader import MemoryReader
from alive_memory.storage.base import BaseStorage
from alive_memory.types import CognitiveState, RecallContext

logger = logging.getLogger(__name__)


async def recall(
    query: str,
    reader: MemoryReader,
    state: CognitiveState,
    *,
    limit: int = 10,
    config: AliveConfig | None = None,
    storage: BaseStorage | None = None,
    visitor_id: str | None = None,
) -> RecallContext:
    """Retrieve context relevant to a query.

    When visitor_id is provided (or detected from the query), does direct
    ID-based lookups for visitor profile, totems, and traits — matching
    Shopkeeper's thalamus→hippocampus pattern.

    Falls back to keyword grep + search for open-ended queries.

    Args:
        query: Search query text.
        reader: MemoryReader for hot memory files.
        state: Current cognitive state.
        limit: Maximum results per category.
        config: Configuration parameters.
        storage: Storage backend (optional for backward compat).
        visitor_id: Known visitor ID for direct lookups (optional).

    Returns:
        RecallContext with categorized results.
    """
    ctx = RecallContext(query=query)

    # Step 1: Visitor identification — try to detect from query if not provided
    resolved_visitor_id = visitor_id
    if storage is not None and not resolved_visitor_id:
        resolved_visitor_id = await _identify_visitor(query, storage)

    # Step 2: Direct visitor lookups (like Shopkeeper's hippocampus)
    if storage is not None and resolved_visitor_id:
        await _fetch_visitor_context(
            resolved_visitor_id, storage, ctx, limit=limit,
        )

    # Step 3: Grep across all hot memory
    hits = reader.grep_memory(query, limit=limit * 3)
    ctx.total_hits += len(hits)

    for hit in hits:
        subdir = hit.get("subdir", "")
        context = hit.get("context", hit.get("match", ""))

        if subdir == "journal":
            if len(ctx.journal_entries) < limit:
                ctx.journal_entries.append(context)
        elif subdir == "visitors":
            if len(ctx.visitor_notes) < limit:
                ctx.visitor_notes.append(context)
        elif subdir == "self":
            if len(ctx.self_knowledge) < limit:
                ctx.self_knowledge.append(context)
        elif subdir == "reflections":
            if len(ctx.reflections) < limit:
                ctx.reflections.append(context)
        elif subdir == "threads":
            if len(ctx.thread_context) < limit:
                ctx.thread_context.append(context)

    # Step 4: Keyword search on structured facts (catches things not tied to a visitor)
    if storage is not None:
        try:
            totems = await storage.search_totems(query, limit=limit)
            for totem in totems:
                fact = _format_totem(totem)
                if fact not in ctx.totem_facts:
                    ctx.totem_facts.append(fact)
                    ctx.total_hits += 1
        except Exception:
            logger.debug("Totem search failed", exc_info=True)

        try:
            traits = await storage.search_traits(query, limit=limit)
            for trait in traits:
                fact = _format_trait(trait)
                if fact not in ctx.trait_facts:
                    ctx.trait_facts.append(fact)
                    ctx.total_hits += 1
        except Exception:
            logger.debug("Trait search failed", exc_info=True)

    # Step 5: Fill gaps with recent context
    if len(ctx.journal_entries) < 3:
        recent = reader.read_recent_journal(days=2, max_entries=3)
        for entry in recent:
            if entry not in ctx.journal_entries:
                ctx.journal_entries.append(entry)
                if len(ctx.journal_entries) >= limit:
                    break

    if not ctx.self_knowledge:
        identity = reader.read_self_knowledge("identity")
        if identity:
            ctx.self_knowledge.append(identity)

    return ctx


async def _identify_visitor(query: str, storage: BaseStorage) -> str | None:
    """Try to identify a visitor mentioned in the query by matching known names.

    Tokenizes the query and searches for each word that looks like a proper name
    (capitalized), since search_visitors() uses LIKE which fails on full sentences.
    """
    try:
        # Extract candidate names: capitalized words from the query
        import re
        words = re.findall(r"[A-Z][a-z]+", query)
        for word in words:
            visitors = await storage.search_visitors(word, limit=3)
            for visitor in visitors:
                if visitor.name.lower() == word.lower():
                    return visitor.id
    except Exception:
        logger.debug("Visitor identification failed", exc_info=True)
    return None


async def _fetch_visitor_context(
    visitor_id: str,
    storage: BaseStorage,
    ctx: RecallContext,
    *,
    limit: int = 10,
) -> None:
    """Fetch visitor profile, totems, and traits by ID — direct lookup."""
    # Visitor profile
    try:
        visitor = await storage.get_visitor(visitor_id)
        if visitor:
            parts = [f"{visitor.name}"]
            if visitor.summary:
                parts.append(visitor.summary)
            if visitor.emotional_imprint:
                parts.append(f"Emotional imprint: {visitor.emotional_imprint}")
            parts.append(f"Trust: {visitor.trust_level}, visits: {visitor.visit_count}")
            ctx.visitor_notes.append(" | ".join(parts))
            ctx.total_hits += 1
    except Exception:
        logger.debug("Visitor lookup failed for %s", visitor_id, exc_info=True)

    # Totems by visitor ID
    try:
        totems = await storage.get_totems(visitor_id=visitor_id, limit=limit)
        for totem in totems:
            ctx.totem_facts.append(_format_totem(totem))
            ctx.total_hits += 1
    except Exception:
        logger.debug("Totem lookup failed for %s", visitor_id, exc_info=True)

    # Traits by visitor ID
    try:
        traits = await storage.get_traits(visitor_id=visitor_id, limit=limit)
        for trait in traits:
            ctx.trait_facts.append(_format_trait(trait))
            ctx.total_hits += 1
    except Exception:
        logger.debug("Trait lookup failed for %s", visitor_id, exc_info=True)


def _format_totem(totem) -> str:
    """Format a totem into a readable fact string."""
    fact = f"{totem.entity}"
    if totem.context:
        fact += f" — {totem.context}"
    if totem.visitor_id:
        fact += f" (about: {totem.visitor_id})"
    return fact


def _format_trait(trait) -> str:
    """Format a trait into a readable fact string."""
    fact = f"{trait.trait_key}: {trait.trait_value}"
    if trait.visitor_id:
        fact += f" (about: {trait.visitor_id})"
    return fact
