"""Dreaming — LLM-driven recombination of memory fragments.

During consolidation, the system "dreams" by asking the LLM to
recombine random memory fragments into new associative insights.
"""

from __future__ import annotations

import random

from alive_memory.config import AliveConfig
from alive_memory.llm.provider import LLMProvider
from alive_memory.storage.base import BaseStorage


async def dream(
    storage: BaseStorage,
    llm: LLMProvider,
    *,
    count: int = 3,
    config: AliveConfig | None = None,
) -> list[str]:
    """Generate dreams by recombining random memory fragments.

    Returns list of dream texts.
    """
    dreams: list[str] = []

    memories = await storage.get_memories_for_consolidation(min_age_hours=0)
    if len(memories) < 3:
        return dreams

    for _ in range(count):
        seed_count = min(random.randint(2, 4), len(memories))
        seeds = random.sample(memories, seed_count)
        fragments = [m.content[:200] for m in seeds]

        prompt = (
            "You are processing memory fragments during a dream state. "
            "Recombine these fragments into a brief, evocative dream-like "
            "thought or insight. Be creative and associative. "
            "Keep it to 1-2 sentences.\n\n"
            "Memory fragments:\n"
        )
        for i, frag in enumerate(fragments, 1):
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
            pass

    return dreams
