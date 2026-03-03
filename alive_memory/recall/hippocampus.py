"""Memory retrieval: markdown-first grep via MemoryReader.

Three-tier recall:
  1. Grep hot memory (journal, visitors, self, reflections, threads)
  2. Return RecallContext with aggregated results
  3. Cold search is NOT used here — only during sleep consolidation
"""

from __future__ import annotations

from alive_memory.config import AliveConfig
from alive_memory.hot.reader import MemoryReader
from alive_memory.types import CognitiveState, RecallContext


async def recall(
    query: str,
    reader: MemoryReader,
    state: CognitiveState,
    *,
    limit: int = 10,
    config: AliveConfig | None = None,
) -> RecallContext:
    """Retrieve context relevant to a query via hot memory grep.

    Pipeline: grep hot memory files → categorize results → return RecallContext

    This is the PRIMARY recall mechanism. No vector search.
    Cold embeddings are only searched during sleep consolidation.

    Args:
        query: Search query text (keywords).
        reader: MemoryReader for hot memory files.
        state: Current cognitive state (for mood-biased ranking).
        limit: Maximum results per category.
        config: Configuration parameters.

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
