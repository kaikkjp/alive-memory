"""llm/cost.py — Cost logging for OpenRouter LLM calls.

Writes to the existing llm_call_log table via db.insert_llm_call_log().
This is the new cost-logging path for calls made through llm/client.py.
The legacy llm_logger.py is kept unchanged for backward compatibility.

Migration 024_llm_call_log_extend.sql adds call_site and latency_ms columns,
which are populated by this module on every call.
"""

from __future__ import annotations

import uuid

import db


async def log_cost(
    call_site: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    cost_usd: float | None = None,
    cycle_id: str | None = None,
    run_id: str | None = None,
    trace_id: str | None = None,
    success: bool = True,
    error_type: str | None = None,
    request_id: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    cache_hit: bool | None = None,
    used_cached_prompt: bool | None = None,
    input_hash: str | None = None,
    output_hash: str | None = None,
) -> None:
    """Log an LLM call cost entry to the database.

    Uses the existing db.insert_llm_call_log() function.  Provider is always
    "openrouter" for calls made through llm/client.py.

    Args:
        call_site: Logical call site name (e.g. "cortex", "reflect").
                   Used as the ``purpose`` field in llm_call_log.
        model: Full model identifier (e.g. "anthropic/claude-sonnet-4-5-20250929").
        input_tokens: Number of prompt tokens consumed.
        output_tokens: Number of completion tokens generated.
        latency_ms: Round-trip latency in milliseconds.
        cost_usd: Exact cost from OpenRouter usage.cost field.  Pass None if
                  the response did not include a cost figure.
        cycle_id: Optional cognitive cycle ID for correlation.
        run_id: Optional strict run identifier.
        trace_id: Optional trace identifier for cross-table joins.
    """
    call_id = str(uuid.uuid4())
    await db.insert_llm_call_log(
        call_id=call_id,
        provider="openrouter",
        model=model,
        purpose=call_site,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd if cost_usd is not None else 0.0,
        cycle_id=cycle_id,
        call_site=call_site,
        latency_ms=latency_ms,
        run_id=run_id,
        stage=call_site,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        success=success,
        error_type=error_type,
        request_id=request_id,
        cache_hit=cache_hit,
        used_cached_prompt=used_cached_prompt,
        input_hash=input_hash,
        output_hash=output_hash,
        trace_id=trace_id,
    )
