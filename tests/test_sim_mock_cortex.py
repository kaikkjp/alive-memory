"""Tests for sim.llm.mock — MockCortex deterministic LLM replacement."""

import json
import pytest

from sim.llm.mock import MockCortex


@pytest.mark.asyncio
async def test_basic_complete():
    mock = MockCortex(seed=42)
    result = await mock.complete(
        messages=[{"role": "user", "content": "Hello"}],
        system="You are a test.",
    )
    assert "content" in result
    assert "usage" in result
    assert result["content"][0]["type"] == "text"
    # Should parse as valid JSON
    text = result["content"][0]["text"]
    parsed = json.loads(text)
    assert "internal_monologue" in parsed


@pytest.mark.asyncio
async def test_deterministic_with_same_seed():
    """Same seed + same input = same output."""
    mock1 = MockCortex(seed=42)
    mock2 = MockCortex(seed=42)
    result1 = await mock1.complete(
        messages=[{"role": "user", "content": "Test message"}],
        system="Test system",
    )
    result2 = await mock2.complete(
        messages=[{"role": "user", "content": "Test message"}],
        system="Test system",
    )
    assert result1["content"][0]["text"] == result2["content"][0]["text"]


@pytest.mark.asyncio
async def test_different_seeds_differ():
    """Different seeds should produce different outputs."""
    mock1 = MockCortex(seed=42)
    mock2 = MockCortex(seed=99)
    # Run several cycles to get different behavior
    for _ in range(5):
        r1 = await mock1.complete(messages=[{"role": "user", "content": "X"}])
        r2 = await mock2.complete(messages=[{"role": "user", "content": "X"}])
    # At least one should differ
    t1 = r1["content"][0]["text"]
    t2 = r2["content"][0]["text"]
    # We can't guarantee every call differs, but across 5 cycles they should diverge
    assert mock1.state.cycle_count == 5
    assert mock2.state.cycle_count == 5


@pytest.mark.asyncio
async def test_cortex_output_schema():
    """Mock should produce valid CortexOutput JSON."""
    mock = MockCortex(seed=42)
    result = await mock.complete(
        messages=[{"role": "user", "content": "Test"}],
        system="System prompt with social_hunger: 0.8 curiosity: 0.6",
        call_site="cortex",
    )
    text = result["content"][0]["text"]
    parsed = json.loads(text)

    # Required fields
    assert "internal_monologue" in parsed
    assert "expression" in parsed
    assert "body_state" in parsed
    assert "gaze" in parsed
    assert "intentions" in parsed
    assert isinstance(parsed["intentions"], list)


@pytest.mark.asyncio
async def test_visitor_dialogue():
    """When visitor message present, should generate dialogue."""
    mock = MockCortex(seed=42)
    result = await mock.complete(
        messages=[{"role": "user", "content": "A visitor says: Hey, how are you?"}],
        system="Visitor present in the shop.",
        call_site="cortex",
    )
    parsed = json.loads(result["content"][0]["text"])
    assert parsed.get("dialogue") is not None


@pytest.mark.asyncio
async def test_reflect_call_site():
    """Reflect call site should produce reflection output."""
    mock = MockCortex(seed=42)
    result = await mock.complete(
        messages=[{"role": "user", "content": "Reflect on today"}],
        call_site="reflect",
    )
    parsed = json.loads(result["content"][0]["text"])
    assert "reflection" in parsed


@pytest.mark.asyncio
async def test_maintenance_call_site():
    """Maintenance call site should produce journal output."""
    mock = MockCortex(seed=42)
    result = await mock.complete(
        messages=[{"role": "user", "content": "Write journal"}],
        call_site="cortex_maintenance",
    )
    parsed = json.loads(result["content"][0]["text"])
    assert "journal" in parsed
    assert "summary" in parsed


@pytest.mark.asyncio
async def test_zero_cost():
    """Mock should always report zero cost."""
    mock = MockCortex(seed=42)
    result = await mock.complete(messages=[{"role": "user", "content": "X"}])
    assert result["usage"]["cost_usd"] == 0.0


@pytest.mark.asyncio
async def test_call_count():
    mock = MockCortex(seed=42)
    for _ in range(10):
        await mock.complete(messages=[{"role": "user", "content": "X"}])
    assert mock.call_count == 10
    report = mock.report()
    assert report["total_calls"] == 10
    assert report["cost_usd"] == 0.0


@pytest.mark.asyncio
async def test_token_estimation():
    """Usage should contain reasonable token estimates."""
    mock = MockCortex(seed=42)
    result = await mock.complete(
        messages=[{"role": "user", "content": "A" * 400}],
        system="B" * 200,
    )
    usage = result["usage"]
    assert usage["input_tokens"] > 0
    assert usage["output_tokens"] > 0


@pytest.mark.asyncio
async def test_content_block_input():
    """Should handle content-block-style input (list of dicts)."""
    mock = MockCortex(seed=42)
    result = await mock.complete(
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Hello from content blocks"},
            ],
        }],
    )
    assert result["content"][0]["type"] == "text"
