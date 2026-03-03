"""Reflection — per-moment LLM reflection during consolidation.

For each day moment, gather hot context + cold echoes,
then ask the LLM to reflect on its significance.
The reflection output is written to hot memory.
"""

from __future__ import annotations

from alive_memory.config import AliveConfig
from alive_memory.hot.reader import MemoryReader
from alive_memory.llm.provider import LLMProvider
from alive_memory.storage.base import BaseStorage
from alive_memory.types import DayMoment


async def reflect_on_moment(
    moment: DayMoment,
    *,
    reader: MemoryReader,
    storage: BaseStorage,
    llm: LLMProvider,
    cold_echoes: list[dict] | None = None,
    config: AliveConfig | None = None,
) -> str:
    """Generate a reflection for a single day moment.

    Gathers hot memory context and cold echoes, then asks the LLM
    to reflect on the moment's significance.

    Args:
        moment: The day moment to reflect on.
        reader: MemoryReader for hot memory context.
        storage: Storage backend for state.
        llm: LLM provider for generation.
        cold_echoes: Cold echoes for this moment (if any).
        config: Configuration.

    Returns:
        Reflection text from the LLM.
    """
    # Gather hot context via grep
    keywords = _extract_keywords(moment.content)
    hot_hits = reader.grep_memory(keywords, limit=5) if keywords else []
    hot_context = "\n".join(h.get("context", h.get("match", "")) for h in hot_hits)

    # Get self-model for traits
    self_model = await storage.get_self_model()
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

    prompt = (
        "Reflect on this moment and what it means. "
        "Write a brief journal-style reflection (2-4 sentences). "
        "Focus on significance, feelings, and connections.\n\n"
        f"The moment: {moment.content[:500]}\n"
        f"Event type: {moment.event_type.value}\n"
        f"Emotional valence: {moment.valence:.2f}\n"
        f"Current mood: {state.mood.word} (valence: {state.mood.valence:.1f})\n"
        f"Current traits: {self_model.traits}\n"
        f"{related_text}"
        f"{echoes_text}"
    )

    try:
        response = await llm.complete(
            prompt,
            system="You are a reflective mind processing the day's experiences into journal entries.",
            max_tokens=200,
            temperature=0.7,
        )
        return response.text.strip()
    except Exception:
        return ""


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
