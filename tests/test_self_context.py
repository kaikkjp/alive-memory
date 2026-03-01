"""Tests for TASK-060: Self-Context Injection.

Verifies:
- Self-context block assembles all 4 sections
- Content accurately reflects actual state values
- Token count stays within budget
- Missing data handled gracefully (no "N/A")
- Empty/first-boot returns empty string
"""

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import sys

import pytest

# ── Mock db before importing self_context ──
# Force-set db module to our mock so prompt.self_context binds to it.
_mock_db = MagicMock()
sys.modules["db"] = _mock_db

# Also need to mock db submodules that may be imported
for sub in ("db.connection", "db.state", "db.events", "db.memory",
            "db.analytics", "db.content", "db.actions", "db.social",
            "db.parameters"):
    sys.modules.setdefault(sub, MagicMock())

from prompt.self_context import (  # noqa: E402
    assemble_self_context,
    _mood_word,
    _drive_level,
    _energy_word,
    _truncate_to_budget,
    _estimate_tokens,
    SELF_CONTEXT_MAX_CHARS,
    SELF_CONTEXT_MAX_TOKENS,
)
import prompt.self_context as _sc_module  # noqa: E402
from models.state import DrivesState, Visitor  # noqa: E402


# ── Fixtures ──

def _make_drives(**overrides) -> DrivesState:
    defaults = dict(
        social_hunger=0.5,
        curiosity=0.5,
        expression_need=0.3,
        rest_need=0.2,
        energy=0.8,
        mood_valence=0.1,
        mood_arousal=0.4,
    )
    defaults.update(overrides)
    return DrivesState(**defaults)


def _make_cycle_log(**overrides) -> dict:
    defaults = {
        'body_state': 'sitting',
        'expression': 'neutral',
        'gaze': 'at_visitor',
        'internal_monologue': 'Thinking about the tea bowl.',
        'actions': ['write_journal'],
        'next_cycle_hints': ['examine the shelf'],
        'dialogue': None,
        'mode': 'idle',
    }
    defaults.update(overrides)
    return defaults


def _setup_mocks(
    drives=None,
    budget=None,
    cycle_log=None,
    room=None,
    actions=None,
    habits=None,
    cycle_count=42,
    days_alive=7,
    last_sleep=None,
):
    """Configure mock db for a test run.

    Patches the db reference inside prompt.self_context directly so the
    module-level `import db` binding picks up our mocks.
    """
    if drives is None:
        drives = _make_drives()
    if budget is None:
        budget = {'budget': 5.0, 'spent': 1.5, 'remaining': 3.5}
    if room is None:
        room = MagicMock(shop_status='open')
    if actions is None:
        actions = [
            {'action': 'write_journal', 'created_at': '2025-01-01T12:00:00'},
            {'action': 'browse_web', 'created_at': '2025-01-01T11:00:00'},
        ]
    if habits is None:
        habits = [
            {'action': 'write_journal', 'trigger_context': 'morning', 'strength': 0.6},
        ]
    if last_sleep is None:
        last_sleep = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()

    # Patch on both the mock and the module reference
    mock = _sc_module.db
    mock.get_drives_state = AsyncMock(return_value=drives)
    mock.get_budget_remaining = AsyncMock(return_value=budget)
    mock.get_last_cycle_log = AsyncMock(
        return_value=_make_cycle_log() if cycle_log is None else cycle_log
    )
    mock.get_room_state = AsyncMock(return_value=room)
    mock.get_action_log = AsyncMock(return_value=actions)
    mock.get_top_habits = AsyncMock(return_value=habits)
    mock.count_cycle_logs = AsyncMock(return_value=cycle_count)
    mock.get_days_alive = AsyncMock(return_value=days_alive)
    mock.get_setting = AsyncMock(return_value=last_sleep)


# ── Unit Tests: Helper Functions ──

class TestMoodWord:
    def test_high_valence_high_arousal(self):
        assert _mood_word(0.7, 0.7) == 'energized'

    def test_high_valence_low_arousal(self):
        assert _mood_word(0.7, 0.3) == 'content'

    def test_neutral(self):
        assert _mood_word(0.0, 0.3) == 'neutral'

    def test_low_valence_low_arousal(self):
        assert _mood_word(-0.7, 0.2) == 'low'

    def test_negative_high_arousal(self):
        assert _mood_word(-0.7, 0.7) == 'distressed'

    def test_slightly_positive_high_arousal(self):
        assert _mood_word(0.3, 0.6) == 'curious'

    def test_slightly_negative_high_arousal(self):
        assert _mood_word(-0.1, 0.6) == 'restless'


class TestDriveLevel:
    def test_high(self):
        assert _drive_level(0.9) == 'high'

    def test_moderate(self):
        assert _drive_level(0.65) == 'moderate'

    def test_low(self):
        assert _drive_level(0.4) == 'low'

    def test_quiet(self):
        assert _drive_level(0.1) == 'quiet'


class TestEnergyWord:
    def test_full(self):
        assert _energy_word(0.9) == 'full'

    def test_good(self):
        assert _energy_word(0.7) == 'good'

    def test_moderate(self):
        assert _energy_word(0.5) == 'moderate'

    def test_low(self):
        assert _energy_word(0.2) == 'low'

    def test_depleted(self):
        assert _energy_word(0.05) == 'depleted'


class TestTruncate:
    def test_under_budget(self):
        text = "Short text"
        assert _truncate_to_budget(text) == text

    def test_over_budget(self):
        text = "a\n" * 1000
        result = _truncate_to_budget(text, max_chars=100)
        assert len(result) <= 100

    def test_cuts_at_newline(self):
        text = "line1\nline2\nline3\nline4\nline5"
        result = _truncate_to_budget(text, max_chars=20)
        assert '\n' in result or len(result) <= 20


class TestEstimateTokens:
    def test_basic(self):
        assert _estimate_tokens("hello world") == 2  # 11 chars / 4

    def test_empty(self):
        assert _estimate_tokens("") == 0


# ── Integration Tests: Full Assembly ──

@pytest.mark.asyncio
async def test_full_assembly_contains_all_sections():
    """Self-context block must contain identity, state, behavior, temporal."""
    _setup_mocks()

    result = await assemble_self_context()

    assert result, "Should not be empty"
    # Section 1: Identity
    assert '[Self-context]' in result
    assert 'keeper' in result.lower() or 'shopkeeper' in result.lower() or 'shop' in result.lower()

    # Section 2: State
    assert 'Energy:' in result
    assert 'Mood:' in result
    assert 'Social hunger:' in result

    # Section 3: Behavior
    assert 'Recent:' in result

    # Section 4: Temporal
    assert 'Cycle' in result
    assert 'Day' in result


@pytest.mark.asyncio
async def test_content_matches_actual_drives():
    """Self-context must reflect actual drive/mood values."""
    drives = _make_drives(
        social_hunger=0.9,
        mood_valence=0.7,
        mood_arousal=0.7,
    )
    _setup_mocks(drives=drives)

    result = await assemble_self_context()

    # High social hunger
    assert 'high' in result.lower()
    # Energized mood (high valence + high arousal)
    assert 'energized' in result.lower()


@pytest.mark.asyncio
async def test_energy_from_budget():
    """Energy should derive from budget remaining, not drives.energy."""
    _setup_mocks(
        budget={'budget': 5.0, 'spent': 4.0, 'remaining': 1.0},
        drives=_make_drives(energy=0.9),  # drives.energy is high but budget is low
    )

    result = await assemble_self_context()

    # remaining/budget = 0.2 → "low"
    assert 'Energy: low' in result


@pytest.mark.asyncio
async def test_body_state_from_cycle_log():
    """Body state should come from last cycle log."""
    _setup_mocks(
        cycle_log=_make_cycle_log(body_state='standing', expression='almost_smile', gaze='window'),
    )

    result = await assemble_self_context()

    assert 'standing' in result
    assert 'almost_smile' in result
    assert 'out the window' in result


@pytest.mark.asyncio
async def test_habits_included():
    """Habits above strength threshold appear in behavior section."""
    _setup_mocks(
        habits=[
            {'action': 'write_journal', 'trigger_context': 'morning', 'strength': 0.6},
            {'action': 'browse_web', 'trigger_context': '', 'strength': 0.5},
        ],
    )

    result = await assemble_self_context()

    assert 'Habits:' in result
    assert 'write journal' in result


@pytest.mark.asyncio
async def test_weak_habits_excluded():
    """Habits below strength threshold should not appear."""
    _setup_mocks(
        habits=[
            {'action': 'write_journal', 'trigger_context': 'morning', 'strength': 0.1},
        ],
    )

    result = await assemble_self_context()

    assert 'Habits:' not in result


@pytest.mark.asyncio
async def test_temporal_includes_sleep_delta():
    """Temporal section includes time since last sleep."""
    sleep_time = (datetime.now(timezone.utc) - timedelta(hours=8, minutes=30)).isoformat()
    _setup_mocks(last_sleep=sleep_time)

    result = await assemble_self_context()

    assert 'since sleep' in result
    # Should show ~8.5h
    assert '8.' in result or '8h' in result


@pytest.mark.asyncio
async def test_no_actions_omits_recent_line():
    """If no recent actions, the Recent: line should be omitted, not show N/A."""
    _setup_mocks(actions=[])

    result = await assemble_self_context()

    assert 'Recent:' not in result
    assert 'N/A' not in result


@pytest.mark.asyncio
async def test_no_cycle_log_returns_minimal():
    """First boot (no cycle log) should still produce something."""
    _setup_mocks(cycle_log=None)
    _mock_db.get_last_cycle_log = AsyncMock(return_value=None)

    result = await assemble_self_context()

    # Should still have identity + drives + temporal (no body state)
    assert '[Self-context]' in result


@pytest.mark.asyncio
async def test_token_budget_enforced():
    """Output must be within the character/token budget."""
    _setup_mocks()

    result = await assemble_self_context()

    assert len(result) <= SELF_CONTEXT_MAX_CHARS
    assert _estimate_tokens(result) <= SELF_CONTEXT_MAX_TOKENS + 50  # small margin


@pytest.mark.asyncio
async def test_habit_boost_nudge():
    """Habit boost from basal_ganglia should appear as a nudge."""
    _setup_mocks()
    habit_boost = MagicMock()
    habit_boost.action = 'write_journal'

    result = await assemble_self_context(habit_boost=habit_boost)

    assert 'drawn to write journal' in result
    assert 'habit' in result.lower()


@pytest.mark.asyncio
async def test_visitor_hands_state():
    """Visitor hands_state should appear in body section."""
    _setup_mocks()
    visitor = MagicMock()
    visitor.hands_state = 'a brass compass'

    result = await assemble_self_context(visitor=visitor)

    assert 'brass compass' in result


@pytest.mark.asyncio
async def test_notable_drives_only_when_high():
    """Curiosity/expression only shown when above threshold."""
    drives = _make_drives(
        curiosity=0.3,  # below 0.5
        expression_need=0.2,  # below 0.5
    )
    _setup_mocks(drives=drives)

    result = await assemble_self_context()

    assert 'Curiosity:' not in result
    assert 'Expression need:' not in result


@pytest.mark.asyncio
async def test_notable_drives_shown_when_high():
    """Curiosity/expression shown when above threshold."""
    drives = _make_drives(
        curiosity=0.8,
        expression_need=0.7,
    )
    _setup_mocks(drives=drives)

    result = await assemble_self_context()

    assert 'Curiosity:' in result
    assert 'Expression need:' in result


@pytest.mark.asyncio
async def test_graceful_db_failure():
    """If db calls fail, should still produce at least identity line."""
    mock = _sc_module.db
    mock.get_drives_state = AsyncMock(side_effect=Exception("DB down"))
    mock.get_budget_remaining = AsyncMock(side_effect=Exception("DB down"))
    mock.get_last_cycle_log = AsyncMock(side_effect=Exception("DB down"))
    mock.get_room_state = AsyncMock(side_effect=Exception("DB down"))
    mock.get_action_log = AsyncMock(side_effect=Exception("DB down"))
    mock.get_top_habits = AsyncMock(side_effect=Exception("DB down"))
    mock.count_cycle_logs = AsyncMock(side_effect=Exception("DB down"))
    mock.get_days_alive = AsyncMock(side_effect=Exception("DB down"))
    mock.get_setting = AsyncMock(side_effect=Exception("DB down"))

    result = await assemble_self_context()

    # With all DB down, only identity header exists → returns empty
    # (len(sections) <= 1 check)
    assert result == ''


@pytest.mark.asyncio
async def test_output_is_prose_not_json():
    """Output must be natural language, not JSON."""
    _setup_mocks()

    result = await assemble_self_context()

    # Must not be parseable as JSON
    import json
    with pytest.raises(json.JSONDecodeError):
        json.loads(result)

    # Should not contain JSON-like braces
    assert '{' not in result
    assert '}' not in result


@pytest.mark.asyncio
async def test_shop_status_included():
    """Shop open/closed status should appear."""
    room = MagicMock(shop_status='closed')
    _setup_mocks(room=room)

    result = await assemble_self_context()

    assert 'closed' in result
