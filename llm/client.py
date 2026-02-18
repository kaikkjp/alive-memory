"""llm/client.py — Single entry point for all LLM completions via OpenRouter.

Uses raw httpx (no openai or anthropic SDK) to POST to the OpenRouter
OpenAI-compatible chat completions endpoint.  All callers receive an
Anthropic-compatible response dict so the rest of the codebase is unchanged.
"""

from __future__ import annotations

import asyncio
import time
import uuid

import httpx

from llm.config import get_api_key, resolve_model
from llm.format import anthropic_to_openai, openai_to_anthropic

OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions"

_HEADERS_STATIC = {
    "Content-Type": "application/json",
    "HTTP-Referer": "https://github.com/TriMinhPham/shopkeeper",
    "X-Title": "The Shopkeeper",
}


async def complete(
    messages: list[dict],
    system: str | None = None,
    call_site: str = "default",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    timeout: float = 60.0,
) -> dict:
    """Single entry point for all LLM completions.

    Converts Anthropic-style input to OpenAI format, sends the request to
    OpenRouter, converts the response back to Anthropic format, and returns it.

    Args:
        messages: Anthropic-style message list with "role" / "content" keys.
        system: Optional system prompt string (separate from messages).
        call_site: Logical name for this call site used for model resolution
                   and cost logging (e.g. "cortex", "reflect").
        max_tokens: Maximum tokens in the completion.
        temperature: Sampling temperature.
        timeout: Read timeout in seconds (connect timeout is fixed at 10 s).

    Returns:
        Anthropic-compatible dict:
        {
            "content": [{"type": "text", "text": "..."}],
            "usage": {"input_tokens": N, "output_tokens": N, "cost_usd": X}
        }

    Raises:
        RuntimeError: On non-2xx HTTP responses (after one retry on 429).
        ValueError: If OPENROUTER_API_KEY is not set.
    """
    api_key = get_api_key()
    model = resolve_model(call_site)

    converted_messages = anthropic_to_openai(messages, system)
    body = {
        "model": model,
        "messages": converted_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        **_HEADERS_STATIC,
        "Authorization": f"Bearer {api_key}",
    }

    timeout_obj = httpx.Timeout(timeout, connect=10.0)

    start_ms = int(time.monotonic() * 1000)
    response_json: dict = {}

    async with httpx.AsyncClient(timeout=timeout_obj) as client:
        resp = await client.post(OPENROUTER_BASE, json=body, headers=headers)

        if resp.status_code == 429:
            # Rate-limited — wait 2 s and retry once.
            await asyncio.sleep(2)
            resp = await client.post(OPENROUTER_BASE, json=body, headers=headers)

        if resp.status_code < 200 or resp.status_code >= 300:
            raise RuntimeError(
                f"OpenRouter error {resp.status_code}: {resp.text}"
            )

        response_json = resp.json()

    latency_ms = int(time.monotonic() * 1000) - start_ms

    result = openai_to_anthropic(response_json)

    # Log cost in the background without blocking the caller.
    from llm.cost import log_cost  # local import to avoid circular deps at module load

    usage = result.get("usage", {})
    asyncio.create_task(
        log_cost(
            call_site=call_site,
            model=model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            latency_ms=latency_ms,
            cost_usd=usage.get("cost_usd"),
        )
    )

    return result
