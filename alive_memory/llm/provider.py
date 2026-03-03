"""LLM provider protocol for alive-memory.

Any LLM backend (Anthropic, OpenRouter, local, mock) must implement
the LLMProvider protocol.  The SDK uses this for dreaming, reflection,
and identity evolution — all consolidation-time operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class LLMResponse:
    """Standardized response from an LLM call."""
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol that any LLM backend must implement.

    Used by consolidation (dreaming, reflection) and identity (evolution).
    Not needed for basic intake/recall.
    """

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Generate a completion from the given prompt.

        Args:
            prompt: The user/content prompt.
            system: Optional system prompt.
            max_tokens: Maximum tokens in response.
            temperature: Sampling temperature.

        Returns:
            LLMResponse with text and usage metadata.
        """
        ...
