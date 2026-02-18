"""llm — OpenRouter-backed LLM client module.

Exports:
    complete: Async function for all LLM completions.  Accepts Anthropic-style
              inputs and returns an Anthropic-compatible response dict.
"""

from llm.client import complete

__all__ = ["complete"]
