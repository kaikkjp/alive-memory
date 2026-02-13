"""Image generation adapter — multi-model fal.ai support.

Uses fal-client SDK. Reads FAL_KEY from environment (auto-detected by client).
Model is selected by FAL_IMAGE_MODEL env var:
  - fal-ai/bytedance/seedream/v4/text-to-image  (default, uses image_size presets)
  - fal-ai/nano-banana-pro  (legacy, uses aspect_ratio + resolution strings)

Each model has a different API contract, handled by model-specific adapters.
All generation is async-safe (called from sprite_gen worker and bootstrap).
"""

import asyncio
import os
import ssl
from abc import ABC, abstractmethod

import aiohttp
import certifi
import llm_logger


# ─── Seedream image_size mapping ────────────────────────────────────────

# Seedream v4 uses `image_size` (preset string or {width, height} dict)
# instead of `aspect_ratio` + `resolution`.
#
# 1K → standard presets; 2K → explicit HD dimensions; 4K → auto_4K.
# Resolution mapping (preset → approx px):
#   square      ~512×512     square_hd   ~1024×1024
#   landscape_* ~1024×…      portrait_*  ~…×1024
#   auto_4K     ~4096 long edge

_SEEDREAM_SIZE_MAP: dict[str, dict[str, str | dict[str, int]]] = {
    # aspect_ratio → {resolution_tier → preset OR {width, height}}
    '1:1': {
        '1K': 'square',
        '2K': 'square_hd',
        '4K': 'auto_4K',
    },
    '16:9': {
        '1K': 'landscape_16_9',
        '2K': {'width': 1920, 'height': 1080},
        '4K': 'auto_4K',
    },
    '9:16': {
        '1K': 'portrait_16_9',
        '2K': {'width': 1080, 'height': 1920},
        '4K': 'auto_4K',
    },
    '4:3': {
        '1K': 'landscape_4_3',
        '2K': {'width': 1920, 'height': 1440},
        '4K': 'auto_4K',
    },
    '3:4': {
        '1K': 'portrait_4_3',
        '2K': {'width': 1440, 'height': 1920},
        '4K': 'auto_4K',
    },
    '3:2': {
        '1K': 'landscape_4_3',   # closest preset
        '2K': {'width': 1920, 'height': 1280},
        '4K': 'auto_4K',
    },
    '2:3': {
        '1K': 'portrait_4_3',    # closest preset
        '2K': {'width': 1280, 'height': 1920},
        '4K': 'auto_4K',
    },
}


def _resolve_seedream_image_size(
    aspect_ratio: str,
    resolution: str = '1K',
) -> str | dict[str, int]:
    """Convert (aspect_ratio, resolution) → Seedream image_size param.

    Returns a preset string when one matches, otherwise an explicit
    {width, height} dict.
    """
    tier = resolution.upper()
    if tier not in ('1K', '2K', '4K'):
        raise ValueError(f'Unsupported resolution tier: {resolution!r}. Use 1K, 2K, or 4K.')

    ratio_map = _SEEDREAM_SIZE_MAP.get(aspect_ratio)
    if ratio_map is None:
        raise ValueError(
            f'No Seedream mapping for aspect_ratio={aspect_ratio!r}. '
            f'Supported: {sorted(_SEEDREAM_SIZE_MAP.keys())}'
        )

    size = ratio_map.get(tier)
    if size is None:
        raise ValueError(
            f'No Seedream mapping for resolution={resolution!r} '
            f'with aspect_ratio={aspect_ratio!r}.'
        )

    return size


# ─── Model adapter ABC ─────────────────────────────────────────────────

class ModelAdapter(ABC):
    """Interface each fal.ai model adapter must implement."""

    @abstractmethod
    async def generate(self, prompt: str, aspect: str) -> bytes:
        """Return raw image bytes (PNG) for *prompt*."""


# ─── Seedream v4 adapter ───────────────────────────────────────────────

class SeedreamAdapter(ModelAdapter):
    """ByteDance Seedream v4 — uses image_size presets."""

    MODEL_ID = 'fal-ai/bytedance/seedream/v4/text-to-image'

    # Hard timeout for a single generation request (seconds).
    # Prevents a stuck fal.ai request from blocking the sprite queue
    # indefinitely.  120 s is generous for a single image.
    TIMEOUT_SECONDS = 120

    async def generate(self, prompt: str, aspect: str) -> bytes:
        import fal_client

        resolution = os.environ.get('FAL_IMAGE_RESOLUTION', '1K')
        image_size = _resolve_seedream_image_size(aspect, resolution)

        result = await asyncio.wait_for(
            fal_client.subscribe_async(
                self.MODEL_ID,
                arguments={
                    'prompt': prompt,
                    'image_size': image_size,
                    'num_images': 1,
                    'enable_safety_checker': True,
                },
            ),
            timeout=self.TIMEOUT_SECONDS,
        )

        return await _download_first_image(result, self.MODEL_ID)


# ─── Generic fal.ai adapter (nano-banana-pro, etc.) ────────────────────

class GenericFalAdapter(ModelAdapter):
    """Generic fal.ai model using aspect_ratio + resolution contract.

    Model contract:
        Input:  prompt (str), aspect_ratio (str), resolution (str),
                output_format (str), num_images (int)
        Output: { "images": [{ "url": "..." }, ...] }

    Models known to match: fal-ai/nano-banana-pro
    """

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    async def generate(self, prompt: str, aspect: str) -> bytes:
        import fal_client

        resolution = os.environ.get('FAL_IMAGE_RESOLUTION', '1K')

        result = await fal_client.run_async(
            self._model_id,
            arguments={
                'prompt': prompt,
                'aspect_ratio': aspect,
                'resolution': resolution,
                'output_format': 'png',
                'num_images': 1,
            },
        )

        return await _download_first_image(result, self._model_id)


# ─── Shared image download ─────────────────────────────────────────────

async def _download_first_image(result: object, model_label: str) -> bytes:
    """Validate fal.ai response and download the first image. Fails loud."""
    if not isinstance(result, dict):
        raise RuntimeError(
            f'fal.ai model {model_label} returned non-dict response: '
            f'{type(result).__name__}.'
        )

    images = result.get('images')
    if not isinstance(images, list) or not images:
        raise RuntimeError(
            f'fal.ai model {model_label} returned no images. '
            f'Response keys: {list(result.keys())}.'
        )

    first = images[0]
    if not isinstance(first, dict) or 'url' not in first:
        raise RuntimeError(
            f'fal.ai model {model_label} image entry missing "url" key. '
            f'Got: {first!r:.200}.'
        )

    image_url = first['url']

    # Download with certifi CA bundle for macOS SSL compatibility
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    async with aiohttp.ClientSession() as session:
        async with session.get(image_url, ssl=ssl_ctx) as resp:
            if resp.status != 200:
                raise RuntimeError(
                    f'Failed to download image from {image_url}: HTTP {resp.status}'
                )
            return await resp.read()


# ─── Adapter registry & public API ──────────────────────────────────────

_SEEDREAM_MODEL = 'fal-ai/bytedance/seedream/v4/text-to-image'

_active_adapter: ModelAdapter | None = None


def _init_adapter() -> ModelAdapter:
    """Resolve and initialise the model adapter. Fails loud."""
    if not os.environ.get('FAL_KEY'):
        raise RuntimeError(
            'FAL_KEY not set. '
            'Get one at https://fal.ai/dashboard/keys'
        )

    model = os.environ.get('FAL_IMAGE_MODEL', _SEEDREAM_MODEL)

    if model == _SEEDREAM_MODEL:
        return SeedreamAdapter()

    return GenericFalAdapter(model)


def _ensure_adapter() -> ModelAdapter:
    global _active_adapter
    if _active_adapter is None:
        _active_adapter = _init_adapter()
    return _active_adapter


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
    adapter = _ensure_adapter()
    image_bytes = await adapter.generate(prompt, aspect)

    # Log image generation for cost tracking (best-effort, don't fail request)
    try:
        await llm_logger.log_llm_call(
            provider='fal',
            model=os.environ.get('FAL_IMAGE_MODEL', _SEEDREAM_MODEL),
            purpose='image_gen',
            images_generated=1,
        )
    except Exception as e:
        print(f'[Warning] Image gen logging failed: {e}')

    return image_bytes
