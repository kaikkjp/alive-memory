"""Tests for cortex API timeout, cancellation, and error-handling behavior.

Updated for TASK-059: cortex now calls llm_complete() instead of the
Anthropic SDK client directly.  All tests patch 'pipeline.cortex.llm_complete'.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Mock db module before importing cortex (avoids sqlite init)
import unittest.mock
import sys
_mock_db = unittest.mock.MagicMock()
_mock_db.get_visitor_traits = unittest.mock.AsyncMock(return_value=[])
_mock_db.get_active_threads = unittest.mock.AsyncMock(return_value=[])
_mock_db.insert_llm_call_log = unittest.mock.AsyncMock(return_value=None)
sys.modules.setdefault("db", _mock_db)

from models.state import DrivesState, Visitor
from models.pipeline import CortexOutput
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


def _make_llm_response(text: str) -> dict:
    """Build a mock llm_complete() return value (Anthropic-compatible dict)."""
    return {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001},
    }


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


# ── Reset module state between tests ──


@pytest.fixture(autouse=True)
def _reset_cortex_state():
    """Reset circuit breaker and daily cap between tests."""
    import pipeline.cortex as cortex
    cortex._consecutive_failures = 0
    cortex._circuit_open_until = 0.0
    cortex._daily_cycle_count = 0
    cortex._daily_cycle_date = ""
    # Ensure cortex uses our mock db even when real db was imported first
    _original_cortex_db = cortex.db
    cortex.db = _mock_db
    yield
    cortex.db = _original_cortex_db


# ── Test: Timeout cancellation ──


@pytest.mark.asyncio
async def test_cortex_call_timeout_returns_fallback():
    """A stalled llm_complete() call returns fallback via asyncio.TimeoutError."""
    import pipeline.cortex as cortex

    async def _stall(**kwargs):
        await asyncio.sleep(10)

    with patch("pipeline.cortex.llm_complete", side_effect=asyncio.TimeoutError()):
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
    assert isinstance(result, CortexOutput)
    assert result.dialogue == "..."

    # Must finish quickly (no actual stall)
    assert elapsed < 3.0, f"Took {elapsed:.1f}s — should be near-instant"

    # Circuit breaker should have recorded a failure
    assert cortex._consecutive_failures == 1


@pytest.mark.asyncio
async def test_maintenance_call_timeout_returns_fallback():
    """Maintenance call asyncio.TimeoutError returns journal fallback."""
    import pipeline.cortex as cortex

    with patch("pipeline.cortex.llm_complete", side_effect=asyncio.TimeoutError()):
        t0 = time.monotonic()
        result = await cortex.cortex_call_maintenance(
            mode="journal",
            digest={"events": []},
        )
        elapsed = time.monotonic() - t0

    assert result["journal"] == "Today happened. I am still here."
    assert elapsed < 3.0
    assert cortex._consecutive_failures == 1


# ── Test: Broader exception handling ──


@pytest.mark.asyncio
async def test_api_error_returns_fallback():
    """RuntimeError from llm_complete is caught and returns fallback."""
    import pipeline.cortex as cortex

    with patch("pipeline.cortex.llm_complete",
               side_effect=RuntimeError("OpenRouter error 500: server error")):
        result = await cortex.cortex_call(
            routing=_make_routing(),
            perceptions=[_make_perception()],
            memory_chunks=[],
            conversation=[],
            drives=_make_drives(),
        )

    assert isinstance(result, CortexOutput)
    assert cortex._consecutive_failures == 1


@pytest.mark.asyncio
async def test_httpx_timeout_returns_fallback():
    """httpx.TimeoutException from llm_complete is caught and returns fallback."""
    import pipeline.cortex as cortex

    with patch("pipeline.cortex.llm_complete",
               side_effect=httpx.TimeoutException("read timed out")):
        result = await cortex.cortex_call(
            routing=_make_routing(),
            perceptions=[_make_perception()],
            memory_chunks=[],
            conversation=[],
            drives=_make_drives(),
        )

    assert isinstance(result, CortexOutput)
    assert cortex._consecutive_failures == 1


@pytest.mark.asyncio
async def test_generic_exception_returns_fallback():
    """Unexpected exceptions from llm_complete are caught and return fallback."""
    import pipeline.cortex as cortex

    with patch("pipeline.cortex.llm_complete",
               side_effect=RuntimeError("something completely unexpected")):
        result = await cortex.cortex_call(
            routing=_make_routing(),
            perceptions=[_make_perception()],
            memory_chunks=[],
            conversation=[],
            drives=_make_drives(),
        )

    assert isinstance(result, CortexOutput)
    assert cortex._consecutive_failures == 1


# ── Test: Successful API call ──


@pytest.mark.asyncio
async def test_successful_call_returns_parsed_json():
    """A successful llm_complete() call returns the parsed JSON response."""
    import pipeline.cortex as cortex

    with patch("pipeline.cortex.llm_complete",
               return_value=_make_llm_response(VALID_RESPONSE_JSON)):
        result = await cortex.cortex_call(
            routing=_make_routing(),
            perceptions=[_make_perception()],
            memory_chunks=[],
            conversation=[],
            drives=_make_drives(),
        )

    assert result.dialogue == "Hello."
    assert result.expression == "neutral"
    assert cortex._consecutive_failures == 0


@pytest.mark.asyncio
async def test_malformed_json_returns_fallback():
    """Unparseable text in llm_complete() response returns fallback without raising."""
    import pipeline.cortex as cortex

    with patch("pipeline.cortex.llm_complete",
               return_value=_make_llm_response("not valid json {{{")):
        result = await cortex.cortex_call(
            routing=_make_routing(),
            perceptions=[_make_perception()],
            memory_chunks=[],
            conversation=[],
            drives=_make_drives(),
        )

    assert isinstance(result, CortexOutput)
    # Malformed JSON is not an API failure — circuit breaker should not trip
    assert cortex._consecutive_failures == 0


# ── Test: Circuit breaker integration ──


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_consecutive_failures():
    """After MAX_CONSECUTIVE_FAILURES errors, circuit opens and skips API."""
    import pipeline.cortex as cortex

    with patch("pipeline.cortex.llm_complete",
               side_effect=RuntimeError("server error")):
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

    # Next call should return fallback immediately (circuit open — no patch needed)
    t0 = time.monotonic()
    result = await cortex.cortex_call(
        routing=_make_routing(),
        perceptions=[_make_perception()],
        memory_chunks=[],
        conversation=[],
        drives=_make_drives(),
    )
    elapsed = time.monotonic() - t0

    assert isinstance(result, CortexOutput)
    # Should be near-instant (no API call)
    assert elapsed < 0.1
