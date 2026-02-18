"""tests/test_llm_format.py — Unit tests for llm/format.py.

No network calls, no DB. Pure format translation logic only.
"""

import pytest

from llm.format import anthropic_to_openai, openai_to_anthropic


# ---------------------------------------------------------------------------
# anthropic_to_openai
# ---------------------------------------------------------------------------


def test_system_becomes_first_message() -> None:
    """System string should become the first message with role 'system'."""
    messages = [{"role": "user", "content": "hello"}]
    result = anthropic_to_openai(messages, system="You are a shopkeeper.")

    assert result[0]["role"] == "system"
    assert result[0]["content"] == "You are a shopkeeper."


def test_no_system_no_prepend() -> None:
    """None system should NOT prepend any system message."""
    messages = [{"role": "user", "content": "hi"}]
    result = anthropic_to_openai(messages, system=None)

    assert result[0]["role"] == "user"
    assert len(result) == 1


def test_string_content_passthrough() -> None:
    """String content should pass through unchanged."""
    messages = [{"role": "assistant", "content": "I am a shopkeeper."}]
    result = anthropic_to_openai(messages, system=None)

    assert result[0]["content"] == "I am a shopkeeper."


def test_content_block_list_extracted() -> None:
    """Content block list should be collapsed to the joined text of all text blocks."""
    content_blocks = [{"type": "text", "text": "hello"}]
    messages = [{"role": "assistant", "content": content_blocks}]
    result = anthropic_to_openai(messages, system=None)

    assert result[0]["content"] == "hello"


def test_content_block_list_multiple_blocks_joined() -> None:
    """Multiple text blocks should be joined without separator."""
    content_blocks = [
        {"type": "text", "text": "hello "},
        {"type": "text", "text": "world"},
    ]
    messages = [{"role": "user", "content": content_blocks}]
    result = anthropic_to_openai(messages, system=None)

    assert result[0]["content"] == "hello world"


def test_content_block_non_text_skipped() -> None:
    """Non-text content blocks (e.g. tool_use) should be ignored."""
    content_blocks = [
        {"type": "tool_use", "id": "t1", "name": "browse", "input": {}},
        {"type": "text", "text": "done"},
    ]
    messages = [{"role": "assistant", "content": content_blocks}]
    result = anthropic_to_openai(messages, system=None)

    assert result[0]["content"] == "done"


def test_message_order_preserved() -> None:
    """Message order should be preserved after system prepend."""
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "second"},
        {"role": "user", "content": "third"},
    ]
    result = anthropic_to_openai(messages, system="sys")

    # system is index 0, then original order
    assert result[0]["role"] == "system"
    assert result[1]["content"] == "first"
    assert result[2]["content"] == "second"
    assert result[3]["content"] == "third"


# ---------------------------------------------------------------------------
# openai_to_anthropic
# ---------------------------------------------------------------------------


def test_openai_to_anthropic_basic() -> None:
    """choices[0].message.content should become content[0].text."""
    response = {
        "choices": [{"message": {"content": "Hello from OpenRouter"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001},
    }
    result = openai_to_anthropic(response)

    assert result["content"][0]["type"] == "text"
    assert result["content"][0]["text"] == "Hello from OpenRouter"


def test_usage_mapping() -> None:
    """prompt_tokens → input_tokens, completion_tokens → output_tokens."""
    response = {
        "choices": [{"message": {"content": "hi"}}],
        "usage": {"prompt_tokens": 42, "completion_tokens": 17, "cost": 0.0},
    }
    result = openai_to_anthropic(response)

    assert result["usage"]["input_tokens"] == 42
    assert result["usage"]["output_tokens"] == 17


def test_cost_field_mapped() -> None:
    """usage.cost in OpenRouter response → usage.cost_usd in output."""
    response = {
        "choices": [{"message": {"content": "text"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.00042},
    }
    result = openai_to_anthropic(response)

    assert result["usage"]["cost_usd"] == pytest.approx(0.00042)


def test_missing_cost_defaults_to_zero() -> None:
    """If usage.cost is absent, cost_usd should default to 0.0."""
    response = {
        "choices": [{"message": {"content": "text"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }
    result = openai_to_anthropic(response)

    assert result["usage"]["cost_usd"] == 0.0


def test_missing_usage_defaults() -> None:
    """If usage block is entirely absent, tokens and cost default to 0."""
    response = {
        "choices": [{"message": {"content": "text"}}],
    }
    result = openai_to_anthropic(response)

    assert result["usage"]["input_tokens"] == 0
    assert result["usage"]["output_tokens"] == 0
    assert result["usage"]["cost_usd"] == 0.0
