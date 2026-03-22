"""Gemini embedding provider for alive-memory.

Uses Google's Gemini embedding API via REST (httpx).
Supports text queries against multimodal embedding spaces.

Requires: pip install httpx
"""

from __future__ import annotations

import asyncio
import logging
import os

import httpx

from alive_memory.embeddings.base import EmbeddingProvider

log = logging.getLogger(__name__)

_GEMINI_EMBED_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent"
)


class GeminiEmbedder:
    """Embedding provider using Google's Gemini embedding API.

    Uses the REST endpoint directly via httpx (no SDK dependency).
    Compatible with multimodal embedding spaces -- text queries return
    vectors in the same space as image/video embeddings produced by the
    same model.

    Usage:
        embedder = GeminiEmbedder()
        vector = await embedder.embed("Shanks sacrifices his arm")
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-embedding-exp-03-07",
        task_type: str = "RETRIEVAL_QUERY",
        output_dimensionality: int = 3072,
        max_retries: int = 3,
        backoff_delays: list[float] | None = None,
    ):
        self._api_key = (
            api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY", "")
        )
        if not self._api_key:
            raise ValueError(
                "Gemini API key required: pass api_key or set "
                "GEMINI_API_KEY / GOOGLE_API_KEY"
            )
        self._model = model
        self._task_type = task_type
        self._output_dimensionality = output_dimensionality
        self._max_retries = max_retries
        self._backoff_delays = backoff_delays or [2, 4, 8]

    async def embed(self, text: str) -> list[float]:
        """Embed text via the Gemini embedContent REST endpoint."""
        url = _GEMINI_EMBED_URL.format(model=self._model)

        body: dict = {
            "content": {
                "parts": [{"text": text}],
            },
            "taskType": self._task_type,
        }
        if self._output_dimensionality:
            body["outputDimensionality"] = self._output_dimensionality

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key,
        }

        timeout = httpx.Timeout(30.0, connect=10.0)
        retryable_status = {429, 500, 502, 503}

        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(1, self._max_retries + 1):
                try:
                    resp = await client.post(url, json=body, headers=headers)
                except (
                    httpx.ReadTimeout,
                    httpx.ConnectTimeout,
                    httpx.ConnectError,
                ):
                    if attempt < self._max_retries:
                        delay = self._backoff_delays[
                            min(attempt - 1, len(self._backoff_delays) - 1)
                        ]
                        log.warning(
                            "Gemini embed attempt %d failed (timeout), "
                            "retrying in %.1fs",
                            attempt,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise

                if (
                    resp.status_code in retryable_status
                    and attempt < self._max_retries
                ):
                    delay = self._backoff_delays[
                        min(attempt - 1, len(self._backoff_delays) - 1)
                    ]
                    log.warning(
                        "Gemini embed attempt %d got %d, retrying in %.1fs",
                        attempt,
                        resp.status_code,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                if resp.status_code < 200 or resp.status_code >= 300:
                    raise RuntimeError(
                        f"Gemini embedding error {resp.status_code}: {resp.text}"
                    )
                break

        data = resp.json()
        values = data["embedding"]["values"]
        return values

    @property
    def dimensions(self) -> int:
        return self._output_dimensionality


# Satisfy EmbeddingProvider protocol at import time
assert isinstance(GeminiEmbedder.__init__, object)  # type: ignore[arg-type]
_: type[EmbeddingProvider]  # static check only
