"""Image generation adapter — fal.ai API.

Uses fal-client SDK. Reads FAL_KEY from environment (auto-detected by client).
Model ID configurable via FAL_IMAGE_MODEL env var.
All generation is async-safe (called from sprite_gen worker and bootstrap).

Model contract:
    The configured model MUST accept these arguments:
        prompt (str), aspect_ratio (str), resolution (str),
        output_format (str), num_images (int)
    And MUST return: { "images": [{ "url": "..." }, ...] }

    Models known to match this contract:
        - fal-ai/nano-banana-pro (default)

    Models that do NOT match (different schema):
        - fal-ai/flux/dev (uses 'image_size' instead of 'aspect_ratio')

    If you need a model with a different schema, update this adapter.
"""

import os
import ssl

import aiohttp
import certifi
import fal_client


# ─── Configuration ───

_DEFAULT_MODEL = 'fal-ai/nano-banana-pro'


def _model_id() -> str:
    return os.environ.get('FAL_IMAGE_MODEL', _DEFAULT_MODEL)


def _resolution() -> str:
    return os.environ.get('FAL_IMAGE_RESOLUTION', '1K')


# ─── Core ───

async def generate_image(prompt: str, aspect: str = '3:2') -> bytes:
    """Generate an image via fal.ai. Returns PNG bytes.

    Args:
        prompt: The text prompt for image generation.
        aspect: Aspect ratio string ('3:2', '3:4', '1:1', etc.).

    Returns:
        Raw PNG image bytes.

    Raises:
        RuntimeError: If FAL_KEY is not set, the API returns no images,
                      the response shape is unexpected, or image download fails.
    """
    if not os.environ.get('FAL_KEY'):
        raise RuntimeError(
            'FAL_KEY not set. '
            'Get one at https://fal.ai/dashboard/keys'
        )

    model = _model_id()

    result = await fal_client.run_async(
        model,
        arguments={
            'prompt': prompt,
            'aspect_ratio': aspect,
            'resolution': _resolution(),
            'output_format': 'png',
            'num_images': 1,
        },
    )

    # Validate response shape (fail loud if model contract doesn't match)
    if not isinstance(result, dict):
        raise RuntimeError(
            f'fal.ai model {model} returned non-dict response: {type(result).__name__}. '
            f'This model may not match the expected contract — see image_gen.py docstring.'
        )

    images = result.get('images')
    if not isinstance(images, list) or not images:
        raise RuntimeError(
            f'fal.ai model {model} returned no images. '
            f'Response keys: {list(result.keys())}. '
            f'This model may not match the expected contract — see image_gen.py docstring.'
        )

    first = images[0]
    if not isinstance(first, dict) or 'url' not in first:
        raise RuntimeError(
            f'fal.ai model {model} image entry missing "url" key. '
            f'Got: {first!r:.200}. '
            f'This model may not match the expected contract — see image_gen.py docstring.'
        )

    image_url = first['url']

    # Download the image bytes (use certifi CA bundle for SSL)
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    async with aiohttp.ClientSession() as session:
        async with session.get(image_url, ssl=ssl_ctx) as resp:
            if resp.status != 200:
                raise RuntimeError(
                    f'Failed to download image from {image_url}: HTTP {resp.status}'
                )
            return await resp.read()
