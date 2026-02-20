"""Tests for sim.llm.cached — CachedCortex with response caching."""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sim.llm.cached import CachedCortex


@pytest.fixture
def cache_dir(tmp_path):
    return str(tmp_path / "test_cache")


@pytest.mark.asyncio
async def test_cache_miss_calls_llm(cache_dir):
    """On cache miss, should call the real LLM."""
    mock_response = {
        "content": [{"type": "text", "text": '{"internal_monologue": "test"}'}],
        "usage": {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001},
    }

    with patch("llm.client.complete", new_callable=AsyncMock, return_value=mock_response):
        cached = CachedCortex(cache_dir=cache_dir)
        result = await cached.complete(
            messages=[{"role": "user", "content": "Hello"}],
            system="Test",
            call_site="cortex",
        )

        assert cached.misses == 1
        assert cached.hits == 0
        assert result == mock_response
        assert cached.total_cost == 0.001


@pytest.mark.asyncio
async def test_cache_hit_returns_cached(cache_dir):
    """On cache hit, should return cached response without LLM call."""
    cached = CachedCortex(cache_dir=cache_dir)

    # Manually write a cache entry
    messages = [{"role": "user", "content": "Hello"}]
    system = "Test"
    cache_key = cached._hash_context(messages, system, "cortex")
    cache_file = Path(cache_dir) / f"{cache_key}.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    expected = {
        "content": [{"type": "text", "text": '{"test": true}'}],
        "usage": {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0},
    }
    cache_file.write_text(json.dumps(expected))

    result = await cached.complete(
        messages=messages,
        system=system,
        call_site="cortex",
    )

    assert cached.hits == 1
    assert cached.misses == 0
    assert result == expected


@pytest.mark.asyncio
async def test_cache_stores_response(cache_dir):
    """After a cache miss, the response should be stored for future use."""
    mock_response = {
        "content": [{"type": "text", "text": '{"cached": true}'}],
        "usage": {"input_tokens": 50, "output_tokens": 20, "cost_usd": 0.0005},
    }

    with patch("llm.client.complete", new_callable=AsyncMock, return_value=mock_response):
        cached = CachedCortex(cache_dir=cache_dir)
        messages = [{"role": "user", "content": "Store me"}]

        # First call — miss
        await cached.complete(messages=messages, call_site="cortex")
        assert cached.misses == 1

        # Second call — should hit cache
        result = await cached.complete(messages=messages, call_site="cortex")
        assert cached.hits == 1
        assert cached.misses == 1  # no new miss
        assert result == mock_response


def test_hash_deterministic(cache_dir):
    """Same input should produce same hash."""
    cached = CachedCortex(cache_dir=cache_dir)

    messages = [{"role": "user", "content": "Hello"}]
    h1 = cached._hash_context(messages, "system", "cortex")
    h2 = cached._hash_context(messages, "system", "cortex")
    assert h1 == h2


def test_hash_different_for_different_input(cache_dir):
    """Different input should produce different hash."""
    cached = CachedCortex(cache_dir=cache_dir)

    h1 = cached._hash_context([{"role": "user", "content": "A"}], "sys", "cortex")
    h2 = cached._hash_context([{"role": "user", "content": "B"}], "sys", "cortex")
    assert h1 != h2


def test_quantize_numbers(cache_dir):
    """Should round floats to 1 decimal place."""
    cached = CachedCortex(cache_dir=cache_dir)

    assert cached._quantize_numbers("value: 0.537") == "value: 0.5"
    assert cached._quantize_numbers("mood: -0.849") == "mood: -0.8"
    assert cached._quantize_numbers("energy: 0.1") == "energy: 0.1"


def test_quantize_preserves_integers(cache_dir):
    """Should not mangle integers."""
    cached = CachedCortex(cache_dir=cache_dir)
    assert "42" in cached._quantize_numbers("count: 42")


def test_stats(cache_dir):
    """Stats should report correct values."""
    cached = CachedCortex(cache_dir=cache_dir)
    cached.hits = 5
    cached.misses = 2
    cached.total_cost = 0.003

    stats = cached.stats()
    assert stats["hits"] == 5
    assert stats["misses"] == 2
    assert stats["total"] == 7
    assert abs(stats["hit_rate"] - 71.4) < 1
    assert stats["cost_usd"] == 0.003


def test_clear_cache(cache_dir):
    """Clear should remove all cached files."""
    cached = CachedCortex(cache_dir=cache_dir)
    Path(cache_dir).mkdir(parents=True, exist_ok=True)

    (Path(cache_dir) / "abc123.json").write_text('{}')
    (Path(cache_dir) / "def456.json").write_text('{}')

    cached.hits = 10
    cached.misses = 5
    cached.total_cost = 1.0

    cached.clear_cache()

    assert list(Path(cache_dir).glob("*.json")) == []
    assert cached.hits == 0
    assert cached.misses == 0
    assert cached.total_cost == 0.0


def test_hash_quantizes_drive_values(cache_dir):
    """Cache keys should be stable despite small drive fluctuations."""
    cached = CachedCortex(cache_dir=cache_dir)

    msg1 = [{"role": "user", "content": "social_hunger: 0.537 curiosity: 0.412"}]
    msg2 = [{"role": "user", "content": "social_hunger: 0.542 curiosity: 0.418"}]

    h1 = cached._hash_context(msg1, "sys", "cortex")
    h2 = cached._hash_context(msg2, "sys", "cortex")

    assert h1 == h2
