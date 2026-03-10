"""Memory retrieval: markdown grep + structured semantic search.

Three-tier recall:
  1. Grep hot memory (journal, visitors, self, reflections, threads)
  2. Search totems and traits tables (structured facts)
  3. Return RecallContext with aggregated results
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
) -> RecallContext:
    """Retrieve context relevant to a query via hot memory grep + semantic search.

    Pipeline:
      1. Grep hot memory files → categorize results
      2. Search totems table for matching facts
      3. Search traits table for matching observations
      4. Return combined RecallContext

    Args:
        query: Search query text (keywords).
        reader: MemoryReader for hot memory files.
        state: Current cognitive state (for mood-biased ranking).
        limit: Maximum results per category.
        config: Configuration parameters.
        storage: Storage backend for totem/trait search (optional for backward compat).

    Returns:
        RecallContext with categorized results.
    """
    ctx = RecallContext(query=query)

    # Grep across all hot memory
    hits = reader.grep_memory(query, limit=limit * 3)
    ctx.total_hits = len(hits)

    # Categorize results by subdirectory
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

    # Search structured facts (totems + traits)
    if storage is not None:
        try:
            totems = await storage.search_totems(query, limit=limit)
            for totem in totems:
                fact = f"{totem.entity}"
                if totem.context:
                    fact += f" — {totem.context}"
                if totem.visitor_id:
                    fact += f" (about: {totem.visitor_id})"
                ctx.totem_facts.append(fact)
                ctx.total_hits += 1
        except Exception:
            logger.debug("Totem search failed", exc_info=True)

        try:
            traits = await storage.search_traits(query, limit=limit)
            for trait in traits:
                fact = f"{trait.trait_key}: {trait.trait_value}"
                if trait.visitor_id:
                    fact += f" (about: {trait.visitor_id})"
                ctx.trait_facts.append(fact)
                ctx.total_hits += 1
        except Exception:
            logger.debug("Trait search failed", exc_info=True)

    # Also pull recent journal entries if query matches "recent" patterns
    # and we don't have many journal hits yet
    if len(ctx.journal_entries) < 3:
        recent = reader.read_recent_journal(days=2, max_entries=3)
        for entry in recent:
            if entry not in ctx.journal_entries:
                ctx.journal_entries.append(entry)
                if len(ctx.journal_entries) >= limit:
                    break

    # Pull self-knowledge for broad context
    if not ctx.self_knowledge:
        identity = reader.read_self_knowledge("identity")
        if identity:
            ctx.self_knowledge.append(identity)

    return ctx
