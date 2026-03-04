"""Dreaming — LLM-driven recombination of day moments + cold echoes.

During consolidation, the system "dreams" by asking the LLM to
recombine today's moments with cold echoes into new associative insights.
"""

from __future__ import annotations

import logging
import random

from alive_memory.config import AliveConfig

logger = logging.getLogger(__name__)
from alive_memory.llm.provider import LLMProvider
from alive_memory.types import DayMoment


async def dream(
    moments: list[DayMoment],
    *,
    cold_echoes: list[dict] | None = None,
    llm: LLMProvider,
    count: int = 3,
    config: AliveConfig | None = None,
) -> list[str]:
    """Generate dreams by recombining day moments and cold echoes.

    Args:
        moments: Today's unprocessed day moments.
        cold_echoes: Cold archive echoes found during sleep.
        llm: LLM provider for generation.
        count: Number of dreams to generate.
        config: Configuration.

    Returns:
        List of dream texts.
    """
    dreams: list[str] = []

    if len(moments) < 2:
        return dreams

    all_fragments: list[str] = [m.content[:200] for m in moments]
    if cold_echoes:
        all_fragments.extend(e["content"][:200] for e in cold_echoes[:5])

    for _ in range(count):
        seed_count = min(random.randint(2, 4), len(all_fragments))
        seeds = random.sample(all_fragments, seed_count)

        prompt = (
            "You are processing memory fragments during a dream state. "
            "Some are from today, some are from older memories. "
            "Recombine these fragments into a brief, evocative dream-like "
            "thought or insight. Be creative and associative. "
            "Keep it to 1-2 sentences.\n\n"
            "Memory fragments:\n"
        )
        for i, frag in enumerate(seeds, 1):
            prompt += f"{i}. {frag}\n"

        try:
            response = await llm.complete(
                prompt,
                system="You are a dreaming mind, recombining memories into new associations.",
                max_tokens=150,
                temperature=0.9,
            )
            if response.text.strip():
                dreams.append(response.text.strip())
        except Exception:
            logger.warning("Dream generation failed", exc_info=True)

    return dreams
