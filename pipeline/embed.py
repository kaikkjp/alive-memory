"""Provider-agnostic embedding abstraction for cold memory search.

Routes to OpenAI text-embedding-3-small by default. Abstracted behind
EMBED_PROVIDER env var so we can swap to a local model later.

All failures return None (graceful degradation — cold search is non-blocking).
"""

import os
from typing import Optional

import aiohttp

EMBED_PROVIDER = os.getenv('EMBED_PROVIDER', 'openai')
EMBED_DIMENSION = 1536  # text-embedding-3-small
_OPENAI_MODEL = 'text-embedding-3-small'
_OPENAI_URL = 'https://api.openai.com/v1/embeddings'
_OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
_MAX_INPUT_CHARS = 8000  # truncate long texts to stay within token limits
_TIMEOUT_SECONDS = 10


async def embed(text: str) -> Optional[list[float]]:
    """Embed text into a vector. Returns None on any failure."""
    if not text or not text.strip():
        return None

    text = text[:_MAX_INPUT_CHARS]

    if EMBED_PROVIDER == 'openai':
        return await _embed_openai(text)
    elif EMBED_PROVIDER == 'local':
        return await _embed_local(text)
    else:
        print(f"[Embed] Unknown provider: {EMBED_PROVIDER}")
        return None


async def _embed_openai(text: str) -> Optional[list[float]]:
    """Call OpenAI embeddings API via aiohttp (async, no openai lib needed)."""
    if not _OPENAI_API_KEY:
        print("[Embed] OPENAI_API_KEY not set — skipping embedding")
        return None

    try:
        timeout = aiohttp.ClientTimeout(total=_TIMEOUT_SECONDS)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                _OPENAI_URL,
                headers={
                    'Authorization': f'Bearer {_OPENAI_API_KEY}',
                    'Content-Type': 'application/json',
                },
                json={
                    'model': _OPENAI_MODEL,
                    'input': text,
                },
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    print(f"[Embed] OpenAI API error {resp.status}: {body[:200]}")
                    return None

                data = await resp.json()
                embedding = data['data'][0]['embedding']

                if len(embedding) != EMBED_DIMENSION:
                    print(f"[Embed] Unexpected dimension: {len(embedding)} (expected {EMBED_DIMENSION})")
                    return None

                return embedding

    except aiohttp.ClientError as e:
        print(f"[Embed] HTTP error: {e}")
        return None
    except (KeyError, IndexError) as e:
        print(f"[Embed] Unexpected response format: {e}")
        return None
    except Exception as e:
        print(f"[Embed] Unexpected error: {e}")
        return None


async def _embed_local(text: str) -> Optional[list[float]]:
    """Placeholder for local embedding model (Phase 3+)."""
    raise NotImplementedError(
        "Local embedding not yet implemented. Set EMBED_PROVIDER=openai."
    )


def embed_model_name() -> str:
    """Return the name of the active embedding model."""
    if EMBED_PROVIDER == 'openai':
        return _OPENAI_MODEL
    elif EMBED_PROVIDER == 'local':
        return 'nomic-embed-text-v1.5'
    return 'unknown'
