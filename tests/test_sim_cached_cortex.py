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


def test_strip_drives_removes_drive_lines(cache_dir):
    """Should strip drive value lines from system prompt."""
    cached = CachedCortex(cache_dir=cache_dir)

    system = """DRIVES:
  social_hunger: 0.537
  curiosity: 0.412
  expression_need: 0.300
  energy: 0.800
  mood_valence: -0.100
  mood_arousal: 0.300

CONSTRAINTS:
- Return ONLY valid JSON"""

    stripped = cached._strip_drives(system)
    assert "social_hunger" not in stripped
    assert "curiosity" not in stripped
    assert "CONSTRAINTS:" in stripped
    assert "Return ONLY valid JSON" in stripped


def test_strip_drives_removes_feelings(cache_dir):
    """Should strip CURRENT FEELINGS block from system prompt."""
    cached = CachedCortex(cache_dir=cache_dir)

    system = """VOICE RULES:
- short sentences

CURRENT FEELINGS:
Mood: neutral, present, quiet. Valence +0.00, arousal 0.30.

CONSTRAINTS:
- Return ONLY valid JSON"""

    stripped = cached._strip_drives(system)
    assert "Mood:" not in stripped
    assert "CURRENT FEELINGS:" not in stripped
    assert "VOICE RULES:" in stripped
    assert "CONSTRAINTS:" in stripped


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


def test_hash_stable_despite_drive_changes(cache_dir):
    """Cache keys should be stable when only drive values change in system prompt."""
    cached = CachedCortex(cache_dir=cache_dir)

    system_a = """DRIVES:
  social_hunger: 0.537
  curiosity: 0.412

CONSTRAINTS:
- Return ONLY valid JSON"""

    system_b = """DRIVES:
  social_hunger: 0.900
  curiosity: 0.100

CONSTRAINTS:
- Return ONLY valid JSON"""

    msg = [{"role": "user", "content": "No new events. Continue your day."}]

    h1 = cached._hash_context(msg, system_a, "cortex")
    h2 = cached._hash_context(msg, system_b, "cortex")

    assert h1 == h2


def test_hash_differs_by_variant(cache_dir):
    """Different variants should produce different cache keys."""
    cached_full = CachedCortex(cache_dir=cache_dir, variant="full")
    cached_ablated = CachedCortex(cache_dir=cache_dir, variant="no_drives")

    msg = [{"role": "user", "content": "No new events."}]
    h1 = cached_full._hash_context(msg, "sys", "cortex")
    h2 = cached_ablated._hash_context(msg, "sys", "cortex")

    assert h1 != h2


@pytest.mark.asyncio
async def test_max_reuse_cap(cache_dir):
    """After max_reuse hits, should force a cache miss."""
    mock_response = {
        "content": [{"type": "text", "text": '{"test": true}'}],
        "usage": {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.001},
    }

    with patch("llm.client.complete", new_callable=AsyncMock, return_value=mock_response):
        cached = CachedCortex(cache_dir=cache_dir, max_reuse=2)
        messages = [{"role": "user", "content": "Same input"}]

        # Call 1 — cache miss (no file yet), reuse_counts[key] = 1
        await cached.complete(messages=messages, call_site="cortex")
        assert cached.misses == 1
        assert cached.hits == 0

        # Call 2 — cache hit (reuse_counts[key]=1 < 2), bumps to 2
        await cached.complete(messages=messages, call_site="cortex")
        assert cached.hits == 1

        # Call 3 — forced miss (reuse_counts[key]=2, not < 2), resets to 1
        await cached.complete(messages=messages, call_site="cortex")
        assert cached.misses == 2
        assert cached.forced_misses == 1

        # Call 4 — cache hit again (reuse_counts[key]=1 < 2)
        await cached.complete(messages=messages, call_site="cortex")
        assert cached.hits == 2
