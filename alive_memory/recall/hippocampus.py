"""Memory retrieval: trust-ordered evidence assembly.

Recall pipeline (trust order):
  1. Visitor identification from query
  2. Raw turn search — verbatim conversation evidence (highest trust)
  3. Neighbor expansion — surrounding turns for matched sessions
  4. Direct visitor lookups — profile, totems, traits
  5. Grep hot memory — journal, visitors, self, reflections, threads
  6. Keyword search on structured facts
  7. Semantic cold search (events only, excludes raw_turn duplicates)
  8. Gap-fill with recent context
  9. Evidence ranking (recency-aware) + confidence scoring
"""

from __future__ import annotations

import logging

from alive_memory.config import AliveConfig
from alive_memory.embeddings.base import EmbeddingProvider
from alive_memory.hot.reader import MemoryReader
from alive_memory.recall.evidence import compute_confidence, rank_with_recency
from alive_memory.recall.temporal import apply_temporal_sort, detect_temporal_hints
from alive_memory.storage.base import BaseStorage
from alive_memory.types import CognitiveState, ColdEntryType, EvidenceBlock, RecallContext

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
    embedder: EmbeddingProvider | None = None,
) -> RecallContext:
    """Retrieve context relevant to a query from all memory tiers.

    Evidence is assembled in trust order: raw turns first, then structured
    facts, then reflections/summaries. Includes temporal awareness,
    recency-based ranking, and confidence scoring.

    Args:
        query: Search query text.
        reader: MemoryReader for hot memory files.
        state: Current cognitive state.
        limit: Maximum results per category.
        config: Configuration parameters.
        storage: Storage backend (optional for backward compat).
        visitor_id: Known visitor ID for direct lookups (optional).
        embedder: Embedding provider for semantic search.

    Returns:
        RecallContext with trust-ordered evidence blocks and confidence.
    """
    ctx = RecallContext(query=query)
    temporal_hints = detect_temporal_hints(query)

    # Step 1: Visitor identification
    resolved_visitor_id = visitor_id
    if storage is not None and not resolved_visitor_id:
        resolved_visitor_id = await _identify_visitor(query, storage)

    # Step 2: Raw turn search — highest trust evidence
    query_vec: list[float] | None = None
    if embedder is not None and storage is not None:
        try:
            query_vec = await embedder.embed(query)
            raw_hits = await storage.search_cold_memory(
                query_vec, limit=limit * 2, entry_type=ColdEntryType.RAW_TURN,
            )
            if temporal_hints:
                raw_hits = apply_temporal_sort(raw_hits, temporal_hints)

            # Track sessions for neighbor expansion
            seen_sessions: dict[str, list[int]] = {}
            _seen_raw: set[str] = set()
            min_raw_score = 0.25
            for hit in raw_hits:
                cos = hit.get("cosine_score", 0)
                if cos < min_raw_score:
                    continue
                content = hit.get("raw_content") or hit.get("content", "")
                if not content or content in _seen_raw:
                    continue
                _seen_raw.add(content)
                ctx.raw_turns.append(content)
                ctx.total_hits += 1
                sid = hit.get("session_id") or ""
                ctx.evidence_blocks.append(EvidenceBlock(
                    text=content,
                    source_type="raw_turn",
                    trust_rank=1,
                    timestamp=hit.get("created_at") or "",
                    session_id=sid,
                    score=cos,
                ))
                tidx = hit.get("turn_index")
                if sid and tidx is not None:
                    seen_sessions.setdefault(sid, []).append(tidx)

            # Step 3: Neighbor expansion — surrounding context for each hit
            for sid, turn_indices in seen_sessions.items():
                for tidx in turn_indices:
                    try:
                        neighbors = await storage.get_neighboring_turns(
                            sid, tidx, window=2,
                        )
                        for nb in neighbors:
                            nb_content = nb.get("raw_content") or nb.get("content", "")
                            if nb_content and nb_content not in _seen_raw:
                                _seen_raw.add(nb_content)
                                ctx.raw_turns.append(nb_content)
                    except Exception:
                        logger.debug("Neighbor expansion failed", exc_info=True)
        except Exception:
            logger.debug("Raw turn search failed", exc_info=True)

    # Step 4: Direct visitor lookups
    if storage is not None and resolved_visitor_id:
        await _fetch_visitor_context(
            resolved_visitor_id, storage, ctx, limit=limit,
        )

    # Step 5: Grep across all hot memory
    hits = reader.grep_memory(query, limit=limit * 3)
    ctx.total_hits += len(hits)

    _SUBDIR_MAP = {
        "journal": "journal_entries",
        "visitors": "visitor_notes",
        "self": "self_knowledge",
        "reflections": "reflections",
        "threads": "thread_context",
    }

    for hit in hits:
        subdir = hit.get("subdir", "")
        context = hit.get("context", hit.get("match", ""))
        field_name = _SUBDIR_MAP.get(subdir, "extra_context")
        target_list = getattr(ctx, field_name)
        if len(target_list) < limit:
            target_list.append(context)

    # Step 6: Keyword search on structured facts
    if storage is not None:
        try:
            totems = await storage.search_totems(query, limit=limit)
            for totem in totems:
                fact = _format_totem(totem)
                if fact not in ctx.totem_facts:
                    ctx.totem_facts.append(fact)
                    ctx.total_hits += 1
                    ctx.evidence_blocks.append(EvidenceBlock(
                        text=fact, source_type="totem", trust_rank=2,
                    ))
        except Exception:
            logger.debug("Totem search failed", exc_info=True)

        try:
            traits = await storage.search_traits(query, limit=limit)
            for trait in traits:
                fact = _format_trait(trait)
                if fact not in ctx.trait_facts:
                    ctx.trait_facts.append(fact)
                    ctx.total_hits += 1
                    ctx.evidence_blocks.append(EvidenceBlock(
                        text=fact, source_type="trait", trust_rank=2,
                    ))
        except Exception:
            logger.debug("Trait search failed", exc_info=True)

    # Step 7: Semantic cold search (all types except raw_turn, already searched)
    if query_vec is not None and storage is not None:
        try:
            cold_hits = await storage.search_cold_memory(
                query_vec, limit=limit,
            )
            _seen = set(ctx.journal_entries) | set(ctx.visitor_notes)
            _seen.update(ctx.totem_facts)
            _seen.update(ctx.trait_facts)
            _seen.update(ctx.raw_turns)
            min_score = 0.3
            for hit in cold_hits:
                if hit.get("cosine_score", 0) < min_score:
                    continue
                # Skip raw_turn entries (already searched in step 2)
                if hit.get("entry_type") == ColdEntryType.RAW_TURN:
                    continue
                content = hit["content"]
                if content in _seen:
                    continue
                _seen.add(content)
                _merge_cold_hit(hit, ctx)
                ctx.total_hits += 1
        except Exception:
            logger.debug("Semantic cold search failed", exc_info=True)

    # Step 8: Fill gaps with recent context
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

    # Step 9: Add remaining evidence blocks for non-raw sources
    for entry in ctx.journal_entries:
        ctx.evidence_blocks.append(EvidenceBlock(
            text=entry, source_type="journal", trust_rank=4,
        ))
    for note in ctx.visitor_notes:
        ctx.evidence_blocks.append(EvidenceBlock(
            text=note, source_type="visitor", trust_rank=3,
        ))
    for ref in ctx.reflections:
        ctx.evidence_blocks.append(EvidenceBlock(
            text=ref, source_type="reflection", trust_rank=5,
        ))

    # Step 10: Rank evidence and compute confidence
    # Skip recency re-ranking when temporal hints request oldest-first
    if not temporal_hints.get("first"):
        ctx.evidence_blocks = rank_with_recency(ctx.evidence_blocks)
    ctx.confidence, ctx.abstain_recommended = compute_confidence(
        ctx.evidence_blocks, ctx.total_hits,
    )

    return ctx


async def _identify_visitor(query: str, storage: BaseStorage) -> str | None:
    """Try to identify a visitor mentioned in the query by matching known names."""
    try:
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

    try:
        totems = await storage.get_totems(visitor_id=visitor_id, limit=limit)
        for totem in totems:
            ctx.totem_facts.append(_format_totem(totem))
            ctx.total_hits += 1
    except Exception:
        logger.debug("Totem lookup failed for %s", visitor_id, exc_info=True)

    try:
        traits = await storage.get_traits(visitor_id=visitor_id, limit=limit)
        for trait in traits:
            ctx.trait_facts.append(_format_trait(trait))
            ctx.total_hits += 1
    except Exception:
        logger.debug("Trait lookup failed for %s", visitor_id, exc_info=True)


def _merge_cold_hit(hit: dict, ctx: RecallContext) -> None:
    """Route a cold memory hit into the appropriate RecallContext bucket."""
    content = hit["content"]
    entry_type = hit.get("entry_type", ColdEntryType.EVENT)
    if entry_type == ColdEntryType.TOTEM:
        ctx.totem_facts.append(content)
    elif entry_type == ColdEntryType.TRAIT:
        ctx.trait_facts.append(content)
    elif entry_type == ColdEntryType.RAW_TURN:
        ctx.raw_turns.append(content)
    elif entry_type == ColdEntryType.EVENT:
        ctx.journal_entries.append(content)
        ctx.cold_echoes.append(content)
    else:
        ctx.extra_context.append(content)


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
