"""Google Gemini provider for alive-memory.

Supports both text completion (LLMProvider protocol) and multimodal
media perception (images, audio, video, PDFs).

Requires: pip install google-genai
"""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path

from alive_memory.llm.provider import LLMResponse

# MIME types Gemini supports natively
_SUPPORTED_MIME_TYPES: frozenset[str] = frozenset({
    # Images
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/heic", "image/heif",
    # Audio
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/ogg", "audio/flac",
    "audio/aac", "audio/x-wav",
    # Video
    "video/mp4", "video/mpeg", "video/webm", "video/quicktime",
    "video/x-msvideo", "video/x-matroska",
    # Documents
    "application/pdf",
})

# 20 MB inline limit — Gemini supports up to 20MB inline, larger needs File API
_MAX_INLINE_BYTES = 20 * 1024 * 1024


def _guess_mime(path: Path) -> str:
    """Guess MIME type from file extension."""
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


class GeminiProvider:
    """LLM provider using Google's Gemini API via the google-genai SDK.

    Implements the LLMProvider protocol for text completions and adds
    perceive_media() for multimodal intake.

    Usage:
        provider = GeminiProvider(api_key="...")
        # Text completion (LLMProvider protocol)
        response = await provider.complete("What is memory?")
        # Multimodal perception
        response = await provider.perceive_media(Path("photo.jpg"))
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.0-flash-lite",
    ):
        try:
            from google import genai
        except ImportError as err:
            raise ImportError(
                "google-genai package required: pip install google-genai"
            ) from err
        key = api_key or os.environ.get("GOOGLE_API_KEY", "")
        if not key:
            raise ValueError(
                "Gemini API key required: pass api_key or set GOOGLE_API_KEY"
            )
        self._client = genai.Client(api_key=key)
        self._model = model

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Text completion — satisfies LLMProvider protocol."""
        from google.genai import types

        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
        )
        if system:
            config.system_instruction = system

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=config,
        )

        text = response.text or ""
        usage = response.usage_metadata
        input_tokens = usage.prompt_token_count if usage else 0
        output_tokens = usage.candidates_token_count if usage else 0

        return LLMResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            metadata={"model": self._model, "provider": "gemini"},
        )

    async def perceive_media(
        self,
        file_path: Path,
        *,
        prompt: str | None = None,
        max_tokens: int = 1000,
        temperature: float = 0.3,
    ) -> LLMResponse:
        """Perceive a media file (image, audio, video, PDF) via Gemini.

        Sends the file bytes inline to Gemini with a perception prompt.
        Returns structured text description suitable for thalamus intake.

        Args:
            file_path: Path to the media file.
            prompt: Custom prompt. Defaults to a structured perception prompt.
            max_tokens: Max response tokens.
            temperature: Low by default for factual descriptions.

        Returns:
            LLMResponse with text description of the media content.

        Raises:
            ValueError: If MIME type is unsupported or file too large.
            FileNotFoundError: If file does not exist.
        """
        from google.genai import types

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Media file not found: {path}")

        mime_type = _guess_mime(path)
        if mime_type not in _SUPPORTED_MIME_TYPES:
            raise ValueError(
                f"Unsupported MIME type {mime_type!r} for {path.name}. "
                f"Supported: images, audio, video, PDF."
            )

        file_bytes = path.read_bytes()
        if len(file_bytes) > _MAX_INLINE_BYTES:
            raise ValueError(
                f"File too large ({len(file_bytes) / 1024 / 1024:.1f}MB). "
                f"Max inline size is {_MAX_INLINE_BYTES / 1024 / 1024:.0f}MB."
            )

        perception_prompt = prompt or _default_perception_prompt(mime_type)

        contents = [
            types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
            perception_prompt,
        ]

        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
        )

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=contents,
            config=config,
        )

        text = response.text or ""
        usage = response.usage_metadata
        input_tokens = usage.prompt_token_count if usage else 0
        output_tokens = usage.candidates_token_count if usage else 0

        return LLMResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            metadata={
                "model": self._model,
                "provider": "gemini",
                "media_file": path.name,
                "mime_type": mime_type,
                "file_size_bytes": len(file_bytes),
            },
        )


def _default_perception_prompt(mime_type: str) -> str:
    """Generate a perception-oriented prompt based on media type."""
    media_category = mime_type.split("/")[0]

    base = (
        "Describe what you perceive in this content. Be specific and factual. Include:\n"
        "- Key entities (people, places, objects, concepts)\n"
        "- Actions or events happening\n"
        "- Emotional tone or mood\n"
        "- Any notable details\n\n"
        "Keep your description concise (2-4 paragraphs). "
        "Write in present tense as if observing it directly."
    )

    if media_category == "image":
        return f"You are perceiving an image.\n\n{base}"
    if media_category == "audio":
        return (
            f"You are perceiving an audio recording.\n\n{base}\n\n"
            "Also include: speaker identification (if distinguishable), "
            "key quotes or statements, and any background sounds."
        )
    if media_category == "video":
        return (
            f"You are perceiving a video.\n\n{base}\n\n"
            "Also include: key moments with approximate timestamps, "
            "transitions or scene changes, and any spoken dialogue."
        )
    # PDF / document
    return (
        f"You are perceiving a document.\n\n{base}\n\n"
        "Also include: the document's purpose, key arguments or data points, "
        "and any conclusions."
    )
