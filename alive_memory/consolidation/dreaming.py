"""Dreaming — cross-temporal synthesis during consolidation.

During full sleep, the system "dreams" by:
  1. Picking top moments by salience from the day
  2. Using pre-gathered cold echoes from per-moment processing
  3. Assembling today's highlights + historical echoes into combined context
  4. Asking the LLM to produce cross-temporal insights

The output is persisted to hot memory (reflections/), creating high-value
cross-session connections that directly help multi-session reasoning.
"""

from __future__ import annotations

import logging

from alive_memory.config import AliveConfig
from alive_memory.llm.provider import LLMProvider
from alive_memory.types import DayMoment

logger = logging.getLogger(__name__)


async def dream(
    moments: list[DayMoment],
    *,
    cold_echoes: list[dict] | None = None,
    llm: LLMProvider,
    count: int = 3,
    config: AliveConfig | None = None,
) -> list[str]:
    """Generate cross-temporal dream insights from today's moments + cold echoes.

    Uses pre-gathered cold echoes from the per-moment consolidation loop
    (no redundant re-searching).

    Args:
        moments: Today's unprocessed day moments.
        cold_echoes: Pre-gathered cold echoes (from per-moment processing).
        llm: LLM provider for generation.
        count: Number of dream insights to generate.
        config: Configuration.

    Returns:
        List of cross-temporal insight texts.
    """
    dreams: list[str] = []

    if len(moments) < 2:
        return dreams

    # Pick top moments by salience
    top_moments = sorted(moments, key=lambda m: m.salience, reverse=True)[:count]

    # Use pre-gathered echoes (already searched per-moment during consolidation)
    echo_pool: list[dict] = list(cold_echoes or [])

    # Build the combined context
    today_section = "Today's key moments:\n"
    for m in top_moments:
        today_section += f"- {m.content[:300]}\n"

    echoes_section = ""
    if echo_pool:
        echoes_section = "\nOlder related memories:\n"
        for echo in echo_pool[:8]:
            echoes_section += f"- {echo.get('content', '')[:200]}\n"

    prompt = (
        "You are reflecting across time — connecting today's experiences "
        "with older memories. For each insight, identify a meaningful "
        "connection, pattern, or evolution across sessions.\n\n"
        "Write cross-temporal insights: what has changed, what persists, "
        "what connects these moments across time? Each insight should be "
        "2-3 sentences and genuinely useful for understanding this person's "
        "story over time.\n\n"
        f"Generate {count} insights.\n\n"
        f"{today_section}"
        f"{echoes_section}\n"
        "Return each insight on its own line, separated by blank lines. "
        "No numbering, no bullets — just the insights."
    )

    try:
        response = await llm.complete(
            prompt,
            system=(
                "You are a reflective mind synthesizing memories across time. "
                "Focus on genuine cross-temporal connections and patterns."
            ),
            max_tokens=500,
            temperature=0.6,
        )
        text = response.text.strip()
        if text:
            # Split on double newlines to get individual insights
            raw_insights = [s.strip() for s in text.split("\n\n") if s.strip()]
            dreams.extend(raw_insights[:count])
    except Exception:
        logger.warning("Dream generation failed", exc_info=True)

    return dreams
