"""llm/config.py — Model resolution and API key configuration for OpenRouter.

Environment variables:
    OPENROUTER_API_KEY      Required. OpenRouter API key.
    LLM_DEFAULT_MODEL       Optional. Fallback model for all call sites.
                            Defaults to x-ai/grok-4.1-fast.
    LLM_CORTEX_MODEL        Optional. Model for "cortex" and "cortex_maintenance" calls.
    LLM_REFLECT_MODEL       Optional. Model for "reflect" calls.
    LLM_SLEEP_MODEL         Optional. Model for "sleep" calls.
    LLM_EMBED_MODEL         Optional. Model for "embed" calls.

Resolution order per call site:
    1. Call-site-specific env var (e.g. LLM_CORTEX_MODEL)
    2. LLM_DEFAULT_MODEL env var
    3. Hardcoded default: x-ai/grok-4.1-fast
"""

from __future__ import annotations

import os

_HARDCODED_DEFAULT: str = "x-ai/grok-4.1-fast"

# Maps call_site name → env var that overrides the model for that site.
_CALL_SITE_ENV: dict[str, str] = {
    "cortex": "LLM_CORTEX_MODEL",
    "cortex_maintenance": "LLM_CORTEX_MODEL",
    "reflect": "LLM_REFLECT_MODEL",
    "sleep": "LLM_SLEEP_MODEL",
    "embed": "LLM_EMBED_MODEL",
}


def get_api_key() -> str:
    """Return the OpenRouter API key from the environment.

    Returns:
        The value of OPENROUTER_API_KEY.

    Raises:
        ValueError: If OPENROUTER_API_KEY is not set.
    """
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise ValueError(
            "OPENROUTER_API_KEY environment variable is not set. "
            "Set it to your OpenRouter API key before running."
        )
    return key


def resolve_model(call_site: str) -> str:
    """Resolve the model name to use for a given call site.

    Resolution order:
        1. Call-site-specific env var (LLM_CORTEX_MODEL, LLM_REFLECT_MODEL, etc.)
        2. LLM_DEFAULT_MODEL env var
        3. Hardcoded default: x-ai/grok-4.1-fast

    Args:
        call_site: Logical name for the call (e.g. "cortex", "reflect", "sleep").
                   Unknown call sites fall through to the default.

    Returns:
        A model identifier string in "provider/model-name" format.
    """
    # Layer 1: call-site-specific env var
    site_env_var = _CALL_SITE_ENV.get(call_site)
    if site_env_var:
        site_model = os.environ.get(site_env_var)
        if site_model:
            return site_model

    # Layer 2: global default env var
    default_model = os.environ.get("LLM_DEFAULT_MODEL")
    if default_model:
        return default_model

    # Layer 3: hardcoded default
    return _HARDCODED_DEFAULT
