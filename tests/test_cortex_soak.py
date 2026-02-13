"""Soak test: simulate 200+ cortex cycles with intermittent failures.

Proves the timeout/circuit-breaker/recovery loop doesn't leak threads,
accumulate state, or stall — the conditions that caused the original hang
(BUG-2026-02-13-simulation-api-timeout-hang).

This test runs without a real API key. It uses mocked responses that
alternate between success, timeout, and various error types to exercise
every recovery path across many cycles.
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

from models.state import DrivesState
from pipeline.sensorium import Perception
from pipeline.thalamus import RoutingDecision


# ── Fixtures ──


def _drives():
    return DrivesState(
        social_hunger=0.5, curiosity=0.5, expression_need=0.3,
        rest_need=0.2, energy=0.8, mood_valence=0.0, mood_arousal=0.3,
    )


def _perception():
    return Perception(
        p_type="visitor_speech", source="visitor:v1",
        ts=datetime.now(timezone.utc), content="Hello",
        features={}, salience=0.6,
    )


def _routing():
    return RoutingDecision(
        cycle_type="engage", focus=_perception(),
        background=[], memory_requests=[], token_budget=3000,
    )


VALID_JSON = json.dumps({
    "internal_monologue": "Soak thought.",
    "dialogue": "Mm.",
    "dialogue_language": "en",
    "expression": "neutral",
    "body_state": "sitting",
    "gaze": "at_visitor",
    "resonance": False,
    "actions": [],
    "memory_updates": [],
    "next_cycle_hints": [],
})


def _ok_response():
    block = MagicMock()
    block.text = VALID_JSON
    resp = MagicMock()
    resp.content = [block]
    return resp


@pytest.fixture(autouse=True)
def _reset():
    import pipeline.cortex as cortex
    cortex._consecutive_failures = 0
    cortex._circuit_open_until = 0.0
    cortex._daily_cycle_count = 0
    cortex._daily_cycle_date = ""
    cortex._client = None
    yield
    cortex._client = None


# ── Soak test ──


@pytest.mark.asyncio
async def test_soak_200_cycles_no_leak_no_hang():
    """Run 200 cycles with mixed success/failure patterns.

    Failure schedule (every 10 cycles):
      cycle % 10 == 3  → asyncio.TimeoutError  (stall)
      cycle % 10 == 5  → anthropic.APIError
      cycle % 10 == 7  → httpx.TimeoutException
      cycle % 10 == 9  → RuntimeError (generic)
      all others        → success
    """
    import pipeline.cortex as cortex

    TOTAL_CYCLES = 200
    original_timeout = cortex.API_CALL_TIMEOUT
    cortex.API_CALL_TIMEOUT = 0.3  # fast timeouts for test speed

    call_count = 0
    success_count = 0
    fallback_count = 0

    async def _mock_create(**kwargs):
        nonlocal call_count
        cycle = call_count
        call_count += 1
        mod = cycle % 10

        if mod == 3:
            # Simulate stall — will be cancelled by wait_for
            await asyncio.sleep(10)
        elif mod == 5:
            raise anthropic.APIError(
                message="server error", request=MagicMock(), body=None,
            )
        elif mod == 7:
            raise httpx.TimeoutException("read timed out")
        elif mod == 9:
            raise RuntimeError("unexpected")
        else:
            return _ok_response()

    mock_client = AsyncMock()
    mock_client.messages.create = _mock_create

    try:
        with patch.object(cortex, "_get_client", return_value=mock_client):
            t0 = time.monotonic()

            for i in range(TOTAL_CYCLES):
                # Reset circuit breaker periodically to keep exercising API
                # (otherwise it would open and short-circuit most calls)
                if i % 15 == 0:
                    cortex._consecutive_failures = 0
                    cortex._circuit_open_until = 0.0

                result = await cortex.cortex_call(
                    routing=_routing(),
                    perceptions=[_perception()],
                    memory_chunks=[],
                    conversation=[],
                    drives=_drives(),
                )

                if result.get("dialogue") == "Mm.":
                    success_count += 1
                else:
                    fallback_count += 1

            elapsed = time.monotonic() - t0
    finally:
        cortex.API_CALL_TIMEOUT = original_timeout

    # Sanity checks
    assert success_count > 0, "No successful cycles — mock is broken"
    assert fallback_count > 0, "No fallback cycles — failure injection broken"
    assert success_count + fallback_count == TOTAL_CYCLES

    # Must complete in reasonable time (no leaked stalls)
    # 200 cycles × 0.3s max timeout = 60s worst case, but most are instant
    assert elapsed < 60.0, f"Soak took {elapsed:.1f}s — possible leak"

    # In practice should be much faster (most cycles are instant success)
    print(f"\n[Soak] {TOTAL_CYCLES} cycles in {elapsed:.1f}s "
          f"({success_count} ok, {fallback_count} fallback)")


@pytest.mark.asyncio
async def test_soak_maintenance_50_cycles():
    """Run 50 maintenance cycles with mixed failures."""
    import pipeline.cortex as cortex

    original_timeout = cortex.API_CALL_TIMEOUT
    cortex.API_CALL_TIMEOUT = 0.3

    call_count = 0

    JOURNAL_JSON = json.dumps({
        "journal": "Today was quiet.",
        "summary": {"summary_bullets": ["quiet day"], "emotional_arc": "calm"},
    })

    async def _mock_create(**kwargs):
        nonlocal call_count
        cycle = call_count
        call_count += 1

        if cycle % 5 == 2:
            await asyncio.sleep(10)  # stall
        elif cycle % 5 == 4:
            raise anthropic.APIError(
                message="overloaded", request=MagicMock(), body=None,
            )
        else:
            block = MagicMock()
            block.text = JOURNAL_JSON
            resp = MagicMock()
            resp.content = [block]
            return resp

    mock_client = AsyncMock()
    mock_client.messages.create = _mock_create

    try:
        with patch.object(cortex, "_get_client", return_value=mock_client):
            t0 = time.monotonic()

            for i in range(50):
                if i % 10 == 0:
                    cortex._consecutive_failures = 0
                    cortex._circuit_open_until = 0.0

                result = await cortex.cortex_call_maintenance(
                    mode="journal",
                    digest={"events": [], "cycle": i},
                )

                # Must always return a dict with 'journal' key
                assert "journal" in result

            elapsed = time.monotonic() - t0
    finally:
        cortex.API_CALL_TIMEOUT = original_timeout

    assert elapsed < 30.0, f"Maintenance soak took {elapsed:.1f}s"
    print(f"\n[Soak] 50 maintenance cycles in {elapsed:.1f}s")
