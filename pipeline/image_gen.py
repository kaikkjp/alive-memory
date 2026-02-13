"""Image generation adapter — Gemini Imagen API.

Uses google-genai SDK. Reads GEMINI_API_KEY from environment.
All generation is async-safe (called from sprite_gen worker).
"""

import asyncio
import os
from functools import partial

from google import genai
from google.genai import types
import llm_logger


def _get_client() -> genai.Client:
    """Lazy-init Gemini client. Fails loud if key missing."""
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        raise RuntimeError(
            'GEMINI_API_KEY not set. '
            'Get one at https://aistudio.google.com/apikey'
        )
    return genai.Client(api_key=api_key)


# Module-level client (lazy)
_client: genai.Client | None = None


def _ensure_client() -> genai.Client:
    global _client
    if _client is None:
        _client = _get_client()
    return _client


def _generate_sync(prompt: str, aspect_ratio: str = '16:9') -> bytes:
    """Synchronous image generation. Called via run_in_executor."""
    client = _ensure_client()
    response = client.models.generate_images(
        model='imagen-4.0-generate-001',
        prompt=prompt,
        config=types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio=aspect_ratio,
            person_generation='allow_adult',
        ),
    )
    if not response.generated_images:
        raise RuntimeError(f'Imagen returned no images for prompt: {prompt[:80]}...')
    return response.generated_images[0].image.image_bytes


async def generate_image(prompt: str, aspect_ratio: str = '16:9') -> bytes:
    """Generate image via Gemini Imagen. Returns PNG bytes.

    Runs the blocking API call in a thread executor so it doesn't
    block the asyncio event loop.
    """
    loop = asyncio.get_event_loop()
    image_bytes = await loop.run_in_executor(
        None,
        partial(_generate_sync, prompt, aspect_ratio),
    )

    # Log image generation for cost tracking
    await llm_logger.log_llm_call(
        provider='google',
        model='imagen-4.0-generate-001',
        purpose='image_gen',
        images_generated=1,
    )

    return image_bytes
