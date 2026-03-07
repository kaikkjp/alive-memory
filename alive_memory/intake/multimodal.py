"""Multimodal intake — media files → text perceptions → thalamus pipeline.

Converts images, audio, video, and PDFs into text descriptions via an LLM
(typically Gemini), then feeds them through the standard intake pipeline.

Usage:
    from alive_memory.intake.multimodal import perceive_media

    text = await perceive_media(Path("photo.jpg"), gemini_provider)
    # Then pass to normal intake:
    moment = await memory.intake(event_type="observation", content=text)
"""

from __future__ import annotations

from pathlib import Path

from alive_memory.llm.provider import LLMResponse


async def perceive_media(
    file_path: str | Path,
    media_llm: object,
    *,
    prompt: str | None = None,
    max_tokens: int = 1000,
) -> str:
    """Convert a media file to text using an LLM with multimodal capabilities.

    This is a thin wrapper that calls perceive_media() on the provider,
    returning just the text. The caller then feeds it to AliveMemory.intake().

    Args:
        file_path: Path to the media file.
        media_llm: An LLM provider with a perceive_media() method
                   (e.g. GeminiProvider).
        prompt: Optional custom perception prompt.
        max_tokens: Max response tokens.

    Returns:
        Text description of the media content.

    Raises:
        TypeError: If the provider lacks perceive_media().
    """
    path = Path(file_path)

    if not hasattr(media_llm, "perceive_media"):
        raise TypeError(
            f"{type(media_llm).__name__} does not support perceive_media(). "
            f"Use GeminiProvider or another multimodal-capable provider."
        )

    kwargs: dict = {"max_tokens": max_tokens}
    if prompt is not None:
        kwargs["prompt"] = prompt

    response: LLMResponse = await media_llm.perceive_media(path, **kwargs)
    return response.text
