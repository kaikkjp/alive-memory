"""llm/format.py — Bidirectional format translation between Anthropic and OpenAI/OpenRouter shapes.

Anthropic request format (what cortex.py produces today):
  system = "You are..."          # separate string param
  messages = [
      {"role": "user", "content": "hello"},
      {"role": "assistant", "content": [{"type": "text", "text": "..."}]},
  ]

OpenAI/OpenRouter request format (what we send to OpenRouter):
  messages = [
      {"role": "system", "content": "You are..."},   # system as first message
      {"role": "user", "content": "hello"},
      {"role": "assistant", "content": "..."},        # string, not list of blocks
  ]

OpenRouter response format:
  {
    "choices": [{"message": {"content": "..."}}],
    "usage": {"prompt_tokens": N, "completion_tokens": N, "cost": X}
  }

Anthropic response format (what cortex.py expects today):
  {
    "content": [{"type": "text", "text": "..."}],
    "usage": {"input_tokens": N, "output_tokens": N, "cost_usd": X}
  }
"""

from __future__ import annotations


def anthropic_to_openai(
    messages: list[dict],
    system: str | None,
) -> list[dict]:
    """Convert Anthropic-style messages + system param to OpenAI messages array.

    Args:
        messages: List of Anthropic message dicts with "role" and "content" keys.
                  Content may be a string or a list of content blocks
                  (e.g. [{"type": "text", "text": "..."}]).
        system: Optional system prompt string. If provided, it is prepended as
                a {"role": "system", "content": <system>} message.

    Returns:
        List of OpenAI-compatible message dicts. Content is always a string.
    """
    result: list[dict] = []

    if system is not None:
        result.append({"role": "system", "content": system})

    for msg in messages:
        content = msg["content"]

        # Content blocks list → extract text and join
        if isinstance(content, list):
            text_parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            content = "".join(text_parts)

        result.append({"role": msg["role"], "content": content})

    return result


def openai_to_anthropic(response: dict) -> dict:
    """Convert an OpenRouter (OpenAI-compatible) response to Anthropic response shape.

    Args:
        response: OpenRouter response dict with the shape:
            {
                "choices": [{"message": {"content": "..."}}],
                "usage": {
                    "prompt_tokens": N,
                    "completion_tokens": N,
                    "cost": X       # USD, provided by OpenRouter
                }
            }

    Returns:
        Anthropic-compatible response dict:
            {
                "content": [{"type": "text", "text": "..."}],
                "usage": {
                    "input_tokens": N,
                    "output_tokens": N,
                    "cost_usd": X
                }
            }
    """
    text: str = response["choices"][0]["message"]["content"]

    raw_usage: dict = response.get("usage", {})
    usage: dict = {
        "input_tokens": raw_usage.get("prompt_tokens", 0),
        "output_tokens": raw_usage.get("completion_tokens", 0),
        "cost_usd": raw_usage.get("cost", 0.0),
    }

    return {
        "content": [{"type": "text", "text": text}],
        "usage": usage,
    }
