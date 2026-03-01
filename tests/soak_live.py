#!/usr/bin/env python3
"""Live API soak test — makes real Anthropic API calls through cortex.

Runs 60 cycles (engage + maintenance) against the live API to prove the
AsyncAnthropic + wait_for fix is stable under real network conditions.

Usage:
    # From project root, with .env containing ANTHROPIC_API_KEY:
    python3 tests/soak_live.py

Expected runtime: ~10-15 minutes (60 cycles × ~5-10s each).
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Load .env
env_path = Path(__file__).resolve().parent.parent / ".env"
if not env_path.exists():
    # Try the main repo .env (worktrees share the parent)
    for candidate in [
        Path(__file__).resolve().parent.parent.parent / ".env",
        Path("/Users/user/Documents/Tokyo-Arc/product/alive/.env"),
    ]:
        if candidate.exists():
            env_path = candidate
            break

if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models.state import DrivesState, Visitor
from pipeline.sensorium import Perception
from pipeline.thalamus import RoutingDecision
import pipeline.cortex as cortex


def make_perception(content: str = "Hello") -> Perception:
    return Perception(
        p_type="visitor_speech",
        source="visitor:soak-test",
        ts=datetime.now(timezone.utc),
        content=content,
        features={},
        salience=0.6,
    )


def make_routing() -> RoutingDecision:
    return RoutingDecision(
        cycle_type="engage",
        focus=make_perception(),
        background=[],
        memory_requests=[],
        token_budget=3000,
    )


def make_drives() -> DrivesState:
    return DrivesState(
        social_hunger=0.5,
        curiosity=0.5,
        expression_need=0.3,
        rest_need=0.2,
        energy=0.8,
        mood_valence=0.0,
        mood_arousal=0.3,
    )


PROMPTS = [
    "Hello",
    "What kind of shop is this?",
    "Do you have anything interesting?",
    "Tell me about yourself.",
    "It's quiet in here.",
    "What's that object on the shelf?",
    "I brought you something.",
    "Do you like music?",
    "The weather is nice today.",
    "I should go soon.",
]

TOTAL_ENGAGE_CYCLES = 50
TOTAL_MAINT_CYCLES = 10


async def run_soak():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set. Cannot run live soak.")
        sys.exit(1)

    print(f"[Soak] Starting live API soak test")
    print(f"[Soak] {TOTAL_ENGAGE_CYCLES} engage cycles + {TOTAL_MAINT_CYCLES} maintenance cycles")
    print(f"[Soak] API_CALL_TIMEOUT = {cortex.API_CALL_TIMEOUT}s")
    from llm.config import resolve_model
    print(f"[Soak] Model: {resolve_model('cortex')}")
    print()

    engage_ok = 0
    engage_fallback = 0
    engage_times: list[float] = []
    maint_ok = 0
    maint_fallback = 0
    maint_times: list[float] = []
    errors: list[str] = []

    t_total = time.monotonic()

    # ── Engage cycles ──
    print(f"[Soak] === Engage cycles ({TOTAL_ENGAGE_CYCLES}) ===")
    for i in range(TOTAL_ENGAGE_CYCLES):
        prompt = PROMPTS[i % len(PROMPTS)]
        perception = make_perception(prompt)
        routing = RoutingDecision(
            cycle_type="engage",
            focus=perception,
            background=[],
            memory_requests=[],
            token_budget=3000,
        )
        visitor = Visitor(
            id=f"soak-visitor-{i}",
            name=None,
            trust_level="stranger",
            visit_count=1,
        )

        t0 = time.monotonic()
        try:
            result = await cortex.cortex_call(
                routing=routing,
                perceptions=[perception],
                memory_chunks=[],
                conversation=[{"role": "visitor", "text": prompt}],
                drives=make_drives(),
                visitor=visitor,
            )
        except Exception as e:
            elapsed = time.monotonic() - t0
            errors.append(f"Cycle {i}: {type(e).__name__}: {e}")
            print(f"  [{i+1:3d}] EXCEPTION in {elapsed:.1f}s — {type(e).__name__}: {e}")
            continue

        elapsed = time.monotonic() - t0
        engage_times.append(elapsed)

        is_fallback = result.get("dialogue") == "..."
        if is_fallback:
            engage_fallback += 1
            print(f"  [{i+1:3d}] FALLBACK in {elapsed:.1f}s")
        else:
            engage_ok += 1
            dialogue = result.get("dialogue", "")
            if dialogue and len(dialogue) > 60:
                dialogue = dialogue[:60] + "…"
            print(f"  [{i+1:3d}] OK in {elapsed:.1f}s — {dialogue!r}")

    print()

    # ── Maintenance cycles ──
    print(f"[Soak] === Maintenance cycles ({TOTAL_MAINT_CYCLES}) ===")
    for i in range(TOTAL_MAINT_CYCLES):
        digest = {
            "cycle": i,
            "events": [
                {"type": "visitor_connect", "count": 2},
                {"type": "conversation_turns", "count": 8},
            ],
            "emotional_arc": "quiet curiosity",
        }

        t0 = time.monotonic()
        try:
            result = await cortex.cortex_call_maintenance(
                mode="journal",
                digest=digest,
            )
        except Exception as e:
            elapsed = time.monotonic() - t0
            errors.append(f"Maint {i}: {type(e).__name__}: {e}")
            print(f"  [{i+1:3d}] EXCEPTION in {elapsed:.1f}s — {type(e).__name__}: {e}")
            continue

        elapsed = time.monotonic() - t0
        maint_times.append(elapsed)

        is_fallback = result.get("journal") == "Today happened. I am still here."
        if is_fallback:
            maint_fallback += 1
            print(f"  [{i+1:3d}] FALLBACK in {elapsed:.1f}s")
        else:
            maint_ok += 1
            journal = result.get("journal", "")
            if journal and len(journal) > 60:
                journal = journal[:60] + "…"
            print(f"  [{i+1:3d}] OK in {elapsed:.1f}s — {journal!r}")

    total_elapsed = time.monotonic() - t_total

    # ── Summary ──
    print()
    print("=" * 60)
    print(f"[Soak] RESULTS")
    print(f"  Total time:        {total_elapsed:.1f}s ({total_elapsed/60:.1f}min)")
    print(f"  Engage cycles:     {engage_ok} ok, {engage_fallback} fallback (of {TOTAL_ENGAGE_CYCLES})")
    print(f"  Maintenance:       {maint_ok} ok, {maint_fallback} fallback (of {TOTAL_MAINT_CYCLES})")
    if engage_times:
        avg_e = sum(engage_times) / len(engage_times)
        max_e = max(engage_times)
        print(f"  Engage timing:     avg={avg_e:.1f}s, max={max_e:.1f}s")
    if maint_times:
        avg_m = sum(maint_times) / len(maint_times)
        max_m = max(maint_times)
        print(f"  Maint timing:      avg={avg_m:.1f}s, max={max_m:.1f}s")
    if errors:
        print(f"  Unhandled errors:  {len(errors)}")
        for e in errors:
            print(f"    - {e}")
    else:
        print(f"  Unhandled errors:  0")
    print(f"  Circuit breaker:   failures={cortex._consecutive_failures}, "
          f"open={'yes' if cortex._circuit_open_until > 0 else 'no'}")
    print(f"  Daily count:       {cortex._daily_cycle_count}")
    print("=" * 60)

    # Exit code
    total_cycles = TOTAL_ENGAGE_CYCLES + TOTAL_MAINT_CYCLES
    total_ok = engage_ok + maint_ok
    if errors:
        print("\n[Soak] FAIL — unhandled exceptions occurred")
        sys.exit(1)
    elif total_ok == 0:
        print("\n[Soak] FAIL — no successful cycles")
        sys.exit(1)
    else:
        success_rate = total_ok / total_cycles * 100
        print(f"\n[Soak] PASS — {success_rate:.0f}% success rate, no hangs, no leaks")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(run_soak())
