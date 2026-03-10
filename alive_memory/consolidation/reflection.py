"""Reflection — per-moment LLM reflection during consolidation.

For each day moment, gather hot context + cold echoes,
then ask the LLM to reflect on its significance AND extract structured facts.
Single LLM call produces both the journal reflection and memory updates
(totems + traits), matching Shopkeeper's cortex → hippocampus_write pattern.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from alive_memory.config import AliveConfig

logger = logging.getLogger(__name__)
from alive_memory.hot.reader import MemoryReader
from alive_memory.llm.provider import LLMProvider
from alive_memory.storage.base import BaseStorage
from alive_memory.types import DayMoment


@dataclass
class ReflectionResult:
    """Output of a single-moment reflection: journal text + structured facts."""
    text: str = ""
    totems: list[dict] = field(default_factory=list)
    traits: list[dict] = field(default_factory=list)


async def reflect_on_moment(
    moment: DayMoment,
    *,
    reader: MemoryReader,
    storage: BaseStorage,
    llm: LLMProvider,
    cold_echoes: list[dict] | None = None,
    config: AliveConfig | None = None,
) -> ReflectionResult:
    """Generate a reflection + extract facts for a single day moment.

    Single LLM call produces:
      - A journal-style reflection (2-4 sentences)
      - Structured totems (facts/entities)
      - Structured traits (observations about people)

    Args:
        moment: The day moment to reflect on.
        reader: MemoryReader for hot memory context.
        storage: Storage backend for state.
        llm: LLM provider for generation.
        cold_echoes: Cold echoes for this moment (if any).
        config: Configuration.

    Returns:
        ReflectionResult with text, totems, and traits.
    """
    # Gather hot context via grep
    keywords = _extract_keywords(moment.content)
    hot_hits = reader.grep_memory(keywords, limit=5) if keywords else []
    hot_context = "\n".join(h.get("context", h.get("match", "")) for h in hot_hits)

    state = await storage.get_cognitive_state()

    # Build cold echoes section
    echoes_text = ""
    if cold_echoes:
        echoes_text = "\nOlder related memories:\n"
        for echo in cold_echoes[:3]:
            echoes_text += f"- {echo['content'][:150]}\n"

    # Build related context section
    related_text = ""
    if hot_context:
        related_text = f"\nRelated context from memory:\n{hot_context[:500]}\n"

    visitor_name = moment.metadata.get("visitor_name", "unknown")

    prompt = (
        "Process this moment. Return a JSON object with three fields:\n\n"
        '1. "reflection": A brief journal-style reflection (2-4 sentences). '
        "Focus on significance, feelings, and connections.\n\n"
        '2. "totems": An array of facts, entities, or concepts mentioned. Each has:\n'
        '   - "entity": the fact or thing (string, be specific)\n'
        '   - "weight": importance 0.0-1.0\n'
        '   - "context": brief context explaining relevance\n'
        '   - "category": one of "personal", "preference", "relationship", '
        '"location", "event", "general"\n\n'
        '3. "traits": An array of observations about people mentioned. Each has:\n'
        '   - "trait_category": one of "personal", "preference", "demographic", '
        '"relationship", "behavioral", "emotional"\n'
        '   - "trait_key": specific attribute name (e.g. "gender_identity", "favorite_food")\n'
        '   - "trait_value": the observed value\n'
        '   - "confidence": 0.0-1.0\n\n'
        "Only extract facts clearly stated in the text. Do not infer.\n"
        "If no facts are found, use empty arrays.\n\n"
        f"The moment: {moment.content[:800]}\n"
        f"Event type: {moment.event_type.value}\n"
        f"Emotional valence: {moment.valence:.2f}\n"
        f"Current mood: {state.mood.word} (valence: {state.mood.valence:.1f})\n"
        f"Visitor: {visitor_name}\n"
        f"{related_text}"
        f"{echoes_text}\n"
        "Return ONLY valid JSON, no markdown fencing."
    )

    try:
        response = await llm.complete(
            prompt,
            system=(
                "You are a reflective mind processing experiences. "
                "You write journal reflections and extract structured facts. "
                "Return only valid JSON."
            ),
            max_tokens=600,
            temperature=0.5,
        )
        text = response.text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        data = json.loads(text)
        return ReflectionResult(
            text=data.get("reflection", ""),
            totems=data.get("totems", []),
            traits=data.get("traits", []),
        )
    except json.JSONDecodeError:
        # If JSON parsing fails, treat the whole response as reflection text
        logger.debug("Reflection JSON parse failed for %s, using as plain text", moment.id)
        return ReflectionResult(text=response.text.strip())
    except Exception:
        logger.warning("Moment reflection failed for %s", moment.id, exc_info=True)
        return ReflectionResult()


async def reflect_daily_summary(
    moments: list[DayMoment],
    *,
    storage: BaseStorage,
    llm: LLMProvider,
    config: AliveConfig | None = None,
) -> str:
    """Generate a daily summary reflection across all moments.

    Args:
        moments: All day moments being processed.
        storage: Storage backend.
        llm: LLM provider.
        config: Configuration.

    Returns:
        Daily summary text.
    """
    if not moments:
        return ""

    self_model = await storage.get_self_model()
    state = await storage.get_cognitive_state()

    summaries = "\n".join(
        f"- [{m.event_type.value}] {m.content[:150]}" for m in moments
    )

    prompt = (
        "Write a brief end-of-day summary (3-5 sentences) reflecting on "
        "these moments. What was today about? What patterns emerge?\n\n"
        f"Current traits: {self_model.traits}\n"
        f"Current mood: {state.mood.word}\n\n"
        f"Today's moments:\n{summaries}"
    )

    try:
        response = await llm.complete(
            prompt,
            system="You are writing a daily journal summary.",
            max_tokens=300,
            temperature=0.7,
        )
        return response.text.strip()
    except Exception:
        logger.warning("Daily summary reflection failed", exc_info=True)
        return ""


def _extract_keywords(content: str, max_keywords: int = 5) -> str:
    """Extract search keywords from content for hot memory grep."""
    # Simple: take longest unique words that aren't stop words
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "can", "shall",
        "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after", "above",
        "below", "between", "and", "but", "or", "nor", "not", "so",
        "yet", "both", "either", "neither", "each", "every", "all",
        "any", "few", "more", "most", "other", "some", "such", "no",
        "only", "own", "same", "than", "too", "very", "just", "that",
        "this", "these", "those", "i", "me", "my", "you", "your",
        "he", "she", "it", "we", "they", "them", "his", "her", "its",
    }

    words = content.lower().split()
    candidates = [w for w in words if w not in stop_words and len(w) >= 3]
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for w in candidates:
        if w not in seen:
            seen.add(w)
            unique.append(w)

    return " ".join(unique[:max_keywords])
