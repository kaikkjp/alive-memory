"""tests/test_llm_cost.py — Unit tests for llm/cost.py.

No real DB or network calls — db.insert_llm_call_log is fully mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_insert_mock() -> AsyncMock:
    """Return a coroutine mock that replaces db.insert_llm_call_log."""
    return AsyncMock(return_value=None)


# ---------------------------------------------------------------------------
# test_log_cost_calls_insert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_cost_calls_insert() -> None:
    """log_cost() should call db.insert_llm_call_log exactly once."""
    mock_insert = _make_insert_mock()

    with patch("llm.cost.db.insert_llm_call_log", mock_insert):
        from llm.cost import log_cost

        await log_cost(
            call_site="cortex",
            model="anthropic/claude-sonnet-4-5-20250929",
            input_tokens=100,
            output_tokens=50,
            latency_ms=1200,
            cost_usd=0.0015,
        )

    mock_insert.assert_called_once()


# ---------------------------------------------------------------------------
# test_log_cost_uses_openrouter_provider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_cost_uses_openrouter_provider() -> None:
    """log_cost() must pass provider='openrouter' to insert_llm_call_log."""
    mock_insert = _make_insert_mock()

    with patch("llm.cost.db.insert_llm_call_log", mock_insert):
        from llm.cost import log_cost

        await log_cost(
            call_site="reflect",
            model="openai/gpt-4o",
            input_tokens=200,
            output_tokens=80,
            latency_ms=900,
            cost_usd=0.003,
        )

    _call_kwargs = mock_insert.call_args.kwargs
    assert _call_kwargs.get("provider") == "openrouter"


# ---------------------------------------------------------------------------
# test_log_cost_passes_call_site_as_purpose
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_cost_passes_call_site_as_purpose() -> None:
    """log_cost() should use call_site as the purpose argument."""
    mock_insert = _make_insert_mock()

    with patch("llm.cost.db.insert_llm_call_log", mock_insert):
        from llm.cost import log_cost

        await log_cost(
            call_site="cortex_maintenance",
            model="anthropic/claude-sonnet-4-5-20250929",
            input_tokens=50,
            output_tokens=20,
            latency_ms=600,
            cost_usd=0.0005,
        )

    _call_kwargs = mock_insert.call_args.kwargs
    assert _call_kwargs.get("purpose") == "cortex_maintenance"


# ---------------------------------------------------------------------------
# test_log_cost_handles_none_cost
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_cost_handles_none_cost() -> None:
    """cost_usd=None should not raise; it is normalised to 0.0 before insert."""
    mock_insert = _make_insert_mock()

    with patch("llm.cost.db.insert_llm_call_log", mock_insert):
        from llm.cost import log_cost

        # Should not raise
        await log_cost(
            call_site="default",
            model="anthropic/claude-sonnet-4-5-20250929",
            input_tokens=10,
            output_tokens=5,
            latency_ms=300,
            cost_usd=None,
        )

    _call_kwargs = mock_insert.call_args.kwargs
    # None should be normalised to 0.0
    assert _call_kwargs.get("cost_usd") == 0.0


# ---------------------------------------------------------------------------
# test_log_cost_passes_token_counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_cost_passes_token_counts() -> None:
    """log_cost() should pass input_tokens and output_tokens correctly."""
    mock_insert = _make_insert_mock()

    with patch("llm.cost.db.insert_llm_call_log", mock_insert):
        from llm.cost import log_cost

        await log_cost(
            call_site="cortex",
            model="anthropic/claude-sonnet-4-5-20250929",
            input_tokens=123,
            output_tokens=456,
            latency_ms=800,
            cost_usd=0.002,
        )

    _call_kwargs = mock_insert.call_args.kwargs
    assert _call_kwargs.get("input_tokens") == 123
    assert _call_kwargs.get("output_tokens") == 456


# ---------------------------------------------------------------------------
# test_log_cost_passes_call_site_and_latency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_cost_passes_call_site_and_latency() -> None:
    """log_cost() should pass call_site and latency_ms to insert_llm_call_log."""
    mock_insert = _make_insert_mock()

    with patch("llm.cost.db.insert_llm_call_log", mock_insert):
        from llm.cost import log_cost

        await log_cost(
            call_site="cortex",
            model="anthropic/claude-sonnet-4-5-20250929",
            input_tokens=100,
            output_tokens=50,
            latency_ms=1234,
            cost_usd=0.001,
        )

    _call_kwargs = mock_insert.call_args.kwargs
    assert _call_kwargs.get("call_site") == "cortex"
    assert _call_kwargs.get("latency_ms") == 1234
