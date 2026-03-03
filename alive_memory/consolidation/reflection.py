"""Reflection — LLM-driven self-model update during consolidation.

The system reflects on recent memories to update its self-understanding.
"""

from __future__ import annotations

from alive_memory.config import AliveConfig
from alive_memory.llm.provider import LLMProvider
from alive_memory.storage.base import BaseStorage


async def reflect(
    storage: BaseStorage,
    llm: LLMProvider,
    *,
    count: int = 2,
    config: AliveConfig | None = None,
) -> list[str]:
    """Generate reflections about recent experiences.

    Returns list of reflection texts.
    """
    reflections: list[str] = []

    memories = await storage.get_memories_for_consolidation(min_age_hours=0)
    if not memories:
        return reflections

    self_model = await storage.get_self_model()
    state = await storage.get_cognitive_state()

    strong_memories = sorted(memories, key=lambda m: m.strength, reverse=True)[:10]

    for _ in range(count):
        memory_summaries = "\n".join(
            f"- {m.content[:150]}" for m in strong_memories
        )

        prompt = (
            "Reflect on these recent experiences and generate a brief "
            "self-reflective insight. What patterns do you notice? "
            "What have you learned about yourself? "
            "Keep it to 1-2 sentences.\n\n"
            f"Current traits: {self_model.traits}\n"
            f"Current mood: {state.mood.word} (valence: {state.mood.valence:.1f})\n\n"
            f"Recent experiences:\n{memory_summaries}"
        )

        try:
            response = await llm.complete(
                prompt,
                system="You are a reflective mind processing the day's experiences.",
                max_tokens=200,
                temperature=0.7,
            )
            if response.text.strip():
                reflections.append(response.text.strip())
        except Exception:
            pass

    return reflections
