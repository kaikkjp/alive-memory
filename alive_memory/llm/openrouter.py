"""OpenRouter provider for alive-memory.

Uses raw httpx to call the OpenRouter chat completions endpoint.
No SDK dependency beyond httpx.

Requires: pip install httpx
"""

from __future__ import annotations

import asyncio
import os

import httpx

from alive_memory.llm.provider import LLMResponse

OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions"

_HEADERS_STATIC = {
    "Content-Type": "application/json",
    "HTTP-Referer": "https://github.com/alive-sdk/alive-memory",
    "X-Title": "alive-memory SDK",
}


class OpenRouterProvider:
    """LLM provider using OpenRouter's OpenAI-compatible API.

    Usage:
        provider = OpenRouterProvider(api_key="sk-or-...")
        response = await provider.complete("What is memory?")
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "anthropic/claude-sonnet-4-20250514",
        max_retries: int = 3,
        backoff_delays: list[float] | None = None,
    ):
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "OpenRouter API key required: pass api_key or set OPENROUTER_API_KEY"
            )
        self._model = model
        self._max_retries = max_retries
        self._backoff_delays = backoff_delays or [2, 4, 8]

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> LLMResponse:
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        headers = {
            **_HEADERS_STATIC,
            "Authorization": f"Bearer {self._api_key}",
        }

        timeout = httpx.Timeout(60.0, connect=10.0)
        retryable_status = {429, 500, 502, 503}

        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(1, self._max_retries + 1):
                try:
                    resp = await client.post(
                        OPENROUTER_BASE, json=body, headers=headers
                    )
                except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError):
                    if attempt < self._max_retries:
                        delay = self._backoff_delays[min(attempt - 1, len(self._backoff_delays) - 1)]
                        await asyncio.sleep(delay)
                        continue
                    raise

                if resp.status_code in retryable_status and attempt < self._max_retries:
                    delay = self._backoff_delays[min(attempt - 1, len(self._backoff_delays) - 1)]
                    await asyncio.sleep(delay)
                    continue

                if resp.status_code < 200 or resp.status_code >= 300:
                    raise RuntimeError(
                        f"OpenRouter error {resp.status_code}: {resp.text}"
                    )
                break

        data = resp.json()
        text = data["choices"][0]["message"].get("content", "")
        raw_usage = data.get("usage", {})

        return LLMResponse(
            text=text,
            input_tokens=raw_usage.get("prompt_tokens", 0),
            output_tokens=raw_usage.get("completion_tokens", 0),
            cost_usd=raw_usage.get("cost", 0.0),
            metadata={
                "model": data.get("model", self._model),
                "provider": "openrouter",
                "request_id": resp.headers.get("x-openrouter-request-id"),
            },
        )
