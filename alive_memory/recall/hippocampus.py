"""Memory retrieval: semantic search first, grep + structured facts as supplement.

Recall pipeline:
  1. Cold semantic search (primary — vector similarity over all embedded content)
  2. If visitor_id provided/detected: direct lookup of visitor profile, totems, traits
  3. Keyword search on totems and traits tables (supplement)
  4. Grep hot memory for remaining slots (supplement)
  5. Recency fallback only if cold returned nothing
"""

from __future__ import annotations

import logging
import re

from alive_memory.config import AliveConfig
from alive_memory.embeddings.base import EmbeddingProvider
from alive_memory.hot.reader import MemoryReader
from alive_memory.storage.base import BaseStorage
from alive_memory.types import CognitiveState, ColdEntryType, RecallContext

logger = logging.getLogger(__name__)


def _keyword_overlap(query: str, doc: str) -> float:
    """Fraction of query keywords found in doc (case-insensitive).

    Simple reranking signal: boosts results that share literal terms
    with the query even if embedding similarity is moderate.
    """
    _STOP = {
        "what",
        "when",
        "where",
        "who",
        "how",
        "which",
        "did",
        "do",
        "was",
        "were",
        "have",
        "has",
        "had",
        "is",
        "are",
        "the",
        "a",
        "an",
        "my",
        "me",
        "i",
        "you",
        "your",
        "their",
        "it",
        "its",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "ago",
        "last",
        "that",
        "this",
        "there",
        "about",
    }
    keywords = [w for w in re.findall(r"\b[a-z]{3,}\b", query.lower()) if w not in _STOP]
    if not keywords:
        return 0.0
    doc_lower = doc.lower()
    hits = sum(1 for kw in keywords if kw in doc_lower)
    return hits / len(keywords)


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
    visual_sources: list | None = None,
    visual_boundary: int | None = None,
) -> RecallContext:
    """Retrieve context relevant to a query.

    Semantic cold search is the PRIMARY retrieval path.
    Grep and structured lookups supplement with what vectors miss.
    """
    ctx = RecallContext(query=query)
    _seen: set[str] = set()

    # ── Step 1: Cold semantic search (PRIMARY) ──────────────────────
    if embedder is not None and storage is not None:
        try:
            query_vec = await embedder.embed(query)
            cold_hits = await storage.search_cold_memory(
                query_vec,
                limit=limit * 2,
            )
            # Rerank with keyword overlap boost
            reranked = []
            for hit in cold_hits:
                cosine = hit.get("cosine_score", 0.0)
                content = hit.get("raw_content") or hit["content"]
                overlap = _keyword_overlap(query, content)
                # Up to 30% boost for keyword overlap (same formula as mempalace)
                fused = cosine * (1.0 + 0.30 * overlap)
                reranked.append((fused, hit, content))
            reranked.sort(key=lambda x: x[0], reverse=True)

            for _, hit, content in reranked[:limit]:
                if content in _seen:
                    continue
                _seen.add(content)
                _merge_cold_hit(hit, ctx, content)
                ctx.total_hits += 1
                # Store full hit for session regrouping
                ctx.cold_hits.append({**hit, "_content": content})
                # Track retrieved session IDs for R@k measurement
                sid = hit.get("session_id")
                if sid and sid not in ctx.retrieved_session_ids:
                    ctx.retrieved_session_ids.append(sid)
        except Exception:
            logger.debug("Semantic cold search failed", exc_info=True)

    # ── Step 2: Visitor identification + direct lookups ─────────────
    resolved_visitor_id = visitor_id
    if storage is not None and not resolved_visitor_id:
        resolved_visitor_id = await _identify_visitor(query, storage)

    if storage is not None and resolved_visitor_id:
        await _fetch_visitor_context(
            resolved_visitor_id,
            storage,
            ctx,
            limit=limit,
            seen=_seen,
        )

    # ── Step 3: Keyword search on structured facts (supplement) ─────
    if storage is not None:
        try:
            totems = await storage.search_totems(query, limit=limit)
            for totem in totems:
                fact = _format_totem(totem)
                if fact not in _seen:
                    _seen.add(fact)
                    ctx.totem_facts.append(fact)
                    ctx.total_hits += 1
        except Exception:
            logger.debug("Totem search failed", exc_info=True)

        try:
            traits = await storage.search_traits(query, limit=limit)
            for trait in traits:
                fact = _format_trait(trait)
                if fact not in _seen:
                    _seen.add(fact)
                    ctx.trait_facts.append(fact)
                    ctx.total_hits += 1
        except Exception:
            logger.debug("Trait search failed", exc_info=True)

    # ── Step 4: Grep hot memory (fills remaining slots) ─────────────
    hits = reader.grep_memory(query, limit=limit * 3)
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
        if context in _seen:
            continue
        field_name = _SUBDIR_MAP.get(subdir, "extra_context")
        target_list = getattr(ctx, field_name)
        if len(target_list) < limit:
            _seen.add(context)
            target_list.append(context)
            ctx.total_hits += 1

    # ── Step 5: Recency fallback (only if cold returned nothing) ────
    if len(ctx.journal_entries) < 3 and ctx.total_hits < 3:
        recent = reader.read_recent_journal(days=2, max_entries=3)
        for entry in recent:
            if entry not in _seen:
                ctx.journal_entries.append(entry)
                _seen.add(entry)
                if len(ctx.journal_entries) >= limit:
                    break

    if not ctx.self_knowledge:
        identity = reader.read_self_knowledge("identity")
        if identity:
            ctx.self_knowledge.append(identity)

    # ── Step 6: Visual source search ────────────────────────────────
    if visual_sources:
        try:
            from alive_memory.visual.search import search_visual
        except ImportError:
            logger.debug("Visual search module not available, skipping")
            visual_sources = None

    if visual_sources:
        for source in visual_sources:
            try:
                matches = await search_visual(
                    source,
                    query,
                    limit=limit,
                    boundary=visual_boundary,
                )
                ctx.visual.extend(matches)
                ctx.total_hits += len(matches)
            except Exception:
                logger.debug("Visual source search failed", exc_info=True)

    return ctx


async def _identify_visitor(query: str, storage: BaseStorage) -> str | None:
    """Try to identify a visitor mentioned in the query by matching known names."""
    try:
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
    seen: set[str] | None = None,
) -> None:
    """Fetch visitor profile, totems, and traits by ID — direct lookup."""
    _seen = seen if seen is not None else set()

    try:
        visitor = await storage.get_visitor(visitor_id)
        if visitor:
            parts = [f"{visitor.name}"]
            if visitor.summary:
                parts.append(visitor.summary)
            if visitor.emotional_imprint:
                parts.append(f"Emotional imprint: {visitor.emotional_imprint}")
            parts.append(f"Trust: {visitor.trust_level}, visits: {visitor.visit_count}")
            note = " | ".join(parts)
            if note not in _seen:
                _seen.add(note)
                ctx.visitor_notes.append(note)
                ctx.total_hits += 1
    except Exception:
        logger.debug("Visitor lookup failed for %s", visitor_id, exc_info=True)

    try:
        totems = await storage.get_totems(visitor_id=visitor_id, limit=limit)
        for totem in totems:
            fact = _format_totem(totem)
            if fact not in _seen:
                _seen.add(fact)
                ctx.totem_facts.append(fact)
                ctx.total_hits += 1
    except Exception:
        logger.debug("Totem lookup failed for %s", visitor_id, exc_info=True)

    try:
        traits = await storage.get_traits(visitor_id=visitor_id, limit=limit)
        for trait in traits:
            fact = _format_trait(trait)
            if fact not in _seen:
                _seen.add(fact)
                ctx.trait_facts.append(fact)
                ctx.total_hits += 1
    except Exception:
        logger.debug("Trait lookup failed for %s", visitor_id, exc_info=True)


def _merge_cold_hit(hit: dict, ctx: RecallContext, content: str) -> None:
    """Route a cold memory hit into the appropriate RecallContext bucket."""
    entry_type = hit.get("entry_type", ColdEntryType.EVENT)
    if entry_type == ColdEntryType.TOTEM:
        ctx.totem_facts.append(content)
    elif entry_type == ColdEntryType.TRAIT:
        ctx.trait_facts.append(content)
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
