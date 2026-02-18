"""tests/test_llm_client.py — Unit tests for llm/client.py.

No real network calls — httpx.AsyncClient is fully mocked.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OPENROUTER_SUCCESS = {
    "choices": [{"message": {"content": "Hello from the model."}}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
}


def _make_http_response(status_code: int = 200, json_body: dict | None = None) -> MagicMock:
    """Return a mock httpx.Response-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or _OPENROUTER_SUCCESS
    resp.text = str(json_body or _OPENROUTER_SUCCESS)
    return resp


def _make_async_client_ctx(responses: list[MagicMock]) -> MagicMock:
    """
    Return a mock that acts as 'async with httpx.AsyncClient(...) as client'.

    responses: ordered list of mock responses returned on successive .post() calls.
    """
    client_instance = AsyncMock()
    # Make .post() return responses in order (side_effect accepts an iterable)
    client_instance.post = AsyncMock(side_effect=responses)

    ctx_manager = MagicMock()
    ctx_manager.__aenter__ = AsyncMock(return_value=client_instance)
    ctx_manager.__aexit__ = AsyncMock(return_value=False)
    return ctx_manager


# ---------------------------------------------------------------------------
# test_complete_formats_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_formats_request() -> None:
    """complete() should POST to the correct URL with correct headers and body."""
    resp_mock = _make_http_response()
    ctx_mock = _make_async_client_ctx([resp_mock])

    env = {
        "OPENROUTER_API_KEY": "test-key-abc",
        "LLM_DEFAULT_MODEL": "anthropic/claude-sonnet-4-5-20250929",
    }
    with patch("httpx.AsyncClient", return_value=ctx_mock), \
         patch.dict("os.environ", env, clear=False), \
         patch("asyncio.create_task"):
        from llm.client import complete
        await complete(
            messages=[{"role": "user", "content": "hi"}],
            system="You are a shopkeeper.",
            call_site="cortex",
            max_tokens=100,
            temperature=0.5,
        )

    client_instance = await ctx_mock.__aenter__()
    post_call = client_instance.post.call_args

    # Correct URL
    assert post_call.args[0] == "https://openrouter.ai/api/v1/chat/completions"

    # Authorization header
    headers = post_call.kwargs["headers"]
    assert headers["Authorization"] == "Bearer test-key-abc"
    assert headers["HTTP-Referer"] == "https://github.com/TriMinhPham/shopkeeper"
    assert headers["X-Title"] == "The Shopkeeper"

    # Body shape
    body = post_call.kwargs["json"]
    assert body["max_tokens"] == 100
    assert body["temperature"] == 0.5
    # System becomes first message in OpenAI format
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][0]["content"] == "You are a shopkeeper."


# ---------------------------------------------------------------------------
# test_complete_returns_anthropic_shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_returns_anthropic_shape() -> None:
    """complete() should return an Anthropic-shaped dict regardless of OpenAI input."""
    openai_response = {
        "choices": [{"message": {"content": "I am the shopkeeper."}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 8, "cost": 0.0005},
    }
    resp_mock = _make_http_response(200, openai_response)
    ctx_mock = _make_async_client_ctx([resp_mock])

    env = {"OPENROUTER_API_KEY": "test-key-xyz"}
    with patch("httpx.AsyncClient", return_value=ctx_mock), \
         patch.dict("os.environ", env, clear=False), \
         patch("asyncio.create_task"):
        from llm.client import complete
        result = await complete(
            messages=[{"role": "user", "content": "who are you?"}],
        )

    # Anthropic shape
    assert "content" in result
    assert result["content"][0]["type"] == "text"
    assert result["content"][0]["text"] == "I am the shopkeeper."

    assert "usage" in result
    assert result["usage"]["input_tokens"] == 20
    assert result["usage"]["output_tokens"] == 8
    assert result["usage"]["cost_usd"] == pytest.approx(0.0005)


# ---------------------------------------------------------------------------
# test_complete_retries_on_429
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_retries_on_429() -> None:
    """complete() should retry once on 429 and succeed on the second call."""
    rate_limit_resp = _make_http_response(429, {"error": "rate limited"})
    success_resp = _make_http_response(200)

    ctx_mock = _make_async_client_ctx([rate_limit_resp, success_resp])

    env = {"OPENROUTER_API_KEY": "test-key"}
    with patch("httpx.AsyncClient", return_value=ctx_mock), \
         patch.dict("os.environ", env, clear=False), \
         patch("asyncio.sleep", new_callable=AsyncMock) as sleep_mock, \
         patch("asyncio.create_task"):
        from llm.client import complete
        result = await complete(messages=[{"role": "user", "content": "test"}])

    # Two POST calls made
    client_instance = await ctx_mock.__aenter__()
    assert client_instance.post.call_count == 2

    # Sleep was called with 2 seconds
    sleep_mock.assert_called_once_with(2)

    # Still returns a valid result from the second call
    assert result["content"][0]["type"] == "text"


# ---------------------------------------------------------------------------
# test_complete_raises_on_error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_raises_on_error() -> None:
    """complete() should raise RuntimeError on a non-2xx, non-429 response."""
    error_resp = _make_http_response(500, {"error": "internal server error"})
    ctx_mock = _make_async_client_ctx([error_resp])

    env = {"OPENROUTER_API_KEY": "test-key"}
    with patch("httpx.AsyncClient", return_value=ctx_mock), \
         patch.dict("os.environ", env, clear=False):
        from llm.client import complete
        with pytest.raises(RuntimeError, match="OpenRouter error 500"):
            await complete(messages=[{"role": "user", "content": "test"}])
