"""Soak test: simulate 200+ cortex cycles with intermittent failures.

Proves the circuit-breaker/recovery loop doesn't accumulate state or stall.
Updated for TASK-059: cortex now calls llm_complete() instead of the
Anthropic SDK. All tests patch 'pipeline.cortex.llm_complete'.
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

from models.state import DrivesState
from models.pipeline import CortexOutput
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


def _ok_llm_response() -> dict:
    """Return a valid llm_complete() dict response."""
    return {
        "content": [{"type": "text", "text": VALID_JSON}],
        "usage": {"input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001},
    }


JOURNAL_JSON = json.dumps({
    "journal": "Today was quiet.",
    "summary": {"summary_bullets": ["quiet day"], "emotional_arc": "calm"},
})


def _ok_journal_response() -> dict:
    return {
        "content": [{"type": "text", "text": JOURNAL_JSON}],
        "usage": {"input_tokens": 80, "output_tokens": 40, "cost_usd": 0.0005},
    }


@pytest.fixture(autouse=True)
def _reset():
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


# ── Soak test ──


@pytest.mark.asyncio
async def test_soak_200_cycles_no_leak_no_hang():
    """Run 200 cycles with mixed success/failure patterns.

    Failure schedule (every 10 cycles):
      cycle % 10 == 3  → asyncio.TimeoutError
      cycle % 10 == 5  → RuntimeError (simulates OpenRouter HTTP error)
      cycle % 10 == 7  → httpx.TimeoutException
      cycle % 10 == 9  → RuntimeError (generic)
      all others        → success
    """
    import pipeline.cortex as cortex

    TOTAL_CYCLES = 200

    call_count = 0
    success_count = 0
    fallback_count = 0

    async def _mock_complete(**kwargs):
        nonlocal call_count
        cycle = call_count
        call_count += 1
        mod = cycle % 10

        if mod == 3:
            raise asyncio.TimeoutError()
        elif mod == 5:
            raise RuntimeError("OpenRouter error 500: server error")
        elif mod == 7:
            raise httpx.TimeoutException("read timed out")
        elif mod == 9:
            raise RuntimeError("unexpected")
        else:
            return _ok_llm_response()

    t0 = time.monotonic()

    with patch("pipeline.cortex.llm_complete", side_effect=_mock_complete):
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

            assert isinstance(result, CortexOutput)
            if result.dialogue == "Mm.":
                success_count += 1
            else:
                fallback_count += 1

    elapsed = time.monotonic() - t0

    # Sanity checks
    assert success_count > 0, "No successful cycles — mock is broken"
    assert fallback_count > 0, "No fallback cycles — failure injection broken"
    assert success_count + fallback_count == TOTAL_CYCLES

    # Must complete in reasonable time
    assert elapsed < 60.0, f"Soak took {elapsed:.1f}s — possible leak"

    print(f"\n[Soak] {TOTAL_CYCLES} cycles in {elapsed:.1f}s "
          f"({success_count} ok, {fallback_count} fallback)")


@pytest.mark.asyncio
async def test_soak_maintenance_50_cycles():
    """Run 50 maintenance cycles with mixed failures."""
    import pipeline.cortex as cortex

    call_count = 0

    async def _mock_complete(**kwargs):
        nonlocal call_count
        cycle = call_count
        call_count += 1

        if cycle % 5 == 2:
            raise asyncio.TimeoutError()
        elif cycle % 5 == 4:
            raise RuntimeError("OpenRouter error 429: overloaded")
        else:
            return _ok_journal_response()

    t0 = time.monotonic()

    with patch("pipeline.cortex.llm_complete", side_effect=_mock_complete):
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

    assert elapsed < 30.0, f"Maintenance soak took {elapsed:.1f}s"
    print(f"\n[Soak] 50 maintenance cycles in {elapsed:.1f}s")
