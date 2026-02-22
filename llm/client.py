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
from runtime_context import hash_json, hash_text, resolve_cycle_id, resolve_run_id, resolve_trace_id

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
    cycle_id: str | None = None,
    run_id: str | None = None,
    trace_id: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
    timeout: float = 60.0,
    tools: list[dict] | None = None,
) -> dict:
    """Single entry point for all LLM completions.

    Converts Anthropic-style input to OpenAI format, sends the request to
    OpenRouter, converts the response back to Anthropic format, and returns it.

    Args:
        messages: Anthropic-style message list with "role" / "content" keys.
        system: Optional system prompt string (separate from messages).
        call_site: Logical name for this call site used for model resolution
                   and cost logging (e.g. "cortex", "reflect").
        cycle_id: Optional cycle correlation id propagated into llm_call_log.
        run_id: Optional run identifier. Defaults to active runtime run id.
        trace_id: Optional trace identifier. Defaults to active cycle trace id.
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
        RuntimeError: On non-2xx HTTP responses (after 3 retries for
            transient errors: ReadTimeout, ConnectError, 429, 502, 503).
        ValueError: If OPENROUTER_API_KEY is not set.
    """
    api_key = get_api_key()
    model = resolve_model(call_site)
    resolved_cycle_id = resolve_cycle_id(cycle_id)
    resolved_run_id = resolve_run_id(run_id)
    resolved_trace_id = resolve_trace_id(trace_id) or str(uuid.uuid4())[:12]

    converted_messages = anthropic_to_openai(messages, system)

    # ── TASK-078: Mark system message as cacheable for cortex calls ──
    # cache_control is an Anthropic extension.  OpenRouter passes it through
    # for Anthropic models and ignores it for others.  Safe to apply
    # unconditionally for cortex — the structured content-part format is
    # accepted by all OpenAI-compatible providers even if they skip the field.
    if call_site == "cortex" and system and converted_messages:
        first = converted_messages[0]
        if first.get("role") == "system":
            converted_messages[0] = {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": first["content"] if isinstance(first["content"], str) else first["content"],
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }

    body = {
        "model": model,
        "messages": converted_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        body["tools"] = tools

    # TASK-076: Native JSON schema for models that benefit from it (sim-only)
    if "minimax" in model.lower() or "m2.5" in model.lower():
        try:
            from llm.schema import SHOPKEEPER_SCHEMA
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "shopkeeper_response",
                    "strict": True,
                    "schema": SHOPKEEPER_SCHEMA,
                }
            }
        except ImportError:
            pass  # schema not defined yet — skip

    headers = {
        **_HEADERS_STATIC,
        "Authorization": f"Bearer {api_key}",
    }

    timeout_obj = httpx.Timeout(timeout, connect=10.0)

    start_ms = int(time.monotonic() * 1000)
    response_json: dict = {}
    request_id: str | None = None
    served_model = model
    usage: dict = {}
    output_hash = ""
    success = False
    error_type: str | None = None
    cache_hit: bool | None = None
    used_cached_prompt: bool | None = None
    input_hash = hash_json({
        "system": system or "",
        "messages": converted_messages,
        "tools": tools or [],
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
    })

    try:
        async with httpx.AsyncClient(timeout=timeout_obj) as client:
            # ── Retry with exponential backoff for transient errors ──
            # Retryable: ReadTimeout, ConnectTimeout, ConnectError, 429, 500, 502, 503
            # Non-retryable: 400, 401, 403 (auth/validation — won't self-heal)
            _RETRYABLE_STATUS = {429, 500, 502, 503}
            _MAX_ATTEMPTS = 3
            _BACKOFF_DELAYS = [2, 4, 8]

            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    resp = await client.post(
                        OPENROUTER_BASE, json=body, headers=headers
                    )
                except (
                    httpx.ReadTimeout,
                    httpx.ConnectTimeout,
                    httpx.ConnectError,
                ) as exc:
                    if attempt < _MAX_ATTEMPTS:
                        delay = _BACKOFF_DELAYS[attempt - 1]
                        print(
                            f"[LLM] Retry {attempt}/{_MAX_ATTEMPTS}: "
                            f"{type(exc).__name__}, backoff {delay}s "
                            f"[{call_site}]"
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise

                if resp.status_code in _RETRYABLE_STATUS:
                    if attempt < _MAX_ATTEMPTS:
                        delay = _BACKOFF_DELAYS[attempt - 1]
                        print(
                            f"[LLM] Retry {attempt}/{_MAX_ATTEMPTS}: "
                            f"HTTP {resp.status_code}, backoff {delay}s "
                            f"[{call_site}]"
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise RuntimeError(
                        f"OpenRouter error {resp.status_code} after "
                        f"{_MAX_ATTEMPTS} attempts: {resp.text}"
                    )

                # Non-retryable HTTP errors — fail immediately
                if resp.status_code < 200 or resp.status_code >= 300:
                    raise RuntimeError(
                        f"OpenRouter error {resp.status_code}: {resp.text}"
                    )

                # Success — exit retry loop
                break

            request_id = (
                resp.headers.get("x-openrouter-request-id")
                or resp.headers.get("x-request-id")
            )
            response_json = resp.json()

        # OpenRouter returns the model that actually served the request,
        # which may differ from what we asked for (fallback routing).
        served_model = response_json.get("model", model)
        if served_model != model:
            print(f"[LLM] WARNING: requested {model} but served {served_model}")

        result = openai_to_anthropic(response_json)
        usage = result.get("usage", {}) or {}

        content_blocks = result.get("content", [])
        if isinstance(content_blocks, list):
            out_text = []
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    out_text.append(str(block.get("text", "")))
                elif isinstance(block, str):
                    out_text.append(block)
            output_hash = hash_text("\n".join(out_text))
        elif isinstance(content_blocks, str):
            output_hash = hash_text(content_blocks)

        cache_hit = response_json.get("cache_hit")
        used_cached_prompt = response_json.get("used_cached_prompt")

        # ── TASK-078: Log cache hit rate for cortex calls ──
        raw_usage = response_json.get("usage", {})
        cached_tokens = raw_usage.get("cache_read_input_tokens", 0) or raw_usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)
        prompt_tokens_total = raw_usage.get("prompt_tokens", 0)
        if prompt_tokens_total > 0 and cached_tokens > 0:
            print(f"  [Cache] {cached_tokens}/{prompt_tokens_total} tokens cached "
                  f"({cached_tokens / prompt_tokens_total * 100:.1f}%)")

        success = True
        return result
    except Exception as e:
        error_type = type(e).__name__
        raise
    finally:
        latency_ms = int(time.monotonic() * 1000) - start_ms
        from llm.cost import log_cost  # local import to avoid circular deps at module load

        prompt_tokens = int(usage.get("input_tokens", 0))
        completion_tokens = int(usage.get("output_tokens", 0))
        total_tokens = prompt_tokens + completion_tokens

        asyncio.create_task(
            log_cost(
                call_site=call_site,
                model=served_model,
                input_tokens=prompt_tokens,
                output_tokens=completion_tokens,
                latency_ms=latency_ms,
                cost_usd=usage.get("cost_usd"),
                cycle_id=resolved_cycle_id,
                run_id=resolved_run_id,
                trace_id=resolved_trace_id,
                success=success,
                error_type=error_type,
                request_id=request_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cache_hit=cache_hit,
                used_cached_prompt=used_cached_prompt,
                input_hash=input_hash,
                output_hash=output_hash,
            )
        )
