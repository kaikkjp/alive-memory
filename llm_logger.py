"""LLM Call Logger — Cost tracking for all LLM/API calls.

Wraps LLM calls with logging to the llm_call_log table for dashboard cost monitoring.
Provides cost estimation based on current API pricing.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional
import db


# Cost per 1K tokens (USD) — updated 2025-01
# Source: https://www.anthropic.com/pricing
COST_PER_1K = {
    'claude-sonnet-4-5-20250929': {
        'input': 0.003,
        'output': 0.015,
    },
    'claude-sonnet-4-20250514': {
        'input': 0.003,
        'output': 0.015,
    },
    'claude-opus-4-20250514': {
        'input': 0.015,
        'output': 0.075,
    },
    'imagen-4.0-generate-001': {
        'per_image': 0.04,  # Google Imagen 4.0 pricing (estimate)
    },
}


def estimate_cost(
    provider: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    images_generated: int = 0,
) -> float:
    """Estimate cost of an LLM/API call in USD.

    Args:
        provider: 'anthropic' | 'google' | 'openai' | etc.
        model: Full model ID string
        input_tokens: Input token count
        output_tokens: Output token count
        images_generated: Number of images generated (for image models)

    Returns:
        Estimated cost in USD

    Raises:
        ValueError: If model pricing unknown
    """
    if model not in COST_PER_1K:
        # Default fallback: use sonnet-4.5 pricing as safe upper bound for unknown models
        pricing = COST_PER_1K['claude-sonnet-4-5-20250929']
        input_cost = (input_tokens / 1000) * pricing['input']
        output_cost = (output_tokens / 1000) * pricing['output']
        return input_cost + output_cost

    pricing = COST_PER_1K[model]

    # Image generation model
    if 'per_image' in pricing:
        return images_generated * pricing['per_image']

    # Token-based model
    input_cost = (input_tokens / 1000) * pricing['input']
    output_cost = (output_tokens / 1000) * pricing['output']
    return input_cost + output_cost


async def log_llm_call(
    provider: str,
    model: str,
    purpose: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    images_generated: int = 0,
    cycle_id: Optional[str] = None,
) -> str:
    """Log an LLM call to the database with cost estimation.

    Args:
        provider: 'anthropic' | 'google' | 'openai' | etc.
        model: Full model ID string
        purpose: 'cortex' | 'cortex_maintenance' | 'image_gen' | etc.
        input_tokens: Input token count (for text models)
        output_tokens: Output token count (for text models)
        images_generated: Number of images generated (for image models)
        cycle_id: Optional cycle ID to link this call to a specific cycle

    Returns:
        Log entry ID
    """
    call_id = str(uuid.uuid4())
    cost_usd = estimate_cost(provider, model, input_tokens, output_tokens, images_generated)

    await db.insert_llm_call_log(
        call_id=call_id,
        provider=provider,
        model=model,
        purpose=purpose,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        cycle_id=cycle_id,
    )

    return call_id
