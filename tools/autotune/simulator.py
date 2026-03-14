"""Scenario simulator — replays scenarios against AliveMemory instances."""

from __future__ import annotations

import copy
import tempfile
import time
from datetime import UTC, datetime

from alive_memory.clock import SimulatedClock
from alive_memory.config import AliveConfig
from tools.autotune.types import RecallResult, Scenario, SimulationResult


def _parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 timestamp."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def run_scenario(
    scenario: Scenario,
    config: AliveConfig,
) -> SimulationResult:
    """Run a scenario against a fresh AliveMemory instance.

    Each run gets an isolated in-memory database and temp directory.
    No LLM is used — consolidation writes raw moments to journal.
    """
    from alive_memory import AliveMemory

    # Determine start time from first turn with a timestamp
    start_time = datetime.now(UTC)
    for turn in scenario.turns:
        if turn.simulated_time:
            start_time = _parse_iso(turn.simulated_time)
            break

    clock = SimulatedClock(start_time)

    # Merge scenario setup_config into base config (deep copy to avoid mutation)
    cfg_data = copy.deepcopy(config.data)
    if scenario.setup_config:
        from alive_memory.config import _deep_merge
        _deep_merge(cfg_data, scenario.setup_config)
    merged_config = AliveConfig(cfg_data)

    with tempfile.TemporaryDirectory(prefix="autotune_") as tmpdir:
        mem = AliveMemory(
            storage=":memory:",
            memory_dir=tmpdir,
            config=merged_config,
            clock=clock,
        )
        await mem.initialize()

        result = SimulationResult(scenario_name=scenario.name)
        intake_attempts = 0
        real_start = time.monotonic()

        try:
            for i, turn in enumerate(scenario.turns):
                # Advance clock if turn has a timestamp
                if turn.simulated_time:
                    clock.set(_parse_iso(turn.simulated_time))

                if turn.action == "intake":
                    intake_attempts += 1
                    moment = await mem.intake(
                        event_type="conversation",
                        content=turn.content,
                        metadata=turn.metadata or None,
                        timestamp=clock.now(),
                    )
                    if moment is not None:
                        result.moments_recorded += 1
                    else:
                        result.moments_rejected += 1

                elif turn.action == "recall":
                    recall_start = time.monotonic()
                    context = await mem.recall(turn.content)
                    recall_ms = int((time.monotonic() - recall_start) * 1000)

                    # Flatten recall text
                    all_text = " ".join(
                        context.journal_entries
                        + context.visitor_notes
                        + context.self_knowledge
                        + context.reflections
                        + context.thread_context
                    )

                    recall_result = RecallResult(
                        turn_index=i,
                        query=turn.content,
                        recalled_text=all_text,
                        expected=turn.expected_recall,
                        num_results=context.total_hits,
                        elapsed_ms=recall_ms,
                    )
                    result.recall_results.append(recall_result)

                elif turn.action == "advance_time":
                    clock.advance(turn.advance_seconds)

                elif turn.action == "consolidate":
                    try:
                        await mem.consolidate(depth="full")
                    except Exception as e:
                        result.errors.append(f"consolidate error: {e}")

        except Exception as e:
            result.errors.append(f"simulation error: {e}")
        finally:
            result.elapsed_real_ms = int((time.monotonic() - real_start) * 1000)
            await mem.close()

    return result
