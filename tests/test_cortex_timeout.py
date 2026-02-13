"""Tests for cortex API timeout, cancellation, and singleton client behavior.

Covers the fix for BUG-2026-02-13-simulation-api-timeout-hang:
- Hard 60s timeout via asyncio.wait_for cancels hung requests
- Broader exception handling catches APIError, httpx, and generic errors
- Singleton client reuse prevents connection pool exhaustion
- Fallback response returned on all failure modes
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import httpx
import pytest

# Mock db module before importing cortex (avoids sqlite init)
import unittest.mock
import sys
_mock_db = unittest.mock.MagicMock()
_mock_db.get_visitor_traits = unittest.mock.AsyncMock(return_value=[])
_mock_db.get_active_threads = unittest.mock.AsyncMock(return_value=[])
sys.modules.setdefault("db", _mock_db)

from models.state import DrivesState, Visitor
from pipeline.sensorium import Perception
from pipeline.thalamus import RoutingDecision

# ── Fixtures ──


def _make_drives() -> DrivesState:
    return DrivesState(
        social_hunger=0.5,
        curiosity=0.5,
        expression_need=0.3,
        rest_need=0.2,
        energy=0.8,
        mood_valence=0.0,
        mood_arousal=0.3,
    )


def _make_perception() -> Perception:
    return Perception(
        p_type="visitor_speech",
        source="visitor:v1",
        ts=datetime.now(timezone.utc),
        content="Hello",
        features={},
        salience=0.6,
    )


def _make_routing() -> RoutingDecision:
    return RoutingDecision(
        cycle_type="engage",
        focus=_make_perception(),
        background=[],
        memory_requests=[],
        token_budget=3000,
    )


def _make_visitor() -> Visitor:
    return Visitor(
        id="v1",
        name="Test",
        trust_level="stranger",
        visit_count=1,
    )


def _make_api_response(text: str) -> MagicMock:
    """Build a mock that looks like anthropic.types.Message."""
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


VALID_RESPONSE_JSON = json.dumps({
    "internal_monologue": "Test thought.",
    "dialogue": "Hello.",
    "dialogue_language": "en",
    "expression": "neutral",
    "body_state": "sitting",
    "gaze": "at_visitor",
    "resonance": False,
    "actions": [],
    "memory_updates": [],
    "next_cycle_hints": [],
})

FALLBACK_KEYS = {
    "internal_monologue", "dialogue", "dialogue_language",
    "expression", "body_state", "gaze", "resonance",
    "actions", "memory_updates", "next_cycle_hints",
}


# ── Reset module state between tests ──


@pytest.fixture(autouse=True)
def _reset_cortex_state():
    """Reset circuit breaker, daily cap, and singleton client between tests."""
    import pipeline.cortex as cortex
    cortex._consecutive_failures = 0
    cortex._circuit_open_until = 0.0
    cortex._daily_cycle_count = 0
    cortex._daily_cycle_date = ""
    cortex._client = None
    yield
    cortex._client = None


# ── Test: Timeout cancellation ──


@pytest.mark.asyncio
async def test_cortex_call_timeout_returns_fallback():
    """A stalled API call that exceeds API_CALL_TIMEOUT returns fallback."""
    import pipeline.cortex as cortex

    original_timeout = cortex.API_CALL_TIMEOUT
    cortex.API_CALL_TIMEOUT = 0.5  # 500ms for fast test

    async def _stall(**kwargs):
        await asyncio.sleep(10)  # Will be cancelled by wait_for

    mock_client = AsyncMock()
    mock_client.messages.create = _stall

    try:
        with patch.object(cortex, "_get_client", return_value=mock_client):
            t0 = time.monotonic()
            result = await cortex.cortex_call(
                routing=_make_routing(),
                perceptions=[_make_perception()],
                memory_chunks=[],
                conversation=[],
                drives=_make_drives(),
                visitor=_make_visitor(),
            )
            elapsed = time.monotonic() - t0

        # Must return fallback
        assert set(result.keys()) == FALLBACK_KEYS
        assert result["dialogue"] == "..."

        # Must finish well under the stall time (cancelled, not waited out)
        assert elapsed < 3.0, f"Took {elapsed:.1f}s — timeout cancellation failed"

        # Circuit breaker should have recorded a failure
        assert cortex._consecutive_failures == 1
    finally:
        cortex.API_CALL_TIMEOUT = original_timeout


@pytest.mark.asyncio
async def test_maintenance_call_timeout_returns_fallback():
    """Maintenance call timeout returns journal fallback."""
    import pipeline.cortex as cortex

    original_timeout = cortex.API_CALL_TIMEOUT
    cortex.API_CALL_TIMEOUT = 0.5

    async def _stall(**kwargs):
        await asyncio.sleep(10)

    mock_client = AsyncMock()
    mock_client.messages.create = _stall

    try:
        with patch.object(cortex, "_get_client", return_value=mock_client):
            t0 = time.monotonic()
            result = await cortex.cortex_call_maintenance(
                mode="journal",
                digest={"events": []},
            )
            elapsed = time.monotonic() - t0

        assert result["journal"] == "Today happened. I am still here."
        assert elapsed < 3.0
        assert cortex._consecutive_failures == 1
    finally:
        cortex.API_CALL_TIMEOUT = original_timeout


# ── Test: Broader exception handling ──


@pytest.mark.asyncio
async def test_api_error_returns_fallback():
    """anthropic.APIError (base class) is caught and returns fallback."""
    import pipeline.cortex as cortex

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        side_effect=anthropic.APIError(
            message="server error",
            request=MagicMock(),
            body=None,
        )
    )

    with patch.object(cortex, "_get_client", return_value=mock_client):
        result = await cortex.cortex_call(
            routing=_make_routing(),
            perceptions=[_make_perception()],
            memory_chunks=[],
            conversation=[],
            drives=_make_drives(),
        )

    assert set(result.keys()) == FALLBACK_KEYS
    assert cortex._consecutive_failures == 1


@pytest.mark.asyncio
async def test_httpx_timeout_returns_fallback():
    """httpx.TimeoutException is caught and returns fallback."""
    import pipeline.cortex as cortex

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        side_effect=httpx.TimeoutException("read timed out")
    )

    with patch.object(cortex, "_get_client", return_value=mock_client):
        result = await cortex.cortex_call(
            routing=_make_routing(),
            perceptions=[_make_perception()],
            memory_chunks=[],
            conversation=[],
            drives=_make_drives(),
        )

    assert set(result.keys()) == FALLBACK_KEYS
    assert cortex._consecutive_failures == 1


@pytest.mark.asyncio
async def test_generic_exception_returns_fallback():
    """Unexpected exceptions are caught and return fallback."""
    import pipeline.cortex as cortex

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        side_effect=RuntimeError("something completely unexpected")
    )

    with patch.object(cortex, "_get_client", return_value=mock_client):
        result = await cortex.cortex_call(
            routing=_make_routing(),
            perceptions=[_make_perception()],
            memory_chunks=[],
            conversation=[],
            drives=_make_drives(),
        )

    assert set(result.keys()) == FALLBACK_KEYS
    assert cortex._consecutive_failures == 1


# ── Test: Singleton client reuse ──


@pytest.mark.asyncio
async def test_singleton_client_reused():
    """_get_client() returns the same instance on repeated calls."""
    import pipeline.cortex as cortex

    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-test-key"}):
        with patch("anthropic.AsyncAnthropic") as MockClass:
            mock_instance = AsyncMock()
            MockClass.return_value = mock_instance

            c1 = cortex._get_client()
            c2 = cortex._get_client()

            assert c1 is c2
            # Constructor called exactly once
            MockClass.assert_called_once()


@pytest.mark.asyncio
async def test_get_client_raises_without_api_key():
    """_get_client() raises RuntimeError when ANTHROPIC_API_KEY is missing."""
    import pipeline.cortex as cortex

    with patch.dict("os.environ", {}, clear=True):
        # Ensure no key leaks from real env
        import os
        os.environ.pop("ANTHROPIC_API_KEY", None)

        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY not set"):
            cortex._get_client()


# ── Test: Successful API call ──


@pytest.mark.asyncio
async def test_successful_call_returns_parsed_json():
    """A successful API call returns the parsed JSON response."""
    import pipeline.cortex as cortex

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=_make_api_response(VALID_RESPONSE_JSON)
    )

    with patch.object(cortex, "_get_client", return_value=mock_client):
        result = await cortex.cortex_call(
            routing=_make_routing(),
            perceptions=[_make_perception()],
            memory_chunks=[],
            conversation=[],
            drives=_make_drives(),
        )

    assert result["dialogue"] == "Hello."
    assert result["expression"] == "neutral"
    assert cortex._consecutive_failures == 0


@pytest.mark.asyncio
async def test_malformed_json_returns_fallback():
    """Unparseable API response returns fallback without raising."""
    import pipeline.cortex as cortex

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(
        return_value=_make_api_response("not valid json {{{")
    )

    with patch.object(cortex, "_get_client", return_value=mock_client):
        result = await cortex.cortex_call(
            routing=_make_routing(),
            perceptions=[_make_perception()],
            memory_chunks=[],
            conversation=[],
            drives=_make_drives(),
        )

    assert set(result.keys()) == FALLBACK_KEYS
    # Malformed JSON is not an API failure — circuit breaker should not trip
    assert cortex._consecutive_failures == 0


# ── Test: Circuit breaker integration ──


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_consecutive_failures():
    """After MAX_CONSECUTIVE_FAILURES timeouts, circuit opens and skips API."""
    import pipeline.cortex as cortex

    original_timeout = cortex.API_CALL_TIMEOUT
    cortex.API_CALL_TIMEOUT = 0.2

    async def _stall(**kwargs):
        await asyncio.sleep(10)

    mock_client = AsyncMock()
    mock_client.messages.create = _stall

    try:
        with patch.object(cortex, "_get_client", return_value=mock_client):
            # Trip the circuit breaker
            for _ in range(cortex.MAX_CONSECUTIVE_FAILURES):
                await cortex.cortex_call(
                    routing=_make_routing(),
                    perceptions=[_make_perception()],
                    memory_chunks=[],
                    conversation=[],
                    drives=_make_drives(),
                )

            assert cortex._consecutive_failures == cortex.MAX_CONSECUTIVE_FAILURES
            assert cortex._circuit_open_until > 0

            # Next call should return fallback immediately (circuit open)
            t0 = time.monotonic()
            result = await cortex.cortex_call(
                routing=_make_routing(),
                perceptions=[_make_perception()],
                memory_chunks=[],
                conversation=[],
                drives=_make_drives(),
            )
            elapsed = time.monotonic() - t0

        assert set(result.keys()) == FALLBACK_KEYS
        # Should be near-instant (no API call)
        assert elapsed < 0.1
    finally:
        cortex.API_CALL_TIMEOUT = original_timeout
